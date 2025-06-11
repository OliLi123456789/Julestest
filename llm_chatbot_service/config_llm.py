# llm_chatbot_service/config_llm.py
import os
import logging
from typing import Optional # Added for type hints

logger = logging.getLogger(__name__) # Use module-level logger

class LLMServiceConfig:
    def __init__(self):
        self.llm_api_provider: str = os.getenv("LLM_API_PROVIDER", "mock").lower()

        # Specific keys for different providers
        self.gemini_api_key: Optional[str] = os.getenv("GEMINI_API_KEY")
        self.gemini_model_name: str = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash-latest") # Or "gemini-pro", "gemini-1.0-pro"

        # Example for another provider (e.g., OpenAI, DeepSeek)
        # self.openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
        # self.openai_model_name: str = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")

        # This could be a generic key if a proxy service is used that handles routing to different models/providers
        self.llm_api_key: Optional[str] = os.getenv("LLM_API_KEY") # This might be the same as GEMINI_API_KEY if only one provider

        log_msg_parts = [f"LLMServiceConfig initialized. Provider: '{self.llm_api_provider}'."]
        if self.llm_api_provider == "gemini":
            if not self.gemini_api_key:
                log_msg_parts.append("GEMINI_API_KEY is NOT SET. Live Gemini calls will fail.")
                logger.warning("LLM_API_PROVIDER is 'gemini' but GEMINI_API_KEY environment variable not set. Live Gemini calls will fail if not using mock.")
            else:
                log_msg_parts.append(f"Gemini API Key is SET (ending with ...{self.gemini_api_key[-4:] if len(self.gemini_api_key) > 4 else '****'}). Model: '{self.gemini_model_name}'.")
        elif self.llm_api_provider != "mock":
            log_msg_parts.append(f"Ensure corresponding API key (e.g., LLM_API_KEY or provider-specific) is set for provider '{self.llm_api_provider}'.")
            if not self.llm_api_key and not self.gemini_api_key : # Add more specific checks if other providers are configured
                 logger.warning(f"LLM_API_PROVIDER is '{self.llm_api_provider}' but no general LLM_API_KEY or specific key found.")


        # For RAG (from step 9.5, included here for completeness of config)
        self.embedding_model_name: str = os.getenv("EMBEDDING_MODEL_NAME", "all-MiniLM-L6-v2") # Default SentenceTransformer
        self.rag_index_path: str = os.getenv("RAG_INDEX_PATH", "./rag_data/faiss_index")
        self.rag_kb_path: str = os.getenv("RAG_KB_PATH", "./knowledge_base")
        log_msg_parts.append(f"RAG: Embedding='{self.embedding_model_name}', Index='{self.rag_index_path}', KB='{self.rag_kb_path}'.")

        # Conversation History settings
        try:
            self.conversation_max_turns: int = int(os.getenv("CONVERSATION_MAX_TURNS", "5")) # Number of user/assistant pairs
            self.conversation_max_sessions_in_memory: int = int(os.getenv("CONVERSATION_MAX_SESSIONS_IN_MEMORY", "1000"))
        except ValueError:
            logger.warning("Invalid conversation history settings in env vars. Using defaults (5 turns, 1000 sessions).")
            self.conversation_max_turns = 5
            self.conversation_max_sessions_in_memory = 1000
        log_msg_parts.append(f"Conversation History: MaxTurns={self.conversation_max_turns} pairs, MaxSessionsInMemory={self.conversation_max_sessions_in_memory}.")

        # External Data API endpoint (for tools to call)
        self.external_data_api_base_url: str = os.getenv("EXTERNAL_DATA_API_BASE_URL", "http://localhost:8002/api/v1")
        log_msg_parts.append(f"External Data API Base URL: '{self.external_data_api_base_url}'.")
        # self.external_data_api_key_for_llm_service: Optional[str] = os.getenv("EXTERNAL_DATA_API_KEY_FOR_LLM_SERVICE")

        # Logging level for the service
        self.llm_service_log_level: str = os.getenv("LLM_SERVICE_LOG_LEVEL", "INFO").upper()
        log_msg_parts.append(f"LLM Service Log Level: '{self.llm_service_log_level}'.")

        # API Key for securing this LLM service itself
        self.service_api_keys_str: Optional[str] = os.getenv("LLM_SERVICE_API_KEYS")
        self.allowed_api_keys: List[str] = [] # Ensure List[str] type hint is imported from typing
        if self.service_api_keys_str:
            self.allowed_api_keys = [key.strip() for key in self.service_api_keys_str.split(',') if key.strip()]

        if not self.allowed_api_keys and self.llm_api_provider != "mock":
            log_msg_parts.append("LLM_SERVICE_API_KEYS is NOT SET or empty. The /chat API will be unprotected unless LLM_API_PROVIDER is 'mock'.")
            # logger.warning("LLM_SERVICE_API_KEYS environment variable not set or empty. The /chat API will be unprotected unless LLM_API_PROVIDER is 'mock'.") # Already part of log_msg_parts
        elif self.allowed_api_keys:
            log_msg_parts.append(f"LLM Service API Key protection ENABLED. {len(self.allowed_api_keys)} key(s) configured.")
            # logger.info(f"LLM Service will be protected by API Key(s). Number of keys: {len(self.allowed_api_keys)}") # Already part of log_msg_parts

        logger.info(" ".join(log_msg_parts))


llm_service_config = LLMServiceConfig()

if __name__ == '__main__':
    # This basic setup will allow seeing the logger messages from the config class
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    print(f"Current LLM Provider: {llm_service_config.llm_api_provider}")
    if llm_service_config.llm_api_provider == "gemini":
        print(f"Gemini API Key Set: {'Yes' if llm_service_config.gemini_api_key else 'No'}")
        print(f"Gemini Model: {llm_service_config.gemini_model_name}")

    print(f"Embedding Model: {llm_service_config.embedding_model_name}")
    print(f"RAG Index Path: {llm_service_config.rag_index_path}")
    print(f"RAG KB Path: {llm_service_config.rag_kb_path}")
    print(f"Conversation Max Turns: {llm_service_config.conversation_max_turns}")
    print(f"Conversation Max Sessions: {llm_service_config.conversation_max_sessions_in_memory}")
    print(f"External Data API Base URL: {llm_service_config.external_data_api_base_url}")
    print(f"LLM Service Log Level: {llm_service_config.llm_service_log_level}")
    print(f"LLM Service API Keys configured: {len(llm_service_config.allowed_api_keys)} keys")
