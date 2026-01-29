# Health Check

The Health Check endpoint is used to verify the operational status of the OpenAlgo application and its connectivity to the database. This is commonly used by load balancers (e.g., AWS ELB, Nginx) and container orchestrators (e.g., Kubernetes) for readiness probes.

## Point

`GET /health`

## Description

Performs a composite health check:
1.  **Web Server**: Verifies the Flask application is running.
2.  **Database**: Executes a lightweight query (`SELECT 1`) to verify connectivity to the primary database.

## Request Parameters

None

## Response

### Success Response

Returns HTTP 200 OK if all checks pass.

```json
{
  "status": "ok",
  "database": "connected"
}
```

### Error Response

Returns HTTP 503 Service Unavailable if any check fails (e.g., database unreachable).

```json
{
  "status": "error",
  "database": "disconnected",
  "error": "OperationalError: ..."
}
```
