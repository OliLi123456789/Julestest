# historical_ingestor/utils/secrets.py
import boto3
import json
import logging
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_clients = {} # Cache Secrets Manager clients per region to reuse

def get_secret(secret_name: str, region_name: str) -> str:
    """
    Retrieves a secret string value from AWS Secrets Manager.
    Assumes the secret value is either a raw string or a JSON object with a single key-value pair.
    Credentials for boto3 are expected to be configured via IAM roles for EC2/ECS/Lambda,
    or via environment variables / shared credentials file for local development.
    """
    global _clients
    if region_name not in _clients:
        try:
            session = boto3.session.Session()
            _clients[region_name] = session.client(
                service_name='secretsmanager',
                region_name=region_name
            )
            logger.info(f"Initialized Secrets Manager client for region: {region_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Secrets Manager client for region {region_name}: {e}")
            raise # Propagate error to fail fast if client can't be created

    client = _clients[region_name]

    try:
        logger.info(f"Attempting to retrieve secret: {secret_name} from region {region_name}")
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        logger.error(f"Failed to retrieve secret {secret_name} from region {region_name}: {e}")
        # Specific error handling based on error code can be added here
        # e.g., if e.response['Error']['Code'] == 'ResourceNotFoundException': ...
        raise e

    if 'SecretString' in get_secret_value_response:
        secret = get_secret_value_response['SecretString']
        # Attempt to parse as JSON. If it's a JSON object with a single key, return its value.
        # This handles secrets created by AWS console where it often stores as {"key":"value"}.
        # If it's just a plain string secret, JSON parsing will fail, and we return the raw string.
        try:
            secret_json = json.loads(secret)
            if isinstance(secret_json, dict) and len(secret_json) == 1:
                # It's a common pattern for secrets to be stored as {"api_key_name": "actual_key_value"}
                # Return the actual key value directly.
                key_name = list(secret_json.keys())[0]
                value = secret_json[key_name]
                logger.info(f"Successfully retrieved and parsed JSON secret for {secret_name}. Key: {key_name}")
                return value
            # If it's a more complex JSON, the caller might need to handle it, or this logic needs adjustment.
            # For now, if it's JSON but not single key-value, returning the whole JSON string.
            logger.info(f"Retrieved complex JSON secret for {secret_name}. Returning as JSON string.")
            return secret
        except json.JSONDecodeError:
            # Not a JSON string, assume it's the raw secret value itself
            logger.info(f"Successfully retrieved raw string secret for {secret_name}.")
            return secret
    elif 'SecretBinary' in get_secret_value_response:
        # API keys are typically strings, but handle if it were binary.
        # decoded_binary_secret = base64.b64decode(get_secret_value_response['SecretBinary'])
        logger.warning(f"Secret {secret_name} is binary, which is not expected for API keys. Returning empty.")
        # For this use case, we expect a string, so binary is an issue.
        raise ValueError(f"Secret {secret_name} is binary and not a string as expected.")

    # Should not be reached if SecretString or SecretBinary is always present on success
    raise ValueError(f"Secret {secret_name} does not contain SecretString or SecretBinary.")
