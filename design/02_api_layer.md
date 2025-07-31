# API Layer

The API layer is the primary interface for interacting with the OpenAlgo platform. It handles incoming HTTP requests, routes them to the appropriate logic, processes data, and returns responses.

## Frameworks Used

*   **Flask:** The core microframework providing routing, request context, and application structure.
*   **Flask-RESTX:** An extension for Flask that adds support for quickly building REST APIs. It provides tools for structuring APIs using Namespaces, marshalling data, and automatically generating Swagger documentation.
*   **Flask Blueprints:** Used alongside or potentially instead of RESTX Namespaces in some parts of the application (`blueprints/` directory) to organize routes and views into reusable components.

## Structure and Organization

*   **Entry Point:** The API is initialized and configured in `app.py`.
*   **RESTX API Definition:** The primary RESTful API structure (likely versioned, e.g., `/api/v1`) is defined in `restx_api/__init__.py`. This module initializes the Flask-RESTX `Api` object and registers different `Namespaces`.
*   **Namespaces:** Flask-RESTX `Namespaces` (likely located within the `restx_api` directory, e.g., `restx_api/endpoints/`) group related resources together (e.g., a namespace for orders, another for positions).
*   **Blueprints:** Traditional Flask `Blueprints` (located in the `blueprints/` directory, e.g., `blueprints/auth.py`, `blueprints/dashboard.py`) are used for organizing both UI routes (rendering HTML templates) and potentially some API endpoints that might not follow the strict RESTX structure.
*   **Registration:** Both RESTX Namespaces (via the `api.add_namespace()` method) and Flask Blueprints (via `app.register_blueprint()`) are registered with the main Flask `app` object in `app.py`.

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
