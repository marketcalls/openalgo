from typing import Optional
from pydantic import BaseModel, EmailStr, Field, validator
import re
from app.auth.password import validate_password_strength


class UserBase(BaseModel):
    """Base User Schema with common attributes"""
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    is_active: Optional[bool] = True


class UserCreate(UserBase):
    """Schema for user creation"""
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=12)
    confirm_password: str

    @validator('username')
    def username_alphanumeric(cls, v):
        if not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError('Username must be alphanumeric with underscores only')
        return v
    
    @validator('password')
    def password_strength(cls, v):
        valid, error_message = validate_password_strength(v)
        if not valid:
            raise ValueError(error_message)
        return v
    
    @validator('confirm_password')
    def passwords_match(cls, v, values, **kwargs):
        if 'password' in values and v != values['password']:
            raise ValueError('Passwords do not match')
        return v


class UserUpdate(UserBase):
    """Schema for user updates"""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    username: Optional[str] = None

    @validator('username')
    def username_alphanumeric(cls, v):
        if v and not re.match(r'^[a-zA-Z0-9_]+$', v):
            raise ValueError('Username must be alphanumeric with underscores only')
        return v


class UserInDB(UserBase):
    """Schema for user in database (with hashed password)"""
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    hashed_password: str
    is_superuser: bool = False
    created_at: str
    updated_at: str


class User(UserBase):
    """Schema for user responses"""
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_superuser: bool = False
    created_at: str


class UserLogin(BaseModel):
    """Schema for user login credentials"""
    username: str
    password: str


class PasswordReset(BaseModel):
    """Schema for password reset request"""
    email: EmailStr


class PasswordChange(BaseModel):
    """Schema for password change"""
    current_password: str
    new_password: str = Field(..., min_length=12)
    confirm_password: str
    
    @validator('new_password')
    def password_strength(cls, v):
        valid, error_message = validate_password_strength(v)
        if not valid:
            raise ValueError(error_message)
        return v
    
    @validator('confirm_password')
    def passwords_match(cls, v, values, **kwargs):
        if 'new_password' in values and v != values['new_password']:
            raise ValueError('Passwords do not match')
        return v


class PasswordResetConfirm(BaseModel):
    """Schema for password reset confirmation"""
    token: str
    new_password: str = Field(..., min_length=12)
    confirm_password: str
    
    @validator('new_password')
    def password_strength(cls, v):
        valid, error_message = validate_password_strength(v)
        if not valid:
            raise ValueError(error_message)
        return v
    
    @validator('confirm_password')
    def passwords_match(cls, v, values, **kwargs):
        if 'new_password' in values and v != values['new_password']:
            raise ValueError('Passwords do not match')
        return v
