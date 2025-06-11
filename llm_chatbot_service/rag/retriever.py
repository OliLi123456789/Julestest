# llm_chatbot_service/rag/retriever.py
import os
import logging
import json
from typing import List, Dict, Any, Optional

# Assuming config_llm is in the parent directory of rag
try:
    from ..config_llm import llm_service_config
except ImportError: # Fallback for direct execution or if path is not set up as expected
    if __name__ == '__main__':
        import sys
        sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..')) # Add root 'llm_chatbot_service' parent
        from llm_chatbot_service.config_llm import llm_service_config
    else: raise


# Conditional imports for actual libraries vs. mocks
try:
    import faiss
    from sentence_transformers import SentenceTransformer
    FAISS_ST_AVAILABLE_RETR = True
    import numpy as np # Required for FAISS and SentenceTransformer operations
except ImportError:
    FAISS_ST_AVAILABLE_RETR = False
    # Mock classes if actual libraries are not available
    class MockSentenceTransformerRetriever:
        def __init__(self, model_name_or_path: str):
            self.model_name = model_name_or_path
            logging.warning("MockSentenceTransformer used in Retriever.")
        def encode(self, texts: List[str], convert_to_numpy: bool = False) -> Any: # Should be np.ndarray
            logging.debug(f"Retriever MockEncode called for query: {texts}")
            # Try to import numpy for mock array, otherwise return list of lists
            try: import numpy as np_mock_ret; return np_mock_ret.random.rand(len(texts), 384).astype('float32')
            except ImportError: return [[0.0]*384 for _ in texts]

    class MockFaissIndexRetriever:
        def __init__(self, dimension: Optional[int] = None): # Dimension not strictly needed for this mock's search
            self.ntotal = 0
            logging.warning("MockFaissIndexRetriever used.")
        def search(self, query_embedding: Any, top_k: int) -> tuple[Any, Any]:
            logging.debug(f"Retriever MockSearch called. Query embedding shape: {query_embedding.shape if hasattr(query_embedding, 'shape') else 'N/A'}")
            # Return empty arrays of the correct expected dimensions if possible
            try: import numpy as np_mock_ret; return (np_mock_ret.array([[]], dtype='float32'), np_mock_ret.array([[]], dtype='int64'))
            except ImportError: return ([], [])

    # Replace actuals with mocks if import failed
    SentenceTransformer = MockSentenceTransformerRetriever
    faiss_module_mock_retriever = type('FaissModuleRetrieverMock', (object,), {
        'read_index': lambda path: logging.warning(f"MockFAISS read_index called for {path}") or MockFaissIndexRetriever(),
        # Add IndexFlatL2 for build_rag_index if it's also mocked there and imported here
    })
    faiss = faiss_module_mock_retriever
    if 'np' not in globals(): # If real numpy didn't load, try for mocks
        try: import numpy as np; logging.info("Retriever: Loaded real numpy for mocks.")
        except ImportError: logging.error("Retriever: Numpy could not be loaded for mocks."); np = None


logger = logging.getLogger(f"LLMChatbotService.rag.{__name__}")

class Retriever:
    def __init__(self):
        self.embedding_model_name = llm_service_config.embedding_model_name
        self.index_path = llm_service_config.rag_index_path
        self.chunk_data_path = self.index_path + "_chunks.json"

        self.model: Optional[SentenceTransformer] = None
        self.index: Optional[Any] = None # faiss.Index
        self.chunks_with_meta: List[Dict[str, Any]] = []

        self._load_resources()

    def _load_resources(self):
        if not FAISS_ST_AVAILABLE_RETR:
            logger.error("Retriever: FAISS or SentenceTransformers library not available. RAG functionality will be disabled.")
            return
        try:
            logger.info(f"Retriever: Loading sentence embedding model: {self.embedding_model_name}...")
            self.model = SentenceTransformer(self.embedding_model_name)
            logger.info("Retriever: Sentence embedding model loaded.")

            if os.path.exists(self.index_path) and os.path.exists(self.chunk_data_path):
                logger.info(f"Retriever: Loading FAISS index from: {self.index_path}")
                self.index = faiss.read_index(self.index_path)
                logger.info(f"Retriever: FAISS index loaded. Total vectors: {self.index.ntotal if self.index and hasattr(self.index, 'ntotal') else 'N/A (Mock? Index not loaded)'}")

                with open(self.chunk_data_path, 'r', encoding='utf-8') as f:
                    self.chunks_with_meta = json.load(f)
                logger.info(f"Retriever: Loaded {len(self.chunks_with_meta)} chunk metadata entries from: {self.chunk_data_path}")
            else:
                logger.warning(f"Retriever: FAISS index file ('{self.index_path}') or chunk data file ('{self.chunk_data_path}') not found. "
                               "RAG will not return results. Please run build_rag_index.py first.")
        except Exception as e:
            logger.error(f"Retriever: Error loading RAG resources: {e}", exc_info=True)
            self.model = None # Ensure reset on error
            self.index = None
            self.chunks_with_meta = []

    def retrieve_relevant_documents(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        if not self.index or not self.model or not self.chunks_with_meta or (hasattr(self.index, 'ntotal') and self.index.ntotal == 0):
            logger.warning("Retriever: RAG resources not loaded, index is empty, or dependencies missing. Cannot retrieve.")
            # Return a system message rather than an empty list if search cannot be performed.
            return [{"source": "System Note", "chunk_id": "rag_unavailable", "content": "Knowledge Base lookup is currently unavailable due to missing resources or empty index."}]

        logger.debug(f"Retriever: Retrieving documents for query='{query[:50]}...', top_k={top_k}")
        try:
            # Ensure query embedding is 2D array for FAISS
            query_embedding = self.model.encode([query], convert_to_numpy=True) # Ensure np output for FAISS
            if not isinstance(query_embedding, np.ndarray): # Should be handled by convert_to_numpy=True
                 query_embedding = np.array(query_embedding).astype('float32')
            if query_embedding.ndim == 1:
                 query_embedding = np.expand_dims(query_embedding, axis=0)

            # Ensure top_k is not greater than the number of items in the index
            actual_top_k = min(top_k, self.index.ntotal if hasattr(self.index, 'ntotal') else top_k)
            if actual_top_k == 0 : # If index is empty after all
                logger.warning("Retriever: FAISS index is empty, cannot perform search.")
                return []

            distances, indices = self.index.search(query_embedding, actual_top_k)

            retrieved_docs = []
            if indices.size > 0: # Check if any indices were returned
                for i in range(indices.shape[1]): # Iterate through columns of the first (and only) row of indices
                    idx = indices[0, i]
                    if 0 <= idx < len(self.chunks_with_meta): # Ensure index is valid
                        retrieved_docs.append(self.chunks_with_meta[idx])
                    else:
                        logger.warning(f"Retriever: Invalid index {idx} from FAISS search. Max index: {len(self.chunks_with_meta)-1}")

            logger.info(f"Retriever: Found {len(retrieved_docs)} relevant document chunks for query '{query[:30]}...'.")
            return retrieved_docs
        except Exception as e:
            logger.error(f"Retriever: Error during document retrieval for query '{query[:30]}...': {e}", exc_info=True)
            return [{"source": "System Error", "chunk_id": "retrieval_error", "content": "An error occurred during knowledge base lookup."}]

    def format_documents_for_prompt(self, documents: List[Dict[str, Any]]) -> str:
        if not documents:
            return "No relevant documents found in the knowledge base for this query."
        # Check for system message indicating RAG is unavailable or errored
        if len(documents) == 1 and documents[0].get("source") in ["System Note", "System Error"]:
            return documents[0]["content"] # Return the system message directly

        formatted_text = "--- Relevant Information from Knowledge Base ---\n"
        for i, doc in enumerate(documents):
            source_info = f"Source: {doc.get('source', 'N/A')}"
            if 'chunk_id' in doc: # chunk_id might be redundant if source + content is enough
                # source_info += f", Chunk: {doc.get('chunk_id')}"
                pass
            formatted_text += f"\nDocument {i+1} ({source_info}):\n{doc.get('content', 'No content.')}\n"
        formatted_text += "\n--- End of Relevant Information ---\n"
        return formatted_text

if __name__ == '__main__':
    # Setup basic logging for retriever testing
    # This will use the hierarchical logger if logging_setup.py was imported and used by a caller,
    # or sets up basic if this is run standalone.
    if not logging.getLogger("LLMChatbotService").hasHandlers() and not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    logger_main_retriever = logging.getLogger(f"LLMChatbotService.rag.{__name__}#__main__")
    logger_main_retriever.info("Retriever __main__ test started.")

    # This test assumes that `build_rag_index.py` has been run successfully first,
    # and the FAISS index and chunk data files are available at the configured paths.
    if FAISS_ST_AVAILABLE_RETR and os.path.exists(llm_service_config.rag_index_path) and os.path.exists(llm_service_config.rag_index_path + "_chunks.json"):
        logger_main_retriever.info("Attempting to initialize Retriever with live models and index...")
        retriever_instance = Retriever()

        if retriever_instance.index and retriever_instance.model:
            logger_main_retriever.info("Retriever initialized successfully with live components.")

            test_queries = [
                "How do I place a market order?",
                "What are limit orders?",
                "Tell me about the SDK functions.",
                "What is a P&L statement?" # Might not find specific docs for this
            ]
            for query in test_queries:
                logger_main_retriever.info(f"\n--- Testing RAG with query: '{query}' ---")
                retrieved_documents = retriever_instance.retrieve_relevant_documents(query, top_k=2)
                formatted_prompt_context = retriever_instance.format_documents_for_prompt(retrieved_documents)

                logger_main_retriever.info("\nFormatted documents for LLM prompt:")
                print(formatted_prompt_context) # Print to console for easy viewing
        else:
            logger_main_retriever.error("Retriever components (model or index) failed to load, even though files might exist.")
    else:
        logger_main_retriever.warning("Skipping Retriever __main__ test: FAISS index/chunk data not found at configured paths, "
                           "or FAISS/SentenceTransformers dependencies are missing (using mocks). "
                           "Run build_rag_index.py first if you have the dependencies.")

    logger_main_retriever.info("Retriever __main__ test finished.")
