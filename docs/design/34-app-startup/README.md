# 34 - Application Startup

## Startup Sequence

`app.py` validates the environment before importing the rest of the application. This ordering is intentional because auth/database modules require installation secrets at import time.

```text
1. load and validate .env
2. import Flask extensions, databases, services, RESTX, proxy integration
3. create_app()
   - Flask + Socket.IO
   - EventBus subscribers
   - CSRF + limiter + CORS + CSP
   - security, traffic, latency, health hooks
   - React, RESTX, and feature blueprints
   - optional Remote MCP
   - request guards and scoped-session teardown
4. setup_environment()
   - plugin discovery and broker capabilities
   - database/table initialization
   - schedulers and restoration
   - sandbox workers and scalping risk monitor
   - broker keepalive and configured bots
5. start WebSocket proxy when embedded mode applies
6. run Socket.IO server for direct startup, or expose app to gunicorn
```

## Required Configuration

`APP_KEY` must exist and contain at least 32 characters. `API_KEY_PEPPER` has its own import-time requirement. Official install paths generate unique values; placeholders are not accepted as production configuration.

Cookie security is derived from `HOST_SERVER`: HTTPS deployments use secure cookies while local HTTP development remains usable. External debug binding is refused unless explicitly allowed.

## Route Registration Order

When `frontend/dist` exists, the React blueprint is registered before REST/UI blueprints. Public REST is then registered and CSRF-exempted. Feature blueprints follow, with explicit CSRF exemptions for callbacks, webhooks, logout, and selected health surfaces.

Flask-RESTX documentation is deliberately disabled (`doc=False`). Startup does not register Swagger UI.

## Remote MCP Gate

Remote MCP is off unless `MCP_HTTP_ENABLED=True`. Enabling it requires:

- Flask debug mode off.
- `MCP_PUBLIC_URL` set as the canonical public origin.
- OAuth/MCP blueprints imported only after the boot guard environment marker is set.

Startup logs warn when write scope is enabled or client approval is disabled.

## Database Readiness

Initialization runs before normal service use, and requests wait up to 30 seconds on `app.db_ready`. Every initialization function must be idempotent and safe after partial prior setup. Sandbox initialization explicitly repairs missing tables.

After each request, `app.py` removes scoped SQLAlchemy sessions from the known database modules. This is part of the file-descriptor reliability contract.

## Background Services

`setup_environment()` initializes/restores background work for Flow, Python strategies, Historify, sandbox execution/square-off, broker keepalive, scalping stops, and configured messaging services. Failures should be logged with enough context and should only abort startup when the component is required for a coherent runtime.

## WebSocket Startup

The market-data proxy is skipped when Docker/standalone configuration owns it. Under eventlet/gunicorn it runs in a child process; direct development startup uses an OS thread. See [06 WebSockets](../06-websockets/).

## Direct Run

The `__main__` block reads `FLASK_HOST_IP`, `FLASK_PORT`, and `FLASK_DEBUG`, performs bind/debug safety checks, and starts the Socket.IO server. Production deployment is orchestrated by `start.sh` and the selected server mode.

## Adding Startup Work

1. Decide whether it belongs in factory registration or environment setup.
2. Make initialization idempotent and bounded.
3. Add teardown/stop ownership for threads, processes, sockets, or scoped sessions.
4. Avoid importing secret-dependent modules before environment validation.
5. Add startup diagnostics and a focused failure/restart test.
