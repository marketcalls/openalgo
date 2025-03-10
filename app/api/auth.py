from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Form
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from jose import jwt, JWTError
import secrets
from pathlib import Path
import logging

from app.core.config import settings
from app.models.user import User
from app.schemas.user import UserCreate, UserLogin, PasswordReset, PasswordResetConfirm
from app.schemas.token import Token
from app.auth.jwt import create_access_token, create_refresh_token, get_current_user
from app.auth.password import verify_password, get_password_hash, validate_password_strength, calculate_password_strength
from app.utils.ip_utils import get_ip_addresses

# Setup templates
templates = Jinja2Templates(directory=str(Path("app/templates")))

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: Optional[str] = None):
    """Render login page"""
    return templates.TemplateResponse(
        "auth/login.html", {"request": request, "error": error}
    )


@router.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """Process login form submission"""
    logger.info(f"Login attempt for username: {username}")
    
    # Capture IP addresses using our utility
    client_host, public_ip = await get_ip_addresses(request)
    
    logger.info(f"Login attempt from Local IP: {client_host}, Public IP: {public_ip}")
    
    # Find user by username or email
    user = await User.get_or_none(username=username)
    if not user:
        logger.info(f"User not found by username, trying email lookup: {username}")
        user = await User.get_or_none(email=username)
    
    if not user:
        logger.warning(f"Login failed: User not found for {username}")
        # Check if this is an HTMX request
        is_htmx = request.headers.get("HX-Request") == "true"
        logger.debug(f"Is HTMX request: {is_htmx}")
        
        if is_htmx:
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "error": "Invalid username or password"},
                status_code=status.HTTP_401_UNAUTHORIZED
            )
        else:
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "error": "Invalid username or password"},
                status_code=status.HTTP_401_UNAUTHORIZED
            )
    
    logger.info(f"User found: {user.username} (ID: {user.id})")
    
    # Check if account is locked
    if user.is_account_locked():
        logger.warning(f"Login attempt on locked account: {user.username} (ID: {user.id})")
        # Check if this is an HTMX request
        is_htmx = request.headers.get("HX-Request") == "true"
        error_message = f"Account locked due to too many failed attempts. Try again later."
        if is_htmx:
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "error": error_message},
                status_code=status.HTTP_403_FORBIDDEN
            )
        else:
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "error": error_message},
                status_code=status.HTTP_403_FORBIDDEN
            )
    
    # Verify password
    logger.debug(f"Verifying password for user: {user.username}")
    if not verify_password(password, user.hashed_password):
        logger.warning(f"Invalid password for user: {user.username} (ID: {user.id})")
        # Increment failed login attempts
        await user.increment_failed_login()
        logger.info(f"Failed login count increased for {user.username}")
        
        # Check if this is an HTMX request
        is_htmx = request.headers.get("HX-Request") == "true"
        if is_htmx:
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "error": "Invalid username or password"},
                status_code=status.HTTP_401_UNAUTHORIZED
            )
        else:
            return templates.TemplateResponse(
                "auth/login.html",
                {"request": request, "error": "Invalid username or password"},
                status_code=status.HTTP_401_UNAUTHORIZED
            )
    
    # Reset failed login attempts on successful login
    await user.reset_failed_login()
    logger.info(f"Password verified for user: {user.username} (ID: {user.id})")
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expires
    )
    logger.info(f"Access token created for user: {user.username} (ID: {user.id})")
    
    # Login successful
    logger.info(f"Login successful for user: {user.username} (ID: {user.id})")
    
    # In a real app, you might want to record login history with IP info
    # await LoginHistory.create(user=user, local_ip=client_host, public_ip=public_ip)
    
    # Store the login info in the session
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    
    # Create JWT token
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    
    # Store login IPs in the cookie for dashboard display
    response.set_cookie(
        key="login_ips",
        value=jwt.encode(
            {"local_ip": client_host, "public_ip": public_ip},
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM
        ),
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
    )
    
    # Set JWT as cookie
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        secure=not settings.DEBUG,  # Secure in production
        samesite="lax",
        max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    logger.info(f"Redirecting to dashboard with status code: {status.HTTP_302_FOUND}")
    
    return response


@router.post("/login/token", response_model=Token)
async def login_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """API endpoint for token-based authentication (OAuth2)"""
    # Find user by username
    user = await User.get_or_none(username=form_data.username)
    if not user:
        user = await User.get_or_none(email=form_data.username)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if account is locked
    if user.is_account_locked():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account locked due to too many failed attempts",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify password
    if not verify_password(form_data.password, user.hashed_password):
        # Increment failed login attempts
        await user.increment_failed_login()
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Reset failed login attempts on successful login
    await user.reset_failed_login()
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expires
    )
    
    # Create refresh token
    refresh_token = create_refresh_token(data={"sub": str(user.id)})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token
    }


@router.post("/logout")
async def logout():
    """Log out user by clearing auth cookie"""
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key="access_token")
    return response


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Render registration page"""
    return templates.TemplateResponse("auth/register.html", {"request": request})


@router.post("/register", response_class=HTMLResponse)
async def register(
    request: Request,
    email: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    """Process registration form submission"""
    # Validate passwords match
    if password != confirm_password:
        return templates.TemplateResponse(
            "auth/register.html",
            {
                "request": request,
                "error": "Passwords do not match",
                "email": email,
                "username": username
            }
        )
    
    # Validate password strength
    valid, error_message = validate_password_strength(password)
    if not valid:
        return templates.TemplateResponse(
            "auth/register.html",
            {
                "request": request,
                "error": error_message,
                "email": email,
                "username": username
            }
        )
    
    # Check if email already exists
    existing_email = await User.get_or_none(email=email)
    if existing_email:
        return templates.TemplateResponse(
            "auth/register.html",
            {
                "request": request,
                "error": "Email already registered",
                "username": username
            }
        )
    
    # Check if username already exists
    existing_username = await User.get_or_none(username=username)
    if existing_username:
        return templates.TemplateResponse(
            "auth/register.html",
            {
                "request": request,
                "error": "Username already taken",
                "email": email
            }
        )
    
    # Check if this is the first user (will be made superadmin)
    user_count = await User.all().count()
    is_first_user = user_count == 0
    
    # Create new user
    hashed_password = get_password_hash(password)
    user = User(
        email=email,
        username=username,
        hashed_password=hashed_password,
        is_superuser=is_first_user  # First user is automatically a superadmin
    )
    
    # Log superadmin creation if this is the first user
    if is_first_user:
        logger.info(f"Creating first user as superadmin: {username} ({email})")
        
    await user.save()
    
    # Create access token
    access_token_expires = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expires
    )
    
    # Set JWT as cookie and redirect to dashboard
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        secure=not settings.DEBUG,  # Secure in production
        samesite="lax",
        max_age=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    
    return response


@router.post("/register/validate", response_class=HTMLResponse)
async def register_validate(
    request: Request,
    email: str = Form(None),
    username: str = Form(None),
    password: str = Form(None),
    confirm_password: str = Form(None),
):
    """Validate registration form data for HTMX requests"""
    errors = []
    
    # Validate email if provided
    if email:
        existing_email = await User.get_or_none(email=email)
        if existing_email:
            errors.append("Email is already registered")
    
    # Validate username if provided
    if username:
        existing_username = await User.get_or_none(username=username)
        if existing_username:
            errors.append("Username is already taken")
    
    # Validate password if provided
    if password and confirm_password:
        if password != confirm_password:
            errors.append("Passwords do not match")
        else:
            valid, error_message = validate_password_strength(password)
            if not valid:
                errors.append(error_message)
    
    # Return HTML for validation errors
    if errors:
        error_html = "<div class='alert alert-error shadow-lg mt-4'><ul>"
        for error in errors:
            error_html += f"<li>{error}</li>"
        error_html += "</ul></div>"
        return HTMLResponse(content=error_html)
    
    return HTMLResponse(content="")


@router.post("/validate-password")
async def validate_password(request: Request, password: str = Form(...)):
    """Validate password strength and return feedback"""
    valid, error_message = validate_password_strength(password)
    strength_score = calculate_password_strength(password)
    
    # Prepare feedback data
    feedback = {
        "valid": valid,
        "message": error_message if not valid else "Password is strong",
        "strength": strength_score,
        "strength_text": "Weak" if strength_score < 50 else "Fair" if strength_score < 75 else "Good" if strength_score < 100 else "Strong"
    }
    
    # Return HTML for password feedback
    strength_class = "strength-weak"
    if strength_score >= 100:
        strength_class = "strength-strong"
    elif strength_score >= 75:
        strength_class = "strength-good"
    elif strength_score >= 50:
        strength_class = "strength-fair"
    
    html_response = f"""
    <div class="password-strength-meter">
        <div class="password-strength-meter-fill {strength_class}" style="width: {min(100, strength_score)}%;"></div>
    </div>
    <div class="mt-1 text-sm">
        Password strength: <span class="{strength_class}">{feedback['strength_text']}</span>
    </div>
    <p class="text-sm text-base-content/70 mt-2">Password must contain:</p>
    <ul class="list-disc list-inside text-xs text-base-content/70 mt-1">
        <li class="{'' if len(password) >= 8 else 'text-error'}">At least 8 characters</li>
        <li class="{'' if any(c.isupper() for c in password) else 'text-error'}">At least one uppercase letter</li>
        <li class="{'' if any(c.islower() for c in password) else 'text-error'}">At least one lowercase letter</li>
        <li class="{'' if any(c.isdigit() for c in password) else 'text-error'}">At least one number</li>
        <li class="{'' if any(c in '!@#$%^&*(),.?":{}|<>' for c in password) else 'text-error'}">At least one special character</li>
    </ul>
    """
    
    return HTMLResponse(content=html_response)


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    """Render forgot password page"""
    return templates.TemplateResponse("auth/forgot_password.html", {"request": request})


@router.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password(request: Request, email: str = Form(...)):
    """Process forgot password request"""
    # Find user by email
    user = await User.get_or_none(email=email)
    
    if user:
        # Generate password reset token
        reset_token = secrets.token_urlsafe(32)
        
        # Set token expiry (24 hours)
        token_expires = datetime.utcnow() + timedelta(hours=24)
        
        # Store token in user record
        user.password_reset_token = reset_token
        user.password_reset_expires = token_expires
        await user.save()
        
        # In a real application, you would send an email with the reset link
        # For this demo, we'll just log it
        reset_url = f"/auth/reset-password?token={reset_token}"
        logger.info(f"Password reset URL: {reset_url}")
    
    # Always return success to prevent email enumeration
    success_html = """
    <div class="alert alert-success mt-4">
        <svg xmlns="http://www.w3.org/2000/svg" class="stroke-current shrink-0 h-6 w-6" fill="none" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
        <span>If an account exists with that email, a password reset link has been sent.</span>
    </div>
    """
    
    return HTMLResponse(content=success_html)


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, token: str):
    """Render reset password page"""
    # Validate token
    user = await User.get_or_none(password_reset_token=token)
    
    if not user or not user.password_reset_expires or user.password_reset_expires < datetime.utcnow():
        # Invalid or expired token
        return templates.TemplateResponse(
            "auth/login.html",
            {
                "request": request,
                "error": "Password reset link is invalid or has expired"
            }
        )
    
    return templates.TemplateResponse(
        "auth/reset_password.html", 
        {
            "request": request,
            "token": token
        }
    )


@router.post("/reset-password", response_class=HTMLResponse)
async def reset_password(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
):
    """Process reset password request"""
    # Validate passwords match
    if password != confirm_password:
        return templates.TemplateResponse(
            "auth/reset_password.html",
            {
                "request": request,
                "token": token,
                "error": "Passwords do not match"
            }
        )
    
    # Validate password strength
    valid, error_message = validate_password_strength(password)
    if not valid:
        return templates.TemplateResponse(
            "auth/reset_password.html",
            {
                "request": request,
                "token": token,
                "error": error_message
            }
        )
    
    # Find user by token
    user = await User.get_or_none(password_reset_token=token)
    
    if not user or not user.password_reset_expires or user.password_reset_expires < datetime.utcnow():
        # Invalid or expired token
        return templates.TemplateResponse(
            "auth/login.html",
            {
                "request": request,
                "error": "Password reset link is invalid or has expired"
            }
        )
    
    # Update password
    user.hashed_password = get_password_hash(password)
    user.password_reset_token = None
    user.password_reset_expires = None
    user.last_password_change = datetime.utcnow()
    await user.save()
    
    # Redirect to login with success message
    return templates.TemplateResponse(
        "auth/login.html",
        {
            "request": request,
            "success": "Your password has been updated successfully. Please log in."
        }
    )
