from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseTool(ABC):
    """
    Abstract base class for tools that can be called by the LLM service.
    """
    name: str = "BaseTool"
    description: str = "This is a base tool."

    @abstractmethod
    def execute(self, **kwargs: Any) -> str:
        """
        Executes the tool with the given parameters.
        Returns a string representation of the tool's output,
        suitable for being passed back to an LLM or directly to a user.
        """
        pass

    # This schema should be overridden by subclasses to define their specific parameters.
    # Key: parameter name
    # Value: dict with "type" (e.g., "string", "integer", "number", "boolean", "array"), "description", and optionally "enum"
    parameter_schema: Dict[str, Dict[str, Any]] = {}


    def get_description_for_llm(self) -> Dict[str, Any]:
        """
        Returns a description of the tool formatted for Gemini's FunctionDeclaration schema.
        Subclasses should override `parameter_schema` and optionally required_parameters list.
        """

        # Determine required parameters. Assume all are required if not specified.
        # Subclasses can override this by defining a 'required_parameters' list.
        required = list(self.parameter_schema.keys())
        if hasattr(self, 'required_parameters') and isinstance(self.required_parameters, list):
            required = self.required_parameters

        # Convert parameter_schema to Gemini's format
        # Gemini expects parameter types like: STRING, INTEGER, NUMBER, BOOLEAN, ARRAY
        # JSON schema types are typically lowercase. We'll assume they need to be uppercase for Gemini.
        gemini_properties = {}
        for name, details in self.parameter_schema.items():
            gemini_properties[name] = {
                "type": details.get("type", "STRING").upper(), # Default to STRING, ensure uppercase
                "description": details.get("description", "")
            }
            if "enum" in details:
                gemini_properties[name]["enum"] = details["enum"]


        return {
            # This structure matches google.generativeai.types.FunctionDeclaration
            "name": self.name,
            "description": self.description,
            "parameters": { # This structure matches google.generativeai.types.Schema
                "type": "OBJECT", # Corresponds to OpenAPISchemaType.OBJECT
                "properties": gemini_properties,
                "required": required,
            }
        }

from loguru import logger # Import Loguru
import sys # For basic logger setup in __main__

if __name__ == '__main__':
    # Basic Loguru setup for testing this module directly
    logger.remove()
    logger.add(sys.stderr, level="DEBUG", format="{time} {level} {message} | {extra}")

    logger.info("BaseTool class defined. This script is not meant for direct execution for service operations.")

    # Example of how a tool (subclass) would define its schema and use the base method:
    class MySampleTool(BaseTool):
        name = "get_stock_price"
        description = "Retrieves the current stock price for a given symbol and exchange."

        parameter_schema = {
            "symbol": {"type": "string", "description": "The stock symbol, e.g., AAPL"},
            "exchange": {"type": "string", "description": "The exchange where the stock is listed, e.g., NASDAQ"}
        }
        # If only 'symbol' was required:
        # required_parameters = ["symbol"]

        async def execute(self, **kwargs: Any) -> str: # Changed to **kwargs to match base
            symbol = kwargs.get("symbol")
            exchange = kwargs.get("exchange")
            if exchange:
                return f"Price for {symbol} on {exchange} is $XYZ (mocked)."
            return f"Price for {symbol} is $XYZ (mocked)."

    sample_tool = MySampleTool()
    gemini_format_description = sample_tool.get_description_for_llm()

    import json
    logger.info("\nExample Gemini FunctionDeclaration format:")
    logger.info(json.dumps(gemini_format_description, indent=2))


    # Example of a tool with an enum
    class MyEnumTool(BaseTool):
        name = "set_trading_mode"
        description = "Sets the trading mode for the account."
        parameter_schema = {
            "mode": {
                "type": "string",
                "description": "The trading mode to set.",
                "enum": ["live", "paper", "backtest"]
            }
        }
        required_parameters = ["mode"] # Type List needs to be imported from typing if used here.

        async def execute(self, **kwargs: Any) -> str: # Changed to **kwargs
            mode = kwargs.get("mode")
            return f"Trading mode set to {mode} (mocked)."

    enum_tool = MyEnumTool()
    enum_desc = enum_tool.get_description_for_llm()
    logger.info("\nExample Gemini FunctionDeclaration with Enum:")
    logger.info(json.dumps(enum_desc, indent=2))
