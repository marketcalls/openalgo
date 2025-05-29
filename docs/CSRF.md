# CSRF Migration Plan

## 1. Introduction
Cross-Site Request Forgery (CSRF) is an attack that forces authenticated users to execute unwanted actions on a web application. To secure OpenAlgo’s REST/API endpoints, we will introduce a token-based CSRF protection layer across all state-changing operations.

## 2. Goals
- Ensure all non-GET HTTP methods (POST, PUT, DELETE, PATCH) require a valid CSRF token.
- Implement a scalable solution with minimal changes to existing controllers.
- Provide a clear path for client (UI/strategies) integration.

## 3. Proposed Approach
1. **Library Selection**: Use [Flask-SeaSurf](https://github.com/maxcountryman/flask-seasurf) for automatic CSRF token generation and validation.  
2. **Token Storage**: Store CSRF token in a secure, HttpOnly cookie.  
3. **Client Submission**: Clients must send token via `X-CSRF-Token` header or form field.

## 4. High-Level Tasks

### 4.1 Configuration
- Add `FLASK_SEASURF_SECRET_KEY` to `.env`.  
- Install `Flask-SeaSurf` (update `requirements.txt`).
- In `app.py`, initialize middleware:
  ```python
  from flask_seasurf import SeaSurf
  app = Flask(__name__)
  app.config['SECRET_KEY'] = os.getenv('APP_SECRET_KEY')
  app.config['SEASURF_SECRET_KEY'] = os.getenv('FLASK_SEASURF_SECRET_KEY')
  csrf = SeaSurf(app)
  ```

### 4.2 Endpoint Protection
- All blueprints under `restx_api/` are automatically protected.  
- Exempt endpoints:
  - `OPTIONS`, `HEAD`, `GET` (default safe methods).
  - Login (`/auth/login`) and health check (`/health`) via `@csrf.exempt`.

### 4.3 Client Integration
- On page load or initial `GET /session`, server sets cookie `csrf_token`.  
- Front-End JS must read cookie and include token:
  ```js
  fetch('/api/order', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': getCookie('csrf_token')
    },
    body: JSON.stringify(order)
  });
  ```

### 4.4 Testing & Validation
- Unit tests:
  - `POST` without token → 403.
  - `POST` with invalid token → 403.
  - `POST` with valid token → 200.
- Integration tests in CI pipeline.

### 4.5 Rollout Plan
1. **Development**: Implement and test locally.  
2. **Staging**: Deploy behind a feature flag; update front-end.  
3. **Production**: Flip flag; monitor 403 rates and client errors.

## 5. Timeline
| Phase       | Task                              | Duration |
|-------------|-----------------------------------|----------|
| Setup       | Install SeaSurf, configure app    | 1 day    |
| Implementation | Protect endpoints, write docs   | 2 days   |
| Client     | Update UI/strategies integration  | 1 day    |
| Testing    | Write tests & CI integration      | 1 day    |
| Deployment | Staging → Production rollout      | 1 day    |

## 6. Conclusion
Adding CSRF protection with Flask-SeaSurf will secure OpenAlgo’s APIs against forgery attacks with minimal overhead. Follow the plan above for a smooth migration.
