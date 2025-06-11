from fastapi import FastAPI, HTTPException, Body, APIRouter, Depends, status
from pydantic import BaseModel
import os
import datetime
import logging
import time
import uuid
from typing import List, Dict, Optional, Any

# Import configuration
from .config_llm import llm_service_config
# Import auth dependency
from .auth_llm import verify_api_key
# Import history manager
from .history_manager import history_manager_instance
# Import RAG Retriever
from .rag.retriever import Retriever, FAISS_ST_AVAILABLE_RETR
# Import Prompts
from .prompts import GENERAL_CHAT_SYSTEM_PROMPT
# Import shared logging setup
from .logging_llm import setup_llm_service_logging, LLM_SERVICE_ROOT_LOGGER_NAME


# Call logging setup at the very beginning of the script
# Pass log level from config. This configures the LLM_SERVICE_ROOT_LOGGER_NAME.
setup_llm_service_logging(log_level_str=llm_service_config.llm_service_log_level)
# Get a child logger for this specific file/module
logger = logging.getLogger(f"{LLM_SERVICE_ROOT_LOGGER_NAME}.main_api")


# Import LLM provider SDKs (Gemini for now)
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    logger.warning("google-generativeai package not found. Gemini provider will not be available.")


# Tools
from .tools.chart_data_tool import ChartDataTool
from .tools.news_analysis_tool import NewsAnalysisTool
from .tools.earnings_analysis_tool import EarningsAnalysisTool

# Initialize Retriever Instance
retriever_instance: Optional[Retriever] = None
if FAISS_ST_AVAILABLE_RETR:
    try:
        retriever_instance = Retriever()
        logger.info("Retriever instance initialized successfully.")
        if not retriever_instance.index or not retriever_instance.model or (hasattr(retriever_instance.index, 'ntotal') and retriever_instance.index.ntotal == 0) :
             logger.warning("Retriever initialized, but RAG resources (index/model) might be missing or index is empty. RAG may be disabled or limited. Run build_rag_index.py.")
    except Exception as e_retriever_init:
        logger.error(f"Failed to initialize Retriever: {e_retriever_init}", exc_info=True)
        retriever_instance = None
else:
    logger.warning("FAISS or SentenceTransformers not available. RAG features will be disabled.")


app = FastAPI(
    title="LLM Chatbot Service",
    description="Service to interact with an LLM, augmented by RAG and Tools, for chatbot functionality and code generation.",
    version="0.1.5" # Incremented version
)

# --- Request and Response Models ---
class ChatMessage(BaseModel):
    user_id: str
    message: str
    session_id: Optional[str] = None

class LLMResponse(BaseModel):
    llm_service_name: str
    original_message: str
    response_text: str
    timestamp: datetime.datetime
    session_id: str
    tool_used: Optional[str] = None
    tool_response: Optional[str] = None # This will be the summary_text from the tool
    structured_tool_data: Optional[Any] = None # For raw JSON-like data from tool
    tool_data_type: Optional[str] = None # e.g., "news_articles", "earnings_reports"
    generated_code: Optional[str] = None
    error_message: Optional[str] = None
    rag_context_used: Optional[bool] = False

class ChatMessageFeedback(BaseModel):
    session_id: str
    message_id: str # Could be timestamp of bot message, or a unique ID if messages have them
    user_id: str # The user who is providing the feedback
    rating: int # e.g., 1 for up, -1 for down
    comment: Optional[str] = None
    # Add other context if useful, like the bot_message_text itself
    bot_message_text_snippet: Optional[str] = None
    user_query_that_led_to_this_response: Optional[str] = None

# --- SDK Snippet ---
PYTHON_SDK_SNIPPET_FOR_LLM = '''
# --- Trading Platform Python SDK Reference ---
# Your strategy code should primarily use these functions.
# Ensure you `import sdk` at the beginning of your strategy file.

# Logging:
# sdk.log(message: Any, level: str = "INFO", **extra_fields)
#   # Logs a message. level can be "DEBUG", "INFO", "WARNING", "ERROR".
#   # e.g., sdk.log(f"Price for {symbol} is {price}", custom_info="some_value")

# Market Data:
# sdk.get_market_data(symbol: str, timeframe: str = "1d",
#                     start_date: Optional[str] = None, # "YYYY-MM-DD"
#                     end_date: Optional[str] = None,   # "YYYY-MM-DD"
#                     lookback_rows: Optional[int] = None) -> List[Dict[str, Any]]
#   # Retrieves historical market data as a list of bars.
#   # Each bar is a dict: {"timestamp": "ISO_ZULU_STR", "OPEN": float, "HIGH": float, "LOW": float, "CLOSE": float, "VOLUME": float}
#   # Note: For current bar data within on_bar(), use the 'current_bar_data_bundle' argument instead of calling this.
#   # e.g., history = sdk.get_market_data("AAPL", lookback_rows=50) # For on_start() warm-up

# Order Submission:
# sdk.submit_order(symbol: str, order_type: str, quantity: float,
#                  price: Optional[float] = None, tif: str = "GTC", # Time In Force (not heavily used by backtester)
#                  stop_price: Optional[float] = None,
#                  trailing_percent: Optional[float] = None, # e.g., 0.5 for 0.5%
#                  trailing_amount: Optional[float] = None,  # e.g., 0.10 for $0.10 currency offset
#                  trail_stop_price: Optional[float] = None) -> Dict[str, Any] # Initial trigger for TRAIL
#   # Submits a trading order. `quantity` is positive for BUY, negative for SELL.
#   # `order_type` (str): "MARKET", "LIMIT", "STOP", "STOP_LIMIT", "TRAIL".
#   # `price`: Required for LIMIT, STOP_LIMIT (as the limit price).
#   # `stop_price`: Required for STOP, STOP_LIMIT (as the stop trigger price).
#   # `trailing_percent` OR `trailing_amount`: One is required for TRAIL orders.
#   # `trail_stop_price`: Optional initial stop price that activates the trail for TRAIL orders.
#   # Returns dict like: {"status": "PENDING_SUBMIT" or "REJECTED", "order_id": "ORD_...", ...}
#   # e.g., sdk.submit_order("MSFT", "LIMIT", 10, price=300.0)
#   # e.g., sdk.submit_order("TSLA", "STOP", -5, stop_price=250.0) # Sell 5 TSLA if price drops to 250

# Portfolio Information (reflects state from backtester when in backtest mode):
# sdk.get_portfolio_summary() -> Dict[str, Any]
#   # Retrieves current cash, total portfolio value, and list of positions.
#   # Example return: {"timestamp": "...", "cash": 10000.0, "total_portfolio_value": 10500.0,
#   #                  "positions_value": 500.0,
#   #                  "positions": [{"symbol": "AAPL", "quantity": 10, "average_price": 150.0,
#   #                                 "market_value": 1550.0, "cost_basis": 1500.0}]}

# sdk.get_position(symbol: str) -> Optional[Dict[str, Any]]
#   # Retrieves details for a specific position including current MTM value. Returns None if no position.
#   # Example return: {"symbol": "AAPL", "quantity": 10, "average_price": 150.0, "cost_basis": 1500.0,
#   #                  "current_market_price": 155.0, "market_value": 1550.0, "timestamp": "..."}

# Base Strategy Class (Your strategy should inherit from this):
# import sdk
# import datetime # For type hints in on_bar
# from typing import Dict, Any, List, Optional # For type hints

# class YourStrategyName(sdk.BaseStrategy):
#     def __init__(self, strategy_id: str, symbols_of_interest: List[str], **strategy_params):
#         super().__init__(strategy_id, symbols_of_interest, **strategy_params)
#         # Access config params: self.my_param = self.strategy_params.get("my_config_param_name", default_value)
#         # sdk.log(f"{self.strategy_id} initialized with params: {self.strategy_params}")

#     def on_start(self): # Called once at the start of the backtest.
#         # sdk.log(f"{self.strategy_id}: on_start called.")
#         pass

#     def on_bar(self, timestamp: datetime.datetime, current_bar_data_bundle: Dict[str, Dict[str, Any]]):
#         # current_bar_data_bundle format: {'SYMBOL': {'OPEN': ..., 'HIGH':..., 'LOW':..., 'CLOSE':..., 'VOLUME':..., 'timestamp': 'ISO_ZULU_STR'}}
#         # This method is called for every new bar of data. Implement your trading logic here.
#         # for symbol, bar_data in current_bar_data_bundle.items():
#         #     if bar_data['CLOSE'] > 100: sdk.submit_order(symbol, "MARKET", 10) # Example
#         pass

#     def on_fill(self, fill_info: Dict[str, Any]): # Called when one of your orders is filled.
#         # fill_info format: {"timestamp": "ISO_ZULU_STR", "symbol": str, "quantity": float, "direction": "BUY"/"SELL",
#         #                    "fill_price": float, "commission": float, "realized_pnl": Optional[float]}
#         # sdk.log(f"{self.strategy_id} received fill: {fill_info['symbol']} Qty {fill_info['quantity']} @ Px {fill_info['fill_price']}", level="INFO")
#         pass

#     def on_stop(self): # Called once at the end of the backtest.
#         # sdk.log(f"{self.strategy_id}: on_stop called.")
#         pass
# --- End of SDK Reference ---
# '''

async def get_live_llm_response(
    user_message: str, user_id: str,
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    rag_context: Optional[str] = None,
    is_code_generation_request: bool = False,
    code_gen_prompt_details: str = ""
) -> tuple[str, str | None, Optional[str]]:

    logger.info("LLM Request", extra={
        "user_id": user_id, "provider": llm_service_config.llm_api_provider,
        "code_gen": is_code_generation_request, "history_len": len(conversation_history) if conversation_history else 0,
        "rag_used": rag_context is not None
    })

    if llm_service_config.llm_api_provider == "gemini":
        if not GEMINI_AVAILABLE: return "Error: Gemini library not installed.", None, "GEMINI_LIB_MISSING"
        if not llm_service_config.gemini_api_key:
            logger.error("Gemini API key not configured.")
            return "Error: Gemini API key not configured.", None, "GEMINI_KEY_MISSING"

        try:
            genai.configure(api_key=llm_service_config.gemini_api_key)

            current_system_instruction: Optional[str] = None
            prompt_content_for_llm: Any # Can be string or list of content dicts

            if is_code_generation_request:
                # Code generation prompt is specific and includes SDK snippet
                # No separate system prompt needed here as the main prompt is comprehensive.
                prompt_content_for_llm = f'''User's Strategy Request: "{code_gen_prompt_details}"

IMPORTANT INSTRUCTIONS AND GUIDELINES:
1.  **SDK Usage:** The generated Python code MUST strictly use the 'Trading Platform Python SDK' functions and classes as defined in the SDK Reference below. Do NOT use any other hypothetical or external trading libraries.
2.  **Strategy Structure:** The main strategy logic MUST be encapsulated within a class that inherits from `sdk.BaseStrategy`.
3.  **Core Methods:** Implement `__init__`, `on_start`, `on_bar`, `on_fill`, and `on_stop`.
4.  **Imports:** Always include `import sdk`. Import `datetime` and `typing` hints as needed.
5.  **Parameters:** Access parameters via `self.strategy_params.get('param_name', default_value)`.
6.  **Market Data in `on_bar`:** Use the `current_bar_data_bundle` argument. Use `sdk.get_market_data()` in `on_start()` for history/warm-up only.
7.  **Order Quantity:** Positive for BUY, negative for SELL.
8.  **Code Only:** Your response MUST BE ONLY the raw Python code. No explanations or markdown.
9.  **Completeness & Clarity:** Generate a complete, runnable script with clear comments.
10. **Error Handling:** Check for `None` returns from SDK calls like `sdk.get_position()`.

{PYTHON_SDK_SNIPPET_FOR_LLM}

Generated Python Code:
'''
                logger.debug(f"LLM Code Gen Prompt (summary): User Request='{code_gen_prompt_details}', SDK reference provided.")
            else: # General chat
                current_system_instruction = GENERAL_CHAT_SYSTEM_PROMPT

                # Assemble history + RAG-augmented current user message for Gemini
                history_plus_current_user_message_parts: List[Dict[str, Any]] = []
                if conversation_history: # Already in Gemini format (list of content dicts)
                    history_plus_current_user_message_parts.extend(conversation_history)

                current_user_message_content_for_llm = user_message
                if rag_context:
                    current_user_message_content_for_llm = f"{rag_context}\n\nUser Query: {user_message}"

                history_plus_current_user_message_parts.append(
                    {'role': 'user', 'parts': [{'text': current_user_message_content_for_llm}]}
                )
                prompt_content_for_llm = history_plus_current_user_message_parts
                logger.debug(f"LLM General Chat. System Instruction Active. History length: {len(conversation_history or [])}. RAG used: {bool(rag_context)}. Current message starts: '{user_message[:50]}...'")

            # Example safety settings (adjust as needed, BLOCK_NONE is very permissive)
            # Consider BLOCK_ONLY_HIGH or BLOCK_MEDIUM_AND_ABOVE for production.
            safety_settings_gemini = {
                'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
                'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
                'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
                'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'
            }

            model = genai.GenerativeModel(
                llm_service_config.gemini_model_name,
                system_instruction=current_system_instruction, # Pass system instruction here
                safety_settings=safety_settings_gemini
            )

            logger.info(f"Sending to Gemini model: {llm_service_config.gemini_model_name}. System instruction active: {bool(current_system_instruction)}.")
            response = await model.generate_content_async(prompt_content_for_llm) # No need to pass safety_settings again if set in model

            response_text_content = ""
            # Try to extract text, handling potential differences in response structure
            if response.parts:
                response_text_content = "".join(part.text for part in response.parts if hasattr(part, 'text'))
            elif response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                response_text_content = "".join(part.text for part in response.candidates[0].content.parts if hasattr(part, 'text'))

            # Check for safety blocks if no content was extracted
            if not response_text_content:
                if response.prompt_feedback and response.prompt_feedback.block_reason:
                    block_reason_detail = response.prompt_feedback.block_reason.name
                    logger.warning(f"Gemini response blocked by prompt feedback.", extra={"reason": block_reason_detail, "prompt_feedback": str(response.prompt_feedback)})
                    return f"Response blocked by safety settings (prompt). Reason: {block_reason_detail}", None, "GEMINI_SAFETY_BLOCK"

                candidate_safety_issues = []
                if response.candidates: # Check candidate-level safety ratings
                    for candidate in response.candidates:
                        if hasattr(candidate, 'finish_reason') and candidate.finish_reason and candidate.finish_reason.name == "SAFETY":
                            for rating in candidate.safety_ratings:
                                if rating.probability.name not in ["NEGLIGIBLE", "LOW"]:
                                    candidate_safety_issues.append(f"{rating.category.name}: {rating.probability.name}")
                            if candidate_safety_issues: break # Found issues in one candidate

                if candidate_safety_issues:
                    detailed_safety_msg = "; ".join(candidate_safety_issues)
                    logger.warning(f"Gemini response blocked by candidate safety settings.", extra={"reason": detailed_safety_msg})
                    return f"Response blocked by safety settings (candidate). Reason: {detailed_safety_msg}", None, "GEMINI_SAFETY_BLOCK"

                if not response.parts and not (response.candidates and response.candidates[0].content.parts): # If truly no parts and no clear safety block
                    logger.warning("Gemini response had no parts and no explicit safety block. Prompt feedback: " + str(response.prompt_feedback))
                    return "Received an empty response from the AI assistant.", None, "GEMINI_EMPTY_RESPONSE"


            if is_code_generation_request:
                generated_code = response_text_content.strip() # Assuming the entire response text is the code
                if generated_code.startswith("```python"):
                    generated_code = generated_code[len("```python"):].lstrip()
                elif generated_code.startswith("```"):
                     generated_code = generated_code[len("```"):].lstrip()
                if generated_code.endswith("```"):
                    generated_code = generated_code[:-len("```")].rstrip()
                generated_code = generated_code.strip() # Final strip for any remaining whitespace
                logger.info(f"Gemini Code Gen Response received.", extra={"code_start": generated_code[:100]})
                return f"Generated Python code for '{code_gen_prompt_details}'.", generated_code, None
            else:
                logger.info(f"Gemini Chat Response received.", extra={"response_start": response_text_content[:100]})
                return response_text_content, None, None
        except Exception as e:
            logger.error(f"Error calling Gemini API.", exc_info=True, extra={"original_error": str(e)})
            return f"Error connecting to Gemini: {str(e)}", None, "GEMINI_API_ERROR"

    elif llm_service_config.llm_api_provider == "mock" or not llm_service_config.llm_api_provider :
        logger.info("Using MOCK LLM response.")
        history_context_mock = ""
        if conversation_history and len(conversation_history) > 0:
            history_context_mock = f" (User mentioned '{conversation_history[-1]['parts'][0]['text']}' before this current message)"
        if rag_context: history_context_mock += f" (RAG provided: '{rag_context[:50]}...')"
        if is_code_generation_request:
            mock_code = f"# Mock Python strategy for: {code_gen_prompt_details}\n# Context: {history_context_mock}\nimport sdk\n\nclass MockStrategy(sdk.BaseStrategy):\n    def on_bar(self, timestamp, bar_data_bundle):\n        sdk.log(f'MockStrategy {{self.strategy_id}} processing bar for {{timestamp}}')\n        sdk.submit_order('AAPL', 'MARKET', 1)\n"
            return f"Generated mock Python code for '{code_gen_prompt_details}'.", mock_code, None
        if "hello" in user_message.lower(): return f"Hello from the mock LLM!{history_context_mock}", None, None
        return f"Mock LLM response to: '{user_message}'.{history_context_mock}", None, None
    else:
        logger.error(f"Unsupported LLM provider configured.", extra={"provider": llm_service_config.llm_api_provider})
        return f"Error: Unsupported LLM provider.", None, "UNSUPPORTED_PROVIDER"

# Tool instances
chart_tool = ChartDataTool(); news_tool = NewsAnalysisTool(); earnings_tool = EarningsAnalysisTool()
chat_router = APIRouter(prefix="/api/v1/chat", tags=["Chat Endpoints"], dependencies=[Depends(verify_api_key)])

@chat_router.post("", response_model=LLMResponse)
async def chat_with_llm_endpoint(chat_message: ChatMessage = Body(...)):
    tool_used_name = None; tool_response_content = None # This will store summary_text
    structured_tool_data_content: Optional[Any] = None
    tool_data_type_content: Optional[str] = None
    generated_code_content = None; final_response_text = ""; error_msg_llm = None
    rag_context_str: Optional[str] = None; rag_context_used_flag = False

    session_id_to_use = chat_message.session_id if chat_message.session_id else chat_message.user_id
    if not session_id_to_use:
        logger.error("API Error: session_id and user_id are missing."); raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="session_id or user_id is required.")

    try:
        logger.info("API: Chat request received.", extra={"user_id": chat_message.user_id, "session_id": session_id_to_use, "message_snippet": chat_message.message[:50]})
        user_msg_lower = chat_message.message.lower()

        is_code_gen_mode = user_msg_lower.startswith("/code"); code_request_details = ""
        is_tool_mode = False

        history_manager_instance.add_message(session_id_to_use, "user", chat_message.message)
        conversation_hist_for_llm = history_manager_instance.get_history(session_id_to_use)[:-1]

        if is_code_gen_mode:
            code_request_details = chat_message.message[len("/code"):].strip()
            if not code_request_details:
                final_response_text = "Please provide details for code generation after /code command."
                error_msg_llm = "CODE_GEN_NO_DETAILS"
            else:
                logger.info(f"API: Code generation requested.", extra={"details": code_request_details})
                final_response_text, generated_code_content, error_msg_llm = await get_live_llm_response(
                    user_message=chat_message.message, user_id=chat_message.user_id,
                    conversation_history=None, rag_context=None,
                    is_code_generation_request=True, code_gen_prompt_details=code_request_details)

        elif "get chart for" in user_msg_lower:
            symbol_query = user_msg_lower.split("get chart for")[-1].strip().upper()
            tool_used_name = chart_tool.name
            # Chart tool currently returns a string directly. We'll adapt it slightly.
            chart_summary_text = chart_tool.execute(symbol=symbol_query if symbol_query else "MSFT") # ChartTool.execute is sync
            tool_response_content = chart_summary_text
            structured_tool_data_content = {"info": chart_summary_text} # Wrap string in a basic structure
            tool_data_type_content = "chart_info_text"
            final_response_text = tool_response_content
            is_tool_mode = True
            logger.info("API: ChartTool executed.", extra={"tool_name": tool_used_name, "response_snippet": final_response_text[:100]})

        elif "news about" in user_msg_lower:
            news_query = user_msg_lower.split("news about")[-1].strip()
            tool_used_name = news_tool.name
            tool_execution_result = await news_tool.execute(query=news_query if news_query else "market", limit=3)
            tool_response_content = tool_execution_result.get("summary_text")
            structured_tool_data_content = tool_execution_result.get("structured_data")
            tool_data_type_content = tool_execution_result.get("data_type")
            final_response_text = tool_response_content
            is_tool_mode = True
            logger.info("API: NewsAnalysisTool executed.", extra={"tool_name": tool_used_name, "response_snippet": final_response_text[:100]})

        elif "earnings for" in user_msg_lower:
            earnings_query = user_msg_lower.split("earnings for")[-1].strip().upper()
            event_type = "historical" if "historical" in user_msg_lower else "upcoming"
            tool_used_name = earnings_tool.name
            tool_execution_result = await earnings_tool.execute(symbol=earnings_query if earnings_query else "TSLA", event_type=event_type, limit=4)
            tool_response_content = tool_execution_result.get("summary_text")
            structured_tool_data_content = tool_execution_result.get("structured_data")
            tool_data_type_content = tool_execution_result.get("data_type")
            final_response_text = tool_response_content
            is_tool_mode = True
            logger.info("API: EarningsAnalysisTool executed.", extra={"tool_name": tool_used_name, "response_snippet": final_response_text[:100]})

        else: # General chat, potentially with RAG
            if retriever_instance and retriever_instance.index and hasattr(retriever_instance.index, 'ntotal') and retriever_instance.index.ntotal > 0:
                logger.debug(f"API: Performing RAG retrieval for query.", extra={"query": chat_message.message})
                try:
                    retrieved_docs = retriever_instance.retrieve_relevant_documents(chat_message.message, top_k=3)
                    if retrieved_docs and not (len(retrieved_docs)==1 and "unavailable" in retrieved_docs[0].get("content","").lower()):
                        rag_context_str = retriever_instance.format_documents_for_prompt(retrieved_docs); rag_context_used_flag = True
                        logger.debug(f"API: RAG context generated.", extra={"context_snippet": rag_context_str[:100]})
                    else: logger.debug("API: No relevant documents found by RAG or RAG unavailable.")
                except Exception as e_rag: logger.error(f"API: Error during RAG retrieval.", exc_info=True, extra={"error": str(e_rag)})

            final_response_text, generated_code_content, error_msg_llm = await get_live_llm_response(
                user_message=chat_message.message, user_id=chat_message.user_id,
                conversation_history=conversation_hist_for_llm, rag_context=rag_context_str,
                is_code_generation_request=False)
            if generated_code_content: logger.warning("General chat returned code, unexpected.")

        if not error_msg_llm and final_response_text and not is_tool_mode:
            response_to_store = generated_code_content if is_code_gen_mode and generated_code_content else final_response_text
            if response_to_store: history_manager_instance.add_message(session_id_to_use, "assistant", response_to_store)

        response = LLMResponse(
            llm_service_name=f"{llm_service_config.llm_api_provider.upper()}" if llm_service_config.llm_api_provider != "mock" else "MockLLM",
            original_message=chat_message.message, response_text=final_response_text,
            tool_used=tool_used_name,
            tool_response=tool_response_content, # This is the summary_text from the tool
            structured_tool_data=structured_tool_data_content,
            tool_data_type=tool_data_type_content,
            generated_code=generated_code_content, error_message=error_msg_llm,
            session_id=session_id_to_use, rag_context_used=rag_context_used_flag,
            timestamp=datetime.datetime.now(datetime.timezone.utc))
        logger.info("API: Sending response.", extra={
            "llm_response_snippet": response.response_text[:100],
            "tool_used": tool_used_name,
            "tool_data_type": tool_data_type_content,
            "has_structured_data": structured_tool_data_content is not None,
            "code_generated": response.generated_code is not None,
            "error": response.error_message
            })
        return response
    except Exception as e:
        logger.error(f"API Error in /chat endpoint.", exc_info=True, extra={"error": str(e)})
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error processing chat.")

app.include_router(chat_router)

@chat_router.post(
    "/sessions/{session_id}/clear",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear Conversation History for a Specific Session ID"
    # verify_api_key dependency is inherited from the chat_router
)
async def clear_specific_chat_session_history(session_id: str):
    logger.info(f"API: Request to clear history for session_id: {session_id}")
    history_manager_instance.clear_history(session_id)
    # FastAPI will automatically return a 204 No Content response.

@chat_router.post(
    "/feedback",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit Feedback on a Chatbot Message"
    # verify_api_key dependency is inherited from the chat_router
)
async def submit_chat_feedback(feedback_data: ChatMessageFeedback):
    logger.info(
        "Received chat message feedback",
        extra={
            "feedback_session_id": feedback_data.session_id,
            "feedback_message_id": feedback_data.message_id,
            "feedback_user_id": feedback_data.user_id,
            "feedback_rating": feedback_data.rating,
            "feedback_comment": feedback_data.comment,
            "feedback_bot_message_snippet": feedback_data.bot_message_text_snippet,
            "feedback_user_query": feedback_data.user_query_that_led_to_this_response
        }
    )
    # For now, just log it. In future, this could write to a DB or analytics.
    # Example: Log to a dedicated feedback file
    # try:
    #     with open("chat_feedback.log", "a", encoding="utf-8") as f:
    #         f.write(f"{datetime.datetime.now(datetime.timezone.utc).isoformat()} - {feedback_data.model_dump_json(exclude_none=True)}\n")
    # except Exception as e_log_feedback:
    #     logger.error(f"Failed to write feedback to file: {e_log_feedback}")

    return {"status": "Feedback received", "session_id": feedback_data.session_id, "message_id": feedback_data.message_id}

@app.get("/health", tags=["Health Check"], summary="Check service health")
async def health_check():
    sub_systems = []
    healthy_overall = True
    if llm_service_config.llm_api_provider != "mock":
        key_is_missing = (llm_service_config.llm_api_provider == "gemini" and not llm_service_config.gemini_api_key)
        if key_is_missing:
            sub_systems.append({"name": "LLM_Provider_Config", "status": "UNHEALTHY", "detail": f"{llm_service_config.llm_api_provider} API key is missing."})
            healthy_overall = False
        else:
            sub_systems.append({"name": "LLM_Provider_Config", "status": "HEALTHY", "detail": f"Provider: {llm_service_config.llm_api_provider}"})
    else:
        sub_systems.append({"name": "LLM_Provider_Config", "status": "HEALTHY", "detail": "Provider: mock"})

    if retriever_instance:
        if retriever_instance.index and retriever_instance.model and hasattr(retriever_instance.index, 'ntotal') and retriever_instance.index.ntotal > 0 :
            sub_systems.append({"name": "RAG_Retriever", "status": "HEALTHY", "detail": f"Index loaded with {retriever_instance.index.ntotal} vectors."})
        elif FAISS_ST_AVAILABLE_RETR : # Libs are there, but index/model issue
            sub_systems.append({"name": "RAG_Retriever", "status": "UNHEALTHY", "detail": "RAG index or model not loaded/empty. Run build_rag_index.py."})
            healthy_overall = False
        else: # Libs missing, RAG effectively disabled
             sub_systems.append({"name": "RAG_Retriever", "status": "DEGRADED", "detail": "RAG dependencies (FAISS/SentenceTransformers) not available. RAG disabled."})
             # This might not make the whole service unhealthy if RAG is optional
    else: # Retriever itself failed to initialize at startup
        sub_systems.append({"name": "RAG_Retriever", "status": "UNAVAILABLE", "detail": "Retriever component failed to initialize at startup (check logs)."})
        if FAISS_ST_AVAILABLE_RETR: healthy_overall = False # If libs there, it should have initialized.

    if healthy_overall:
        return {"status": "HEALTHY", "provider": llm_service_config.llm_api_provider, "components": sub_systems}
    else:
        from fastapi.responses import JSONResponse # Local import for this case
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            content={"status": "UNHEALTHY", "provider": llm_service_config.llm_api_provider, "components": sub_systems})


@app.get("/")
async def root(): return {"message": "LLM Chatbot Service running. Use /api/v1/chat."}

# Gunicorn command: gunicorn -w 4 -k uvicorn.workers.UvicornWorker llm_chatbot_service.main:app --bind 0.0.0.0:8001
