from fastapi import APIRouter, Depends, Request, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from pathlib import Path
from datetime import datetime
from typing import Optional

from app.auth.jwt import get_current_user
from app.models.user import User

# Setup templates
templates = Jinja2Templates(directory=str(Path("app/templates")))

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, current_user: Optional[User] = Depends(get_current_user)):
    """Render home page"""
    return templates.TemplateResponse(
        "index.html", {
            "request": request,
            "user": current_user,
            "year": datetime.now().year
        }
    )


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: User = Depends(get_current_user)):
    """Render user dashboard"""
    import logging
    from jose import jwt, JWTError
    from app.core.config import settings
    
    logger = logging.getLogger(__name__)
    
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    
    # Get client's IP address for current session
    client_host = request.client.host if request.client else "127.0.0.1"
    
    # Get public IP from headers (if behind proxy) or from client host
    public_ip = request.headers.get('X-Forwarded-For', client_host)
    if ',' in public_ip:  # Handle multiple IPs in X-Forwarded-For
        public_ip = public_ip.split(',')[0].strip()
    
    logger.debug(f"Dashboard access - Local IP: {client_host}, Public IP: {public_ip}")
    
    # Try to get login IPs from cookie
    login_local_ip = client_host
    login_public_ip = public_ip
    
    login_ips_cookie = request.cookies.get("login_ips")
    if login_ips_cookie:
        try:
            ips_data = jwt.decode(
                login_ips_cookie, 
                settings.SECRET_KEY, 
                algorithms=[settings.ALGORITHM]
            )
            login_local_ip = ips_data.get("local_ip", client_host)
            login_public_ip = ips_data.get("public_ip", public_ip)
            logger.debug(f"Retrieved login IPs from cookie: {login_local_ip}, {login_public_ip}")
        except JWTError:
            logger.warning("Failed to decode login_ips cookie")
    
    # In a real application, you would fetch recent activities from a database
    # Mock data for demonstration
    activities = [
        {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "description": "Logged in",
            "local_ip": login_local_ip,
            "public_ip": login_public_ip
        }
    ]
    
    logger.debug(f"Activities data: {activities}")
    
    return templates.TemplateResponse(
        "dashboard.html", {
            "request": request,
            "user": current_user,
            "activities": activities,
            "last_login": "Today",
            "last_login_time": datetime.now().strftime("%H:%M"),
            "year": datetime.now().year
        }
    )


@router.get("/debug/auth-status", response_class=HTMLResponse)
async def debug_auth_status(request: Request, current_user: Optional[User] = Depends(get_current_user)):
    """Debug endpoint to check authentication status"""
    import logging
    logger = logging.getLogger(__name__)
    
    # Log request information
    logger.debug(f"Auth debug request from: {request.client.host}")
    logger.debug(f"Request headers: {dict(request.headers)}")
    logger.debug(f"Request cookies: {request.cookies}")
    
    # Authentication status
    auth_status = {
        "is_authenticated": current_user is not None,
        "auth_cookie_present": "access_token" in request.cookies,
        "auth_header_present": "authorization" in [h.lower() for h in request.headers.keys()],
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    if current_user:
        auth_status["user_id"] = str(current_user.id)
        auth_status["username"] = current_user.username
        auth_status["email"] = current_user.email
    
    logger.info(f"Auth debug status: {auth_status}")
    
    return templates.TemplateResponse(
        "debug/auth_status.html", {
            "request": request,
            "user": current_user,
            "auth_status": auth_status
        }
    )


@router.get("/download", response_class=HTMLResponse)
async def download(request: Request, current_user: Optional[User] = Depends(get_current_user)):
    """Render download page with resources"""
    # In a real application, this would display download links or directly
    # initiate a download. For now, we'll just render a simple page.
    return templates.TemplateResponse(
        "download.html", {
            "request": request,
            "user": current_user,
            "year": datetime.now().year
        }
    )
