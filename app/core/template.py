from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import os
from pathlib import Path


def setup_templates(app: FastAPI) -> Jinja2Templates:
    """Setup Jinja2 template engine with FastAPI"""
    # Define the templates directory
    templates_dir = Path("app/templates")
    templates = Jinja2Templates(directory=str(templates_dir))
    
    return templates


def setup_static_files(app: FastAPI) -> None:
    """Mount static files directory to FastAPI app"""
    static_dir = Path("app/static")
    
    # Mount the static directory
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
