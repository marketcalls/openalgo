# Requirements Document

## Introduction

This document defines the requirements for deploying the OpenAlgo Flask application on AWS Lightsail. OpenAlgo is a multi-broker algorithmic trading platform built with Flask, Flask-SocketIO (eventlet), a WebSocket proxy server, SQLite databases, and a React frontend. The deployment targets a single AWS Lightsail container service instance running the existing Docker image, with persistent storage for databases and logs, HTTPS termination, and environment-based configuration — consistent with how the app already runs on Railway and other cloud platforms.

The codebase is already Docker-ready (`Dockerfile`, `start.sh`, `docker-compose.yaml`) and cloud-aware (`start.sh` auto-generates `.env` from environment variables when `HOST_SERVER` is set). No application code changes are required; this spec covers the infrastructure, configuration, and operational requirements for a Lightsail deployment.

---

## Glossary

- **Lightsail_Container_Service**: AWS Lightsail managed container hosting service that runs Docker images and provides a public HTTPS endpoint.
- **Lightsail_Storage**: AWS Lightsail persistent block storage (disk) attached to the container service for stateful data.
- **OpenAlgo_App**: The Flask + Flask-SocketIO application defined in `app.py`, served by gunicorn with the eventlet worker class.
- **WebSocket_Proxy**: The secondary process (`websocket_proxy/server.py`) started by `start.sh` on port 8765, providing real-time broker data streaming.
- **Env_Config**: The set of environment variables consumed by `start.sh` and `utils/env_check.py` to configure the application at runtime.
- **Health_Endpoint**: The `/api/v1/ping` HTTP endpoint used by container health checks.
- **SQLite_DB**: The four SQLite database files (`openalgo.db`, `latency.db`, `logs.db`, `sandbox.db`) stored under `/app/db`.
- **HTTPS_Endpoint**: The public TLS-terminated URL provided by Lightsail Container Service (e.g., `https://<service>.us-east-1.cs.amazonlightsail.com`).
- **Custom_Domain**: An optional user-owned domain name mapped to the Lightsail HTTPS endpoint via DNS CNAME.
- **Gunicorn**: The WSGI server used to serve OpenAlgo_App, configured with one eventlet worker.
- **ECR**: Amazon Elastic Container Registry, used to store and version the OpenAlgo Docker image before deployment to Lightsail.

---

## Requirements

### Requirement 1: Container Image Build and Registry

**User Story:** As a developer, I want to build the OpenAlgo Docker image and push it to a container registry, so that Lightsail can pull and run it.

#### Acceptance Criteria

1. THE Developer SHALL build the Docker image using the existing `Dockerfile` with `docker build -t openalgo:latest .`
2. THE Developer SHALL tag and push the image to ECR or Docker Hub before creating the Lightsail container deployment.
3. WHEN the image build completes, THE Dockerfile SHALL produce a single production image containing the Python venv, the pre-built React frontend (`frontend/dist`), and the `start.sh` entrypoint.
4. IF the `frontend/dist` directory is absent at build time, THEN THE Dockerfile SHALL build the React frontend from source using the `frontend-builder` stage.

---

### Requirement 2: Lightsail Container Service Provisioning

**User Story:** As a developer, I want to provision an AWS Lightsail Container Service, so that the OpenAlgo application has a managed, scalable hosting environment.

#### Acceptance Criteria

1. THE Developer SHALL create a Lightsail Container Service with a minimum power of `Small` (1 vCPU, 2 GB RAM) to satisfy gunicorn + eventlet + numba memory requirements.
2. THE Lightsail_Container_Service SHALL be configured with a scale of 1 node for single-instance deployment.
3. WHEN the container service is created, THE Lightsail_Container_Service SHALL expose port 5000 (HTTP) as the public endpoint port mapped to the container's port 5000.
4. THE Lightsail_Container_Service SHALL be configured with `FLASK_HOST_IP=0.0.0.0` so gunicorn binds to all interfaces inside the container.

---

### Requirement 3: Environment Variable Configuration

**User Story:** As a developer, I want to configure all required environment variables in Lightsail, so that `start.sh` can auto-generate the `.env` file and the application starts correctly without a pre-baked secrets file.

#### Acceptance Criteria

1. THE Developer SHALL set `HOST_SERVER` to the Lightsail HTTPS endpoint URL (e.g., `https://<service>.us-east-1.cs.amazonlightsail.com`) or the Custom_Domain URL in the Lightsail container environment variables.
2. WHEN `HOST_SERVER` is set, THE start.sh SHALL auto-generate `/app/.env` from the provided environment variables, as per the existing cloud-detection logic.
3. THE Developer SHALL set `APP_KEY` and `API_KEY_PEPPER` to unique 64-character hex secrets generated with `python -c "import secrets; print(secrets.token_hex(32))"`.
4. THE Developer SHALL set `BROKER_API_KEY`, `BROKER_API_SECRET`, and `REDIRECT_URL` matching the broker OAuth application configuration.
5. THE Developer SHALL set `REDIRECT_URL` to `https://<host>/zerodha/callback` (or the relevant broker callback path) pointing to the Lightsail HTTPS endpoint.
6. THE Developer SHALL set `FLASK_HOST_IP=0.0.0.0`, `FLASK_PORT=5000`, `FLASK_ENV=production`, and `FLASK_DEBUG=False`.
7. THE Developer SHALL set `WEBSOCKET_HOST=0.0.0.0`, `WEBSOCKET_PORT=8765`, and `WEBSOCKET_URL=wss://<host>/ws`.
8. THE Developer SHALL set `DATABASE_URL=sqlite:///db/openalgo.db` and the three companion database URLs pointing to the `/app/db` directory.
9. THE Developer SHALL set `NGROK_ALLOW=FALSE` for cloud deployment.
10. THE Developer SHALL set `CSP_UPGRADE_INSECURE_REQUESTS=TRUE` since Lightsail provides HTTPS.
11. THE Developer SHALL set `CORS_ALLOWED_ORIGINS` to the Lightsail HTTPS endpoint URL.

---

### Requirement 4: Persistent Storage for Databases and Logs

**User Story:** As a developer, I want SQLite databases and log files to survive container restarts and redeployments, so that trading history, API logs, and user data are not lost.

#### Acceptance Criteria

1. THE Developer SHALL attach a Lightsail_Storage disk (minimum 20 GB) to the container service and mount it at `/app/db` to persist all four SQLite_DB files.
2. THE Developer SHALL mount a second path at `/app/log` (or include it on the same disk) to persist application log files across restarts.
3. WHEN the container restarts, THE OpenAlgo_App SHALL reconnect to the existing SQLite_DB files on the mounted volume without data loss.
4. IF Lightsail_Storage is unavailable, THEN THE Developer SHALL document that SQLite data will be lost on container restart and recommend upgrading to a persistent disk before production use.

> **Compatibility Note:** Lightsail Container Services currently have limited native persistent storage support. The recommended workaround is to use an Amazon EFS mount or to accept ephemeral storage for the `db/` directory and schedule regular backups to S3. Alternatively, the Developer MAY migrate `DATABASE_URL` to an external managed database (e.g., Lightsail Managed Database with PostgreSQL) by updating the SQLAlchemy connection string.

---

### Requirement 5: WebSocket Proxy Accessibility

**User Story:** As a developer, I want the WebSocket proxy server to be accessible from the browser, so that real-time broker data streaming works through the Lightsail HTTPS endpoint.

#### Acceptance Criteria

1. THE Lightsail_Container_Service SHALL expose port 8765 as a secondary port, OR THE Developer SHALL configure an NGINX reverse proxy sidecar to forward `/ws` path traffic to the internal port 8765.
2. WHEN a browser client connects to `wss://<host>/ws`, THE WebSocket_Proxy SHALL accept the connection and relay broker streaming data.
3. THE Developer SHALL set `WEBSOCKET_URL=wss://<host>/ws` in the Env_Config so the React frontend connects to the correct WebSocket endpoint.
4. IF the Lightsail_Container_Service does not support multiple exposed ports, THEN THE Developer SHALL add an NGINX container as a sidecar in the deployment to proxy both HTTP (port 5000) and WebSocket (port 8765) traffic through a single port 443/80.

---

### Requirement 6: HTTPS and TLS Termination

**User Story:** As a developer, I want all traffic to be served over HTTPS, so that broker OAuth callbacks, API keys, and session cookies are transmitted securely.

#### Acceptance Criteria

1. THE Lightsail_Container_Service SHALL provide automatic TLS termination via the built-in HTTPS endpoint.
2. WHERE a Custom_Domain is configured, THE Developer SHALL add a CNAME DNS record pointing the Custom_Domain to the Lightsail HTTPS endpoint and enable the custom domain in the Lightsail console.
3. WHEN `HOST_SERVER` starts with `https://`, THE OpenAlgo_App SHALL set `SESSION_COOKIE_SECURE=True` and prefix session and CSRF cookie names with `__Secure-`, as per the existing `app.py` logic.
4. THE Developer SHALL set `CSP_UPGRADE_INSECURE_REQUESTS=TRUE` to enforce HTTPS for all sub-resources.

---

### Requirement 7: Health Check Configuration

**User Story:** As a developer, I want Lightsail to monitor application health, so that unhealthy containers are automatically restarted.

#### Acceptance Criteria

1. THE Lightsail_Container_Service health check SHALL be configured to send HTTP GET requests to `/api/v1/ping` on port 5000.
2. THE Health_Endpoint SHALL return HTTP 200 within 10 seconds for the container to be considered healthy.
3. WHEN the Health_Endpoint returns a non-200 response for 3 consecutive checks, THE Lightsail_Container_Service SHALL restart the container.
4. THE health check interval SHALL be set to 30 seconds with a timeout of 10 seconds, consistent with the existing `docker-compose.yaml` configuration.

---

### Requirement 8: Broker OAuth Callback Compatibility

**User Story:** As a developer, I want broker OAuth redirect URLs to resolve correctly on Lightsail, so that broker login flows complete successfully.

#### Acceptance Criteria

1. THE Developer SHALL register the Lightsail HTTPS endpoint URL as the authorized redirect URI in each broker's developer portal (e.g., `https://<host>/<broker>/callback`).
2. WHEN a broker OAuth flow completes, THE brlogin_bp blueprint SHALL receive the callback at the configured `REDIRECT_URL` path and complete the token exchange.
3. THE Developer SHALL update `REDIRECT_URL` in the Env_Config whenever the Lightsail endpoint URL or Custom_Domain changes.

---

### Requirement 9: Security Hardening for Production

**User Story:** As a developer, I want the Lightsail deployment to follow security best practices, so that the trading platform is not exposed to unnecessary risk.

#### Acceptance Criteria

1. THE Developer SHALL generate unique values for `APP_KEY` and `API_KEY_PEPPER` and SHALL NOT reuse values from `.sample.env` or development environments.
2. THE Developer SHALL set `FLASK_DEBUG=False` and `FLASK_ENV=production` in the Lightsail Env_Config.
3. THE Developer SHALL set `NGROK_ALLOW=FALSE` to disable the ngrok tunnel in the cloud environment.
4. THE Developer SHALL restrict Lightsail firewall rules to allow only ports 80 and 443 from the public internet.
5. THE Developer SHALL set `CSRF_ENABLED=TRUE` and `CSP_ENABLED=TRUE` in the Env_Config.
6. THE Developer SHALL NOT store `APP_KEY`, `API_KEY_PEPPER`, or broker secrets in the Docker image or source control; all secrets SHALL be injected via Lightsail environment variables at deploy time.

---

### Requirement 10: Deployment Verification

**User Story:** As a developer, I want to verify the deployment is working end-to-end after going live on Lightsail, so that I can confirm all services are operational before using the platform for trading.

#### Acceptance Criteria

1. WHEN the container reaches a healthy state, THE Developer SHALL verify the web UI is accessible at `https://<host>/` and returns HTTP 200.
2. THE Developer SHALL verify the Health_Endpoint at `https://<host>/api/v1/ping` returns HTTP 200.
3. THE Developer SHALL verify that a broker login flow completes successfully by navigating to the broker login page and completing OAuth.
4. THE Developer SHALL verify that WebSocket connectivity works by opening the dashboard and confirming real-time data updates appear without console errors.
5. THE Developer SHALL verify that the SQLite databases are persisted by restarting the container and confirming that previously created API keys and settings are still present.
6. IF any verification step fails, THEN THE Developer SHALL inspect container logs via `aws lightsail get-container-log` and resolve the issue before proceeding to live trading.

---

## Compatibility Assessment

The existing codebase is compatible with AWS Lightsail container deployment with the following notes:

| Area | Status | Notes |
|---|---|---|
| Docker image | Compatible | `Dockerfile` is production-ready with multi-stage build |
| Cloud env detection | Compatible | `start.sh` auto-generates `.env` when `HOST_SERVER` is set |
| HTTPS cookies | Compatible | `app.py` auto-enables `SESSION_COOKIE_SECURE` when `HOST_SERVER` starts with `https://` |
| Gunicorn/eventlet | Compatible | `start.sh` already uses `gunicorn --worker-class eventlet` |
| WebSocket proxy | Needs config | Port 8765 must be proxied or exposed; recommend NGINX sidecar |
| SQLite persistence | Needs config | Lightsail Container Services have limited native persistent storage; use EFS or managed DB |
| Health check | Compatible | `/api/v1/ping` endpoint exists and is CSRF-exempt |
| Broker OAuth | Needs config | Redirect URLs must be updated in broker developer portals |
| Secrets management | Needs config | All secrets must be set as Lightsail environment variables |
