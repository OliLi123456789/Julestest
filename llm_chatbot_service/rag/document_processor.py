# llm_chatbot_service/rag/document_processor.py
import os
import logging
from typing import List, Dict, Any

# Use hierarchical logger
logger = logging.getLogger(f"LLMChatbotService.rag.{__name__}")

def load_documents_from_directory(dir_path: str) -> List[Dict[str, Any]]:
    """
    Loads all .txt and .md files from a specified directory.
    Each document is returned as a dictionary with 'source' (filename) and 'content'.
    """
    documents = []
    if not os.path.isdir(dir_path):
        logger.warning(f"Knowledge base directory not found or is not a directory: {dir_path}")
        return documents

    for filename in os.listdir(dir_path):
        filepath = os.path.join(dir_path, filename)
        if os.path.isfile(filepath) and (filename.lower().endswith(".txt") or filename.lower().endswith(".md")):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                documents.append({"source": filename, "content": content})
                logger.debug(f"Successfully loaded document: {filename}")
            except Exception as e:
                logger.error(f"Error loading document {filepath}: {e}", exc_info=True)

    logger.info(f"Loaded {len(documents)} documents from directory: {dir_path}")
    return documents

def chunk_document_content(doc_content: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[str]:
    """
    Splits a document's content into overlapping chunks.
    :param doc_content: The text content of the document.
    :param chunk_size: The desired maximum size of each chunk (in characters).
    :param chunk_overlap: The number of characters to overlap between consecutive chunks.
    :return: A list of text chunks.
    """
    if not doc_content:
        return []

    chunks = []
    current_pos = 0
    content_len = len(doc_content)

    while current_pos < content_len:
        end_pos = min(current_pos + chunk_size, content_len)
        chunk = doc_content[current_pos:end_pos]
        chunks.append(chunk)

        if end_pos == content_len: # Reached the end of the document
            break

        # Move current_pos for the next chunk, considering overlap
        current_pos += (chunk_size - chunk_overlap)

        # Safety break if something is wrong with overlap logic, though unlikely with min check above
        if current_pos >= end_pos and end_pos != content_len : # Avoid infinite loop if overlap >= chunk_size
             logger.warning(f"Chunking issue: current_pos {current_pos} not advancing past end_pos {end_pos}. Resetting to advance.")
             current_pos = end_pos # Force advance

    # Filter out very small or whitespace-only chunks that might result from aggressive overlap or empty sections
    meaningful_chunks = [chk for chk in chunks if len(chk.strip()) > 10]
    if not meaningful_chunks and chunks: # If all chunks were tiny, keep at least one original if it had some content
        if len(doc_content.strip()) > 10: return [doc_content.strip()[:chunk_size]] # Return first part

    return meaningful_chunks


def process_documents_for_rag(dir_path: str, chunk_size: int = 500, chunk_overlap: int = 50) -> List[Dict[str, Any]]:
    """
    Loads documents from a directory and processes them into text chunks with metadata.
    Each chunk dict includes 'source', 'chunk_id', and 'content'.
    """
    raw_docs = load_documents_from_directory(dir_path)
    all_chunks_with_meta = []

    if not raw_docs:
        logger.warning(f"No documents found in {dir_path} to process for RAG.")
        return all_chunks_with_meta

    for doc_idx, doc in enumerate(raw_docs):
        doc_content = doc.get("content", "")
        doc_source = doc.get("source", f"unknown_doc_{doc_idx}")

        content_chunks = chunk_document_content(doc_content, chunk_size, chunk_overlap)

        for chunk_idx, chunk_text in enumerate(content_chunks):
            chunk_id = f"{doc_source}_chunk_{chunk_idx}"
            all_chunks_with_meta.append({
                "source": doc_source,
                "chunk_id": chunk_id,
                "content": chunk_text
            })
            logger.debug(f"Created chunk: {chunk_id} from source: {doc_source}")

    logger.info(f"Processed {len(raw_docs)} documents into a total of {len(all_chunks_with_meta)} text chunks.")
    return all_chunks_with_meta

if __name__ == '__main__':
    # Configure basic logging for standalone testing of this module
    if not logger.handlers: # Avoid adding handlers if already configured by a root setup
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Create dummy knowledge_base for testing if it doesn't exist
    test_kb_dir = "../../knowledge_base_test_doc_proc" # Relative to this file's location
    if not os.path.exists(test_kb_dir):
        os.makedirs(test_kb_dir, exist_ok=True)
        with open(os.path.join(test_kb_dir, "test_faq.md"), "w") as f:
            f.write("# Test FAQ\n\nQ1: What is RAG?\nA1: Retrieval Augmented Generation.\n\nQ2: How big are chunks?\nA2: About 500 chars.")
        with open(os.path.join(test_kb_dir, "test_notes.txt"), "w") as f:
            f.write("These are some important notes about the system. Sentence one. Sentence two. Sentence three is a bit longer and might be split. Sentence four follows closely.")
        logger.info(f"Created dummy files in {test_kb_dir} for testing document_processor.")

    logger.info("\n--- Testing load_documents_from_directory ---")
    docs = load_documents_from_directory(test_kb_dir)
    for d in docs:
        logger.info(f"Loaded: {d['source']} (Content length: {len(d['content'])})")
    assert len(docs) == 2

    logger.info("\n--- Testing chunk_document_content ---")
    sample_text = "This is the first sentence. This is the second sentence, which is a bit longer. The third sentence provides even more details and context. Finally, the fourth sentence concludes this small paragraph."
    chunks = chunk_document_content(sample_text, chunk_size=50, chunk_overlap=10)
    logger.info(f"Chunked sample_text (size 50, overlap 10) into {len(chunks)} chunks:")
    for i,c in enumerate(chunks): logger.info(f"  Chunk {i}: '{c}' (len: {len(c)})")
    # Expected: "This is the first sentence. This is the second se", "sentence, which is a bit longer. The third sent", etc.
    assert len(chunks) > 1
    assert chunks[0].startswith("This is the first")
    assert chunks[1].startswith(sample_text[50-10:]) # Check overlap start

    logger.info("\n--- Testing process_documents_for_rag ---")
    processed_chunks = process_documents_for_rag(test_kb_dir, chunk_size=100, chunk_overlap=20)
    logger.info(f"Processed into {len(processed_chunks)} total chunks with metadata:")
    for i, pc in enumerate(processed_chunks[:3]): # Print first 3
        logger.info(f"  Chunk {i}: Source='{pc['source']}', ID='{pc['chunk_id']}', Content='{pc['content'][:50]}...'")
    assert len(processed_chunks) > 0
    if processed_chunks:
      assert "source" in processed_chunks[0]
      assert "chunk_id" in processed_chunks[0]
      assert "content" in processed_chunks[0]

    # Clean up dummy directory after test
    # import shutil
    # if os.path.exists(test_kb_dir):
    #     shutil.rmtree(test_kb_dir)
    #     logger.info(f"Cleaned up test directory: {test_kb_dir}")
    logger.info("Document processor tests finished. Manual cleanup of 'knowledge_base_test_doc_proc' may be needed if not automated.")
