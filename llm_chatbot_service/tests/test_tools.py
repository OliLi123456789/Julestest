import pytest
import json
from llm_chatbot_service.tools.chart_data_tool import ChartDataTool, InvalidParameterError as ChartInvalidParameterError, SymbolNotFoundError as ChartSymbolNotFoundError, InternalAPITimeoutError as ChartInternalAPITimeoutError
from llm_chatbot_service.tools.news_analysis_tool import NewsAnalysisTool, InvalidNewsQueryError, NoNewsFoundError, InternalNewsServiceError
from llm_chatbot_service.tools.earnings_analysis_tool import EarningsAnalysisTool, InvalidEarningsSymbolError, NoEarningsDataFoundError, InternalEarningsServiceError as EarningsInternalServiceError

# Common test data
test_symbol = "TESTCO"
test_query = "latest on TESTCO"

@pytest.mark.asyncio
async def test_chart_data_tool_success():
    tool = ChartDataTool()
    result_str = await tool.execute(symbol=test_symbol, timeframe="1D", lookback_period="1M")
    result = json.loads(result_str)
    assert result["symbol"] == test_symbol.upper()
    assert result["timeframe"] == "1D"
    assert result["lookback_period"] == "1M"
    assert "data_points" in result
    assert len(result["data_points"]) > 0
    assert "open" in result["data_points"][0]

@pytest.mark.asyncio
async def test_chart_data_tool_symbol_not_found():
    tool = ChartDataTool()
    result = await tool.execute(symbol="NOTFOUND", timeframe="1D", lookback_period="1M")
    assert "Error: Could not retrieve chart data. Symbol 'NOTFOUND' not found." in result

@pytest.mark.asyncio
async def test_chart_data_tool_timeout():
    tool = ChartDataTool()
    result = await tool.execute(symbol="TIMEOUT", timeframe="1D", lookback_period="1M")
    assert "Error: Could not retrieve chart data for 'TIMEOUT'. The data service timed out." in result

@pytest.mark.asyncio
async def test_chart_data_tool_generic_error():
    tool = ChartDataTool()
    result = await tool.execute(symbol="ERROR", timeframe="1D", lookback_period="1M")
    assert "Error: An unexpected issue occurred while fetching chart data for 'ERROR'." in result

@pytest.mark.asyncio
async def test_chart_data_tool_invalid_params():
    tool = ChartDataTool()
    result = await tool.execute(symbol=test_symbol, timeframe="INVALID_TF", lookback_period="1M")
    assert "Error: Invalid parameters for chart data. Invalid timeframe: INVALID_TF" in result
    result_missing_symbol = await tool.execute(symbol="", timeframe="1D", lookback_period="1M")
    assert "Error: Stock symbol must be provided." in result_missing_symbol


@pytest.mark.asyncio
async def test_news_analysis_tool_success():
    tool = NewsAnalysisTool()
    result_str = await tool.execute(query=test_query, limit=3)
    result = json.loads(result_str)
    assert result["query"] == test_query
    assert result["limit_requested"] == 3
    assert len(result["articles"]) == 3
    assert "title" in result["articles"][0]
    assert "sentiment_score" in result["articles"][0]

@pytest.mark.asyncio
async def test_news_analysis_tool_no_news():
    tool = NewsAnalysisTool()
    result = await tool.execute(query="NO_RESULTS_FOR_THIS_QUERY")
    assert "Error: No news articles found for 'NO_RESULTS_FOR_THIS_QUERY'." in result

@pytest.mark.asyncio
async def test_news_analysis_tool_service_down():
    tool = NewsAnalysisTool()
    result = await tool.execute(query="SERVICE_DOWN")
    assert "Error: Could not retrieve news for 'SERVICE_DOWN'. The news service reported an error:" in result

@pytest.mark.asyncio
async def test_news_analysis_tool_invalid_query():
    tool = NewsAnalysisTool()
    result = await tool.execute(query="Q") # Too short
    assert "Error: Invalid news query. Query term 'Q' is too short." in result
    result_empty = await tool.execute(query="")
    assert "Error: A query (e.g., stock symbol or topic) must be provided." in result_empty
    result_bad_limit = await tool.execute(query="Test", limit=0)
    assert "Error: Limit must be a positive integer, not exceeding 20." in result_bad_limit


@pytest.mark.asyncio
async def test_earnings_analysis_tool_success_upcoming():
    tool = EarningsAnalysisTool()
    result_str = await tool.execute(symbol=test_symbol, event_type="upcoming")
    result = json.loads(result_str)
    assert result["symbol"] == test_symbol.upper()
    assert result["event_type"] == "upcoming"
    assert "date" in result
    assert "eps_estimate" in result

@pytest.mark.asyncio
async def test_earnings_analysis_tool_success_historical():
    tool = EarningsAnalysisTool()
    result_str = await tool.execute(symbol=test_symbol, event_type="historical")
    result = json.loads(result_str)
    assert result["symbol"] == test_symbol.upper()
    assert result["event_type"] == "historical"
    assert "eps_actual" in result
    assert "eps_surprise_pct" in result

@pytest.mark.asyncio
async def test_earnings_analysis_tool_no_data():
    tool = EarningsAnalysisTool()
    result = await tool.execute(symbol="NO_DATA", event_type="upcoming")
    assert "Error: No upcoming earnings data found for 'NO_DATA'." in result

@pytest.mark.asyncio
async def test_earnings_analysis_tool_service_error():
    tool = EarningsAnalysisTool()
    result = await tool.execute(symbol="SERVICE_ERROR", event_type="historical")
    assert "Error: Could not retrieve earnings data for 'SERVICE_ERROR'. The data service reported an error:" in result

@pytest.mark.asyncio
async def test_earnings_analysis_tool_invalid_symbol():
    tool = EarningsAnalysisTool()
    result = await tool.execute(symbol="INVALID!", event_type="upcoming")
    assert "Error: Invalid symbol for earnings data. Symbol 'INVALID!' appears invalid for earnings lookup." in result

@pytest.mark.asyncio
async def test_earnings_analysis_tool_invalid_event_type():
    tool = EarningsAnalysisTool()
    result = await tool.execute(symbol=test_symbol, event_type="nonexistent_type")
    assert "Error: Invalid event_type. Must be 'upcoming' or 'historical'." in result


# Basic schema validation for LLM descriptions
def validate_llm_schema(schema: dict):
    assert "name" in schema
    assert isinstance(schema["name"], str)
    assert "description" in schema
    assert isinstance(schema["description"], str)
    assert "parameters" in schema
    assert isinstance(schema["parameters"], dict)
    assert "type" in schema["parameters"]
    assert schema["parameters"]["type"] == "OBJECT"
    assert "properties" in schema["parameters"]
    assert isinstance(schema["parameters"]["properties"], dict)
    assert "required" in schema["parameters"]
    assert isinstance(schema["parameters"]["required"], list)

    for param_name, param_details in schema["parameters"]["properties"].items():
        assert "type" in param_details
        assert isinstance(param_details["type"], str)
        assert "description" in param_details
        assert isinstance(param_details["description"], str)
        if "enum" in param_details:
            assert isinstance(param_details["enum"], list)

def test_chart_data_tool_llm_description():
    tool = ChartDataTool()
    schema = tool.get_description_for_llm()
    validate_llm_schema(schema)
    assert schema["name"] == "get_chart_data"
    assert "symbol" in schema["parameters"]["properties"]
    assert "timeframe" in schema["parameters"]["properties"]
    assert "lookback_period" in schema["parameters"]["properties"]
    assert schema["parameters"]["properties"]["timeframe"]["enum"] == ["1Min", "5Min", "15Min", "1H", "1D", "1W", "1M"]

def test_news_analysis_tool_llm_description():
    tool = NewsAnalysisTool()
    schema = tool.get_description_for_llm()
    validate_llm_schema(schema)
    assert schema["name"] == "get_news_analysis"
    assert "query" in schema["parameters"]["properties"]
    assert "limit" in schema["parameters"]["properties"]
    assert schema["parameters"]["properties"]["limit"]["type"] == "INTEGER" # Check specific type

def test_earnings_analysis_tool_llm_description():
    tool = EarningsAnalysisTool()
    schema = tool.get_description_for_llm()
    validate_llm_schema(schema)
    assert schema["name"] == "get_earnings_data"
    assert "symbol" in schema["parameters"]["properties"]
    assert "event_type" in schema["parameters"]["properties"]
    assert schema["parameters"]["properties"]["event_type"]["enum"] == ["upcoming", "historical"]
    assert "event_type" in schema["parameters"]["required"]
