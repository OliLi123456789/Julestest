# LLM Chatbot Service

## Overview

The LLM Chatbot Service is a FastAPI-based application designed to provide a flexible and extensible interface to various Large Language Models (LLMs). It supports multiple LLM providers, integrates a Retrieval Augmented Generation (RAG) system for domain-specific knowledge, allows for extensible tools to perform specific actions, maintains conversation history, and offers a code generation mode. The service is containerized using Docker and includes structured logging and Prometheus metrics for observability.

## Features

*   **Multiple LLM Provider Support**:
    *   Google Gemini (with function calling for tool use)
    *   DeepSeek
    *   Mock LLM (for testing and development)
*   **Retrieval Augmented Generation (RAG) System**:
    *   Uses FAISS and SentenceTransformers to embed and retrieve documents from a knowledge base.
    *   Augments LLM prompts with relevant context to improve response accuracy and provide domain-specific information.
    *   Supports loading pre-built indexes or building from source documents (including ingestion from directories).
*   **Extensible Tools**:
    *   `ChartDataTool`: Retrieves (mock) historical market data for charting.
    *   `NewsAnalysisTool`: Fetches (mock) news articles and sentiment.
    *   `EarningsAnalysisTool`: Provides (mock) past and upcoming earnings data.
    *   Tools are triggered via Gemini's function calling or keyword detection for other providers.
*   **Conversation History**:
    *   Maintains a sliding window of recent messages for each session to provide conversational context to LLMs.
*   **Code Generation Mode**:
    *   Supports a specific `/code` command to instruct the LLM to generate code, particularly Python trading strategies using a mock SDK.
*   **Structured Logging**:
    *   Uses `loguru` for JSON-formatted, structured logs.
    *   Includes unique request IDs for easier tracing.
    *   Log level is configurable.
*   **Prometheus Metrics**:
    *   Exposes a `/metrics` endpoint with default FastAPI request/latency metrics via `prometheus-fastapi-instrumentator`.
*   **Dockerization**:
    *   Includes a `Dockerfile` for building a containerized version of the service.
    *   Uses a non-root user for enhanced security.

## API Documentation

The service provides automatically generated OpenAPI documentation:

*   **Swagger UI**: Accessible at `/docs`
*   **ReDoc**: Accessible at `/redoc`

## Configuration (Environment Variables)

The service is configured using environment variables:

| Variable                            | Description                                                                                                | Default Value (if any)                                  |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| `LLM_API_PROVIDER`                  | Specifies the LLM provider to use. Options: "gemini", "deepseek", "mock".                                 | "mock"                                                  |
| `LLM_API_KEY_SECRET_NAME_TEMPLATE`  | Template for AWS Secrets Manager secret name. `{provider}` is replaced by `LLM_API_PROVIDER`.             | "llm_chatbot_service/api_keys/{provider}"             |
| `AWS_REGION`                        | AWS region for Secrets Manager.                                                                            | "us-east-1" (or as configured in your AWS environment)  |
| `GEMINI_MODEL_NAME`                 | The specific Gemini model to use (e.g., "gemini-pro", "gemini-1.5-flash").                                   | "gemini-pro"                                            |
| `DEEPSEEK_MODEL_NAME`               | The specific DeepSeek model to use.                                                                        | "deepseek-chat"                                         |
| `DEEPSEEK_API_ENDPOINT`             | The API endpoint for DeepSeek.                                                                             | "https://api.deepseek.com/chat/completions"             |
| `LLM_REQUEST_TIMEOUT`               | Timeout in seconds for requests to external LLM APIs.                                                      | 60                                                      |
| `RAG_EMBEDDING_MODEL`               | SentenceTransformer model name for RAG embeddings.                                                         | "all-MiniLM-L6-v2"                                      |
| `RAG_INDEX_PATH`                    | Filesystem path to the pre-built FAISS index for RAG.                                                      | `./rag_index_data/faiss.index` (relative to `retriever.py`) |
| `RAG_DOCUMENTS_PATH`                | Filesystem path to the JSON file containing documents corresponding to the RAG index.                      | `./rag_index_data/documents.json` (relative to `retriever.py`) |
| `RAG_TOP_K`                         | Number of top relevant documents to retrieve from RAG.                                                     | 3                                                       |
| `MAX_HISTORY_TURNS`                 | Number of user/assistant turn pairs to keep in conversation history.                                       | 5                                                       |
| `LOG_LEVEL`                         | Logging level for the application (e.g., DEBUG, INFO, WARNING, ERROR).                                   | "INFO"                                                  |
| `PORT`                              | Port on which the FastAPI service will run.                                                                | 8001                                                    |
| `HOST`                              | Host address to bind the service to.                                                                       | "0.0.0.0"                                               |

## Prerequisites

*   Python 3.10+
*   Docker (for containerized deployment)
*   Access to AWS Secrets Manager if using "gemini" or "deepseek" providers (requires AWS credentials configured in the environment where the service runs).
*   If building RAG index locally or running tests that require it: `FAISS` and `SentenceTransformers` dependencies might require system libraries (e.g., C++ build tools for FAISS).

## Local Development

1.  **Clone the Repository**:
    ```bash
    # git clone <repository_url>
    # cd <repository_name>/llm_chatbot_service
    ```

2.  **Install Dependencies**:
    It's recommended to use a virtual environment:
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    ```

3.  **Set Environment Variables**:
    Create a `.env` file in the `llm_chatbot_service` directory (this file is gitignored) or set environment variables directly in your shell:
    ```env
    LLM_API_PROVIDER="mock" # Or "gemini", "deepseek"
    # If using AWS Secrets Manager for API keys:
    # LLM_API_KEY_SECRET_NAME_TEMPLATE="your/secret/template/{provider}"
    # AWS_REGION="your-aws-region"
    # Ensure your AWS credentials are configured (e.g., via AWS CLI, instance profile)

    # If setting API keys directly (NOT RECOMMENDED for production, use for local testing only if necessary):
    # LLM_API_KEY="your_actual_api_key_here" # This env var is read if direct key use is implemented (currently not for gemini/deepseek)

    PORT="8001"
    LOG_LEVEL="DEBUG"
    # Add other variables as needed from the table above
    ```
    **Note**: For `LLM_API_KEY`, the current setup for Gemini/DeepSeek primarily uses AWS Secrets Manager. If you wish to use direct environment variable keys, you would need to modify the API key retrieval logic in `main.py`.

4.  **Running the Service**:
    From within the `llm_chatbot_service` directory:
    ```bash
    uvicorn main:app --reload --port ${PORT:-8001} --host ${HOST:-0.0.0.0}
    ```
    The service will be available at `http://localhost:8001` (or the configured host/port).

## Docker Deployment

1.  **Build the Docker Image**:
    Navigate to the `llm_chatbot_service` directory (where the `Dockerfile` is located) and run:
    ```bash
    docker build -t llm-chatbot-service:latest .
    ```

2.  **Run the Docker Container**:
    ```bash
    docker run -d \
        -p 8001:8001 \
        -e PORT="8001" \
        -e LLM_API_PROVIDER="mock" \
        # Add other necessary environment variables using -e
        # Example for AWS (ensure the container runtime environment has AWS credentials):
        # -e AWS_REGION="your-aws-region" \
        # -e LLM_API_KEY_SECRET_NAME_TEMPLATE="your/secret/template/{provider}" \
        llm-chatbot-service:latest
    ```
    **Managing Secrets in Docker**:
    *   For AWS-based deployments (EC2, ECS, EKS), use IAM Roles assigned to the instances or tasks to provide permissions to access Secrets Manager. The application's Boto3 client will automatically use these roles.
    *   For other environments, you might pass AWS credentials securely as environment variables (less secure, use with caution) or mount a configuration file containing credentials (requires careful volume management). Using a dedicated secrets management tool for your Docker environment is recommended if not on AWS.

## RAG System

*   **Purpose**: The Retrieval Augmented Generation (RAG) system enhances LLM responses by providing relevant context from a local knowledge base. This helps in answering domain-specific questions and improving factual accuracy.
*   **Technology**: It uses `SentenceTransformers` to generate embeddings for text documents and `FAISS` (CPU version) for efficient similarity search.
*   **Behavior**:
    *   On startup, the `Retriever` attempts to load a pre-built FAISS index from `RAG_INDEX_PATH` and corresponding documents from `RAG_DOCUMENTS_PATH`.
    *   If these paths are not found or loading fails, it falls back to building an index from the `MOCK_KB_DOCUMENTS` defined in `rag/retriever.py`.
    *   If RAG dependencies (`faiss-cpu`, `sentence-transformers`) are not installed, RAG functionality will be disabled.
*   **Custom Index**: The `llm_chatbot_service/rag/retriever.py` script includes an example in its `if __name__ == '__main__':` block demonstrating how to:
    1.  Ingest documents from a local directory (e.g., a folder with `.txt` or `.md` files).
    2.  Build a FAISS index and document list from these files.
    3.  Save the index and document list to disk for later use by the main application.
    You can run `python -m llm_chatbot_service.rag.retriever` (from the project root) to see this example in action (it creates temporary files).

## Available Tools

The service supports extensible tools that the LLM (primarily Gemini via function calling) can use:

*   **`ChartDataTool` (get_chart_data)**: Retrieves (mock) historical market data for a given symbol, timeframe, and lookback period.
*   **`NewsAnalysisTool` (get_news_analysis)**: Fetches (mock) recent news articles and their sentiment for a query (symbol or topic).
*   **`EarningsAnalysisTool` (get_earnings_data)**: Provides (mock) past or upcoming earnings information for a stock symbol.

These tools are defined in the `llm_chatbot_service/tools/` directory. For LLM providers other than Gemini, basic keyword detection in `main.py` might trigger these tools.

## Logging & Monitoring

*   **Structured Logging**: Application logs are written to `stdout` in JSON format using `loguru`. Each log entry includes a timestamp, level, message, and any bound `extra` fields (like `request_id`). The `LOG_LEVEL` can be set via environment variable.
*   **Prometheus Metrics**: A `/metrics` endpoint is exposed, providing default FastAPI metrics such as request counts, latencies, and response sizes. This can be scraped by a Prometheus server for monitoring.

## Project Structure

```
llm_chatbot_service/
├── .dockerignore
├── Dockerfile
├── README.md
├── pytest.ini
├── requirements.txt
├── main.py                     # FastAPI application, endpoints, LLM interaction logic
├── conversation_manager.py     # Manages conversation history
├── rag/
│   ├── __init__.py
│   ├── retriever.py            # RAG system implementation (FAISS, SentenceTransformers)
│   └── rag_index_data/         # Default directory for storing/loading FAISS index and docs
├── tools/
│   ├── __init__.py
│   ├── base_tool.py            # Abstract base class for tools
│   ├── chart_data_tool.py
│   ├── earnings_analysis_tool.py
│   └── news_analysis_tool.py
└── tests/
    ├── __init__.py
    ├── test_conversation_manager.py
    ├── test_main_api.py
    ├── test_retriever.py
    └── test_tools.py
```

## Testing

Unit and integration tests are written using `pytest`.

*   **Running Tests**:
    Navigate to the `llm_chatbot_service` directory (or the project root if `PYTHONPATH` is set up correctly) and run:
    ```bash
    pytest
    ```
    The `pytest.ini` file configures `pytest` to automatically find `test_*.py` files and handle `asyncio` tests.

## Security Considerations

*   **Authentication/Authorization**: The current service is unauthenticated and accessible by anyone who can reach its network endpoint. For production environments, robust authentication (e.g., OAuth2, API Keys with a management system) and authorization mechanisms (e.g., role-based access control) must be implemented to protect the service from unauthorized access and ensure users can only access appropriate data and functionality.
*   **Input Validation**: Pydantic models are used for request body validation, providing a baseline level of protection against malformed inputs. Depending on the sensitivity of the data and tools, further input sanitization or validation might be necessary within tool logic or before passing data to LLMs.
*   **Secrets Management**: API keys for LLM providers are intended to be managed via AWS Secrets Manager, as configured by `LLM_API_KEY_SECRET_NAME_TEMPLATE`. Direct injection of secrets via environment variables should be avoided in production. Ensure the runtime environment (e.g., EC2 instance, ECS task, Lambda function) has appropriate IAM permissions to access these secrets.
*   **CSRF (Cross-Site Request Forgery)**: As a backend API primarily consumed by programmatic clients or a decoupled frontend, traditional browser-based CSRF is less of a direct concern. However, if the service were to be directly called from browser-based JavaScript on a different domain without proper CORS and if it used session/cookie-based authentication, CSRF protection (e.g., CSRF tokens) would be critical.
*   **Security Headers**: The application includes middleware to add important security headers to HTTP responses:
    *   `X-Content-Type-Options: nosniff`: Prevents browsers from MIME-sniffing the content-type.
    *   `X-Frame-Options: DENY`: Prevents the site from being framed, mitigating clickjacking.
    *   `Strict-Transport-Security: max-age=31536000; includeSubDomains`: Enforces HTTPS connections (ensure HTTPS is terminated at or before the service).
    *   `Content-Security-Policy: default-src 'self'; frame-ancestors 'none';`: Restricts sources for content and framing, enhancing protection against XSS and clickjacking.
*   **Dependency Scanning**: Dependencies should be regularly scanned for known vulnerabilities. The `pip-audit` library is included in `requirements.txt`. You can run `pip-audit` or `python -m pip_audit` to check for vulnerabilities. Integrate this into your CI/CD pipeline.
*   **HTTPS Enforcement**: The service should always be deployed behind a reverse proxy (e.g., Nginx, AWS ALB/API Gateway) that terminates SSL/TLS and enforces HTTPS. The HSTS header encourages this.
*   **Rate Limiting**: To protect against abuse, denial-of-service attacks, and runaway costs (especially with LLM APIs), implement rate limiting. This is typically best handled at the API gateway, load balancer, or reverse proxy level.
*   **LLM Content Safety**:
    *   While LLM providers (like Google Gemini) often have built-in content safety features, be aware of the potential for generating harmful, biased, or inaccurate content.
    *   Depending on the application's sensitivity and user base, you might need to implement additional input sanitization before sending prompts to the LLM and/or output filtering/moderation on the LLM's responses.
    *   Clearly communicate to users that responses are AI-generated.
*   **Log Review**: Regularly review application logs for suspicious activity, errors, and potential security events. The structured JSON logging facilitates this.
*   **Principle of Least Privilege**: Ensure the service itself (and its Docker container, if used) runs with the minimum necessary permissions, especially concerning file system access, network access, and cloud provider permissions (e.g., IAM roles).
