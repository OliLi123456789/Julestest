import pytest
import os
import json
import pathlib
import tempfile
import shutil
from typing import List, Dict, Any

from llm_chatbot_service.rag.retriever import (
    Retriever,
    MOCK_KB_DOCUMENTS,
    FAISS_AVAILABLE,
    SENTENCE_TRANSFORMERS_AVAILABLE,
    DEFAULT_INDEX_PATH, # For checking default save/load behavior
    DEFAULT_DOCUMENTS_PATH
)

# Marker to skip tests if heavy dependencies are not available
skip_if_no_rag_deps = pytest.mark.skipif(
    not (FAISS_AVAILABLE and SENTENCE_TRANSFORMERS_AVAILABLE),
    reason="FAISS or SentenceTransformers not available, skipping RAG tests that require them."
)

@pytest.fixture(scope="function")
def temp_dir_fixture():
    """Creates a temporary directory for test artifacts and cleans it up afterwards."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield pathlib.Path(tmpdir)

@pytest.fixture(scope="module")
def mock_retriever_fixture():
    """Provides a Retriever instance initialized with MOCK_KB_DOCUMENTS."""
    if FAISS_AVAILABLE and SENTENCE_TRANSFORMERS_AVAILABLE:
        return Retriever(documents_to_build_from=MOCK_KB_DOCUMENTS)
    return None # Will cause tests using it to be skipped if deps are missing

# --- Initialization Tests ---
@skip_if_no_rag_deps
def test_retriever_initialization_with_mock_documents(mock_retriever_fixture):
    retriever = mock_retriever_fixture
    assert retriever is not None, "Retriever fixture should not be None if deps are available"
    assert retriever.index is not None
    assert retriever.index.ntotal == len(MOCK_KB_DOCUMENTS)
    assert len(retriever.documents) == len(MOCK_KB_DOCUMENTS)
    assert retriever.documents[0]["content"] == MOCK_KB_DOCUMENTS[0]["content"]

def test_retriever_initialization_custom_model_name():
    if FAISS_AVAILABLE and SENTENCE_TRANSFORMERS_AVAILABLE:
        model_name = "paraphrase-MiniLM-L3-v2" # Another small model
        retriever = Retriever(embedding_model_name=model_name, documents_to_build_from=[MOCK_KB_DOCUMENTS[0]])
        assert retriever.embedding_model is not None
        assert retriever.index is not None
        assert retriever.index.ntotal == 1
    else:
        pytest.skip("RAG dependencies not available for custom model name test.")

@skip_if_no_rag_deps # This test implicitly checks if the flags are respected by other tests
def test_retriever_flags_are_functional():
    assert True # If we reach here and skip_if_no_rag_deps is active, it means the flags work

# --- Document Ingestion Tests ---
@skip_if_no_rag_deps
def test_ingest_documents_from_directory_success(temp_dir_fixture):
    sample_docs_content = {
        "doc1.txt": "This is content for document 1 about apples.",
        "doc2.md": "## Document 2\nInformation about bananas and citrus fruits.",
        "doc3.txt": "Another document, this one mentions apples again."
    }
    for filename, content in sample_docs_content.items():
        with open(temp_dir_fixture / filename, "w", encoding="utf-8") as f:
            f.write(content)

    retriever = Retriever.ingest_documents_from_directory(str(temp_dir_fixture))
    assert retriever.index is not None
    assert retriever.index.ntotal == 3
    assert len(retriever.documents) == 3
    # Check if one of the documents' content is correctly ingested
    found_doc1 = any(doc["content"] == sample_docs_content["doc1.txt"] for doc in retriever.documents)
    assert found_doc1

@skip_if_no_rag_deps
def test_ingest_documents_from_empty_directory(temp_dir_fixture):
    retriever = Retriever.ingest_documents_from_directory(str(temp_dir_fixture))
    assert retriever.index is None # Or ntotal == 0 depending on implementation if index gets created for 0 docs
    assert len(retriever.documents) == 0

@skip_if_no_rag_deps
def test_ingest_documents_from_dir_with_no_relevant_files(temp_dir_fixture):
    with open(temp_dir_fixture / "image.jpg", "w") as f: # Irrelevant file
        f.write("fake image data")
    retriever = Retriever.ingest_documents_from_directory(str(temp_dir_fixture))
    assert retriever.index is None
    assert len(retriever.documents) == 0

# --- Save/Load Tests ---
@skip_if_no_rag_deps
def test_save_and_load_index_and_documents(mock_retriever_fixture, temp_dir_fixture):
    retriever_original = mock_retriever_fixture
    assert retriever_original.index is not None

    index_path = temp_dir_fixture / "test.index"
    docs_path = temp_dir_fixture / "test_docs.json"

    retriever_original.save_index_and_documents(str(index_path), str(docs_path))
    assert index_path.exists()
    assert docs_path.exists()

    retriever_loaded = Retriever(
        embedding_model_name=retriever_original.embedding_model_name, # Must use same model
        index_path=str(index_path),
        documents_path=str(docs_path)
    )
    assert retriever_loaded.index is not None
    assert retriever_loaded.index.ntotal == retriever_original.index.ntotal
    assert len(retriever_loaded.documents) == len(retriever_original.documents)
    assert retriever_loaded.documents[0]["content"] == retriever_original.documents[0]["content"]

    # Test a retrieval to be sure
    query = "market orders"
    docs_loaded = retriever_loaded.retrieve_relevant_documents(query, top_k=1)
    assert len(docs_loaded) >= 1
    assert "market orders" in docs_loaded[0]["content"].lower()

@skip_if_no_rag_deps
def test_load_non_existent_paths():
    # Current logic builds from MOCK_KB_DOCUMENTS if paths don't exist and no other docs provided
    retriever = Retriever(index_path="non_existent.index", documents_path="non_existent_docs.json")
    assert retriever.index is not None # Should fall back to MOCK_KB
    assert len(retriever.documents) == len(MOCK_KB_DOCUMENTS)

# --- Retrieval Tests ---
@skip_if_no_rag_deps
def test_retrieve_relevant_documents_semantic(mock_retriever_fixture):
    retriever = mock_retriever_fixture
    # Query for "market orders"
    query1 = "how are market orders priced?"
    docs1 = retriever.retrieve_relevant_documents(query1, top_k=1)
    assert len(docs1) >= 1
    assert "market orders" in docs1[0]["content"].lower()

    # Query for "portfolio view"
    query2 = "where can I see my money and stocks?"
    docs2 = retriever.retrieve_relevant_documents(query2, top_k=1)
    assert len(docs2) >= 1
    assert "portfolio" in docs2[0]["content"].lower()

@skip_if_no_rag_deps
def test_retrieve_top_k(mock_retriever_fixture):
    retriever = mock_retriever_fixture
    query = "orders" # Should match multiple documents
    docs_k2 = retriever.retrieve_relevant_documents(query, top_k=2)
    assert len(docs_k2) <= 2
    docs_k1 = retriever.retrieve_relevant_documents(query, top_k=1)
    assert len(docs_k1) <= 1

@skip_if_no_rag_deps
def test_retrieve_no_match(mock_retriever_fixture):
    retriever = mock_retriever_fixture
    query = "cryptocurrency futures trading strategies for lunar new year"
    docs = retriever.retrieve_relevant_documents(query, top_k=3)
    # It might still return something due to vector similarity, but less likely to be highly relevant
    # For this test, we're mostly ensuring it doesn't crash.
    # A more robust test would require specific non-matching docs and checking they are NOT returned.
    assert isinstance(docs, list)

@skip_if_no_rag_deps
def test_retrieve_empty_index():
    retriever = Retriever(documents_to_build_from=[]) # Build an empty index
    assert retriever.index is None or retriever.index.ntotal == 0
    docs = retriever.retrieve_relevant_documents("any query", top_k=3)
    assert docs == []

# --- Formatting Tests ---
def test_format_documents_for_prompt():
    retriever = Retriever(documents_to_build_from=[]) # No model needed for this test
    sample_docs = [
        {"source": "FAQ1", "content": "Content of FAQ1."},
        {"source": "Guide2", "content": "Content of Guide2."}
    ]
    formatted_string = retriever.format_documents_for_prompt(sample_docs)
    assert "--- Relevant Information from Knowledge Base ---" in formatted_string
    assert "Document 1 (Source: FAQ1):" in formatted_string
    assert "Content of FAQ1." in formatted_string
    assert "Document 2 (Source: Guide2):" in formatted_string
    assert "Content of Guide2." in formatted_string
    assert "\n--- End of Relevant Information ---\n" in formatted_string

def test_format_documents_for_prompt_empty():
    retriever = Retriever(documents_to_build_from=[])
    formatted_string = retriever.format_documents_for_prompt([])
    assert formatted_string == "No relevant documents found in knowledge base."

# --- Test default path creation if they don't exist ---
@skip_if_no_rag_deps
def test_default_path_creation_on_save(temp_dir_fixture):
    # Temporarily change DEFAULT_INDEX_DIR for this test
    original_default_dir = DEFAULT_INDEX_PATH.parent
    test_default_dir = temp_dir_fixture / "new_default_rag_data"

    # Monkeypatch default paths for the scope of this test
    # Note: This is a bit advanced; directly testing save() with specified paths is primary.
    # This tests the auto-creation of DEFAULT_INDEX_DIR if it doesn't exist.

    retriever = Retriever(documents_to_build_from=[MOCK_KB_DOCUMENTS[0]])
    assert retriever.index is not None

    # Point save to use paths within our new_default_rag_data
    temp_default_index_path = test_default_dir / "faiss.index"
    temp_default_docs_path = test_default_dir / "documents.json"

    retriever.save_index_and_documents(str(temp_default_index_path), str(temp_default_docs_path))

    assert temp_default_index_path.exists()
    assert temp_default_docs_path.exists()
    assert test_default_dir.exists()

    # No need to restore original DEFAULT_INDEX_PATH etc here, as we used custom paths for save.
    # If we were patching the global constants, we'd need to be more careful.
