from fastapi import FastAPI, HTTPException, Body, Request
from pydantic import BaseModel
import os
import sys # For Loguru configuration
import datetime
import json # For parsing secrets if they are JSON
import uuid # For request IDs

# --- Logging Setup (Loguru) ---
from loguru import logger
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logger.remove() # Remove default handler
# Configure for JSON output
logger.add(
    sys.stdout,
    format="{time} {level} {message} {extra}",
    serialize=True,
    level=LOG_LEVEL,
    enqueue=True # Make logging asynchronous
)
# Example of how to add file logging if needed:
# logger.add("file_{time}.log", rotation="500 MB", serialize=True, level=LOG_LEVEL, enqueue=True)


try:
    import boto3
    from botocore.exceptions import ClientError
    AWS_SDK_AVAILABLE = True
except ImportError:
    AWS_SDK_AVAILABLE = False
    logger.warning("AWS SDK (boto3) not installed. Secrets Manager integration will be disabled.")

# Attempt to import LLM-specific SDKs and other necessary libraries
import asyncio # For running sync tool code in async context
from typing import List, Dict, Any, Optional # For type hinting

try:
    import google.generativeai as genai
    from google.generativeai.types import FunctionDeclaration, Tool, Part # For Gemini function calling
    GEMINI_SDK_AVAILABLE = True
except ImportError:
    GEMINI_SDK_AVAILABLE = False
    logger.warning("Google Generative AI SDK (google-generativeai) not installed. Gemini provider will be unavailable.")

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    logger.warning("HTTPX library not installed. DeepSeek provider will be unavailable.")


# --- Tool Imports and Registration ---
from .tools.base_tool import BaseTool
from .tools.chart_data_tool import ChartDataTool
from .tools.news_analysis_tool import NewsAnalysisTool
from .tools.earnings_analysis_tool import EarningsAnalysisTool

# Initialize tools
# These instances will be used by both Gemini function calling and keyword-based fallback.
available_tools: List[BaseTool] = [
    ChartDataTool(),
    NewsAnalysisTool(),
    EarningsAnalysisTool()
]
# Create a mapping of tool names to tool instances for easy lookup
tools_map: Dict[str, BaseTool] = {tool.name: tool for tool in available_tools}

# Generate Gemini-compatible tool schemas IF Gemini SDK is available
gemini_tool_schemas: List[FunctionDeclaration] = []
if GEMINI_SDK_AVAILABLE:
    try:
        gemini_tool_schemas = [
            # Directly use the dict returned by get_description_for_llm()
            # as it's already formatted for FunctionDeclaration.
            # The genai library can construct FunctionDeclaration from such dicts.
            tool.get_description_for_llm() for tool in available_tools
        ]
        # Wrap these in a genai.types.Tool object for the API
        gemini_tools_wrapper = Tool(function_declarations=gemini_tool_schemas) if gemini_tool_schemas else None
        if gemini_tools_wrapper:
             logger.info(f"Successfully prepared {len(gemini_tool_schemas)} tools for Gemini function calling.")
        else:
            logger.info("No tools configured or available for Gemini function calling.")
    except Exception as e:
        logger.exception(f"Error preparing Gemini tool schemas: {e}")
        gemini_tools_wrapper = None
else:
    gemini_tools_wrapper = None
    logger.warning("Gemini SDK not available, skipping Gemini tool schema generation.")

# --- RAG Retriever Initialization ---
from .rag.retriever import Retriever, MOCK_KB_DOCUMENTS, DEFAULT_INDEX_PATH, DEFAULT_DOCUMENTS_PATH, FAISS_AVAILABLE, SENTENCE_TRANSFORMERS_AVAILABLE

RAG_EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
RAG_INDEX_PATH_STR = os.getenv("RAG_INDEX_PATH", str(DEFAULT_INDEX_PATH))
RAG_DOCUMENTS_PATH_STR = os.getenv("RAG_DOCUMENTS_PATH", str(DEFAULT_DOCUMENTS_PATH))
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "3"))

rag_retriever: Retriever | None = None
if FAISS_AVAILABLE and SENTENCE_TRANSFORMERS_AVAILABLE:
    try:
        print(f"RAG: Attempting to initialize Retriever with model '{RAG_EMBEDDING_MODEL}'.")
        print(f"RAG: Index path: '{RAG_INDEX_PATH_STR}', Documents path: '{RAG_DOCUMENTS_PATH_STR}'.")

        rag_retriever = Retriever(
            embedding_model_name=RAG_EMBEDDING_MODEL,
            index_path=RAG_INDEX_PATH_STR,
            documents_path=RAG_DOCUMENTS_PATH_STR
        )
        # Check if loading was successful or if it fell back to an empty/mock state
        if not rag_retriever.index or not rag_retriever.documents:
            print("RAG: Index/documents not loaded from paths or paths do not exist.")
            if not os.path.exists(RAG_INDEX_PATH_STR) or not os.path.exists(RAG_DOCUMENTS_PATH_STR):
                 print("RAG: One or both RAG data files not found. Attempting to build from MOCK_KB_DOCUMENTS as a fallback.")
                 # This will re-initialize and build from MOCK_KB_DOCUMENTS
                 rag_retriever = Retriever(
                     embedding_model_name=RAG_EMBEDDING_MODEL,
                     documents_to_build_from=MOCK_KB_DOCUMENTS
                 )
                 if rag_retriever.index and rag_retriever.documents:
                     print("RAG: Successfully built index from MOCK_KB_DOCUMENTS.")
                 else:
                     print("RAG: Failed to build index from MOCK_KB_DOCUMENTS. RAG might be non-functional.")
            else: # Files existed but loading failed for other reasons
                 print("RAG: Files existed but failed to load index/documents. RAG might be non-functional.")
        else:
            print("RAG: Retriever loaded successfully from specified index and document paths.")

    except Exception as e:
        print(f"RAG: Critical error initializing RAG retriever: {e}. RAG will be disabled.")
        rag_retriever = None
else:
    print("RAG: Dependencies (FAISS or SentenceTransformers) not available. RAG will be disabled.")

# --- Conversation History Manager ---
from .conversation_manager import ConversationHistoryManager
MAX_HISTORY_TURNS = int(os.getenv("MAX_HISTORY_TURNS", "5"))
history_manager = ConversationHistoryManager(max_history_turns=MAX_HISTORY_TURNS)


# --- Configuration & API Key Management ---
LLM_API_PROVIDER = os.getenv("LLM_API_PROVIDER", "mock").lower()
LLM_API_KEY = None # Will be loaded by get_secret or from env
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-pro") # Ensure this model supports function calling
DEEPSEEK_MODEL_NAME = os.getenv("DEEPSEEK_MODEL_NAME", "deepseek-chat")
DEEPSEEK_API_ENDPOINT = os.getenv("DEEPSEEK_API_ENDPOINT", "https://api.deepseek.com/chat/completions")
LLM_REQUEST_TIMEOUT = int(os.getenv("LLM_REQUEST_TIMEOUT", "60")) # seconds


def get_secret(secret_name: str) -> str | None:
    """
    Retrieves a secret from AWS Secrets Manager.
    Assumes the AWS environment (credentials, region) is configured.
    """
    if not AWS_SDK_AVAILABLE:
        logger.error("Attempted to get secret, but AWS SDK (boto3) is not available.")
        return None

    region_name = os.getenv("AWS_REGION", "us-east-1") # Or your preferred region
    session = boto3.session.Session()
    client = session.client(service_name='secretsmanager', region_name=region_name)

    try:
        print(f"Attempting to retrieve secret: {secret_name} from region: {region_name}")
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code == 'DecryptionFailureException':
            print(f"Secrets Manager can't decrypt the protected secret text using the configured KMS key: {e}")
        elif error_code == 'InternalServiceErrorException':
            print(f"An error occurred on the server side: {e}")
        elif error_code == 'InvalidParameterException':
            print(f"The request had invalid params: {e}")
        elif error_code == 'InvalidRequestException':
            print(f"The request was invalid due to:", e)
        elif error_code == 'ResourceNotFoundException':
            print(f"The requested secret {secret_name} was not found: {e}")
        else:
            print(f"An unexpected error occurred with Secrets Manager: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred while trying to use boto3: {e}")
        return None

    # Decrypts secret using the associated KMS key.
    # Depending on whether the secret is a string or binary, one of these fields will be populated.
    if 'SecretString' in get_secret_value_response:
        secret = get_secret_value_response['SecretString']
        # If the secret is a JSON string, you might want to parse it.
        # For this use case, we assume the API key is stored directly as a string
        # or as a JSON with a specific key (e.g., {"api_key": "value"})
        # For simplicity, let's assume if it's JSON, it's {"api_key": "THE_KEY"}
        try:
            secret_json = json.loads(secret)
            if isinstance(secret_json, dict) and "api_key" in secret_json:
                print(f"Successfully retrieved and parsed JSON secret for {secret_name}. Using 'api_key' field.")
                return secret_json["api_key"]
            else:
                # If it's JSON but not in the expected format, return the whole string.
                # Or you might want to log a warning.
                print(f"Secret {secret_name} is valid JSON but not in the expected format {{'api_key': ...}}. Using the raw string.")
                return secret
        except json.JSONDecodeError:
            # Not a JSON string, assume it's the raw key
            print(f"Successfully retrieved raw string secret for {secret_name}.")
            return secret
    else:
        # Binary secrets are less common for API keys
        # decoded_binary_secret = base64.b64decode(get_secret_value_response['SecretBinary'])
        print(f"Secret {secret_name} is binary, which is not expected for API keys. Returning None.")
        return None

if LLM_API_PROVIDER != "mock":
    if not AWS_SDK_AVAILABLE:
        logger.warning(f"LLM_API_PROVIDER is '{LLM_API_PROVIDER}' but AWS SDK is not available. Cannot fetch API key.", provider=LLM_API_PROVIDER)
    else:
        secret_name_template = os.getenv("LLM_API_KEY_SECRET_NAME_TEMPLATE", "llm_chatbot_service/api_keys/{provider}")
        safe_provider_name = LLM_API_PROVIDER.replace("/", "_")
        secret_name = secret_name_template.format(provider=safe_provider_name)

        logger.info(f"Attempting to fetch API key for provider '{LLM_API_PROVIDER}' from AWS Secrets Manager using secret name '{secret_name}'...",
                    provider=LLM_API_PROVIDER, secret_id=secret_name)
        LLM_API_KEY = get_secret(secret_name)

        if not LLM_API_KEY:
            logger.warning(f"LLM_API_PROVIDER is '{LLM_API_PROVIDER}' but failed to retrieve API key from AWS Secrets Manager (secret: {secret_name}). Service might not work as expected.",
                           provider=LLM_API_PROVIDER, secret_id=secret_name)
        else:
            logger.info(f"LLM_API_PROVIDER set to '{LLM_API_PROVIDER}'. API Key successfully retrieved from AWS Secrets Manager.", provider=LLM_API_PROVIDER)

elif LLM_API_PROVIDER == "mock":
    logger.info("LLM_API_PROVIDER set to 'mock'. LLM calls will be simulated. No API key retrieval needed.", provider=LLM_API_PROVIDER)

if LLM_API_PROVIDER != "mock" and not LLM_API_KEY:
    logger.warning(f"Final Check: LLM_API_PROVIDER is '{LLM_API_PROVIDER}' but LLM_API_KEY IS NOT SET after attempting retrieval.", provider=LLM_API_PROVIDER)
elif LLM_API_PROVIDER != "mock" and LLM_API_KEY:
     logger.info(f"Final Check: LLM_API_PROVIDER is '{LLM_API_PROVIDER}' and LLM_API_KEY IS SET.", provider=LLM_API_PROVIDER)
else:
    logger.info(f"Final Check: LLM_API_PROVIDER is 'mock'. No API key needed.", provider=LLM_API_PROVIDER)


# Placeholder for tool registration and RAG components
from .tools.chart_data_tool import ChartDataTool
from .tools.news_analysis_tool import NewsAnalysisTool
from .tools.earnings_analysis_tool import EarningsAnalysisTool
# from .rag import Retriever # Placeholder

# --- FastAPI App and Middleware ---
app = FastAPI(
    title="LLM Chatbot Service",
    description="Service to interact with an LLM for chatbot functionality with RAG, tools, and history.",
    version="0.1.1" # Incremented version
)

# Prometheus Instrumentator
from prometheus_fastapi_instrumentator import Instrumentator
# Expose /metrics endpoint. See https://github.com/trallnag/prometheus-fastapi-instrumentator#basic-example
# for more options on what to instrument.
# Default metrics include: http_requests_total, http_requests_created, http_requests_in_progress_total,
# http_request_duration_seconds, http_response_size_bytes, http_request_size_bytes
Instrumentator().instrument(app).expose(app)

@app.middleware("http")
async def log_request_id_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    # Bind request_id to the logger context for all logs within this request
    with logger.contextualize(request_id=request_id):
        logger.info(f"Incoming request: {request.method} {request.url.path}",
                    extra={"client_host": request.client.host if request.client else "N/A", "path": request.url.path, "method": request.method})

        response = await call_next(request)

        logger.info(f"Outgoing response: {response.status_code}",
                    extra={"status_code": response.status_code})
        return response


# --- Request and Response Models ---
class ChatMessage(BaseModel):
    user_id: str # To identify the user session, for context management later
    message: str
    session_id: str | None = None # Optional: For multi-turn conversation tracking

class LLMResponse(BaseModel):
    llm_service_name: str # e.g., "MockLLM/DeepSeek_Emulated"
    original_message: str
    response_text: str
    timestamp: datetime.datetime
    tool_used: str | None = None # To indicate if a tool was used
    tool_response: str | None = None # Raw response from the tool
    generated_code: str | None = None # For code generation responses
    error_message: str | None = None

PYTHON_SDK_SNIPPET_FOR_LLM = """
# --- Trading Platform Python SDK Snippet ---
# Available functions:
#
# import sdk # Standard import
#
# def log(message: str):
#   """Logs a message to the platform's logging system."""
#
# def get_market_data(symbol: str, timeframe: str = "1d", lookback_period: int = 10) -> list[dict]:
#   """Retrieves historical market data. Each item in the list is a dict:
#      {"timestamp": "YYYY-MM-DDTHH:MM:SSZ", "open": float, "high": float, "low": float, "close": float, "volume": int}"""
#
# def submit_order(symbol: str, order_type: str, quantity: int, price: float = None, tif: str = "GTC") -> dict:
#   """Submits a trading order. order_type can be "MARKET" or "LIMIT".
#      Returns a dict with order confirmation, e.g., {"status": "ACCEPTED", "order_id": "ORD-123", ...}"""
#
# def get_portfolio_summary() -> dict:
#   """Retrieves current cash and positions.
#      Returns a dict: {"cash": float, "positions": {"SYMBOL": {"quantity": int, "average_price": float}}}"""
#
# # Example Strategy Structure (User can define their own structure or use a provided base class)
# # class MyStrategy:
# #   def __init__(self):
# #     sdk.log("Strategy initialized")
# #   def on_bar(self, symbol, bar_data): # This method name might be part of a platform convention
# #     sdk.log(f"Processing {symbol}: {bar_data['close']}")
# #     # ... strategy logic ...
# #     if some_condition:
# #       sdk.submit_order(symbol, "MARKET", 10)
# --- End of SDK Snippet ---
"""

# --- Live LLM Interaction ---
async def get_live_llm_response(
    user_message: str,  # For general chat, this is the direct message. For code gen, this is the base user message (e.g. "/code ...")
    user_id: str,
    session_id: str | None, # session_id is now more critical
    is_code_generation_request: bool = False,
    code_gen_prompt_details: str = "",
    use_rag: bool = False,
    conversation_history: Optional[List[Dict[str, str]]] = None, # New parameter
    # Pass the initialized tools and their schemas to the function
    current_tools_map: Dict[str, BaseTool] = tools_map,
    current_gemini_tools_wrapper: Tool | None = gemini_tools_wrapper
) -> tuple[str, str | None, str | None, str | None]:
    """
    Handles interaction with the configured LLM provider.
    Supports direct chat, code generation, function calling (for Gemini), RAG augmentation, and conversation history.
    """
    logger.info(
        f"LLM Interface call. User: {user_id}, Session: {session_id}, Provider: {LLM_API_PROVIDER}, "
        f"Code Gen: {is_code_generation_request}, Use RAG: {use_rag}, History messages: {len(conversation_history or [])}"
    )

    tool_used_name: str | None = None
    tool_response_content: str | None = None
    history_for_llm = [msg.copy() for msg in (conversation_history or [])]

    if not LLM_API_KEY and LLM_API_PROVIDER not in ["mock", "mock_ollama"]:
        error_msg = f"LLM_API_KEY not configured for provider '{LLM_API_PROVIDER}'. Cannot make live API calls."
        logger.error(error_msg, provider=LLM_API_PROVIDER, user_id=user_id, session_id=session_id)
        return error_msg, None, None, None

    # Determine the primary content for the LLM (current query or code gen prompt)
    current_llm_content_input: str
    if is_code_generation_request:
        current_llm_content_input = f"""
You are an expert trading strategy programmer for the 'Trading Platform'.
Your goal is to generate Python code based on the user's request.
The code must use the provided 'Trading Platform Python SDK'.

User Request: "{code_gen_prompt_details}"

Target Language: Python

SDK Information:
{PYTHON_SDK_SNIPPET_FOR_LLM}

Please generate a complete, runnable Python script or class structure.
Ensure all necessary SDK imports are included.
The main logic should be within a class or functions that the platform can call (e.g., an event handler like `on_bar`).
Comment your code clearly.
Respond ONLY with the Python code, enclosed in triple backticks (```python ... ```).
Do not include any introductory text or explanations outside the code block.
"""
        logger.debug(f"Code Generation Prompt for {user_id} (summary): User Request: {code_gen_prompt_details}, SDK Snippet Included: Yes",
                     user_id=user_id, session_id=session_id, code_request=code_gen_prompt_details)
        history_for_llm = [{"role": "user", "content": current_llm_content_input}]

    else:
        current_user_actual_message = history_for_llm[-1]["content"] if history_for_llm and history_for_llm[-1]["role"] == "user" else user_message
        if use_rag and rag_retriever and rag_retriever.index:
            logger.info(f"RAG: Retrieving documents for query (User: {user_id}): '{current_user_actual_message}'",
                        user_id=user_id, session_id=session_id, query_snippet=current_user_actual_message[:100])
            try:
                retrieved_docs = rag_retriever.retrieve_relevant_documents(current_user_actual_message, top_k=RAG_TOP_K)
                if retrieved_docs:
                    rag_context = rag_retriever.format_documents_for_prompt(retrieved_docs)
                    if history_for_llm and history_for_llm[-1]["role"] == "user":
                        history_for_llm[-1]["content"] = f"{rag_context}\n\nUser Question: {history_for_llm[-1]['content']}"
                        logger.info(f"RAG: Context prepended to last user message for {user_id}.", user_id=user_id, session_id=session_id)
                    else:
                        history_for_llm.append({"role": "user", "content": f"{rag_context}\n\nUser Question: {current_user_actual_message}"})
                        logger.info(f"RAG: Context added as new user message for {user_id} (history was empty or ended with model).", user_id=user_id, session_id=session_id)
                else:
                    logger.info(f"RAG: No relevant documents found for query (User: {user_id}).", user_id=user_id, session_id=session_id)
            except Exception as e:
                logger.exception(f"RAG: Error during document retrieval or formatting for {user_id}: {e}", user_id=user_id, session_id=session_id)
        else:
            if use_rag: logger.warning(f"RAG was requested for {user_id} but retriever is not available/functional.", user_id=user_id, session_id=session_id)

    # --- Gemini Integration ---
    if LLM_API_PROVIDER == "gemini":
        if not GEMINI_SDK_AVAILABLE:
            logger.error("Gemini SDK not available.", user_id=user_id, session_id=session_id)
            return "Error: Gemini SDK not available. Please install google-generativeai.", None, None, None
        if not LLM_API_KEY:
             logger.error("Gemini API key not configured.", user_id=user_id, session_id=session_id)
             return "Error: Gemini API key not configured.", None, None, None

        try:
            logger.info(f"Calling Gemini API (model: {GEMINI_MODEL_NAME}) for user '{user_id}'. Tools enabled: {current_gemini_tools_wrapper is not None}",
                        user_id=user_id, session_id=session_id, model_name=GEMINI_MODEL_NAME, tools_enabled=current_gemini_tools_wrapper is not None)
            genai.configure(api_key=LLM_API_KEY)
            model = genai.GenerativeModel(GEMINI_MODEL_NAME)

            gemini_history_content = []
            for msg in history_for_llm:
                role = "model" if msg["role"] == "assistant" else msg["role"]
                gemini_history_content.append({"role": role, "parts": [{"text": msg["content"]}]})

            logger.debug(f"Gemini request content for {user_id} (history length {len(gemini_history_content)}): {json.dumps(gemini_history_content, indent=2)[:500]}...",
                        user_id=user_id, session_id=session_id) # Log snippet
            response = await model.generate_content_async(
                contents=gemini_history_content,
                tools=current_gemini_tools_wrapper
            )

            function_call_part = None
            for part_idx, part in enumerate(response.candidates[0].content.parts): # Added index for logging
                # logger.debug(f"Gemini response part {part_idx} for user {user_id}: {part}", user_id=user_id, session_id=session_id)
                if part.function_call.name and part.function_call.args is not None:
                    function_call_part = part
                    break

            if function_call_part:
                fc_name = function_call_part.function_call.name
                fc_args = dict(function_call_part.function_call.args)
                logger.info(f"Gemini requested function call: {fc_name} with args: {fc_args} for user {user_id}",
                            user_id=user_id, session_id=session_id, tool_name=fc_name, tool_args=fc_args)

                if fc_name in current_tools_map:
                    tool_to_call = current_tools_map[fc_name]
                    tool_result = await tool_to_call.execute(**fc_args)
                    tool_used_name = fc_name
                    tool_response_content = tool_result

                    logger.info(f"Sending tool result for {fc_name} back to Gemini for user {user_id}.",
                                user_id=user_id, session_id=session_id, tool_name=fc_name)
                    response = await model.generate_content_async(
                        [
                            *response.candidates[0].content.parts,
                            Part(function_response=genai.types.FunctionResponse(name=fc_name, response={"content": tool_result}))
                        ],
                        tools=current_gemini_tools_wrapper
                    )
                    generated_text = response.text
                    logger.info(f"Gemini final response after tool execution for {user_id} (snippet): '{generated_text[:100]}...'",
                                user_id=user_id, session_id=session_id, response_snippet=generated_text[:100])
                    return generated_text, None, tool_used_name, tool_response_content
                else:
                    logger.error(f"Gemini requested unknown tool: {fc_name} for user {user_id}",
                                 user_id=user_id, session_id=session_id, tool_name=fc_name)
                    return f"Error: LLM requested an unknown tool ('{fc_name}').", None, None, None
            else:
                generated_text = response.text
                if is_code_generation_request:
                    logger.info(f"Gemini code generation successful for {user_id} (no function call).", user_id=user_id, session_id=session_id)
                    if generated_text.strip().startswith("```python"): generated_text = generated_text.strip()[len("```python"):].strip()
                    if generated_text.strip().endswith("```"): generated_text = generated_text.strip()[:-len("```")].strip()
                    return f"Code generated by Gemini ({GEMINI_MODEL_NAME}).", generated_text, None, None
                else:
                    logger.info(f"Gemini chat response successful for {user_id} (no function call). Snippet: '{generated_text[:100]}...'",
                                user_id=user_id, session_id=session_id, response_snippet=generated_text[:100])
                    return generated_text, None, None, None
        except Exception as e:
            logger.exception(f"Error calling Gemini API for user {user_id}: {e}", user_id=user_id, session_id=session_id)
            return f"Error interacting with Gemini: {str(e)}", None, None, None

    # --- DeepSeek Integration ---
    elif LLM_API_PROVIDER == "deepseek":
        if not HTTPX_AVAILABLE:
            logger.error("HTTPX library not available for DeepSeek.", user_id=user_id, session_id=session_id)
            return "Error: HTTPX library not available. Please install httpx.", None, None, None
        if not LLM_API_KEY:
             logger.error("DeepSeek API key not configured.", user_id=user_id, session_id=session_id)
             return "Error: DeepSeek API key not configured.", None, None, None

        headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"}
        deepseek_messages = []
        for msg in history_for_llm:
            role = "assistant" if msg["role"] == "model" else msg["role"]
            deepseek_messages.append({"role": role, "content": msg["content"]})
        payload = {"model": DEEPSEEK_MODEL_NAME, "messages": deepseek_messages}

        try:
            logger.info(f"Calling DeepSeek API (model: {DEEPSEEK_MODEL_NAME}) for user '{user_id}' with {len(deepseek_messages)} messages.",
                        user_id=user_id, session_id=session_id, model_name=DEEPSEEK_MODEL_NAME, message_count=len(deepseek_messages))
            logger.debug(f"DeepSeek request payload for {user_id} (snippet): {json.dumps(payload, indent=2)[:500]}...",
                         user_id=user_id, session_id=session_id)
            async with httpx.AsyncClient() as client:
                api_response = await client.post(DEEPSEEK_API_ENDPOINT, json=payload, headers=headers, timeout=LLM_REQUEST_TIMEOUT)
            api_response.raise_for_status()
            response_json = api_response.json()
            generated_text = response_json['choices'][0]['message']['content']

            if is_code_generation_request:
                logger.info(f"DeepSeek code generation successful for {user_id}.", user_id=user_id, session_id=session_id)
                if generated_text.strip().startswith("```python"): generated_text = generated_text.strip()[len("```python"):].strip()
                if generated_text.strip().endswith("```"): generated_text = generated_text.strip()[:-len("```")].strip()
                return f"Code generated by DeepSeek ({DEEPSEEK_MODEL_NAME}).", generated_text, None, None
            else:
                logger.info(f"DeepSeek chat response successful for {user_id}. Snippet: '{generated_text[:100]}...'",
                            user_id=user_id, session_id=session_id, response_snippet=generated_text[:100])
                return generated_text, None, None, None
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error calling DeepSeek API for {user_id}: {e.response.status_code} - {e.response.text}",
                         user_id=user_id, session_id=session_id, status_code=e.response.status_code, error_detail=e.response.text)
            return f"Error from DeepSeek (HTTP {e.response.status_code}): {e.response.text}", None, None, None
        except httpx.RequestError as e:
            logger.error(f"Request error calling DeepSeek API for {user_id}: {e}", user_id=user_id, session_id=session_id)
            return f"Network error connecting to DeepSeek: {str(e)}", None, None, None
        except Exception as e:
            logger.exception(f"Error processing DeepSeek response for {user_id}: {e}", user_id=user_id, session_id=session_id)
            return f"Error interacting with DeepSeek: {str(e)}", None, None, None

    # --- Mock Provider ---
    elif LLM_API_PROVIDER == "mock":
        logger.info(f"Using 'mock' provider for user '{user_id}'.", user_id=user_id, session_id=session_id)
        if is_code_generation_request:
            mock_generated_code = f"""# Mock generated Python strategy for: {code_gen_prompt_details} using {LLM_API_PROVIDER}"""
            response_text = f"Mock code generated for '{code_gen_prompt_details}'. Review the code."
            return response_text, mock_generated_code, None, None
        else:
            last_user_msg_content = history_for_llm[-1]["content"] if history_for_llm and history_for_llm[-1]["role"] == "user" else ""
            if "hello" in last_user_msg_content.lower(): # Adjusted to check last user message
                return "Hello from the mock LLM!", None, None, None
            if "mocktool_chart" in last_user_msg_content.lower():
                tool_used_name = "get_chart_data"
                symbol = last_user_msg_content.split("mocktool_chart")[-1].strip() or "MOCK_HIST"
                tool_response_content = await tools_map[tool_used_name].execute(symbol=symbol, timeframe="1D", lookback_period="1M")
                final_text = f"Mock LLM (history aware) used {tool_used_name} for {symbol}. Result: {tool_response_content}"
                logger.info(f"Mock LLM used tool '{tool_used_name}' for user {user_id}.", user_id=user_id, session_id=session_id, tool_name=tool_used_name)
                return final_text, None, tool_used_name, tool_response_content

            mock_response_text = f"Mock response to: '{last_user_msg_content}'."
            if len(history_for_llm) > 1:
                mock_response_text += f" I remember you previously said: '{history_for_llm[-2]['content']}'"
            return mock_response_text, None, None, None

    else:
        error_msg = f"LLM provider '{LLM_API_PROVIDER}' is not recognized or not fully configured. History may be lost for this turn."
        logger.error(error_msg, provider=LLM_API_PROVIDER, user_id=user_id, session_id=session_id)
        return error_msg, None, None, None


# --- API Endpoint ---
@app.post("/chat", response_model=LLMResponse)
async def chat_with_llm(chat_message: ChatMessage = Body(...)):
    """
    Receives a user's chat message, routes to the appropriate LLM provider (handling function calls for Gemini),
    and returns an LLM response, potentially including tool usage details.
    """
    final_response_text: str | None = None
    generated_code_content: str | None = None
    tool_used_name: str | None = None
    tool_response_content: str | None = None


    # Ensure session_id is present
    session_id = chat_message.session_id or f"default_session_{chat_message.user_id}"
    if not chat_message.session_id:
        logger.info(f"API: No session_id provided by client for user {chat_message.user_id}. Using default: {session_id}",
                    extra={"user_id": chat_message.user_id, "default_session_id": session_id})

    # Add current user message to history
    history_manager.add_message(session_id, "user", chat_message.message)
    current_conversation_history = history_manager.get_formatted_history(session_id)

    user_msg_lower = chat_message.message.lower() # Define here for use in is_code_gen_req
    is_code_gen_req = user_msg_lower.startswith("/code")
    code_gen_details = ""


    try:
        logger.info(f"API: Received chat message from user {chat_message.user_id}, session '{session_id}'. Message: '{chat_message.message}'",
                    extra={"user_id": chat_message.user_id, "session_id": session_id, "message_snippet": chat_message.message[:100]})

        if is_code_gen_req:
            code_gen_details = chat_message.message[len("/code"):].strip()
            if not code_gen_details:
                final_response_text = "Please provide details for code generation after /code command. E.g., /code generate python strategy for EMA crossover."
                logger.warning(f"API: Incomplete /code command from user {chat_message.user_id}.", extra={"user_id": chat_message.user_id})
            else:
                logger.info(f"API: Code generation requested by user {chat_message.user_id}: '{code_gen_details}'",
                            extra={"user_id": chat_message.user_id, "code_request": code_gen_details})
                final_response_text, generated_code_content, tool_used_name, tool_response_content = await get_live_llm_response(
                    user_message=chat_message.message,
                    user_id=chat_message.user_id,
                    session_id=session_id,
                    is_code_generation_request=True,
                    code_gen_prompt_details=code_gen_details,
                    use_rag=False,
                    conversation_history=current_conversation_history
                )
        elif LLM_API_PROVIDER == "gemini" and GEMINI_SDK_AVAILABLE and gemini_tools_wrapper:
            logger.info(f"API: Using Gemini provider with function calling for user {chat_message.user_id}, message: '{chat_message.message}'.",
                        extra={"user_id": chat_message.user_id, "message_snippet": chat_message.message[:100]})
            final_response_text, generated_code_content, tool_used_name, tool_response_content = await get_live_llm_response(
                user_message=chat_message.message,
                user_id=chat_message.user_id,
                session_id=session_id,
                is_code_generation_request=False,
                use_rag=True,
                conversation_history=current_conversation_history
            )
        else:
            logger.info(f"API: Using {LLM_API_PROVIDER} (or Gemini without tools). Fallback logic for user {chat_message.user_id}, message: '{chat_message.message}'.",
                        extra={"user_id": chat_message.user_id, "message_snippet": chat_message.message[:100]})
            use_rag_for_this_call = True

            # Simplified: No keyword tool detection here anymore, assuming function calling or direct RAG chat.
            # If specific keyword tools were essential for non-Gemini, they'd be re-added here.
            # For now, all non-/code, non-Gemini-function-calls go to general RAG-augmented chat.
            if not tool_used_name:
                logger.info(f"API: No specific tool detected by keywords. Proceeding to general LLM call (RAG: {use_rag_for_this_call}) for user {chat_message.user_id}.",
                            extra={"user_id": chat_message.user_id, "use_rag": use_rag_for_this_call})
                final_response_text, generated_code_content, tool_used_name, tool_response_content = await get_live_llm_response(
                    user_message=chat_message.message,
                    user_id=chat_message.user_id,
                    session_id=session_id,
                    is_code_generation_request=False,
                    use_rag=use_rag_for_this_call,
                    conversation_history=current_conversation_history
                )

        response_to_store = generated_code_content if is_code_gen_req and generated_code_content else final_response_text
        if response_to_store: # Ensure there's something to store
             history_manager.add_message(session_id, "model", response_to_store)
             logger.debug(f"API: Stored model response for session {session_id}.", extra={"session_id": session_id})

        response_obj = LLMResponse(
            llm_service_name=LLM_API_PROVIDER.upper(),
            original_message=chat_message.message,
            response_text=final_response_text if final_response_text is not None else "No response generated.",
            tool_used=tool_used_name,
            tool_response=tool_response_content,
            generated_code=generated_code_content,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )

        logger.info(f"API: Sending back response to user {chat_message.user_id}. Tool: {tool_used_name}, Code: {response_obj.generated_code is not None}. Response snippet: '{response_obj.response_text[:100]}...'",
                    extra={"user_id": chat_message.user_id, "tool_used": tool_used_name, "has_code": response_obj.generated_code is not None, "response_snippet": response_obj.response_text[:100]})
        return response_obj

    except Exception as e:
        logger.exception(f"API Error: An error occurred during chat processing for user {chat_message.user_id}: {e}",
                         extra={"user_id": chat_message.user_id})
        raise HTTPException(
            status_code=500,
            detail=f"An internal error occurred. Please check logs. Request ID for support: {logger.context.get('request_id', 'N/A') if hasattr(logger, 'context') else 'N/A'}"
        )

@app.get("/")
async def root(request: Request): # Added Request for middleware
    logger.info("Root endpoint '/' accessed.")
    return {"message": "Welcome to the LLM Chatbot Service. Use the /chat endpoint to interact."}

# To run this FastAPI app:
# 1. Create a directory `llm_chatbot_service` and place this file as `main.py`.
# 2. Install FastAPI and Uvicorn: pip install fastapi "uvicorn[standard]"
# 3. Run Uvicorn: uvicorn llm_chatbot_service.main:app --reload --port 8001
# (Using port 8001 to distinguish from the other backend service on port 8000 if running simultaneously)

# Example of how to test with curl:
# curl -X POST "http://localhost:8001/chat" \
# -H "Content-Type: application/json" \
# -d '{"user_id": "test_user_123", "message": "Hello chatbot!", "session_id": "sess_abc_123"}'
