from typing import List, Dict, Any, Optional
import numpy as np
import os
import json
import pathlib # For robust path operations

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    # This print will be replaced by logger in main.py where it's imported, or here if run standalone
    # For standalone, we'd need to configure a basic logger here too.
    # print("Warning: FAISS library not found. Retriever will not function with FAISS indexing.")

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    # print("Warning: Sentence-transformers library not found. Retriever will not function.")

from loguru import logger # Import Loguru

# Default paths for saved index and documents
DEFAULT_INDEX_DIR = pathlib.Path(__file__).parent.resolve() / "rag_index_data"
DEFAULT_INDEX_PATH = DEFAULT_INDEX_DIR / "faiss.index"
DEFAULT_DOCUMENTS_PATH = DEFAULT_INDEX_DIR / "documents.json"


MOCK_KB_DOCUMENTS = [
    {
        "id": "doc_1",
        "source": "Platform FAQ",
        "content": "Market orders are executed at the best available current price. They are fast but price is not guaranteed.",
        "metadata": {"topic": "order types", "keywords": ["market order", "execution", "price"]}
    },
    {
        "id": "doc_2",
        "source": "Platform FAQ",
        "content": "Limit orders allow you to set a specific price at which you want to buy or sell. The order will only fill at that price or better.",
        "metadata": {"topic": "order types", "keywords": ["limit order", "execution", "price guarantee"]}
    },
    {
        "id": "doc_3",
        "source": "Trading Basics Guide",
        "content": "Slippage refers to the difference between the expected price of a trade and the price at which the trade is actually executed.",
        "metadata": {"topic": "trading concepts", "keywords": ["slippage", "execution", "price difference"]}
    },
    {
        "id": "doc_4",
        "source": "Platform Documentation",
        "content": "To view your current portfolio, navigate to the 'Portfolio' tab in the main dashboard. It shows your cash balance and positions.",
        "metadata": {"topic": "platform features", "keywords": ["portfolio", "dashboard", "positions", "cash"]}
    },
    {
        "id": "doc_5",
        "source": "Risk Management Guide",
        "content": "Stop-loss orders are designed to limit an investor's loss on a security position. Setting a stop-loss order for 10% below the price at which you bought the stock will limit your loss to 10%.",
        "metadata": {"topic": "order types", "keywords": ["stop-loss", "risk management", "loss limit"]}
    },
    {
        "id": "doc_6",
        "source": "API Documentation",
        "content": "The API rate limit is 100 requests per minute. Exceeding this limit will result in a 429 error.",
        "metadata": {"topic": "platform features", "keywords": ["api", "rate limit", "error", "programming"]}
    }
]

class Retriever:
    """
    Retrieves relevant documents from a knowledge base using FAISS and sentence embeddings.
    Supports loading/saving the index and ingesting documents from a directory.
    """
    def __init__(self,
                 embedding_model_name: str = 'all-MiniLM-L6-v2',
                 index_path: Optional[str] = None,
                 documents_path: Optional[str] = None,
                 documents_to_build_from: Optional[List[Dict[str, Any]]] = None):
        """
        Initializes the Retriever.
        - embedding_model_name: Name of the SentenceTransformer model.
        - index_path: Path to load a pre-built FAISS index.
        - documents_path: Path to load corresponding documents.
        - documents_to_build_from: A list of documents to build a new index from if not loading.
        """
        if not FAISS_AVAILABLE or not SENTENCE_TRANSFORMERS_AVAILABLE:
            self.embedding_model = None
            self.index = None
            self.documents: List[Dict[str, Any]] = []
            logger.error("FAISS or SentenceTransformers not available. Retriever is non-functional.")
            return

        self.documents: List[Dict[str, Any]] = []
        self.index = None
        self.embedding_model_name = embedding_model_name

        try:
            logger.info(f"Retriever: Initializing SentenceTransformer model '{embedding_model_name}'...")
            self.embedding_model = SentenceTransformer(embedding_model_name)
            logger.info("Retriever: Embedding model loaded successfully.")
        except Exception as e:
            logger.exception(f"Error loading SentenceTransformer model '{embedding_model_name}'.", error=e)
            self.embedding_model = None
            return

        _index_path = pathlib.Path(index_path) if index_path else DEFAULT_INDEX_PATH
        _documents_path = pathlib.Path(documents_path) if documents_path else DEFAULT_DOCUMENTS_PATH

        if _index_path.exists() and _documents_path.exists():
            logger.info(f"Retriever: Attempting to load index from '{_index_path}' and documents from '{_documents_path}'.")
            self._load_index_and_documents(str(_index_path), str(_documents_path))
        elif documents_to_build_from:
            logger.info("Retriever: Building new index from provided documents.")
            self._build_index(documents_to_build_from)
        elif MOCK_KB_DOCUMENTS and not documents_to_build_from and not (index_path and documents_path) :
            logger.info("Retriever: No specific index or documents provided, building index from MOCK_KB_DOCUMENTS.")
            self._build_index(MOCK_KB_DOCUMENTS)
        else:
            logger.warning("Retriever initialized with no documents or pre-built index. It will not be able to retrieve.")


    def _build_index(self, documents: List[Dict[str, Any]]):
        """
        Builds the FAISS index from the provided documents.
        """
        if not self.embedding_model or not FAISS_AVAILABLE:
            logger.error("Retriever (_build_index): Cannot build index, embedding model or FAISS not available.")
            return

        if not documents:
            logger.warning("Retriever (_build_index): No documents provided to build index.")
            self.documents = []
            self.index = None
            return

        self.documents = documents
        contents = [doc.get('content', '') for doc in self.documents]

        try:
            logger.info(f"Retriever (_build_index): Embedding {len(contents)} documents for FAISS index...")
            embeddings = self.embedding_model.encode(contents, convert_to_tensor=False, show_progress_bar=True) # show_progress_bar can be noisy for many calls

            if not isinstance(embeddings, np.ndarray) or embeddings.ndim != 2:
                logger.error(f"Retriever (_build_index): Embeddings are not a valid NumPy array or have incorrect dimensions. Shape: {getattr(embeddings, 'shape', 'N/A')}")
                self.index = None
                return

            if embeddings.dtype != np.float32:
                embeddings = embeddings.astype(np.float32)

            logger.info(f"Retriever (_build_index): Embeddings generated with shape: {embeddings.shape}")

            dimension = embeddings.shape[1]
            if dimension == 0:
                 logger.error("Retriever (_build_index): Embedding dimension is 0. Cannot build index.")
                 self.index = None
                 return

            self.index = faiss.IndexFlatL2(dimension)
            self.index.add(embeddings)
            logger.info(f"Retriever (_build_index): FAISS index built successfully with {self.index.ntotal} documents.")
        except Exception as e:
            logger.exception("Error building FAISS index.", error=e)
            self.index = None

    def _load_index_and_documents(self, index_path: str, documents_path: str):
        """Loads the FAISS index and documents from specified paths."""
        if not self.embedding_model:
            logger.error("Retriever (_load_index_and_documents): Embedding model not loaded. Cannot proceed.")
            return
        try:
            logger.info(f"Retriever: Loading FAISS index from '{index_path}'...")
            self.index = faiss.read_index(index_path)
            logger.info(f"Retriever: FAISS index loaded successfully with {self.index.ntotal} entries.")

            logger.info(f"Retriever: Loading documents from '{documents_path}'...")
            with open(documents_path, 'r', encoding='utf-8') as f:
                self.documents = json.load(f)
            logger.info(f"Retriever: Documents loaded successfully ({len(self.documents)} documents).")
        except Exception as e:
            logger.exception(f"Error loading index or documents from {index_path} / {documents_path}.", error=e)
            self.index = None
            self.documents = []

    def save_index_and_documents(self, index_path: Optional[str] = None, documents_path: Optional[str] = None):
        """Saves the FAISS index and documents to specified paths."""
        if not self.index or not self.documents:
            logger.warning("Retriever: No index or documents to save.")
            return

        _index_path = pathlib.Path(index_path) if index_path else DEFAULT_INDEX_PATH
        _documents_path = pathlib.Path(documents_path) if documents_path else DEFAULT_DOCUMENTS_PATH

        _index_path.parent.mkdir(parents=True, exist_ok=True)
        _documents_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            logger.info(f"Retriever: Saving FAISS index to '{_index_path}'...")
            faiss.write_index(self.index, str(_index_path))
            logger.info("Retriever: FAISS index saved successfully.")

            logger.info(f"Retriever: Saving documents to '{_documents_path}'...")
            with open(_documents_path, 'w', encoding='utf-8') as f:
                json.dump(self.documents, f, indent=4)
            logger.info("Retriever: Documents saved successfully.")
        except Exception as e:
            logger.exception(f"Error saving index or documents to {_index_path} / {_documents_path}.", error=e)

    @staticmethod
    def ingest_documents_from_directory(dir_path: str, embedding_model_name: str = 'all-MiniLM-L6-v2') -> 'Retriever':
        """
        Scans a directory for .txt and .md files, creates document dictionaries,
        and returns a new Retriever instance with an index built from these documents.
        """
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            logger.error("Retriever (ingest_documents_from_directory): SentenceTransformers not available. Cannot create retriever.")
            return Retriever(embedding_model_name=embedding_model_name, documents_to_build_from=[])


        doc_list: List[Dict[str, Any]] = []
        abs_dir_path = pathlib.Path(dir_path).resolve()
        logger.info(f"Retriever: Ingesting documents from directory: '{abs_dir_path}'")

        for filename in os.listdir(abs_dir_path):
            file_path = abs_dir_path / filename
            if file_path.is_file() and (filename.endswith(".txt") or filename.endswith(".md")):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    doc_list.append({
                        "id": filename,
                        "source": str(file_path),
                        "content": content,
                        "metadata": {"ingested_from": str(abs_dir_path)}
                    })
                    logger.debug(f"Retriever: Successfully read '{filename}'.")
                except Exception as e:
                    logger.exception(f"Retriever: Error reading file '{filename}'.", error=e)

        if not doc_list:
            logger.warning(f"Retriever: No .txt or .md files found or read in '{abs_dir_path}'.")

        return Retriever(embedding_model_name=embedding_model_name, documents_to_build_from=doc_list)

    def retrieve_relevant_documents(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """
        Queries the FAISS index for documents relevant to the user's query.
        """
        if not self.index or not self.embedding_model:
            logger.warning("Retriever: Index or embedding model not available. Cannot retrieve documents.")
            return []

        if not query:
            logger.warning("Retriever: Query is empty. Cannot retrieve documents.")
            return []

        logger.info(f"Retriever: Received query: '{query[:100]}...', finding top {top_k} documents.", query_snippet=query[:100], top_k=top_k)
        try:
            query_embedding = self.embedding_model.encode([query])
            if query_embedding.dtype != np.float32:
                query_embedding = query_embedding.astype(np.float32)

            distances, indices = self.index.search(query_embedding, top_k)

            retrieved_docs = [self.documents[i] for i in indices[0] if 0 <= i < len(self.documents)]
            logger.info(f"Retriever: Found {len(retrieved_docs)} relevant documents using semantic search for query snippet: '{query[:50]}...'.",
                        num_retrieved=len(retrieved_docs), query_snippet=query[:50])
            return retrieved_docs
        except Exception as e:
            logger.exception(f"Error during FAISS search for query: '{query[:50]}...'.", error=e, query_snippet=query[:50])
            return []

    def format_documents_for_prompt(self, documents: List[Dict[str, Any]]) -> str:
        """
        Formats the retrieved documents into a string to be included in the LLM prompt.
        """
        if not documents:
            return "No relevant documents found in knowledge base."

        formatted_text = "--- Relevant Information from Knowledge Base ---\n"
        for i, doc in enumerate(documents):
            formatted_text += f"\nDocument {i+1} (Source: {doc.get('source', 'N/A')}):\n"
            formatted_text += doc.get('content', 'No content.') + "\n"
        formatted_text += "\n--- End of Relevant Information ---\n"
        return formatted_text

# (The rest of the conceptual explanation comments can remain as they are)
# ...

if __name__ == '__main__':
    # Basic Loguru setup for testing this module directly
    import sys
    logger.remove() # Remove default handler if it exists
    logger.add(sys.stderr, level="DEBUG", format="{time} {level} {message} | {extra}")


    if not FAISS_AVAILABLE or not SENTENCE_TRANSFORMERS_AVAILABLE:
        logger.warning("FAISS or SentenceTransformers not installed. Skipping Retriever full test.")
    else:
        logger.info("\n--- Test 1: Initializing Retriever with MOCK_KB_DOCUMENTS ---")
        retriever_mock = Retriever(embedding_model_name='all-MiniLM-L6-v2')
        if retriever_mock.embedding_model and retriever_mock.index:
            logger.info("Retriever (from MOCK) initialized successfully.")
            docs = retriever_mock.retrieve_relevant_documents("Information about market execution", top_k=1)
            logger.info(f"Retrieved for 'market execution' (from MOCK): {json.dumps(docs, indent=2)}")
        else:
            logger.error("Failed to initialize Retriever with MOCK_KB_DOCUMENTS.")

        logger.info("\n\n--- Test 2: Full Ingestion, Save, Load, Query Cycle ---")
        TEST_DOC_DIR = pathlib.Path("./temp_kb_docs")
        TEST_DOC_DIR.mkdir(parents=True, exist_ok=True)

        INDEX_FILE_PATH = DEFAULT_INDEX_DIR / "test_faiss.index"
        DOCS_FILE_PATH = DEFAULT_INDEX_DIR / "test_documents.json"

        if INDEX_FILE_PATH.exists(): INDEX_FILE_PATH.unlink()
        if DOCS_FILE_PATH.exists(): DOCS_FILE_PATH.unlink()

        sample_files_content = {
            "doc_A.txt": "Alpha is the first letter. It often signifies the beginning or the primary position.",
            "doc_B.md": "# Beta Information\nBeta is the second letter. In finance, it measures volatility.",
            "doc_C.txt": "Charlie represents the third item. It is commonly used in phonetic alphabets."
        }
        for fname, content in sample_files_content.items():
            with open(TEST_DOC_DIR / fname, 'w', encoding='utf-8') as f:
                f.write(content)

        logger.info(f"\nStep 2a: Ingesting documents from '{TEST_DOC_DIR}'...")
        retriever_ingested = Retriever.ingest_documents_from_directory(str(TEST_DOC_DIR))

        if retriever_ingested.embedding_model and retriever_ingested.index and retriever_ingested.documents:
            logger.info("Retriever (from directory) initialized successfully after ingestion.")

            logger.info(f"\nStep 2b: Saving index to '{INDEX_FILE_PATH}' and documents to '{DOCS_FILE_PATH}'...")
            retriever_ingested.save_index_and_documents(str(INDEX_FILE_PATH), str(DOCS_FILE_PATH))

            logger.info("\nStep 2c: Creating new Retriever instance by loading from saved files...")
            retriever_loaded = Retriever(
                embedding_model_name='all-MiniLM-L6-v2',
                index_path=str(INDEX_FILE_PATH),
                documents_path=str(DOCS_FILE_PATH)
            )

            if retriever_loaded.embedding_model and retriever_loaded.index and retriever_loaded.documents:
                logger.info("Retriever (loaded from files) initialized successfully.")

                query1 = "What is alpha?"
                logger.info(f"\nTesting loaded retriever with query: '{query1}'")
                docs1 = retriever_loaded.retrieve_relevant_documents(query1, top_k=1)
                logger.info(f"Retrieved for '{query1}': {json.dumps(docs1, indent=2)}")
                if docs1 and "Alpha is the first letter" in docs1[0]['content']:
                    logger.info(f"Correct document for '{query1}' retrieved by loaded retriever.")
                else:
                    logger.error(f"FAILED: Incorrect or no document for '{query1}' by loaded retriever.")

                query2 = "Tell me about financial beta."
                logger.info(f"\nTesting loaded retriever with query: '{query2}'")
                docs2 = retriever_loaded.retrieve_relevant_documents(query2, top_k=1)
                logger.info(f"Retrieved for '{query2}': {json.dumps(docs2, indent=2)}")
                if docs2 and "finance, it measures volatility" in docs2[0]['content']:
                     logger.info(f"Correct document for '{query2}' retrieved by loaded retriever.")
                else:
                    logger.error(f"FAILED: Incorrect or no document for '{query2}' by loaded retriever.")
            else:
                logger.error("Failed to initialize Retriever from saved files.")
        else:
            logger.error("Failed to initialize Retriever from directory ingestion.")

        logger.info("\nCleaning up temporary test files and directory...")
        for fname in sample_files_content.keys():
            if (TEST_DOC_DIR / fname).exists():
                (TEST_DOC_DIR / fname).unlink()
        if TEST_DOC_DIR.exists():
            TEST_DOC_DIR.rmdir()
        logger.info("Cleanup complete.")
