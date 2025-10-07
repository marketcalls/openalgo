# OpenAlgo API Layer Architecture

## Executive Summary

The API layer serves as the primary programmatic interface for the OpenAlgo platform, providing comprehensive RESTful endpoints for trading operations, market data access, and portfolio management. Built with Flask-RESTX, it offers automatic API documentation, robust validation, and standardized responses across 25+ broker integrations.

## Core Architecture

### Technology Stack

*   **Flask 3.0.3**: Core web framework with extensive middleware support
*   **Flask-RESTX**: RESTful API framework with OpenAPI/Swagger generation
*   **Flask-Limiter**: Rate limiting and throttling
*   **Flask-CORS**: Cross-Origin Resource Sharing management
*   **Marshmallow**: Request/response serialization and validation
*   **HTTPx**: Modern async HTTP client with connection pooling

### API Organization

```python
# API Structure in restx_api/__init__.py
from flask_restx import Api, Namespace

api = Api(
    version='1.0',
    title='OpenAlgo Trading API',
    description='Unified trading API for 25+ Indian brokers',
    doc='/api/v1/docs',
    prefix='/api/v1',
    authorizations={
        'apikey': {
            'type': 'apiKey',
            'in': 'header',
            'name': 'X-API-KEY'
        }
    }
)

# Namespace organization
trading_ns = Namespace('trading', description='Trading operations')
market_ns = Namespace('market', description='Market data')
portfolio_ns = Namespace('portfolio', description='Portfolio management')
analytics_ns = Namespace('analytics', description='Trade analytics')
utility_ns = Namespace('utility', description='Utility endpoints')
```

## Request Handling

1.  An HTTP request arrives at the server (e.g., Gunicorn/Werkzeug).
2.  Flask routes the request based on the URL path and HTTP method to the corresponding Blueprint route or RESTX Resource method.
3.  **Middleware:** Requests may pass through middleware layers:
    *   **CORS:** `Flask-CORS` handles Cross-Origin Resource Sharing headers (`cors.py`).
    *   **Rate Limiting:** `Flask-Limiter` enforces rate limits based on configured strategies (`limiter.py`).
    *   **Traffic Logging:** Custom middleware likely logs request/response details (`utils/traffic_logger.py`).
    *   **Latency Monitoring:** Custom middleware measures request processing time (`utils/latency_monitor.py`).
    *   **Authentication:** `Flask-Login` or custom token/API key validation checks occur.
4.  **Data Validation/Parsing:**
    *   **Flask-RESTX:** Uses `@api.expect()` decorators with defined models (`api.model`) to validate incoming request payloads (JSON). Parses arguments using `reqparse.RequestParser`.
    *   **Flask-WTF:** Used in Blueprint routes (especially for HTML forms) for data validation (`WTForms`).
5.  **Business Logic:** The request is passed to the appropriate function/method containing the core application logic (interacting with brokers, database, strategies).
6.  **Response Generation:**
    *   **Flask-RESTX:** Uses `@api.marshal_with()` decorators and models to serialize Python objects into JSON responses.
    *   **Flask Blueprints:** Can return JSON using `jsonify()` or render HTML templates using `render_template()`.
7.  The response is sent back to the client.

## Error Handling

*   Custom error handlers are defined in `app.py` for standard HTTP errors like 404 (Not Found) and 500 (Internal Server Error), typically rendering HTML error pages.
*   Flask-RESTX provides its own mechanisms for handling validation errors and other API-specific exceptions, usually returning structured JSON error responses.

## API Documentation

*   Flask-RESTX automatically generates interactive **Swagger UI** documentation from the defined Namespaces, Resources, Models, and decorators. This is usually accessible at a specific endpoint (e.g., `/api/v1/`).
