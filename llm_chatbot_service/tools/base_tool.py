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

    def get_description_for_llm(self) -> Dict[str, Any]:
        """
        Returns a description of the tool formatted for an LLM (e.g., for function calling).
        This is a conceptual representation; actual format depends on the LLM API.
        """
        # Example format, actual may vary based on LLM (OpenAI, Gemini, etc.)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        # Define expected parameters here, e.g.:
                        # "symbol": {"type": "string", "description": "The stock symbol, e.g., AAPL"},
                        # "query": {"type": "string", "description": "The user's query for this tool"}
                    },
                    # "required": ["parameter_name"] # List required parameters
                }
            }
        }

if __name__ == '__main__':
    # This base class is not meant to be run directly.
    print("BaseTool class defined. This script is not meant for direct execution.")
    # Example of how a tool description might look (conceptual)
    # class MySampleTool(BaseTool):
    #     name = "get_stock_price"
    #     description = "Retrieves the current stock price for a given symbol."
    #     def execute(self, symbol: str) -> str:
    #         return f"Price for {symbol} is $XYZ (mocked)."
    #     def get_description_for_llm(self):
    #         desc = super().get_description_for_llm()
    #         desc['function']['parameters']['properties']['symbol'] = {"type": "string", "description": "The stock symbol, e.g., AAPL"}
    #         desc['function']['parameters']['required'] = ['symbol']
    #         return desc
    #
    # sample_tool_desc = MySampleTool().get_description_for_llm()
    # import json
    # print(json.dumps(sample_tool_desc, indent=2))
