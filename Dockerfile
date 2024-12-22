# Dockerfile
FROM python:3.14.0a1-slim

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
