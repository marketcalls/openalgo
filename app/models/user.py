from tortoise import fields, models
from tortoise.contrib.pydantic import pydantic_model_creator
from datetime import datetime, timedelta
from app.core.config import settings


class User(models.Model):
    """
    User model for authentication and account management
    Implements secure password storage and account lockout functionality
    """
    id = fields.IntField(pk=True)
    email = fields.CharField(max_length=255, unique=True, index=True)
    username = fields.CharField(max_length=50, unique=True, index=True)
    hashed_password = fields.CharField(max_length=255)
    first_name = fields.CharField(max_length=50, null=True)
    last_name = fields.CharField(max_length=50, null=True)
    is_active = fields.BooleanField(default=True)
    is_superuser = fields.BooleanField(default=False)
    
    # Account security fields
    failed_login_attempts = fields.IntField(default=0)
    last_failed_login = fields.DatetimeField(null=True)
    account_locked_until = fields.DatetimeField(null=True)
    last_password_change = fields.DatetimeField(auto_now_add=True)
    password_reset_token = fields.CharField(max_length=255, null=True)
    password_reset_expires = fields.DatetimeField(null=True)
    
    # Timestamps
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    
    def is_account_locked(self) -> bool:
        """Check if account is currently locked due to failed login attempts"""
        if not self.account_locked_until:
            return False
        
        return self.account_locked_until > datetime.utcnow()
    
    async def increment_failed_login(self) -> None:
        """Increment failed login attempts and lock account if threshold reached"""
        self.failed_login_attempts += 1
        self.last_failed_login = datetime.utcnow()
        
        # Lock account if max attempts reached
        if self.failed_login_attempts >= settings.ACCOUNT_LOCKOUT_ATTEMPTS:
            lockout_time = datetime.utcnow() + timedelta(
                minutes=settings.ACCOUNT_LOCKOUT_TIME_MINUTES
            )
            self.account_locked_until = lockout_time
        
        await self.save()
    
    async def reset_failed_login(self) -> None:
        """Reset failed login attempts counter after successful login"""
        self.failed_login_attempts = 0
        self.last_failed_login = None
        self.account_locked_until = None
        await self.save()
    
    def __str__(self):
        return f"{self.username} ({self.email})"
    
    class Meta:
        table = "users"


# Pydantic models for validation and serialization
User_Pydantic = pydantic_model_creator(
    User, name="User", exclude=("hashed_password", "password_reset_token")
)

UserCreate_Pydantic = pydantic_model_creator(
    User, name="UserCreate", exclude_readonly=True
)
