# ibkr_gateway_service/utils/secrets.py
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
            raise

    client = _clients[region_name]

    try:
        logger.info(f"Attempting to retrieve secret: {secret_name} from region {region_name}")
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        logger.error(f"Failed to retrieve secret {secret_name} from region {region_name}: {e}")
        raise e

    if 'SecretString' in get_secret_value_response:
        secret = get_secret_value_response['SecretString']
        try:
            secret_json = json.loads(secret)
            if isinstance(secret_json, dict) and len(secret_json) == 1:
                key_name = list(secret_json.keys())[0]
                value = secret_json[key_name]
                logger.info(f"Successfully retrieved and parsed JSON secret for {secret_name}. Key: {key_name}")
                return value
            logger.info(f"Retrieved complex JSON secret for {secret_name}. Returning as JSON string.")
            return secret
        except json.JSONDecodeError:
            logger.info(f"Successfully retrieved raw string secret for {secret_name}.")
            return secret
    elif 'SecretBinary' in get_secret_value_response:
        logger.warning(f"Secret {secret_name} is binary, which is not expected for these credentials. Returning empty.")
        raise ValueError(f"Secret {secret_name} is binary and not a string as expected.")

    raise ValueError(f"Secret {secret_name} does not contain SecretString or SecretBinary.")
