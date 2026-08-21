# SPX 1:45 PM Sandwich

This is a QuantConnect LEAN implementation of the Option Alpha `1:45pm
Sandwich` paper strategy.

Rules currently reproduced from the bot and its closed positions:

- SPXW 0DTE short iron condor.
- Entry scan from 1:45 PM through 2:00 PM New York time.
- Monday, Tuesday, Thursday, and Friday only.
- Round SPX to the nearest $5 strike grid; short put/call are one grid step
  below/above the center and long wings are another $5 away.
- VIX must be greater than 0 and below 24.
- Conservative executable credit must produce at least 100% credit-to-defined-
  risk reward/risk.
- One position per day, one open position, and maximum defined risk of $2,500.
- Positions are held to expiration by default.

The scanner's visible market-condition block is `Market closes at 4:00PM
today` and `VIX is between 0 - 24`. The exact hidden exit-option behavior still
needs confirmation before live deployment.

## Safety

Copy `.env.example` to `.env`. Paper mode places paper orders by default; set
`SPX_SANDWICH_PLACE_ORDERS=false` for a decision-only run. Real-money mode
remains disabled unless explicitly enabled through the live safety gates. This
strategy uses the shared LEAN IB runner. The runner automatically uses an
already-running IB Gateway, or starts IBAutomater when Gateway is not running.

## Run

```bash
cp strategies/python/spx_1_45pm_sandwich/.env.example strategies/python/spx_1_45pm_sandwich/.env
LIVE_CONFIRM=true strategies/python/spx_1_45pm_sandwich/run-live.sh
```

Paper mode and paper order placement are the defaults. Do not start a second
copy while one LEAN process is already running; stop the active process with
`Ctrl+C` first.

Dashboard:

```text
http://127.0.0.1:3001/d/spx-1-45pm-sandwich/spx-1-45pm-sandwich?orgId=1&from=now-1h&to=now&timezone=browser&refresh=5s
```
