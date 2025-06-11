# llm_chatbot_service/auth_llm.py
from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader # For header-based API key
import logging # Added for logging within the auth function

from .config_llm import llm_service_config # Import your config instance

logger = logging.getLogger(__name__) # Standard logger for this module
# If using hierarchical logging from a shared setup:
# from .logging_setup import EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME (if logging_setup was for all services)
# logger = logging.getLogger(f"{EXTERNAL_DATA_SERVICES_ROOT_LOGGER_NAME}.auth_llm")


API_KEY_NAME = "X-API-Key" # Standard header name for API keys
api_key_header_auth = APIKeyHeader(name=API_KEY_NAME, auto_error=False) # Set auto_error=False to handle missing key manually

async def verify_api_key(api_key_header_value: Optional[str] = Security(api_key_header_auth)):
    """
    Verifies the API key provided in the X-API-Key header.
    Allows access if:
    1. API key is valid and present in configured allowed_api_keys.
    2. No API keys are configured AND the LLM provider is 'mock' (for local dev/testing).
    """
    if not llm_service_config.allowed_api_keys:
        # Case 1: No API keys are configured for the service.
        if llm_service_config.llm_api_provider == "mock":
            logger.debug("API key auth: No service API keys configured, but LLM provider is 'mock'. Allowing request.")
            return True # Effectively bypasses auth for mock provider if no keys are set
        else:
            # This is a server misconfiguration: live LLM provider but service itself is unprotected.
            logger.error("CRITICAL SERVER MISCONFIGURATION: LLM_SERVICE_API_KEYS is not set, but LLM_API_PROVIDER is not 'mock'. Denying all requests.")
            raise HTTPException(
               status_code=status.HTTP_503_SERVICE_UNAVAILABLE, # Or 500
               detail="API authentication is not configured correctly on the server."
            )

    # Case 2: API keys are configured. Validate the provided key.
    if not api_key_header_value:
        logger.warning(f"API key auth: Missing '{API_KEY_NAME}' header.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Not authenticated: Missing '{API_KEY_NAME}' header."
        )

    if api_key_header_value not in llm_service_config.allowed_api_keys:
        logger.warning(f"API key auth: Invalid API Key received: '{api_key_header_value[:5]}...'")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API Key." # Don't reveal which one was wrong
        )

    logger.debug(f"API key auth: Valid API Key received (key ending with ...{api_key_header_value[-4:] if len(api_key_header_value) > 4 else '****'}). Access granted.")
    return True # API key is valid and present in allowed_api_keys

if __name__ == '__main__':
    # Basic test setup for verify_api_key
    # This requires llm_service_config to be usable.
    # You'd typically test this via API integration tests for the FastAPI app.

    # Example:
    # To run this, you might need to set some environment variables first.
    # export LLM_SERVICE_API_KEYS="testkey1,testkey2"
    # export LLM_API_PROVIDER="gemini" # or something other than mock to enforce key check

    if not logger.handlers: # Basic logging for this test
        logging.basicConfig(level=logging.DEBUG)

    logger.info("Testing verify_api_key function (requires environment setup for LLM_SERVICE_API_KEYS)...")

    # Simulate FastAPI's Security dependency for testing
    async def call_verify(key_to_test: Optional[str]):
        try:
            await verify_api_key(api_key_header_value=key_to_test)
            logger.info(f"Test with key '{key_to_test}': PASSED")
        except HTTPException as e:
            logger.warning(f"Test with key '{key_to_test}': FAILED with {e.status_code} - {e.detail}")

    import asyncio

    # Test scenarios (these will only pass if LLM_SERVICE_API_KEYS is set in env)
    # Note: llm_service_config is loaded once at module import.
    # To test different config states, you might need to reload the module or mock the config object.

    logger.info(f"Configured allowed keys: {llm_service_config.allowed_api_keys}")
    logger.info(f"Configured LLM provider: {llm_service_config.llm_api_provider}")

    # asyncio.run(call_verify("testkey1")) # Should pass if "testkey1" is in LLM_SERVICE_API_KEYS
    # asyncio.run(call_verify("wrongkey")) # Should fail (401)
    # asyncio.run(call_verify(None))       # Should fail (401 as auto_error=False, then manual check)

    # Test mock provider bypass if no keys are set (requires specific env state)
    # If LLM_SERVICE_API_KEYS is empty and LLM_API_PROVIDER="mock", it should pass.
    # If LLM_SERVICE_API_KEYS is empty and LLM_API_PROVIDER!="mock", it should raise 503.
    logger.info("To fully test verify_api_key, run with different environment variables for LLM_SERVICE_API_KEYS and LLM_API_PROVIDER.")
