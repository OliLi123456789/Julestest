import pytest
from llm_chatbot_service.conversation_manager import ConversationHistoryManager

def test_conversation_manager_initialization_default():
    manager = ConversationHistoryManager()
    assert manager.max_history_turns == 5
    assert manager.conversations == {}

def test_conversation_manager_initialization_custom():
    manager = ConversationHistoryManager(max_history_turns=3)
    assert manager.max_history_turns == 3

def test_add_message_new_session():
    manager = ConversationHistoryManager()
    session_id = "test_session_1"
    manager.add_message(session_id, "user", "Hello")
    assert session_id in manager.conversations
    assert len(manager.conversations[session_id]) == 1
    assert manager.conversations[session_id][0] == {"role": "user", "content": "Hello"}

def test_add_message_existing_session():
    manager = ConversationHistoryManager()
    session_id = "test_session_1"
    manager.add_message(session_id, "user", "Hello")
    manager.add_message(session_id, "model", "Hi there!")
    assert len(manager.conversations[session_id]) == 2
    assert manager.conversations[session_id][1] == {"role": "model", "content": "Hi there!"}

def test_prune_history():
    manager = ConversationHistoryManager(max_history_turns=1) # Keep only 1 turn (2 messages)
    session_id = "test_prune"

    manager.add_message(session_id, "user", "Message 1")
    manager.add_message(session_id, "model", "Response 1")
    assert len(manager.get_formatted_history(session_id)) == 2

    manager.add_message(session_id, "user", "Message 2") # This should push out "Message 1" and "Response 1"
    assert len(manager.get_formatted_history(session_id)) == 2
                                                        # History: User:M1, Model:R1, User:M2
                                                        # After prune, it should keep Model:R1, User:M2 if we add model after this
                                                        # Let's clarify the pruning logic: it keeps the *last* N messages.
                                                        # So if max_messages = 2, after adding User:M2, history is [U1, M1, U2]
                                                        # Pruning will take [-2:], so [M1, U2]

    # Let's test more rigorously
    manager_strict_prune = ConversationHistoryManager(max_history_turns=1) # Max 2 messages
    session_strict = "strict_prune_session"
    manager_strict_prune.add_message(session_strict, "user", "U1")
    manager_strict_prune.add_message(session_strict, "model", "M1")
    # History: [U1, M1]

    manager_strict_prune.add_message(session_strict, "user", "U2")
    # History before prune: [U1, M1, U2]. After prune (last 2): [M1, U2]
    history = manager_strict_prune.get_formatted_history(session_strict)
    assert len(history) == 2
    assert history[0] == {"role": "model", "content": "M1"}
    assert history[1] == {"role": "user", "content": "U2"}

    manager_strict_prune.add_message(session_strict, "model", "M2")
    # History before prune: [M1, U2, M2]. After prune: [U2, M2]
    history = manager_strict_prune.get_formatted_history(session_strict)
    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "U2"}
    assert history[1] == {"role": "model", "content": "M2"}


def test_get_formatted_history_existing_session():
    manager = ConversationHistoryManager()
    session_id = "test_get"
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "model", "content": "Hi"}
    ]
    manager.add_message(session_id, messages[0]["role"], messages[0]["content"])
    manager.add_message(session_id, messages[1]["role"], messages[1]["content"])

    retrieved_history = manager.get_formatted_history(session_id)
    assert retrieved_history == messages

def test_get_formatted_history_non_existing_session():
    manager = ConversationHistoryManager()
    retrieved_history = manager.get_formatted_history("non_existent_session")
    assert retrieved_history == []

def test_clear_history_existing_session():
    manager = ConversationHistoryManager()
    session_id = "test_clear"
    manager.add_message(session_id, "user", "Message to be cleared")
    assert session_id in manager.conversations

    manager.clear_history(session_id)
    assert session_id not in manager.conversations
    assert manager.get_formatted_history(session_id) == []

def test_clear_history_non_existing_session():
    manager = ConversationHistoryManager()
    # Clearing a non-existent session should not raise an error
    try:
        manager.clear_history("non_existent_clear")
    except Exception as e:
        pytest.fail(f"clear_history raised an exception for non-existent session: {e}")

def test_pruning_multiple_turns():
    manager = ConversationHistoryManager(max_history_turns=2) # Keep 2 turns = 4 messages
    session_id = "multi_turn_prune"

    # Add 3 turns (6 messages)
    manager.add_message(session_id, "user", "U1")
    manager.add_message(session_id, "model", "M1")
    manager.add_message(session_id, "user", "U2")
    manager.add_message(session_id, "model", "M2")
    manager.add_message(session_id, "user", "U3")
    manager.add_message(session_id, "model", "M3")

    history = manager.get_formatted_history(session_id)
    assert len(history) == 4 # Should be pruned to last 2 turns (U2, M2, U3, M3)

    expected_history = [
        {"role": "user", "content": "U2"},
        {"role": "model", "content": "M2"},
        {"role": "user", "content": "U3"},
        {"role": "model", "content": "M3"}
    ]
    assert history == expected_history
