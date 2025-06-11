# llm_chatbot_service/rag/build_rag_index.py
import os
import logging
import json
from typing import Any # For type hint of faiss module mock

# Conditional imports for actual libraries vs. mocks for subtask environment
try:
    import faiss
    from sentence_transformers import SentenceTransformer
    FAISS_ST_AVAILABLE = True
    import numpy as np # numpy is essential for FAISS and SentenceTransformer
except ImportError:
    FAISS_ST_AVAILABLE = False
    # Mock classes if actual libraries are not available in the execution environment
    # This allows the script to be imported and basic structure checked, but RAG won't work.
    class MockSentenceTransformer:
        def __init__(self, model_name_or_path: str):
            self.model_name = model_name_or_path
            # Try to get dimension from common model names if possible for mock
            if "all-MiniLM-L6-v2" in model_name_or_path: self._dimension = 384
            elif "all-mpnet-base-v2" in model_name_or_path: self._dimension = 768
            else: self._dimension = 384 # Default mock dimension
            logging.warning(f"MockSentenceTransformer used. Model: {model_name_or_path}, Mock Dimension: {self._dimension}")

        def encode(self, texts: list[str], show_progress_bar: bool = False, convert_to_numpy: bool = True) -> Any: # Should return np.ndarray
            logging.debug(f"MockSentenceTransformer.encode called for {len(texts)} texts.")
            # Ensure numpy is available for this mock to work as expected by FAISS
            try: import numpy as np_mock
            except ImportError: logging.error("Numpy not found for MockSentenceTransformer!"); return []
            return np_mock.random.rand(len(texts), self._dimension).astype('float32')

        def get_sentence_embedding_dimension(self) -> int: # Added for compatibility
             return self._dimension

    class MockFaissIndex:
        def __init__(self, dimension: int):
            self.dimension = dimension
            self.ntotal = 0
            logging.warning(f"MockFaissIndex used with dimension {dimension}.")
        def add(self, embeddings: Any): # Expects np.ndarray
            if hasattr(embeddings, 'shape'): self.ntotal += embeddings.shape[0]
            else: self.ntotal += len(embeddings) # Fallback if not numpy array
        def search(self, query_embedding: Any, top_k: int) -> tuple[Any, Any]:
            logging.debug(f"MockFaissIndex.search called. Returning empty results.")
            try: import numpy as np_mock
            except ImportError: logging.error("Numpy not found for MockFaissIndex search!"); return ([],[])
            return (np_mock.array([[]]), np_mock.array([[]]))


    # Replace actual SentenceTransformer and faiss if they couldn't be imported
    SentenceTransformer = MockSentenceTransformer
    faiss_module_mock = type('FaissModuleMock', (object,), {
        'IndexFlatL2': MockFaissIndex,
        'write_index': lambda idx, path: logging.info(f"MockFAISS: write_index called for path {path} (index has {idx.ntotal} vectors)"),
        'read_index': lambda path: logging.warning(f"MockFAISS: read_index called for {path}, returning new mock index.") or MockFaissIndex(384) # Default dim
    })
    faiss = faiss_module_mock
    # Also ensure numpy is available for the mocks that use it.
    if 'np' not in globals() and 'np_mock' not in globals():
        try: import numpy as np; logging.info("build_rag_index: Loaded real numpy for mocks.")
        except ImportError: logging.error("build_rag_index: Numpy could not be loaded for mocks."); np = None


# Assuming config_llm and document_processor are in paths accessible by Python
# For direct execution, ensure PYTHONPATH is set or this script is run as part of a package.
try:
    from ..config_llm import llm_service_config
    from .document_processor import process_documents_for_rag
except ImportError: # Fallback for standalone execution if path is not set up (e.g. direct run)
    if __name__ == '__main__': # Only do this if script is main, otherwise it's a real import issue
        import sys
        sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..')) # Add root 'llm_chatbot_service' parent
        from llm_chatbot_service.config_llm import llm_service_config
        from llm_chatbot_service.rag.document_processor import process_documents_for_rag
    else: raise


# Setup logger for this script using hierarchical naming
logger = logging.getLogger(f"LLMChatbotService.rag.{__name__}")


def build_and_save_index():
    kb_path = llm_service_config.rag_kb_path
    index_path = llm_service_config.rag_index_path
    embedding_model_name = llm_service_config.embedding_model_name
    chunk_data_path = index_path + "_chunks.json" # Store chunk metadata alongside the index

    # Ensure parent directory for index exists
    index_dir = os.path.dirname(index_path)
    if index_dir: # Check if index_dir is not empty (i.e. not just a filename in current dir)
        os.makedirs(index_dir, exist_ok=True)
    else: # If index_path is just a filename, use current directory for chunk_data_path too
        chunk_data_path = os.path.basename(index_path) + "_chunks.json"


    logger.info(f"Starting RAG index build. Knowledge Base Dir: '{kb_path}', FAISS Index Path: '{index_path}', Embedding Model: '{embedding_model_name}'")

    if not FAISS_ST_AVAILABLE:
        logger.warning("FAISS or SentenceTransformers library not found. Using MOCKS. The generated index will be non-functional for real searches but allows testing the pipeline structure.")

    all_chunks_with_meta = process_documents_for_rag(kb_path)

    if not all_chunks_with_meta:
        logger.warning("No document chunks found to process. Attempting to save an empty index (if possible with mocks/FAISS).")
        # Create a dummy model instance just to get the expected dimension for mock faiss index
        try:
            temp_model_for_dim = SentenceTransformer(embedding_model_name)
            dimension = temp_model_for_dim.get_sentence_embedding_dimension() # Requires this method on mock too
        except Exception as e_dim:
            logger.error(f"Could not determine embedding dimension for empty index: {e_dim}. Defaulting to 384.")
            dimension = 384 # Fallback dimension

        empty_faiss_index = faiss.IndexFlatL2(dimension)
        try:
            faiss.write_index(empty_faiss_index, index_path)
            with open(chunk_data_path, 'w', encoding='utf-8') as f:
                json.dump([], f)
            logger.info("Empty FAISS index and chunk data file saved.")
        except Exception as e_save_empty:
            logger.error(f"Error saving empty FAISS index or chunk data: {e_save_empty}", exc_info=True)
        return

    chunk_texts = [chunk['content'] for chunk in all_chunks_with_meta]

    logger.info(f"Initializing sentence transformer model: {embedding_model_name}")
    model = SentenceTransformer(embedding_model_name)

    logger.info(f"Generating embeddings for {len(chunk_texts)} text chunks...")
    # show_progress_bar=True is good for long processes if run in a console that supports it.
    embeddings = model.encode(chunk_texts, show_progress_bar=False, convert_to_numpy=True) # Ensure numpy array output

    # Ensure embeddings are numpy array of float32, as FAISS expects
    if not isinstance(embeddings, np.ndarray):
        embeddings_np = np.array(embeddings).astype('float32')
    else:
        embeddings_np = embeddings.astype('float32')

    logger.info(f"Embeddings generated. Shape: {embeddings_np.shape}")

    dimension = embeddings_np.shape[1]
    faiss_index = faiss.IndexFlatL2(dimension) # Using a simple L2 distance index
    faiss_index.add(embeddings_np)
    logger.info(f"FAISS index built. Total vectors added: {faiss_index.ntotal}")

    try:
        faiss.write_index(faiss_index, index_path)
        logger.info(f"FAISS index saved successfully to: {index_path}")
    except Exception as e_write_idx:
        logger.error(f"Error writing FAISS index to {index_path}: {e_write_idx}", exc_info=True)
        return # Stop if index cannot be saved

    try:
        with open(chunk_data_path, 'w', encoding='utf-8') as f:
            json.dump(all_chunks_with_meta, f, indent=2)
        logger.info(f"Chunk metadata saved successfully to: {chunk_data_path}")
    except Exception as e_write_chunks:
        logger.error(f"Error writing chunk metadata to {chunk_data_path}: {e_write_chunks}", exc_info=True)

    logger.info("RAG index and metadata build process complete.")

if __name__ == '__main__':
    # Setup logging for the script itself if it's not configured by a higher-level setup
    # This uses the hierarchical logger defined above if logging_setup was imported and used.
    # If not, it will configure a basic logger for this run.
    if not logging.getLogger("LLMChatbotService").hasHandlers() and not logging.getLogger().hasHandlers():
         logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    logger.info("Running RAG index build process from __main__...")

    # Ensure knowledge_base directory exists for the __main__ test, using path from config
    kb_dir_for_test = llm_service_config.rag_kb_path
    if not os.path.exists(kb_dir_for_test):
        logger.info(f"Knowledge base directory '{kb_dir_for_test}' not found. Creating it for test.")
        os.makedirs(kb_dir_for_test, exist_ok=True)

    # Create dummy KB files if they don't exist for the __main__ test
    faq_path = os.path.join(kb_dir_for_test, "faq_platform.md")
    sdk_notes_path = os.path.join(kb_dir_for_test, "sdk_notes.txt")

    if not os.path.exists(faq_path):
        with open(faq_path, "w", encoding="utf-8") as f:
            f.write("# Platform FAQ Snippet\n\n## How to submit a LIMIT order?\nUse `sdk.submit_order(symbol='XYZ', order_type='LIMIT', quantity=10, price=100.50)`.\n")
        logger.info(f"Created dummy FAQ file: {faq_path}")

    if not os.path.exists(sdk_notes_path):
        with open(sdk_notes_path, "w", encoding="utf-8") as f:
            f.write("The SDK is used for trading. Key functions: submit_order, get_market_data.")
        logger.info(f"Created dummy SDK notes file: {sdk_notes_path}")

    build_and_save_index()
    logger.info("RAG index build script __main__ finished.")
