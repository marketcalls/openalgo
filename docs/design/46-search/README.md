# 46 - Symbol Search

## Surfaces

OpenAlgo has two search contracts with different authentication and response shapes.

| Surface | Method and path | Auth | Purpose |
|---|---|---|---|
| Public RESTX contract | `POST /api/v1/search` | `apikey` in JSON | External symbol search |
| React/session suggestions | `GET /search/api/search` | App session | Filtered UI search |
| Expiry helper | `GET /search/api/expiries` | App session | Distinct expiries |
| Underlying helper | `GET /search/api/underlyings` | App session | Distinct option/futures underlyings |

The React `/search` page is registered before the legacy template blueprint. `/search/token` and the blueprint's `/search/` renderer remain legacy session routes; the supported first-viewport UI is `frontend/src/pages/Search.tsx`.

## RESTX Search

`POST /api/v1/search` validates this JSON shape:

```json
{
  "apikey": "<openalgo-api-key>",
  "query": "NIFTY 26000 DEC CE",
  "exchange": "NFO"
}
```

`query` and `apikey` are required; `exchange` is optional in the schema. `services/search_service.py` verifies the key, uses the enhanced in-memory token cache when loaded and valid, and falls back to `database.symbol.enhanced_search_symbols()`.

The normalized result includes OpenAlgo and broker symbol/exchange values, name, token, expiry, strike, lot size, instrument type, tick size, and option freeze quantity where available.

## Session Search

`GET /search/api/search` accepts:

- `q`
- comma-separated `exchange`
- comma-separated `instrumenttype`
- `expiry`
- `underlying`
- `strike_min` and `strike_max`

At least a query or exchange is required to avoid a full-table scan. Standard instruments use `database.symbol.enhanced_search_symbols()`. F&O filters or an F&O exchange use `database.token_db_enhanced.fno_search_symbols()`. Results are de-duplicated by `(symbol, exchange)`.

The expiry helper accepts optional `exchange` and `underlying`. The underlying helper accepts optional `exchange` and `include_futures=true`; test symbols are filtered from its response.

## Cache Model

`database.token_db_enhanced` owns the token cache and cached F&O discovery. It provides:

- Validity-aware general symbol search.
- Indexed F&O filtering.
- Cached distinct expiry lookup.
- Cached distinct underlying lookup, optionally including futures-only names.

The search service must retain a database fallback because cache restoration happens asynchronously at startup and can be invalidated when master contracts change.

## Consumers

- `frontend/src/pages/Search.tsx` uses the session suggestion endpoint.
- IV, GEX, Gamma Density, OI Tracker/Profile, and related tools use the expiry/underlying helpers.
- External scripts and MCP-backed API behavior use the RESTX search contract.

## Key Files

| File | Responsibility |
|---|---|
| `restx_api/search.py` | External POST contract |
| `services/search_service.py` | API-key verification, cache-first search, DB fallback |
| `blueprints/search.py` | Session search and discovery helpers |
| `database/token_db_enhanced.py` | Enhanced token/F&O cache |
| `database/symbol.py` | SQLAlchemy fallback search |
| `frontend/src/pages/Search.tsx` | React search page |

See `docs/api/symbol-services/search.md` and `docs/bdd/market_data.feature`.
