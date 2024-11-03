# Docker Development Setup for OpenAlgo Flask
This guide focuses on setting up a development environment for OpenAlgo Flask using Docker.

## Prerequisites
* Docker Engine 
* Docker Compose
* Git

## Files Required
**1. Dockerfile**
```
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc python3-dev libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements-nginx.txt .
RUN pip install --no-cache-dir -r requirements-nginx.txt
RUN pip install gunicorn eventlet>=0.24.1


# Copy project files
COPY . .

# Create directories and set permissions
RUN mkdir -p db logs && \
    chmod -R 777 db logs

# Command to run the application
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--worker-class", "eventlet", \
     "--workers", "1", \
     "--reload", \
     "--log-level", "debug", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]
```

**2. docker-compose.yml**
```
version: '3.8'

services:
  web:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - .:/app
      - ./db:/app/db
    env_file:
      - .env
    environment:
      - FLASK_DEBUG=True
      - FLASK_ENV=development
      - DATABASE_URL=sqlite:///db/openalgo.db
    restart: unless-stopped
```

**3. .dockerignore**
```
**/__pycache__
**/*.pyc
**/*.pyo
**/*.pyd
.Python
env/
venv/
.env*
!.env.example
*.sqlite
.git
.gitignore
.docker
Dockerfile
README.md
*.sock
```

## Quick Start
1. **Create Environment File:**
   
    Copy `.sample.env` to `.env`:
    ```
    cp .sample.env .env
    ```

2. **Build and Start:**
    ```
    docker-compose up --build
    ```

3. **View Logs:**
    ```
    docker-compose logs -f
    ```

## Development Features
* Hot reload enabled (code changes reflect immediately)
* Debug mode active
* Console logging
* Port 5000 exposed
* Volume mounting for live code updates

## Common Commands
```
# Start development server
docker-compose up

# Start in detached mode
docker-compose up -d

# View logs
docker-compose logs -f

# Stop containers
docker-compose down

# Rebuild after dependency changes
docker-compose up --build

# Enter container shell
docker-compose exec web bash

# Check container status
docker-compose ps
```

## Directory Structure
```
openalgo/
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env
├── app.py
├── requirements-nginx.txt
└── db/
    └── openalgo.db
```

## Development Tips
1. **Live Reload:**
   * Code changes will automatically reload
   * Check logs for errors after changes

2. **Database Access:**
   * SQLite database persists in ./db directory
   * Can be accessed from both host and container
  
3. **Debugging:**
   * Logs are printed to console
   * Debug mode enables detailed error pages

4. **Dependencies:**
   * Add new packages to requirements-nginx.txt
   * Rebuild container after adding dependencies:
      ```
      docker-compose up --build
      ```

## Troubleshooting
1. **Port Already In Use:**
     ```
     # Check what's using port 5000
     sudo lsof -i :5000
     
     # Stop the container and restart
     docker-compose down
     docker-compose up
     ```

2. **Database Issues:**
    ```
    # Fix permissions if needed
    chmod -R 777 db/
    ```

3. **Container Won't Start:**
    ```
    # Check logs
    docker-compose logs
    
    # Remove container and try again
    docker-compose down
    docker-compose up --build
    ```

4. **Package Installation Issues:**
    ```
    # Rebuild without cache
    docker-compose build --no-cache
    docker-compose up
    ```

## Note
This configuration is optimized for development. For production deployment, additional security measures and optimizations would be necessary.

