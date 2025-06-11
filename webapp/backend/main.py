import logging
import time # For WebSocket ping/pong example
from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime # Ensure datetime is imported

# Middleware and Rate Limiting
# from slowapi import Limiter, _rate_limit_exceeded_handler # Limiter is now imported from rate_limiter.py
# from slowapi.util import get_remote_address # get_remote_address is used in rate_limiter.py
from slowapi import _rate_limit_exceeded_handler # Keep this for the handler
from slowapi.errors import RateLimitExceeded
from fastapi.middleware.cors import CORSMiddleware
from .rate_limiter import limiter # Import the shared limiter instance

# Import centralized application configuration
from .config_web import app_config

# Import authentication components
from .auth import auth_router, get_current_active_user, User, get_user_from_token_for_websocket

# Import Kafka related components
# from .kafka_config_web import KafkaWebBackendConfig # Removed, using app_config
from .order_producer import WebOrderProducer
from .data_cache_service import DataCacheService
from .event_consumer_service import WebAppEventConsumerService

# Import WebSocket manager
from .websocket_manager import websocket_conn_manager


# Setup logger for this module
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# --- Rate Limiter Initialization (now imported) ---
# limiter = Limiter(key_func=get_remote_address, default_limits=[app_config.DEFAULT_RATE_LIMIT]) # Defined in rate_limiter.py

# --- FastAPI App Initialization ---
app = FastAPI(title=app_config.PROJECT_NAME, version=app_config.VERSION)
app.state.limiter = limiter # Attach the imported limiter to app state
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# --- Global Exception Handler Middleware ---
# This should be one of the first middleware to catch all subsequent exceptions.
@app.middleware("http")
async def global_exception_handler_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except Exception as exc:
        # Log the full exception for backend diagnostics
        logger.critical(f"Unhandled exception for request {request.method} {request.url}: {exc}", exc_info=True)
        # Return a generic JSON error response to the client
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "type": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected error occurred on the server."
                }
            }
        )

# --- Security Headers Middleware ---
from fastapi import Response # Ensure Response is imported

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    # response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; object-src 'none';" # Keep commented for now
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# --- CORS Middleware ---
# Applied after security headers, so CORS headers can also be added.
if app_config.ALLOWED_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_config.ALLOWED_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info(f"CORS enabled for origins: {app_config.ALLOWED_CORS_ORIGINS}")

# --- Models (OrderCreate, OrderResponse, PositionResponse) ---
# These would ideally be shared models or adaptors for the OMS Order model
# These would ideally be shared models or adaptors for the OMS Order model
class OrderCreate(BaseModel):
    symbol: str
    quantity: int # Should be float for IBKR, or handle conversion
    order_type: str # e.g., "MARKET", "LIMIT", "STOP", "STOP_LIMIT", "TRAIL"
    price: Optional[float] = None # For LIMIT orders
    limit_price: Optional[float] = None # For STOP_LIMIT orders (the limit part)
    stop_price: Optional[float] = None # For STOP, STOP_LIMIT orders
    time_in_force: Optional[str] = "DAY" # Default to DAY, could be GTC, IOC, FOK etc.

    # Fields for Trailing Stop orders
    trailing_percent: Optional[float] = None # e.g., 1.0 for 1%
    trailing_amount: Optional[float] = None # e.g., 10 for $10 offset
    trail_stop_price: Optional[float] = None # Initial trigger price for the trail activation (optional)

    # Could add more like:
    # sec_type: Optional[str] = "STK" (default)
    # currency: Optional[str] = "USD" (default)
    # exchange: Optional[str] = "SMART" (default)
    # account_id: Optional[str] = None (if users can select accounts)


class OrderResponse(BaseModel): # Keep this model, but status will change
    order_id: str
    user_id: str
    symbol: str
    quantity: int
    order_type: str
    price: Optional[float] = None
    status: str # Will be e.g. "ACCEPTED_BY_GATEWAY"
    # Add fields that might be updated by events and stored in cache
    limit_price: Optional[float] = None
    filled_quantity: Optional[float] = None
    average_fill_price: Optional[float] = None
    last_fill_price: Optional[float] = None
    commission: Optional[float] = None
    remaining_quantity: Optional[float] = None
    broker_order_id: Optional[str] = None
    reason: Optional[str] = None # For rejections/cancellations
    timestamp_utc: Optional[str] = None # Last update timestamp

# Define Pydantic model for position response
class PositionResponse(BaseModel):
    user_id: str
    symbol: str
    quantity: float
    average_price: float
    sec_type: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    con_id: Optional[int] = None
    last_market_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    market_value: Optional[float] = None
    realized_pnl_from_event: Optional[float] = None

# Pydantic model for Portfolio Summary
class PortfolioSummaryResponse(BaseModel):
    user_id: str
    total_portfolio_value_usd: float
    total_positions_value_usd: float
    total_cash_balance_usd: float
    buying_power_usd: float
    total_realized_pnl_usd: float
    total_unrealized_pnl_usd: float
    timestamp_utc: datetime


# Initialize Kafka Producer and Consumer related objects
# These now use app_config internally, so no kafka_web_cfg needed for instantiation
web_order_producer = WebOrderProducer() # Uses app_config internally
data_cache_svc = DataCacheService()
event_consumer_svc = WebAppEventConsumerService(data_cache_svc=data_cache_svc) # Uses app_config internally
event_consumer_svc.start()

# Include the authentication router (already configured to use app_config)
# Apply rate limit to the entire auth router, or specific endpoints within it (see auth.py modification)
app.include_router(auth_router, prefix="/auth", tags=["authentication"])


# --- API Endpoints ---

@app.post("/orders", response_model=OrderResponse, status_code=status.HTTP_202_ACCEPTED, summary="Submit a New Order")
@limiter.limit("30/minute") # Example rate limit for order submission
async def create_order(request: Request, order_payload: OrderCreate, current_user: User = Depends(get_current_active_user)):
    logger.info(f"API: User '{current_user.username}' submitting order: {order_payload.symbol}, Qty: {order_payload.quantity}")
    try:
        platform_order_id = web_order_producer.send_new_order_request(
            user_id=current_user.username,
            api_order_data=order_payload
        )

        # Return an acknowledgement. The final status will come via WebSocket/polling later.
        response = OrderResponse(
            order_id=platform_order_id, # This is the ID generated by web_order_producer
            user_id=current_user.username,
            symbol=order_payload.symbol.upper(), # Ensure symbol is uppercase
            quantity=order_payload.quantity,
            order_type=order_payload.order_type.upper(),
            price=order_payload.price,
            status="ACCEPTED_BY_GATEWAY" # Or "PENDING_ENGINE_ACCEPTANCE" / "ROUTED"
        )
        logger.info(f"API: Order {platform_order_id} for user '{current_user.username}' accepted by gateway, sent to Trading Engine.")
        return response
    except Exception as e:
        logger.error(f"API: Failed to submit order for user '{current_user.username}': {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to submit order to trading system.")

@app.get("/orders/{order_id}", response_model=OrderResponse, summary="Get Order Status by ID")
async def get_order(order_id: str, current_user: User = Depends(get_current_active_user)):
    logger.info(f"API: User '{current_user.username}' requesting status for order '{order_id}'")
    # DataCacheService.get_order_by_id returns an OrderResponse Pydantic model or None
    order_data = data_cache_svc.get_order_by_id(user_id=current_user.username, order_id=order_id)
    if not order_data:
        # To distinguish between not found and not owned, cache would need to store orders without user_id key first
        # For now, assume if not found for this user, it's a 404.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found or not associated with this user.")
    # Ensure the order actually belongs to the user if cache get_order_by_id doesn't check user_id internally
    if order_data.user_id != current_user.username:
        logger.warning(f"User '{current_user.username}' attempted to access order '{order_id}' not belonging to them (belongs to '{order_data.user_id}').")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this order.")
    return order_data

@app.get("/orders", response_model=List[OrderResponse], summary="Get All Orders for Current User")
async def get_all_user_orders(current_user: User = Depends(get_current_active_user)):
    logger.info(f"API: User '{current_user.username}' requesting all their orders.")
    # DataCacheService.get_orders_by_user returns a list of OrderResponse Pydantic models
    user_orders = data_cache_svc.get_orders_by_user(user_id=current_user.username)
    return user_orders

@app.get("/portfolio/positions", response_model=List[PositionResponse], summary="Get All Positions for Current User")
async def get_user_positions(current_user: User = Depends(get_current_active_user)):
    logger.info(f"API: User '{current_user.username}' requesting all their positions.")
    # DataCacheService.get_all_positions_by_user returns List[PositionData Pydantic models]
    positions_data = data_cache_svc.get_all_positions_by_user(user_id=current_user.username)
    # Pydantic models are directly usable in response if response_model matches type
    return positions_data

@app.get("/portfolio/summary", response_model=PortfolioSummaryResponse, summary="Get Portfolio Summary for Current User")
async def get_portfolio_summary_endpoint(current_user: User = Depends(get_current_active_user)):
    logger.info(f"API: User '{current_user.username}' requesting portfolio summary.")
    try:
        summary_data = data_cache_svc.get_portfolio_summary(user_id=current_user.username)
        # Check if the summary has meaningful data, especially if no account summary was ever cached.
        if summary_data.total_portfolio_value_usd == 0.0 and \
           summary_data.total_cash_balance_usd == 0.0 and \
           not data_cache_svc._account_summary_cache.get(current_user.username):
            logger.warning(f"Portfolio summary for {current_user.username} might be incomplete; no account summary data in cache. Returning potentially zeroed data.")
            # Depending on requirements, could return 404 or a specific message.
            # For now, returns the (potentially zeroed) summary.
        return summary_data
    except Exception as e:
        logger.error(f"API: Error generating portfolio summary for user '{current_user.username}': {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not generate portfolio summary.")

@app.get("/health", summary="Health Check", response_model=dict)
async def health_check(current_user: User = Depends(get_current_active_user)):
    """
    Health check endpoint that also verifies authentication.
    Returns the current active user's username.
    """
    return {"status": "healthy", "active_user": current_user.username, "message": "Authenticated and operational."}

@app.get("/")
async def read_root():
    return {"message": "Welcome to the Trading Platform API. Visit /docs for API documentation."}

# Add shutdown event for FastAPI to close producer
@app.on_event("shutdown")
def shutdown_event():
    logger.info("Web backend shutting down. Closing Kafka producer and event consumer...")
    if web_order_producer:
        web_order_producer.close()
        logger.info("Web order producer closed.")
    if event_consumer_svc:
        event_consumer_svc.stop()
        logger.info("Web event consumer service stopped.")

# --- WebSocket Endpoint ---
@app.websocket("/ws/user")
async def websocket_user_endpoint(websocket: WebSocket, token: Optional[str] = None):
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing token query parameter")
        return

    user = await get_user_from_token_for_websocket(token)
    if not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or expired token")
        return

    await websocket_conn_manager.connect(websocket, user.username)
    try:
        while True:
            # Keep connection alive, listen for client messages (e.g., ping, commands)
            data = await websocket.receive_text()
            logger.debug(f"Received text from user {user.username} via WebSocket: {data}")

            # Example: Echo back or handle specific client messages like ping
            if data.lower() == "ping":
                await websocket.send_json({"type": "PONG", "timestamp": time.time()})
            # else:
            #     await websocket.send_text(f"Message text was: {data}") # Example echo

    except WebSocketDisconnect:
        logger.info(f"WebSocket for user {user.username} disconnected (client closed).")
    except Exception as e:
        logger.error(f"Error in WebSocket for user {user.username}: {e}", exc_info=True)
        # Attempt to close gracefully if not already closed by an error during send/receive
        try:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        except RuntimeError: # May happen if connection is already abruptly closed
            pass
    finally:
        websocket_conn_manager.disconnect(websocket, user.username)


# To run this FastAPI app:
# 1. Install FastAPI and Uvicorn: pip install fastapi "uvicorn[standard]"
# 2. Ensure KAFKA_BOOTSTRAP_SERVERS and KAFKA_NEW_ORDERS_TOPIC env vars are set if not using defaults.
# 3. Ensure trading_engine.gen is in PYTHONPATH or accessible.
# 4. Run Uvicorn: uvicorn webapp.backend.main:app --reload --port 8000
# Then access the API at http://localhost:8000 or docs at http://localhost:8000/docs
