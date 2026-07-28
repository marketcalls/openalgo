# Analytics Tools PRD

## Current Tools

OpenAlgo includes session-authenticated trading analytics pages in addition to the REST market-data contract.

| Tool | Current source | Core behavior |
|---|---|---|
| Arbitrage | `blueprints/arbitrage.py`, `services/arbitrage_service.py` | Builds near-versus-later futures calendar-spread pairs and a de-duplicated WebSocket universe |
| Gamma Density | `blueprints/gamma_density.py`, `services/gamma_density_service.py` | Derives gamma-times-open-interest density and convexity-zone data from an option chain |
| OI Tracker | `blueprints/oitracker.py`, `services/oi_tracker_service.py` | Returns option OI distribution and max-pain calculations |
| OI Range | `frontend/src/pages/OIRange.tsx` | Applies a configurable strike-range view to option-chain data |

## Requirements

- Analytics endpoints must validate their exchange, underlying, and expiry inputs before calculation.
- Futures pairing must group contracts by underlying and pair the near contract with later expiries.
- Responses used for live views must include the symbols needed for de-duplicated WebSocket subscriptions.
- Gamma Density and OI views must not fabricate calculations when option-chain inputs are unavailable.
- UI pages must treat broker and market-data failures as explicit unavailable states.

## Acceptance Coverage

See `docs/bdd/scalping_and_tools.feature` and `docs/bdd/historify_and_tools.feature`.
