from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from jose import jwt, JWTError
from fastapi import HTTPException, status, Depends, Request
from fastapi.security import OAuth2PasswordBearer
from pydantic import ValidationError
import logging

from app.core.config import settings
from app.models.user import User
from app.schemas.token import TokenPayload, TokenData

logger = logging.getLogger(__name__)

# OAuth2 configuration for token validation
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/login/token",
    auto_error=False
)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a new JWT access token
    
    Args:
        data: Data to encode in the token (must include 'sub' key with user ID)
        expires_delta: Optional expiration time delta
        
    Returns:
        Encoded JWT token as string
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )
    
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    
    return encoded_jwt


def create_refresh_token(data: Dict[str, Any]) -> str:
    """
    Create a new JWT refresh token with longer expiry
    
    Args:
        data: Data to encode in the token (must include 'sub' key with user ID)
        
    Returns:
        Encoded JWT token as string
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode.update({"exp": expire, "type": "refresh"})
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    
    return encoded_jwt


async def get_current_user(token: str = Depends(oauth2_scheme), request: Request = None) -> Optional[User]:
    """
    Validate token and return current user
    
    Args:
        token: JWT token from Authorization header
        request: FastAPI request object to check for cookies
        
    Returns:
        User object if token is valid, None otherwise
        
    Raises:
        HTTPException: If token is invalid
    """
    # Log the start of authentication process
    logger.debug("Starting user authentication process")
    
    # Check for token in cookie if no Authorization header token
    if not token and request:
        logger.debug("No Authorization header token, checking cookies")
        auth_cookie = request.cookies.get("access_token")
        if auth_cookie and auth_cookie.startswith("Bearer "):
            token = auth_cookie.replace("Bearer ", "")
            logger.debug("Found token in cookies")
        else:
            logger.debug("No token found in cookies")
    
    if not token:
        logger.debug("No authentication token provided - likely unauthenticated page access")
        return None
    
    try:
        logger.debug("Decoding JWT token")
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        
        token_data = TokenPayload(**payload)
        
        # Check token expiration
        if datetime.fromtimestamp(token_data.exp) < datetime.utcnow():
            logger.warning("Authentication failed: Token expired")
            return None
        
        # Ensure it's an access token
        if getattr(token_data, "type", None) != "access":
            logger.warning(f"Authentication failed: Invalid token type: {getattr(token_data, 'type', 'None')}")
            return None
        
        # Extract user ID
        user_id = token_data.sub
        if user_id is None:
            logger.warning("Authentication failed: No user ID in token")
            return None
            
    except (JWTError, ValidationError) as e:
        logger.error(f"Authentication failed: JWT Error: {str(e)}")
        return None
    
    # Get user from database
    logger.debug(f"Looking up user with ID: {user_id}")
    user = await User.get_or_none(id=user_id)
    if user is None:
        logger.warning(f"Authentication failed: User with ID {user_id} not found")
        return None
    
    # Check if user is active
    if not user.is_active:
        logger.warning(f"Authentication failed: User {user.username} (ID: {user_id}) is inactive")
        return None
    
    logger.info(f"Authentication successful for user: {user.username} (ID: {user_id})")
    return user


def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Get current active user, raising an exception if no user or inactive
    
    Args:
        current_user: User from token validation
        
    Returns:
        User object if active
        
    Raises:
        HTTPException: If no user or user is inactive
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    
    return current_user
