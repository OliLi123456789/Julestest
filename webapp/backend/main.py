from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional # Required for type hinting

# --- Mocked User Authentication ---
# In a real application, use OAuth2 with password flow, JWT tokens, etc.
# For now, a simple hardcoded user and a dependency to check a mock token.

# Mock database of users (username: hashed_password) - Hashing not shown for simplicity
MOCK_USERS_DB = {"testuser": "testpassword"}
# Mock database for API keys or tokens
MOCK_API_TOKENS = {"supersecretapikey": "testuser"}

def get_current_user(x_token: str = Depends(lambda x_token: x_token if x_token else HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"))):
    """
    Mock dependency to "authenticate" a user based on a token.
    In a real app, this would involve validating a JWT or session.
    The x_token is expected to be passed as a header.
    """
    user = MOCK_API_TOKENS.get(x_token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"}, # Though not strictly Bearer here
        )
    return user

class UserLogin(BaseModel):
    username: str
    password: str

# --- OMS Interface (Order Model - simplified for API) ---
# These would ideally be shared models or adaptors for the OMS Order model
class OrderCreate(BaseModel):
    symbol: str
    quantity: int
    order_type: str # e.g., "MARKET" or "LIMIT"
    price: Optional[float] = None

class OrderResponse(BaseModel):
    order_id: str
    user_id: str
    symbol: str
    quantity: int
    order_type: str
    price: Optional[float] = None
    status: str

# Mock OMS - In a real system, this would interface with the trading_engine.oms.OrderManagementSystem
class MockOMS:
    def __init__(self):
        self.orders = {}
        self.next_order_id = 1

    def submit_order(self, user_id: str, order_data: OrderCreate) -> OrderResponse:
        order_id = f"WEB_ORD_{self.next_order_id}"
        self.next_order_id += 1
        # Basic validation/transformation can happen here or in OMS
        response = OrderResponse(
            order_id=order_id,
            user_id=user_id,
            symbol=order_data.symbol,
            quantity=order_data.quantity,
            order_type=order_data.order_type.upper(),
            price=order_data.price,
            status="PENDING" # Initial status
        )
        self.orders[order_id] = response
        print(f"MockOMS: Order {order_id} submitted by {user_id} for {order_data.symbol}")
        return response

    def get_order_status(self, order_id: str) -> Optional[OrderResponse]:
        order = self.orders.get(order_id)
        # Simulate status changes for demonstration
        if order and order.status == "PENDING" and self.next_order_id % 3 == 0: # Arbitrary logic for simulation
            order.status = "FILLED"
            print(f"MockOMS: Order {order_id} status updated to FILLED")
        elif order and order.status == "PENDING" and self.next_order_id % 5 == 0:
             order.status = "CANCELED"
             print(f"MockOMS: Order {order_id} status updated to CANCELED")
        return order

    def get_user_orders(self, user_id: str) -> List[OrderResponse]:
        return [o for o in self.orders.values() if o.user_id == user_id]

# Initialize FastAPI app and Mock OMS
app = FastAPI(title="Trading Platform API")
mock_oms = MockOMS()

# --- API Endpoints ---

@app.post("/auth/token", summary="Mock User Login - Get API Token")
async def login_for_access_token(form_data: UserLogin):
    """
    Mock login. In a real app, validate user, create & return JWT.
    Here, it just checks hardcoded credentials and returns a mock API key.
    """
    if MOCK_USERS_DB.get(form_data.username) == form_data.password:
        # Find the token for the user (in a real app, you'd generate one)
        for token, user in MOCK_API_TOKENS.items():
            if user == form_data.username:
                return {"access_token": token, "token_type": "bearer"} # "bearer" is conventional
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )

@app.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED, summary="Submit a New Order")
async def create_order(order: OrderCreate, current_user: str = Depends(get_current_user)):
    """
    Submit a new trading order. Requires mock authentication.
    Interfaces with the (mocked) Order Management System.
    """
    # In a real system, you would convert OrderCreate to the OMS's Order model
    # and call the actual OMS. For now, directly use mock_oms.
    # Also, user_id would come from the authentication system (current_user here)
    print(f"API: Received order from user '{current_user}': {order.symbol}, Qty: {order.quantity}")
    order_response = mock_oms.submit_order(user_id=current_user, order_data=order)
    return order_response

@app.get("/orders/{order_id}", response_model=OrderResponse, summary="Get Order Status by ID")
async def get_order(order_id: str, current_user: str = Depends(get_current_user)):
    """
    Get the status of a specific order by its ID. Requires mock authentication.
    """
    print(f"API: User '{current_user}' requesting status for order '{order_id}'")
    order_status = mock_oms.get_order_status(order_id)
    if not order_status:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if order_status.user_id != current_user: # Ensure users can only see their own orders
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this order")
    return order_status

@app.get("/orders", response_model=List[OrderResponse], summary="Get All Orders for Current User")
async def get_all_user_orders(current_user: str = Depends(get_current_user)):
    """
    Get all orders submitted by the currently authenticated user.
    """
    print(f"API: User '{current_user}' requesting all their orders.")
    user_orders = mock_oms.get_user_orders(user_id=current_user)
    return user_orders

@app.get("/")
async def read_root():
    return {"message": "Welcome to the Trading Platform API. Visit /docs for API documentation."}

# To run this FastAPI app:
# 1. Install FastAPI and Uvicorn: pip install fastapi "uvicorn[standard]"
# 2. Run Uvicorn: uvicorn webapp.backend.main:app --reload --port 8000
# Then access the API at http://localhost:8000 or docs at http://localhost:8000/docs

# Placeholder for requirements.txt
# fastapi
# uvicorn[standard]
# pydantic
