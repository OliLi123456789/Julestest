class IBGatewayServiceError(Exception):
    """Base exception for errors raised by the IBKR Gateway Service."""
    pass

class IBError(IBGatewayServiceError):
    """Represents an error reported by the Interactive Brokers API."""
    def __init__(self, reqId: int, code: int, message: str, advancedOrderRejectJson: str = ""):
        super().__init__(f"IB API Error - ReqId: {reqId}, Code: {code}, Message: {message}, AdvancedReject: {advancedOrderRejectJson if advancedOrderRejectJson else 'N/A'}")
        self.reqId = reqId
        self.code = code
        self.message = message
        self.advancedOrderRejectJson = advancedOrderRejectJson

class ConnectionError(IBGatewayServiceError):
    """Raised when there is a connection issue with IB Gateway or TWS."""
    pass

class RateLimitExceededError(IBGatewayServiceError):
    """Custom exception for rate limit exceeded after timeout."""
    pass
