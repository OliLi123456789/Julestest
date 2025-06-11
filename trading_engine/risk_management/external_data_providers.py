import logging
from typing import Optional, Dict, Any
# Ensure AccountInfo is imported if it's a return type
from .risk_rules import AccountInfo

logger = logging.getLogger(__name__)

class MockMarketDataClient: # Placeholder
    def get_last_trade_price(self, symbol: str) -> Optional[float]:
        logger.debug(f"MockMarketDataClient: Queried for price of {symbol}")
        # Simulate fetching price, return None if not found or error
        # These prices should align with _get_current_price in RiskManager if that's the fallback
        mock_prices = {
            "AAPL": 150.50,
            "GOOG": 2500.75,
            "MSFT": 300.10,
            "TSLA": 700.20,
            "EUR.USD": 1.09,
            "BTC.USD": 40050.00,
            "TESTSYM": 95.00, # For dummy strategy tests
            "SOME_ILLIQUID_SYM": 5.25
            }
        price = mock_prices.get(symbol)
        if price is None:
            logger.warning(f"MockMarketDataClient: No mock price found for {symbol}, returning None.")
        return price

class MockAccountInfoProvider: # Placeholder
    def get_account_info(self, user_id: str) -> Optional[AccountInfo]:
        logger.debug(f"MockAccountInfoProvider: Queried for account info of {user_id}")
        # Simulate fetching account info
        if user_id == "user_with_funds" or "STRAT_ACC_001" in user_id or "manual_user" in user_id or "dummy_strat_1_user" in user_id: # Common test users
            return AccountInfo(user_id=user_id, balance=100000.0, buying_power=200000.0, margin_available=150000.0)
        elif user_id == "user_with_insufficient_funds":
            return AccountInfo(user_id=user_id, balance=100.0, buying_power=50.0, margin_available=50.0)

        logger.warning(f"MockAccountInfoProvider: No mock account info found for user {user_id}, returning None.")
        return None

class MockRiskEventPublisher: # Placeholder
    def publish_risk_violation(self, event_data: Dict[str, Any]):
        # In real system, this would send to Kafka or another messaging system/alerting framework
        logger.info(f"MockRiskEventPublisher: Publishing Risk Violation: {event_data}")

    def publish_risk_check_failed_event(self, event_data: Dict[str, Any]): # For generic errors
        logger.info(f"MockRiskEventPublisher: Publishing Generic Risk Check Failed Event: {event_data}")

# Example of how these might be instantiated if needed for testing this module directly
if __name__ == '__main__':
    market_client = MockMarketDataClient()
    print(f"AAPL Price: {market_client.get_last_trade_price('AAPL')}")
    print(f"UNKNOWN Price: {market_client.get_last_trade_price('UNKNOWN')}")

    account_provider = MockAccountInfoProvider()
    print(f"user_with_funds info: {account_provider.get_account_info('user_with_funds')}")
    print(f"unknown_user info: {account_provider.get_account_info('unknown_user')}")

    event_publisher = MockRiskEventPublisher()
    event_publisher.publish_risk_violation({"rule": "TestRule", "detail": "Detail for test"})
    event_publisher.publish_risk_check_failed_event({"error": "System Error", "detail": "Detail for test"})
