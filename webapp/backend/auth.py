import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt # Ensure python-jose[cryptography] is installed
from passlib.context import CryptContext # Ensure passlib[bcrypt] is installed
from pydantic import BaseModel, EmailStr

# Import centralized application configuration
from .config_web import app_config

# --- Configuration (now sourced from app_config) ---
# SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES are now accessed via app_config
# e.g., app_config.JWT_SECRET_KEY

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# tokenUrl should be relative to the prefix of the auth router itself,
# so if auth_router is mounted at /auth, and this endpoint is /token, then tokenUrl="token"
# If auth_router is mounted at / (app level), then tokenUrl="/auth/token" (if endpoint is /auth/token)
# Given auth_router.post("/token", ...), tokenUrl="token" is correct if router is at /auth
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# --- User Model (Pydantic for API, could be SQLAlchemy for DB) ---
class UserBase(BaseModel):
    username: str
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None

class UserCreate(UserBase):
    password: str

class User(UserBase):
    disabled: Optional[bool] = False

class UserInDBBase(UserBase):
    id: Optional[int] = None # Or UUID, depending on DB

    class Config:
        orm_mode = True # Pydantic V1 style, or from_attributes = True for V2

class UserInDB(UserInDBBase): # Represents user stored in DB (includes hashed_password)
    hashed_password: str


# --- Mock User Database ---
MOCK_USERS_DB_WITH_HASHED_PASSWORDS: Dict[str, UserInDB] = {}

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def _init_mock_user():
    if "testuser" not in MOCK_USERS_DB_WITH_HASHED_PASSWORDS:
        hashed_password = get_password_hash("testpassword")
        test_user = UserInDB(
            username="testuser",
            email="testuser@example.com",
            full_name="Test User",
            disabled=False,
            hashed_password=hashed_password
        )
        MOCK_USERS_DB_WITH_HASHED_PASSWORDS["testuser"] = test_user
_init_mock_user()


def get_user_from_db(username: str) -> Optional[UserInDB]:
    """Retrieves a user from the mock database."""
    return MOCK_USERS_DB_WITH_HASHED_PASSWORDS.get(username)

# --- Token Creation ---
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=app_config.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, app_config.JWT_SECRET_KEY, algorithm=app_config.JWT_ALGORITHM)
    return encoded_jwt

# --- Dependency to get current user ---
async def get_current_active_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, app_config.JWT_SECRET_KEY, algorithms=[app_config.JWT_ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user_in_db = get_user_from_db(username) # This returns UserInDB
    if user_in_db is None:
        raise credentials_exception

    # Convert UserInDB to User Pydantic model.
    # UserInDB has orm_mode = True (via UserInDBBase), so User.from_orm can be used.
    user = User.from_orm(user_in_db)

    if user.disabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")
    return user

# --- Token Model for response ---
class Token(BaseModel):
    access_token: str
    token_type: str

# --- FastAPI Router for Authentication ---
from fastapi import APIRouter, Request
from ..rate_limiter import limiter # Import the shared limiter

auth_router = APIRouter()

@auth_router.post("/token", response_model=Token, summary="User Login - Get JWT Access Token")
@limiter.limit("5/minute") # Apply rate limit decorator
async def login_for_access_token(request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    user_in_db = get_user_from_db(form_data.username)
    if not user_in_db or not verify_password(form_data.password, user_in_db.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=app_config.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_in_db.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


# --- Get User from Token for WebSocket ---
async def get_user_from_token_for_websocket(token: str) -> Optional[User]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, app_config.JWT_SECRET_KEY, algorithms=[app_config.JWT_ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if username is None:
            return None

        user_in_db = get_user_from_db(username) # Uses existing mock DB
        if user_in_db is None:
            return None

        # Convert UserInDB to User Pydantic model
        # Pydantic V1: .dict(exclude=...)
        # Pydantic V2: .model_dump(exclude=...)
        # Assuming UserInDB.Config.orm_mode = True allows User.from_orm(user_in_db) as well
        user_for_ws = User.from_orm(user_in_db) # Excludes hashed_password by model definition

        if user_for_ws.disabled:
            return None
        return user_for_ws
    except JWTError:
        return None
