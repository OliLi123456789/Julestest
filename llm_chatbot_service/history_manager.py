# llm_chatbot_service/history_manager.py
import logging
from typing import List, Dict, Optional, Any
from collections import deque
# from cachetools import LRUCache # For future enhancement if more robust eviction needed

# Import config from the same package.
# This assumes config_llm.py is in the same directory or accessible via package imports.
try:
    from .config_llm import llm_service_config
    LLM_CONFIG_AVAILABLE = True
except ImportError:
    logging.getLogger(__name__).error("Failed to import llm_service_config. HistoryManager will use hardcoded defaults.")
    LLM_CONFIG_AVAILABLE = False
    # Define dummy llm_service_config if needed for code structure to pass,
    # but functionality will be impaired.
    class DummyLLMConfig:
        conversation_max_turns = 5
        conversation_max_sessions_in_memory = 100
    llm_service_config = DummyLLMConfig()


logger = logging.getLogger(__name__) # Use module-level logger
# If using hierarchical logging from a shared setup:
# from .logging_setup import EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME (if logging_setup was for all services)
# logger = logging.getLogger(f"{EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME}.history_manager")


class ConversationHistoryManager:
    def __init__(self, max_turns: Optional[int] = None, max_sessions: Optional[int] = None):
        # Use values from llm_service_config if available and parameters not overridden
        _max_turns_cfg = llm_service_config.conversation_max_turns if LLM_CONFIG_AVAILABLE else 5
        _max_sessions_cfg = llm_service_config.conversation_max_sessions_in_memory if LLM_CONFIG_AVAILABLE else 1000

        self.max_turns_per_session = (max_turns if max_turns is not None else _max_turns_cfg) * 2 # Each turn = user + assistant
        self.max_sessions_limit = max_sessions if max_sessions is not None else _max_sessions_cfg

        # histories: session_id -> deque of messages [{'role': 'user'|'model', 'parts': [{'text': content}]}]
        # Storing in Gemini's expected format directly.
        self.histories: Dict[str, deque[Dict[str, Any]]] = {}

        logger.info(f"ConversationHistoryManager initialized. "
                    f"Max turns per session (pairs): {self.max_turns_per_session // 2}. "
                    f"Max sessions (conceptual for current dict): {self.max_sessions_limit}")

    def add_message(self, session_id: str, role: str, content: str):
        """
        Adds a message to the conversation history for a given session_id.
        Role should be 'user' or 'model' (for Gemini compatibility).
        """
        if not session_id:
            logger.warning("Attempted to add message with no session_id.")
            return
        if role not in ["user", "model", "assistant"]: # "assistant" for OpenAI, map to "model"
             logger.warning(f"Invalid role '{role}' for message in session {session_id}. Using 'user'.")
             role = "user"
        if role == "assistant": # Map to Gemini's role name
            role = "model"

        if session_id not in self.histories:
            # Basic check to prevent unbounded growth of the self.histories dictionary
            if len(self.histories) >= self.max_sessions_limit:
                try:
                    # Simple FIFO eviction for sessions if max_sessions_limit is reached
                    oldest_session_id = next(iter(self.histories)) # Get first key (oldest by insertion in Py3.7+)
                    del self.histories[oldest_session_id]
                    logger.warning(f"Max sessions ({self.max_sessions_limit}) reached. Evicted oldest session: {oldest_session_id}")
                except StopIteration: # Should not happen if len >= max_sessions_limit and limit > 0
                    logger.error("Error during eviction: histories dict was unexpectedly empty.")
                except Exception as e_evict:
                    logger.error(f"Error during session eviction: {e_evict}", exc_info=True)

            self.histories[session_id] = deque(maxlen=self.max_turns_per_session)

        # Store in Gemini's content block format
        message_to_store = {"role": role, "parts": [{"text": content}]}
        self.histories[session_id].append(message_to_store)
        logger.debug(f"Added message to session '{session_id}'. Role: '{role}'. History size: {len(self.histories[session_id])}")

    def get_history(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves the conversation history for a given session_id.
        Returns a list of message dicts, already in Gemini's expected format.
        """
        if not session_id:
            logger.debug("get_history called with no session_id.")
            return []
        history_deque = self.histories.get(session_id)
        logger.debug(f"Retrieved history for session '{session_id}'. Length: {len(history_deque) if history_deque else 0}")
        return list(history_deque) if history_deque else []

    def clear_history(self, session_id: str):
        """Clears the conversation history for a given session_id."""
        if not session_id:
            logger.warning("Attempted to clear history with no session_id.")
            return
        if session_id in self.histories:
            del self.histories[session_id]
            logger.info(f"Cleared history for session '{session_id}'.")
        else:
            logger.debug(f"Attempted to clear history for non-existent session '{session_id}'.")

# Global instance, configured by llm_service_config when history_manager.py is imported.
# This requires llm_service_config to be fully initialized before this line.
# To ensure this, the instantiation can be wrapped in a function or deferred.
# For simplicity of this subtask, direct instantiation is used.
if LLM_CONFIG_AVAILABLE:
    history_manager_instance = ConversationHistoryManager(
       max_turns=llm_service_config.conversation_max_turns,
       max_sessions=llm_service_config.conversation_max_sessions_in_memory
    )
else: # Fallback if config couldn't be loaded (e.g. testing history_manager.py standalone)
    logger.warning("LLMServiceConfig not available during history_manager_instance creation. Using hardcoded defaults for HistoryManager.")
    history_manager_instance = ConversationHistoryManager(max_turns=5, max_sessions=100)


if __name__ == '__main__':
    # Basic logging for testing this module
    if not LLM_CONFIG_AVAILABLE: # Ensure logger is configured if config import failed
        logging.basicConfig(level=logging.DEBUG)
    else: # If config was available, it might have set up SDK logging. Or main script does.
          # For this specific test, ensure its logger is active.
        if not logger.handlers:
             logging.basicConfig(level=logging.DEBUG)
             logger.info("Configured basic logging for history_manager __main__.")


    logger.info("--- Testing ConversationHistoryManager ---")
    # Test with default config values loaded by the global instance
    manager = history_manager_instance

    session1 = "session_test_1"
    manager.add_message(session1, "user", "Hello, what's the weather like?")
    manager.add_message(session1, "model", "I am an AI and do not have real-time weather information.")
    manager.add_message(session1, "user", "Okay, can you tell me a joke then?")
    manager.add_message(session1, "model", "Why don't scientists trust atoms? Because they make up everything!")

    hist1 = manager.get_history(session1)
    logger.info(f"History for {session1} (max_turns_pairs={manager.max_turns_per_session//2}): {json.dumps(hist1, indent=2)}")
    assert len(hist1) == 4

    # Test max turns eviction
    logger.info(f"\n--- Testing Max Turns Eviction (limit set to 1 pair, i.e., 2 messages) ---")
    short_turn_manager = ConversationHistoryManager(max_turns=1) # 1 pair = 2 messages (1 user, 1 model)
    session2 = "session_test_2"
    short_turn_manager.add_message(session2, "user", "Message 1 User")
    short_turn_manager.add_message(session2, "model", "Message 1 Model")
    logger.info(f"History for {session2} after 1 pair: {short_turn_manager.get_history(session2)}")
    assert len(short_turn_manager.get_history(session2)) == 2

    short_turn_manager.add_message(session2, "user", "Message 2 User (should evict M1U)")
    hist2_after_add1 = short_turn_manager.get_history(session2)
    logger.info(f"History for {session2} after new user message: {hist2_after_add1}")
    assert len(hist2_after_add1) == 2 # Still 2 due to maxlen of deque
    assert hist2_after_add1[0]['content'] == "Message 1 Model" # M1U evicted
    assert hist2_after_add1[1]['content'] == "Message 2 User"

    short_turn_manager.add_message(session2, "model", "Message 2 Model (should evict M1M)")
    hist2_after_add2 = short_turn_manager.get_history(session2)
    logger.info(f"History for {session2} after new model message: {hist2_after_add2}")
    assert len(hist2_after_add2) == 2
    assert hist2_after_add2[0]['content'] == "Message 2 User"
    assert hist2_after_add2[1]['content'] == "Message 2 Model"


    logger.info(f"\n--- Testing Max Sessions Eviction (limit set to 1 session for test) ---")
    # This requires llm_service_config to be mocked or testing instance directly
    # For this __main__, let's test the logic directly.
    # The global history_manager_instance uses config.
    # For this specific test, create a new manager.
    max_sessions_test_manager = ConversationHistoryManager(max_turns=2, max_sessions=1)
    max_sessions_test_manager.add_message("s1", "user", "s1_u1")
    logger.info(f"Histories after s1: {list(max_sessions_test_manager.histories.keys())}")
    assert "s1" in max_sessions_test_manager.histories

    max_sessions_test_manager.add_message("s2", "user", "s2_u1") # s1 should be evicted
    logger.info(f"Histories after s2: {list(max_sessions_test_manager.histories.keys())}")
    assert "s1" not in max_sessions_test_manager.histories
    assert "s2" in max_sessions_test_manager.histories

    max_sessions_test_manager.clear_history("s2")
    logger.info(f"Histories after clearing s2: {list(max_sessions_test_manager.histories.keys())}")
    assert "s2" not in max_sessions_test_manager.histories

    logger.info("\nConversationHistoryManager tests finished.")
