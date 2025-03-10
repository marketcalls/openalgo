from passlib.context import CryptContext
from argon2 import PasswordHasher
import re
from typing import Tuple

# Use Argon2 for password hashing as specified in requirements
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")
ph = PasswordHasher()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash"""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """Generate a secure hash for a password"""
    return pwd_context.hash(password)


def validate_password_strength(password: str) -> Tuple[bool, str]:
    """
    Validate password based on strength requirements
    Returns: (is_valid, error_message)
    """
    # Check password length (minimum 8 characters)
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    # Check for uppercase letters
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    
    # Check for lowercase letters
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    
    # Check for digits
    if not re.search(r'\d', password):
        return False, "Password must contain at least one number"
    
    # Check for special characters
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"
    
    # Check for common patterns
    common_patterns = [
        "password", "123456", "qwerty", "admin", "welcome",
        "123123", "abcabc", "abc123", "Password", "admin123"
    ]
    
    for pattern in common_patterns:
        if pattern in password.lower():
            return False, "Password contains a common pattern"
    
    # Check for sequential characters
    for i in range(len(password) - 2):
        if ord(password[i]) + 1 == ord(password[i+1]) and ord(password[i+1]) + 1 == ord(password[i+2]):
            return False, "Password contains sequential characters"
    
    return True, ""


def calculate_password_strength(password: str) -> int:
    """
    Calculate password strength score (0-100)
    This powers the visual password strength meter
    """
    score = 0
    
    # Length contribution (up to 40 points)
    length_score = min(len(password) * 2, 40)
    score += length_score
    
    # Character variety (up to 40 points)
    has_lower = bool(re.search(r'[a-z]', password))
    has_upper = bool(re.search(r'[A-Z]', password))
    has_digit = bool(re.search(r'\d', password))
    has_special = bool(re.search(r'[!@#$%^&*(),.?":{}|<>]', password))
    
    variety_score = (has_lower + has_upper + has_digit + has_special) * 10
    score += variety_score
    
    # Complexity patterns (up to 20 points)
    complexity_score = 0
    
    # Reward for non-sequential characters
    sequential_count = 0
    for i in range(len(password) - 2):
        if ord(password[i]) + 1 == ord(password[i+1]) and ord(password[i+1]) + 1 == ord(password[i+2]):
            sequential_count += 1
    
    if sequential_count == 0:
        complexity_score += 10
    else:
        complexity_score += max(0, 10 - sequential_count * 2)
    
    # Reward for no common patterns
    common_patterns = ["password", "123456", "qwerty", "admin", "welcome"]
    has_common_pattern = any(pattern in password.lower() for pattern in common_patterns)
    
    if not has_common_pattern:
        complexity_score += 10
    
    score += complexity_score
    
    return score
