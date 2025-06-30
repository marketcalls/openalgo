# System Architecture

## Architectural Style

OpenAlgo employs a **Monolithic Application Architecture** with a **RESTful API** interface. The core logic, broker interactions, database management, and API endpoints are contained within a single Flask application process.

Key characteristics:
*   **Centralized Codebase:** All components reside within the same project structure.
*   **Flask Framework:** Utilizes the Flask microframework for web application structure and request handling.
*   **Flask-RESTX:** Leverages Flask-RESTX for building structured REST APIs with Swagger documentation.
*   **Blueprints/Namespaces:** Organizes API endpoints and application logic into modular blueprints (Flask) and namespaces (Flask-RESTX).
*   **SQLAlchemy:** Uses SQLAlchemy as the Object-Relational Mapper (ORM) for database interactions.

## Technology Stack

*   **Programming Language:** Python 3
*   **Web Framework:** Flask
*   **API Framework:** Flask-RESTX
*   **Database ORM:** SQLAlchemy
*   **Real-time Communication:** Flask-SocketIO, WebSocket Proxy Server
*   **Rate Limiting:** Flask-Limiter
*   **Cross-Origin Resource Sharing:** Flask-CORS
*   **Authentication:** Flask-Login, Flask-Bcrypt, PyJWT (likely for API keys/tokens)
*   **Web Server Gateway Interface (WSGI):** Werkzeug (Flask's default), potentially Gunicorn/uWSGI for production.
*   **Database:** (Defined by `DATABASE_URL` environment variable, likely PostgreSQL or MySQL based on common usage with SQLAlchemy)
*   **Environment Management:** python-dotenv
*   **Deployment:** Docker (Dockerfile, docker-compose.yaml), AWS Elastic Beanstalk (`.ebextensions`)
*   **Frontend (UI Templates):** Jinja2, potentially with Tailwind CSS (based on `tailwind.config.js`)
*   **Message Broker:** ZeroMQ for internal communication
*   **WebSocket Infrastructure:** Custom WebSocket proxy with broker-specific adapters
*   **Logging System:** Centralized colored logging with sensitive data filtering
*   **Streaming Data:** Real-time market data distribution via WebSocket connections

## Directory Structure Overview

*   `.ebextensions/`: Configuration files for AWS Elastic Beanstalk deployment.
*   `blueprints/`: Contains Flask Blueprints, organizing application features and web routes (e.g., `auth`, `dashboard`, `orders`).
*   `broker/`: Core logic for interacting with different stock brokers. Contains subdirectories for each supported broker (e.g., `jainampro`).
*   `database/`: SQLAlchemy models, database initialization scripts, and data access logic (e.g., `auth_db.py`, `user_db.py`).
*   `design/`: Location for this design documentation.
*   `docs/`: Likely contains user-facing documentation or generated docs.
*   `restx_api/`: Defines the Flask-RESTX API structure, namespaces, and models.
*   `static/`: Static assets for the web UI (CSS, JavaScript, images).
*   `strategies/`: Implementation of trading strategies.
*   `templates/`: Jinja2 HTML templates for the web UI.
*   `utils/`: Common utility functions and classes used across the application (e.g., `env_check.py`, `latency_monitor.py`, `plugin_loader.py`).
*   `websocket_proxy/`: WebSocket proxy server implementation with broker adapters for real-time market data streaming.
*   `app.py`: Main Flask application entry point, initializes the app, extensions, and blueprints.
*   `requirements.txt`: Lists Python package dependencies.
*   `Dockerfile`, `docker-compose.yaml`: Configuration for building and running the application with Docker.
*   `.env`, `.sample.env`: Environment variable configuration.

## Component Diagram (Mermaid)

```mermaid
graph TD
    subgraph "Client Layer"
        WebUI[Web Browser UI]
        APIClient[External API Client]
        WSClient[WebSocket Client]
    end

    subgraph "OpenAlgo Application - Flask"
        direction TB
        APILayer[API Layer - Flask-RESTX - Blueprints]
        Auth[Auth & Session Mgmt]
        RateLimiter[Rate Limiter]
        SocketIO[WebSocket - Flask-SocketIO]
        CoreLogic[Core Application Logic]
        StrategyEngine[Strategy Engine - strategies]
        BrokerInterface[Broker Interface - broker]
        DBLayer[Database Layer - SQLAlchemy]
        Utils[Utilities - utils]
        LoggingSystem[Centralized Logging System]
    end

    subgraph "WebSocket Infrastructure"
        direction TB
        WSProxy[WebSocket Proxy Server]
        BrokerAdapters[Broker WebSocket Adapters]
        ZMQBroker[ZeroMQ Message Broker]
        AdapterFactory[Broker Adapter Factory]
    end

    subgraph "External Systems"
        DB[(Database)]
        BrokerAPI1[Broker A API]
        BrokerAPI2[Broker B API]
        BrokerAPIn[... Broker N API]
        BrokerWS1[Broker A WebSocket]
        BrokerWS2[Broker B WebSocket]
        BrokerWSn[... Broker N WebSocket]
    end

    %% Main Application Flow
    WebUI --> APILayer
    APIClient --> APILayer
    APILayer --> Auth
    APILayer --> RateLimiter
    APILayer --> CoreLogic
    APILayer --> SocketIO
    CoreLogic --> StrategyEngine
    CoreLogic --> BrokerInterface
    CoreLogic --> DBLayer
    Auth --> DBLayer
    StrategyEngine --> BrokerInterface
    BrokerInterface --> BrokerAPI1
    BrokerInterface --> BrokerAPI2
    BrokerInterface --> BrokerAPIn
    DBLayer --> DB
    
    %% WebSocket Flow
    WSClient --> WSProxy
    WSProxy --> AdapterFactory
    AdapterFactory --> BrokerAdapters
    BrokerAdapters --> ZMQBroker
    ZMQBroker --> WSProxy
    WSProxy --> WSClient
    BrokerAdapters --> BrokerWS1
    BrokerAdapters --> BrokerWS2
    BrokerAdapters --> BrokerWSn
    
    %% Utility Dependencies
    APILayer --> Utils
    CoreLogic --> Utils
    BrokerInterface --> Utils
    DBLayer --> Utils
    Auth --> Utils
    WSProxy --> Utils
    BrokerAdapters --> Utils
    
    %% Logging System
    APILayer --> LoggingSystem
    CoreLogic --> LoggingSystem
    BrokerInterface --> LoggingSystem
    WSProxy --> LoggingSystem
    BrokerAdapters --> LoggingSystem
    Utils --> LoggingSystem
```
