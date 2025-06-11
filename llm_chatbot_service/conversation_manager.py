from typing import List, Dict, Any
from loguru import logger # Import Loguru

class ConversationHistoryManager:
    """
    Manages conversation histories for different sessions in memory.
    """
    def __init__(self, max_history_turns: int = 5):
        """
        Initializes the ConversationHistoryManager.
        :param max_history_turns: The maximum number of user/assistant turn pairs to keep in history.
        """
        self.conversations: Dict[str, List[Dict[str, str]]] = {}
        self.max_history_turns = max_history_turns
        logger.info(f"ConversationHistoryManager initialized with max_history_turns={max_history_turns}")

    def add_message(self, session_id: str, role: str, content: str):
        """
        Adds a message to the conversation history for a given session_id.
        Roles should typically be "user" or "model".
        """
        if session_id not in self.conversations:
            self.conversations[session_id] = []
            logger.debug(f"New conversation started for session_id: {session_id}", session_id=session_id)

        self.conversations[session_id].append({"role": role, "content": content})
        logger.debug(f"Message added to session {session_id}. Role: {role}, Content snippet: '{content[:50]}...'",
                     session_id=session_id, role=role, content_snippet=content[:50])
        self._prune_history(session_id)
        # logger.trace(f"History for {session_id} after add: {self.conversations[session_id]}", session_id=session_id)

    def _prune_history(self, session_id: str):
        """
        Prunes the history for a session_id to keep only the most recent max_history_turns.
        Each turn consists of a user message and a model message.
        """
        if session_id in self.conversations:
            max_messages = self.max_history_turns * 2
            if len(self.conversations[session_id]) > max_messages:
                self.conversations[session_id] = self.conversations[session_id][-max_messages:]
                logger.debug(f"History for session {session_id} pruned. New length: {len(self.conversations[session_id])}",
                             session_id=session_id, new_length=len(self.conversations[session_id]))


    def get_formatted_history(self, session_id: str) -> List[Dict[str, str]]:
        """
        Retrieves the conversation history for a session_id, formatted for LLM APIs.
        Returns an empty list if the session_id is not found.
        """
        return self.conversations.get(session_id, [])

    def clear_history(self, session_id: str):
        """
        Clears the conversation history for a given session_id.
        """
        if session_id in self.conversations:
            del self.conversations[session_id]
            logger.info(f"Conversation history cleared for session_id: {session_id}", session_id=session_id)
        else:
            logger.info(f"No conversation history found to clear for session_id: {session_id}", session_id=session_id)

if __name__ == '__main__':
    # Basic Loguru setup for testing this module directly
    import sys
    logger.remove()
    logger.add(sys.stderr, level="DEBUG", format="{time} {level} {message} | {extra}")

    manager = ConversationHistoryManager(max_history_turns=2)

    session_1 = "user123_session_abc"
    session_2 = "user456_session_xyz"

    logger.info(f"\n--- Testing Session: {session_1} ---")
    manager.add_message(session_1, "user", "Hello, who are you?")
    manager.add_message(session_1, "model", "I am a helpful AI assistant.")
    logger.info(f"History after 1 turn for {session_1}: {manager.get_formatted_history(session_1)}")

    manager.add_message(session_1, "user", "What is the weather like?")
    manager.add_message(session_1, "model", "I cannot provide real-time weather information.")
    logger.info(f"History after 2 turns for {session_1}: {manager.get_formatted_history(session_1)}")
    assert len(manager.get_formatted_history(session_1)) == 4

    manager.add_message(session_1, "user", "Tell me a joke.")
    manager.add_message(session_1, "model", "Why did the scarecrow win an award? Because he was outstanding in his field!")
    logger.info(f"History after 3 turns for {session_1} (pruning should occur): {manager.get_formatted_history(session_1)}")
    assert len(manager.get_formatted_history(session_1)) == 4
    assert manager.get_formatted_history(session_1)[0]["content"] == "What is the weather like?"

    logger.info(f"\n--- Testing Session: {session_2} ---")
    manager.add_message(session_2, "user", "Any good books to read?")
    manager.add_message(session_2, "model", "I can recommend 'Sapiens' by Yuval Noah Harari.")
    logger.info(f"History for session {session_2}: {manager.get_formatted_history(session_2)}")
    assert len(manager.get_formatted_history(session_2)) == 2

    logger.info(f"\n--- Testing Clearing History for Session: {session_1} ---")
    manager.clear_history(session_1)
    logger.info(f"History for session {session_1} after clearing: {manager.get_formatted_history(session_1)}")
    assert len(manager.get_formatted_history(session_1)) == 0
    assert len(manager.get_formatted_history(session_2)) == 2

    logger.info("\nConversationHistoryManager tests completed.")
