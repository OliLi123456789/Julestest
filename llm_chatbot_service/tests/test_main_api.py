import pytest
import json
import os
from unittest.mock import patch, AsyncMock # AsyncMock for async methods

from fastapi.testclient import TestClient

# Import the FastAPI app instance from your main application file
# Ensure that llm_chatbot_service is in PYTHONPATH or adjust relative path
# For example, if tests are run from the project root:
from llm_chatbot_service.main import app, history_manager # Import history_manager to clear
from llm_chatbot_service.rag.retriever import Retriever, MOCK_KB_DOCUMENTS # For RAG testing
from llm_chatbot_service.tools.chart_data_tool import ChartDataTool


# --- Test Client Setup ---
client = TestClient(app)

# --- Fixtures ---
@pytest.fixture(autouse=True)
def clear_history_fixture():
    """Clears conversation history before and after each test that might use it."""
    # No specific setup needed before test for this simple in-memory manager
    yield
    # Teardown: Clear all histories (or specific ones if IDs are known and managed)
    # For simplicity, clearing all. In a more complex scenario, might target specific session IDs.
    if hasattr(history_manager, 'conversations'):
        history_manager.conversations.clear()

# --- Test Cases ---

def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to the LLM Chatbot Service. Use the /chat endpoint to interact."}

def test_read_metrics():
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.text.startswith("# HELP python_gc_objects_collected_total Objects collected during gc") # Example Prometheus metric start

# --- /chat Endpoint Tests ---

@patch('llm_chatbot_service.main.get_live_llm_response', new_callable=AsyncMock)
def test_chat_general_message(mock_get_live_llm_response):
    mock_get_live_llm_response.return_value = ("Hello from mock LLM!", None, None, None)

    response = client.post("/chat", json={"user_id": "test_user", "message": "Hello"})
    assert response.status_code == 200
    data = response.json()
    assert data["original_message"] == "Hello"
    assert data["response_text"] == "Hello from mock LLM!"
    assert data["tool_used"] is None
    mock_get_live_llm_response.assert_called_once()

@patch('llm_chatbot_service.main.get_live_llm_response', new_callable=AsyncMock)
def test_chat_code_generation(mock_get_live_llm_response):
    mock_response_text = "Generated Python code for you:"
    mock_code = "print('Hello, world!')"
    mock_get_live_llm_response.return_value = (mock_response_text, mock_code, None, None)

    response = client.post("/chat", json={
        "user_id": "test_user_code",
        "message": "/code generate a simple python script"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["original_message"] == "/code generate a simple python script"
    assert data["response_text"] == mock_response_text
    assert data["generated_code"] == mock_code
    mock_get_live_llm_response.assert_called_once()
    # Check if is_code_generation_request and code_gen_prompt_details were passed correctly
    call_args = mock_get_live_llm_response.call_args[1] # kwargs
    assert call_args['is_code_generation_request'] is True
    assert call_args['code_gen_prompt_details'] == "generate a simple python script"

@patch.dict(os.environ, {"LLM_API_PROVIDER": "mock"}) # Use mock provider for keyword test
@patch('llm_chatbot_service.tools.chart_data_tool.ChartDataTool.execute', new_callable=AsyncMock)
@patch('llm_chatbot_service.main.get_live_llm_response', new_callable=AsyncMock) # Mock this so it's not called after keyword tool
async def test_chat_keyword_tool_usage(mock_llm_response, mock_chart_execute):
    # This test is a bit tricky because the keyword logic is currently in main.py's /chat
    # and it directly calls the tool. If a tool is hit by keyword, get_live_llm_response might not be called.
    # The refactor in a previous step made Gemini function calling primary, with keyword as fallback.
    # For this test, we'll assume the keyword path in /chat is hit for a "mock" provider.

    mock_chart_tool_output = {"symbol": "MSFT", "data": "mock chart data"}
    mock_chart_execute.return_value = json.dumps(mock_chart_tool_output)

    # This setup implies that the keyword logic in /chat endpoint calls the tool directly
    # and its output becomes the final_response_text.
    # We are essentially bypassing get_live_llm_response if a keyword is matched.

    # To make this test work with current structure, we'd need to ensure get_live_llm_response is NOT called
    # if the keyword tool is supposed to provide the final answer.
    # The current /chat logic: if keyword tool hit -> tool_response becomes final_response_text.
    # If NOT Gemini primary path AND no keyword tool hit -> then calls get_live_llm_response.

    response = client.post("/chat", json={
        "user_id": "keyword_user",
        "message": "get chart for MSFT"
    })
    assert response.status_code == 200
    data = response.json()

    assert data["tool_used"] == "get_chart_data"
    assert data["tool_response"] == json.dumps(mock_chart_tool_output)
    assert data["response_text"] == json.dumps(mock_chart_tool_output) # As per current main.py logic for keyword tools
    mock_chart_execute.assert_called_once_with(symbol="MSFT")
    mock_llm_response.assert_not_called() # IMPORTANT: LLM should not be called if keyword tool provides response


@patch('llm_chatbot_service.rag.retriever.Retriever.retrieve_relevant_documents')
@patch('llm_chatbot_service.rag.retriever.Retriever.format_documents_for_prompt')
@patch('llm_chatbot_service.main.get_live_llm_response', new_callable=AsyncMock)
def test_chat_with_rag_augmentation(mock_get_live_llm_response, mock_format_docs, mock_retrieve_docs):
    mock_retrieve_docs.return_value = [{"id": "doc1", "content": "RAG content"}]
    mock_rag_context = "---RAG Context---\nDoc1: RAG content\n---End RAG---"
    mock_format_docs.return_value = mock_rag_context

    # Mock LLM's final response after RAG + original query
    mock_get_live_llm_response.return_value = ("Response with RAG.", None, None, None)

    user_message = "What is RAG?"
    response = client.post("/chat", json={"user_id": "rag_user", "message": user_message, "session_id": "rag_session"})

    assert response.status_code == 200
    data = response.json()
    assert data["response_text"] == "Response with RAG."

    mock_retrieve_docs.assert_called_once_with(user_message, top_k=int(os.getenv("RAG_TOP_K", "3")))
    mock_format_docs.assert_called_once_with([{"id": "doc1", "content": "RAG content"}])

    # Check that get_live_llm_response was called with use_rag=True
    # And that its conversation_history's last user message was augmented
    called_kwargs = mock_get_live_llm_response.call_args[1]
    assert called_kwargs['use_rag'] is True

    history_passed_to_llm = called_kwargs['conversation_history']
    assert len(history_passed_to_llm) > 0
    last_message_in_history = history_passed_to_llm[-1]
    assert last_message_in_history["role"] == "user"
    # This part is tricky: the RAG context is prepended *inside* get_live_llm_response
    # to the history that *it* then uses. The history that /chat passes to it will have the raw user message.
    # So, we check that use_rag=True was passed. The internal logic of get_live_llm_response handles augmentation.

@patch('llm_chatbot_service.main.get_live_llm_response', new_callable=AsyncMock)
def test_chat_conversation_history(mock_get_live_llm_response):
    session_id = "history_test_session"
    user_id = "history_user"

    # First message
    mock_get_live_llm_response.return_value = ("Response 1", None, None, None)
    client.post("/chat", json={"user_id": user_id, "message": "Message 1", "session_id": session_id})

    args_first_call = mock_get_live_llm_response.call_args_list[0][1] # kwargs of first call
    history_first_call = args_first_call['conversation_history']
    assert len(history_first_call) == 1
    assert history_first_call[0] == {"role": "user", "content": "Message 1"}

    # Second message
    mock_get_live_llm_response.return_value = ("Response 2", None, None, None)
    client.post("/chat", json={"user_id": user_id, "message": "Message 2", "session_id": session_id})

    args_second_call = mock_get_live_llm_response.call_args_list[1][1] # kwargs of second call
    history_second_call = args_second_call['conversation_history']
    assert len(history_second_call) == 3 # User1, Model1, User2
    assert history_second_call[0] == {"role": "user", "content": "Message 1"}
    assert history_second_call[1] == {"role": "model", "content": "Response 1"}
    assert history_second_call[2] == {"role": "user", "content": "Message 2"}

def test_chat_invalid_payload_empty():
    response = client.post("/chat", json={})
    assert response.status_code == 422 # Unprocessable Entity for Pydantic validation error

def test_chat_invalid_payload_missing_fields():
    response = client.post("/chat", json={"user_id": "test_user"}) # Missing 'message'
    assert response.status_code == 422
    response = client.post("/chat", json={"message": "test_message"}) # Missing 'user_id'
    assert response.status_code == 422

# Simplified test for Gemini function calling path indication
@patch.dict(os.environ, {"LLM_API_PROVIDER": "gemini"})
@patch('llm_chatbot_service.main.get_live_llm_response', new_callable=AsyncMock)
def test_chat_gemini_function_call_indication(mock_get_live_llm_response):
    mock_tool_name = "get_chart_data"
    mock_tool_response_str = '{"chart": "data"}'
    mock_final_text = "Here is the chart data you requested."

    # Simulate that get_live_llm_response has handled the two-step Gemini call
    # and returns the final text along with tool details.
    mock_get_live_llm_response.return_value = (mock_final_text, None, mock_tool_name, mock_tool_response_str)

    response = client.post("/chat", json={
        "user_id": "gemini_fc_user",
        "message": "show me chart for AAPL",
        "session_id": "gemini_fc_session"
    })

    assert response.status_code == 200
    data = response.json()
    assert data["response_text"] == mock_final_text
    assert data["tool_used"] == mock_tool_name
    assert data["tool_response"] == mock_tool_response_str

    mock_get_live_llm_response.assert_called_once()
    call_args = mock_get_live_llm_response.call_args[1]
    assert call_args['user_message'] == "show me chart for AAPL"
    assert call_args['use_rag'] is True # As per current logic for Gemini path
    assert call_args['is_code_generation_request'] is False
    assert len(call_args['conversation_history']) == 1 # User message "show me chart for AAPL"
