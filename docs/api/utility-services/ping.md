# Authenticated Ping

Verify that the OpenAlgo API key resolves to an active broker session.

## Endpoint

```http
POST /api/v1/ping
```

```bash
curl -X POST 'http://127.0.0.1:5000/api/v1/ping' \
  -H 'Content-Type: application/json' \
  -d '{"apikey":"<your_app_apikey>"}'
```

```json
{
  "status": "success",
  "data": {
    "message": "pong",
    "broker": "zerodha"
  }
}
```

This is not an anonymous process-health endpoint. An invalid key or revoked/missing broker session returns HTTP 403.

**Back to**: [API documentation](../README.md)
