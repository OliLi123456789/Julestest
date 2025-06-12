# Secrets Management Strategy

This document outlines the strategy for managing secrets within the Prop Firm Platform deployed on AWS. Securely handling sensitive information like API keys, database credentials, and other secrets is critical for the platform's security.

## 1. Naming Convention for Secrets

A consistent naming convention for secrets stored in AWS Secrets Manager is crucial for organization, discoverability, and applying IAM permissions effectively.

The recommended pattern is:

`<environment_name>/<service_name>/<secret_description>`

Where:
*   **`<environment_name>`**: The deployment environment (e.g., `dev`, `staging`, `production`).
*   **`<service_name>`**: The logical name of the service or component that owns/uses the secret (e.g., `llm-chatbot-service`, `webapp-backend`, `data-pipeline`).
*   **`<secret_description>`**: A descriptive name for the secret itself (e.g., `database_credentials`, `gemini_api_key`, `kafka_sasl_password`).

**Examples:**

*   `staging/llm-chatbot-service/gemini_api_key`
*   `staging/llm-chatbot-service/deepseek_api_key`
*   `production/webapp-backend/database_url`
*   `dev/data-writer/kafka_brokers_sasl_scram_password`
*   `staging/global/oauth_client_secret` (for a secret shared across services in an environment)

Using this hierarchical path-based naming allows for easier management and wildcard permissions in IAM policies (e.g., granting a service access to all secrets under `staging/my-service/*`).

## 2. Process for Creating/Updating Secrets

*   **Manual Creation/Update**: Secret *values* (the actual sensitive data) **must be populated manually** directly in AWS Secrets Manager via the AWS Management Console or AWS CLI. They should not be hardcoded in Terraform or application code.
    *   Terraform can be used to define the secret *metadata* (name, description, tags, KMS key) if desired, but the `secret_string` or `secret_binary` should not be set in Terraform code that is committed to version control.
*   **KMS Encryption**:
    *   Secrets are automatically encrypted by AWS Secrets Manager. By default, this uses an AWS-managed KMS key.
    *   For enhanced security or specific compliance requirements, consider using a Customer-Managed Key (CMK) for encrypting secrets. This CMK can be created and managed via the `kms_key` Terraform module.
*   **Tagging**: Apply consistent tags to secrets for better organization, cost tracking, and access control. Recommended tags include:
    *   `Environment`: (e.g., `staging`, `production`)
    *   `Service`: (e.g., `llm-chatbot-service`, `webapp-backend`)
    *   `ManagedBy`: (e.g., `Manual`, `Terraform-MetadataOnly`)
    *   `Description`: (A brief, human-readable description of the secret)
*   **Rotation**: Enable automatic rotation for secrets where supported and applicable (e.g., database credentials). For other secrets like API keys, establish a manual or semi-automated rotation schedule.

## 3. IAM Permissions for Secrets

*   **Least Privilege**: Application IAM roles (e.g., ECS Task Roles, Lambda Execution Roles) must be granted least-privilege access to secrets.
*   **Path-Based Access**: The primary method for granting access should be based on the secret's path (name). For example, an IAM policy can grant `secretsmanager:GetSecretValue` permission to resources like `arn:aws:secretsmanager:<region>:<account-id>:secret:<environment_name>/<service_name>/*`.
    *   This is demonstrated by the `iam_service_role` module and the `llm_chatbot_service_staging_policy` in the staging environment, which uses `var.llm_secrets_path_prefix` to scope permissions.
*   **Specific Secret ARNs**: For highly sensitive secrets or where path-based access is too broad, permissions can be granted to individual secret ARNs.
*   **Avoid Wildcard Account/Region**: Do not use wildcards for the AWS account ID or region in IAM policy resources unless absolutely necessary and well-justified.

## 4. Application Configuration for Accessing Secrets

Applications should be designed to dynamically construct the full secret name or ARN they need to fetch based on environment variables provided at runtime. This makes the application code environment-agnostic.

**Example for `llm_chatbot_service`**:

1.  **Environment Variables Injected into the Application**:
    *   `LLM_API_PROVIDER`: (e.g., "gemini", "deepseek") - Determines *which* key to fetch.
    *   `SECRETS_PATH_PREFIX` (or similar): Injected by the deployment environment (e.g., ECS Task Definition for staging would set this to `staging/llm-chatbot-service/`). This variable tells the application the base path for its secrets.
    *   `LLM_API_KEY_SECRET_NAME_TEMPLATE` (optional, or logic built into app): A template like `{provider}_api_key`.

2.  **Application Logic (Python example)**:
    ```python
    # In llm_chatbot_service/main.py or a config module
    # import os
    #
    # llm_provider = os.getenv("LLM_API_PROVIDER") # e.g., "gemini"
    # secrets_path_prefix = os.getenv("SECRETS_PATH_PREFIX") # e.g., "staging/llm-chatbot-service/"
    #
    # # Construct the full secret name
    # # The application currently uses LLM_API_KEY_SECRET_NAME_TEMPLATE which includes the provider.
    # # A slight refinement to align with the documented convention more directly:
    # # The app could use LLM_API_KEY_SECRET_NAME_TEMPLATE = "{provider}_api_key"
    # # And then form the full name: f"{secrets_path_prefix}{LLM_API_KEY_SECRET_NAME_TEMPLATE.format(provider=llm_provider)}"
    # # This would result in, e.g., "staging/llm-chatbot-service/gemini_api_key"
    #
    # # The current implementation in llm_chatbot_service/main.py uses:
    # # secret_name_template = os.getenv("LLM_API_KEY_SECRET_NAME_TEMPLATE", "llm_chatbot_service/api_keys/{provider}")
    # # safe_provider_name = LLM_API_PROVIDER.replace("/", "_")
    # # secret_name = secret_name_template.format(provider=safe_provider_name)
    # # This results in names like "llm_chatbot_service/api_keys/gemini" if the template is not overridden by env var.
    # # To align with the documented convention "staging/llm-chatbot-service/gemini_api_key",
    # # the env var LLM_API_KEY_SECRET_NAME_TEMPLATE should be set to e.g.,
    # # "{environment}/{service_name}/{provider}_api_key" and the app would need 'environment' and 'service_name'
    # # OR, more simply, the app uses the pre-defined path from var.llm_secrets_path_prefix directly.
    #
    # # Current relevant variable from Terraform for IAM policy:
    # # var.llm_secrets_path_prefix = "staging/llm_chatbot_service/"
    #
    # # The application's Python code should be configured such that the `secret_name` it passes to
    # # `get_secret()` (which then calls boto3 `get_secret_value`) matches the secrets created in Secrets Manager
    # # and allowed by the IAM policy.
    # # For instance, the app could expect:
    # # - LLM_API_PROVIDER_SECRET_PREFIX (e.g., "staging/llm-chatbot-service/")
    # # - And then it appends "{provider}_api_key" to it.
    # # This aligns with the var.llm_secrets_path_prefix used in the IAM policy.
    ```
    The `llm_chatbot_service` uses `os.getenv("LLM_API_KEY_SECRET_NAME_TEMPLATE", "llm_chatbot_service/api_keys/{provider}")`.
    If `LLM_API_KEY_SECRET_NAME_TEMPLATE` is set in the environment to `staging/llm-chatbot-service/{provider}_api_key`, then it would fetch, for example, `staging/llm-chatbot-service/gemini_api_key`.
    The IAM policy in `environments/staging/main.tf` uses `var.llm_secrets_path_prefix` (defaulting to `staging/llm_chatbot_service/`) with a wildcard (`*`) at the end. This means it would grant access to any secret starting with `staging/llm-chatbot-service/`, such as `staging/llm-chatbot_service/gemini_api_key`. This is consistent.

This approach ensures that the application code itself does not need to be aware of the specific environment it's running in to locate its secrets, as the correct path prefix is provided through its runtime environment.
