# Analytics Tools PRD

## Current Tools

OpenAlgo includes trading analytics pages and analytics REST services in addition to its order/market-data contract. The `/tools` and home pages derive their 20-tool catalogue from `frontend/src/lib/tools.ts`; that registry is the source of truth for discovery.

| Tool | Current source | Core behavior |
|---|---|---|
| Arbitrage | `blueprints/arbitrage.py`, `services/arbitrage_service.py` | Builds near-versus-later futures calendar-spread pairs and a de-duplicated WebSocket universe |
| Gamma Density | `blueprints/gamma_density.py`, `services/gamma_density_service.py` | Derives gamma-times-open-interest density and convexity-zone data from an option chain |
| OI Tracker | `blueprints/oitracker.py`, `services/oi_tracker_service.py` | Returns option OI distribution and max-pain calculations |
| Strike Profile | `blueprints/strike_profile.py`, `services/strike_profile_service.py` | GEX and DEX per strike across selected expiries, with flip/wall summaries |
| Sector Rotation | `restx_api/sector_rotation.py`, `services/sector_rotation_service.py` | Benchmark-relative rotation map for sectors, stocks and indices from Historify or broker history |
| Portfolio Backtester / Analyzer | `restx_api/portfolio.py`, `portfolio/` | Weighted portfolio simulation, tearsheets and holdings analysis |
| SIP Backtester | `restx_api/sip.py`, `services/sip_service.py`, `sip/` | Periodic-investment simulation and comparison with a lump sum |
| OI Range | `frontend/src/pages/OIRange.tsx` | Applies a configurable strike-range view to option-chain data |

## Requirements

- Analytics endpoints must validate their exchange, underlying, and expiry inputs before calculation.
- Futures pairing must group contracts by underlying and pair the near contract with later expiries.
- Responses used for live views must include the symbols needed for de-duplicated WebSocket subscriptions.
- Gamma Density and OI views must not fabricate calculations when option-chain inputs are unavailable.
- UI pages must treat broker and market-data failures as explicit unavailable states.

## Strike Profile Contract

`POST /strikeprofile/api/profile-data` is session-authenticated and resolves the user's OpenAlgo API key. It requires an uppercase `underlying`, `exchange`, and nonempty `expiry_dates` array in `DDMMMYY` format. The endpoint takes at most the first 20 expiry entries. `range_pct` accepts `2`, `5`, `10` or `null` (all loaded strikes).

Each expiry requires one option-chain fetch. GEX is reported in rupees crore for a 1% underlying move, with positive call and negative put exposure; DEX uses the signed option delta. The gamma flip is a repriced sign change within the loaded strike range, and can be absent. The UI also shows each expiry's own peaks so a far-dated expiry is not hidden by the near expiry's larger gamma.

## Sector Rotation Contract

`GET /api/v1/sectorrotation/options` discovers defaults and supported choices. `POST /api/v1/sectorrotation` computes RS-Ratio and RS-Momentum, centered on 100, using linearly weighted moving averages. Daily and weekly modes read daily closes; weekly mode aligns symbol/benchmark sessions before resampling. Each instrument is aligned with the benchmark independently so a shorter history does not truncate the whole map.

The request chooses `source="db"` (Historify) or `source="api"` (broker history), a benchmark, and up to 40 cash/index instruments. A missing benchmark fails the map; missing or short member history is returned with a reason while usable members remain. Thinly published sector indices are excluded from the default set but can be added through search. See the [analytics API reference](../api/README.md#portfolio-sip-and-sector-analysis) for request/response schemas.

## Acceptance Coverage

See `docs/bdd/scalping_and_tools.feature` and `docs/bdd/historify_and_tools.feature`.
