from typing import Optional
from pydantic import BaseModel, Field


class Token(BaseModel):
    """Schema for token response"""
    access_token: str
    token_type: str
    refresh_token: Optional[str] = None


class TokenData(BaseModel):
    """Schema for data contained in a token"""
    username: Optional[str] = None
    user_id: Optional[int] = None


class TokenPayload(BaseModel):
    """Schema for JWT token payload"""
    sub: Optional[str] = None
    exp: int = Field(..., description="Expiration timestamp")
    type: Optional[str] = "access"


class RefreshToken(BaseModel):
    """Schema for refresh token request"""
    refresh_token: str
