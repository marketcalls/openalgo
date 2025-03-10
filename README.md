# OpenAlgo

A secure FastAPI-based login and dashboard application with modern authentication features and real-time IP tracking capabilities.

## Features

- **Modern Authentication**
  - JWT token-based authentication
  - Argon2 password hashing for enhanced security
  - Complete user management (registration, login, password reset)
  - Account lockout protection after failed login attempts

- **Security Features**
  - HTTPS ready configuration
  - Password strength validation
  - Secure cookie handling
  - IP address tracking for improved user activity monitoring

- **Frontend**
  - Clean responsive UI with Tailwind CSS and DaisyUI
  - Dynamic page updates with HTMX
  - Form validation with client and server-side checks

- **IP Tracking**
  - Records both local and public IP addresses during login
  - Displays IP information in user activity logs
  - Secure storage of IP data in JWT cookies

## Getting Started

### Prerequisites

- Python 3.9+ (Python 3.12 recommended)
- pip package manager

### Local Development Setup

1. Clone the repository

```bash
git clone https://github.com/marketcalls/openalgo.git
cd openalgo
```

2. Create and activate a virtual environment

```bash
python -m venv venv
# On Windows
venv\Scripts\activate
# On macOS/Linux
source venv/bin/activate
```

3. Install dependencies

```bash
pip install -r requirements.txt
```

4. Set up environment variables (copy `.env.example` to `.env` and modify)

5. Run the application

```bash
python app.py
```

The application will be available at http://localhost:5000

### Docker Deployment

For production deployment, use the included Dockerfile:

```bash
docker build -t openalgo .
docker run -p 5000:5000 -d --name openalgo openalgo
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Secret key for JWT encoding | - |
| `DEBUG` | Enable debug mode | False |
| `ENVIRONMENT` | Application environment | development |
| `COOKIE_SECURE` | Use secure cookies | False (True in production) |
| `COOKIE_SAMESITE` | SameSite cookie policy | lax |
| `JWT_SECRET_KEY` | Secret key for JWT tokens | - |
| `JWT_ALGORITHM` | Algorithm used for JWT | HS256 |

## IP Tracking System

The application records both local and public IP addresses during user login attempts. This information is securely stored in JWT-encoded cookies and displayed in the user's dashboard under the activity log.

### How it Works

1. When a user logs in, the application captures:
   - Local IP address from the request headers
   - Public IP address (external IP) from request headers or a trusted proxy

2. This information is stored in a secure cookie with appropriate settings based on the environment.

3. The dashboard retrieves and decodes this information to display it in the user activity log.

## License

This project is licensed under the MIT License - see the LICENSE file for details.
