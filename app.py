import uvicorn
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
import logging
from datetime import datetime
from typing import List
from contextlib import asynccontextmanager
import os
import sys
from importlib import import_module

# Configure logging
logging.config.dictConfig({
    'version': 1,
    'formatters': {
        'default': {
            'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            'level': 'INFO',  
        },
        'file': {
            'class': 'logging.FileHandler',
            'formatter': 'default',
            'level': 'DEBUG',
            'filename': 'app.log',
        },
    },
    'loggers': {
        'app': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',  
            'propagate': False,
        },
        'app.auth.jwt': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',  
            'propagate': False,
        },
        'app.api': {
            'handlers': ['console', 'file'],
            'level': 'DEBUG',  
            'propagate': False,
        },
        'tortoise': {
            'handlers': ['file'],  
            'level': 'DEBUG',  
            'propagate': False,
        },
        'aiosqlite': {
            'handlers': ['file'],  
            'level': 'DEBUG',  
            'propagate': False,
        },
        'uvicorn.access': {
            'handlers': ['console', 'file'],
            'level': 'WARNING',  
            'propagate': False,
        },
        'uvicorn': {
            'handlers': ['console', 'file'],
            'level': 'WARNING',  
            'propagate': False,
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
})

logger = logging.getLogger(__name__)

# Make sure the app package is in the Python path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Import app modules after adding to path
from app.core.config import settings
from app.core.template import setup_templates, setup_static_files
from app.db.init_db import init_db, close_db
from app.api import auth, pages
from app.auth.jwt import get_current_user
from app.models.user import User


# Lifespan context manager (modern approach instead of on_event)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"Starting up {settings.APP_NAME} application")
    await init_db()
    
    yield
    
    # Shutdown
    logger.info(f"Shutting down {settings.APP_NAME} application")
    await close_db()


# Create FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description=f"{settings.APP_NAME} - A secure FastAPI application",
    version="1.0.0",
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(origin) for origin in settings.CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup static files
setup_static_files(app)

# Setup templates
templates = setup_templates(app)


# Request middleware for context
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    # Process the request
    response = await call_next(request)
    
    # Add current year to all templates
    if hasattr(request, "state"):
        request.state.year = datetime.now().year
    
    return response


# Custom exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return templates.TemplateResponse(
        "errors/500.html", 
        {
            "request": request,
            "year": datetime.now().year
        },
        status_code=500
    )


# Handle 404 Not Found errors
@app.exception_handler(404)
async def not_found_exception_handler(request: Request, exc: Exception):
    logger.info(f"404 Not Found: {request.url}")
    return templates.TemplateResponse(
        "errors/404.html", 
        {
            "request": request,
            "year": datetime.now().year
        },
        status_code=404
    )

# Catch HTTPException 404s as well
from fastapi.exceptions import HTTPException
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 404:
        return templates.TemplateResponse(
            "errors/404.html",
            {
                "request": request,
                "year": datetime.now().year
            },
            status_code=404
        )
    
    # For other HTTP exceptions, return the default response
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers
    )

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(pages.router, tags=["pages"])


# Mount favicon
@app.get("/favicon.ico")
async def favicon():
    return RedirectResponse(url=app.url_path_for("static", path="favicon/favicon.ico"))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)
