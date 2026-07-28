# Chart Preferences

Read and update per-API-key chart workspace preferences.

## Read Preferences

```http
GET /api/v1/chart?apikey=<key>
```

```bash
curl --get 'http://127.0.0.1:5000/api/v1/chart' \
  --data-urlencode 'apikey=<your_app_apikey>'
```

Successful responses return all stored keys under `data`.

## Update Preferences

```http
POST /api/v1/chart
```

```bash
curl -X POST 'http://127.0.0.1:5000/api/v1/chart' \
  -H 'Content-Type: application/json' \
  -d '{
    "apikey": "<your_app_apikey>",
    "tv_theme": "dark",
    "tv_chart_layout": {"interval": "15m"}
  }'
```

The POST schema accepts arbitrary preference keys in addition to `apikey`. A request may update at most 50 keys; keys are limited to 50 characters and each JSON-serialized value is limited to 1 MiB. The request must contain at least one preference.

Both methods verify the OpenAlgo API key. Invalid keys return HTTP 403.

**Back to**: [API documentation](../README.md)
