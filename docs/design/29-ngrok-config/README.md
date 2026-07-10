# 29 - Ngrok Configuration

## Purpose

The optional ngrok manager exposes the local Flask HTTP port for external webhook callbacks during self-hosted development or evaluation. It does not create a second OpenAlgo API or bypass normal webhook/API authentication.

## Configuration

```bash
NGROK_ALLOW='TRUE'
HOST_SERVER='https://your-domain.ngrok.app'
```

`NGROK_ALLOW` is the actual enable flag. There are no OpenAlgo `NGROK_ENABLED`, `NGROK_AUTH_TOKEN`, or `NGROK_DOMAIN` environment variables in the current application contract. `pyngrok` obtains its ngrok credentials from its normal ngrok configuration.

When `HOST_SERVER` is a non-local URL, the manager extracts its host and asks ngrok for that custom domain. With a local `HOST_SERVER`, ngrok allocates a random public URL. A reserved custom domain must already be available to the configured ngrok account.

## Startup And Lifecycle

Direct app startup calls `start_ngrok_tunnel(FLASK_PORT)` only when `NGROK_ALLOW=TRUE`. In Flask debug/reloader mode it runs only in the serving child process.

The manager:

1. Stops any existing pyngrok process before evaluating the flag.
2. Opens the tunnel to the configured Flask port.
3. Stores the returned public URL in process memory.
4. Registers `atexit`, SIGINT, and Unix SIGTERM cleanup.
5. Disconnects the tracked tunnel and kills the ngrok process during shutdown.

Startup failure is logged and returns no tunnel URL; it does not replace application startup error handling.

## Webhook Paths

Examples of routes that may need a public base URL include:

| Integration | Route shape |
|---|---|
| Strategy | `POST /strategy/webhook/<webhook_id>` |
| Chartink | `POST /chartink/webhook/<webhook_id>` |
| Flow | `POST /flow/webhook/<token>` or `/flow/webhook/<token>/<symbol>` |
| TradingView / GoCharting | Their registered JSON automation routes |

The REST order API remains under `/api/v1`; `/api/v1/webhook/<id>` is not a registered generic webhook route.

## Security

- A tunnel makes the selected Flask port internet-reachable. Keep Flask debug disabled for any non-loopback exposure.
- Use webhook secrets/auth modes where the integration supports them.
- Preserve rate limits, CSRF exemptions only on intended external callbacks, and API-key validation.
- Do not log or commit ngrok credentials.
- Prefer a stable HTTPS deployment URL for production integrations.

## Key Files

| File | Responsibility |
|---|---|
| `utils/ngrok_manager.py` | Tunnel creation, URL access, signal cleanup |
| `app.py` | Direct-server startup gate |
| `.sample.env` | `NGROK_ALLOW` and `HOST_SERVER` reference |
