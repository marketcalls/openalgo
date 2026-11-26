# Docker Environment Settings

These settings apply to both the default eventlet worker and optional gthread. The build helpers prepare them for a fresh local install. Existing installations should retain their installation secrets and review their public addresses before changing `.env`.

## Container Listeners

```bash
FLASK_HOST_IP='0.0.0.0'
FLASK_PORT='5000'
FLASK_DEBUG='False'
WEBSOCKET_HOST='0.0.0.0'
WEBSOCKET_PORT='8765'
```

The web and market-data servers must accept traffic from Docker's mapped ports. The internal ZeroMQ bus stays on loopback because its publisher processes and proxy are in the same container:

```bash
ZMQ_HOST='127.0.0.1'
ZMQ_PORT='5555'
```

The proxy's SUB socket is the only binder; broker and cache-invalidation PUB sockets connect to that fixed endpoint. Do not publish port 5555 or change it to a fallback port when busy.

## Public Addresses

For local Docker Desktop access:

```bash
HOST_SERVER='http://localhost:5000'
WEBSOCKET_URL='ws://localhost:8765'
```

These are addresses the browser or external client can reach, not container listener addresses. For an HTTPS reverse proxy use your public origin and its WebSocket path, for example `HOST_SERVER='https://trade.example.com'` and `WEBSOCKET_URL='wss://trade.example.com/ws'`. Another computer cannot reach your container using its own `localhost`.

## Secrets And Broker Setup

The `.env` bind mount must be writable by the container's `appuser` (UID/GID 1000); the current Compose file mounts it read/write. This lets startup rotate public sample placeholders and lets server settings save. Keep the file private and back it up with the database. Do not create new installation secrets for an existing database.

Broker application keys can be added after app sign-in at `/broker/config`; new helper-created `.env` files leave broker values empty. When using legacy `.env` broker configuration, the callback in `REDIRECT_URL` and `BROKER_API_KEY` identify the broker whose environment keys take precedence. See [Broker And System Configuration](../design/51-broker-system-config/README.md).

## Optional Worker

`OPENALGO_WORKER_CLASS='gthread'` selects 64 request threads in one worker; eventlet remains the default. Configure a 45-second stop grace and recreate a current image using the [gthread guide](../gthread/README.md#switch-on-docker).

## Verification

```bash
docker compose ps
curl -f http://localhost:5000/auth/check-setup
docker compose logs --tail=100 openalgo
```

Then verify market-data authentication and subscriptions against the configured public WebSocket URL with the [documented protocol](../prompt/websockets-format.md).
