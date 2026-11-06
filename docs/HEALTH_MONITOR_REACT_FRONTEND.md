# Health monitor React frontend

The dashboard at `/health` is implemented in
`frontend/src/pages/HealthMonitor.tsx`. It is already registered in React Router
and `blueprints/react_app.py`. The API client is
`frontend/src/api/health.ts`; shared `webClient` supplies the browser session and
CSRF handling. For probes, configuration and response contracts, use the
[health operations reference](HEALTH_MONITORING_IMPLEMENTATION.md).

## What the page displays

- Overall `pass`, `warn` or `fail` status and the last sample time in IST.
- File descriptors on POSIX, or process handles where no descriptor limit is
  reported; memory, database connections, WebSocket connections and active threads.
- File descriptor and memory history charts covering the last six hours.
- Statistics for the last 24 hours, process memory details, thread details,
  active alerts and recent samples.
- Manual refresh, a ten-second auto-refresh toggle, alert acknowledgement and
  CSV export.

Auto-refresh pauses while the browser tab is hidden. Each refresh fetches
current metrics, six-hour history, 24-hour statistics and active alerts in
parallel. Export requests 24 hours. The backend collection interval is a separate
setting: a faster UI refresh does not produce more samples.

## Chart implementation

Both history charts use `openalgo-charts`, also used by `/trading`. The page
creates line series on host elements, downsamples history to at most 1200 points,
updates data, and disposes chart instances on cleanup. It reapplies themes with
`setTheme` when the application theme or mode changes; it does not recreate the
charts on every metrics refresh.

The line colours are `FD_LINE_COLOR` and `MEMORY_LINE_COLOR`. Background, axes
and crosshair colours come from application tokens through `buildChartTheme`.
History timestamps include their timezone offset. `Date.parse` supplies UTC
milliseconds to the engine, which labels in IST. Do not add another 5h30m shift.

## API access

The dashboard uses these existing client functions:

| Function | Endpoint |
|---|---|
| `getCurrentMetrics()` | `GET /health/api/current` |
| `getMetricsHistory(hours)` | `GET /health/api/history` |
| `getHealthStats(hours)` | `GET /health/api/stats` |
| `getActiveAlerts()` | `GET /health/api/alerts` |
| `acknowledgeAlert(id)` | `POST /health/api/alerts/<id>/acknowledge` |
| `exportMetricsCSV(hours)` | `GET /health/export` |

The backend also offers `resolveAlert(id)` and the unauthenticated JSON probes
`GET /health/status` and `GET /health/check`. `/health` is the HTML application
route. At the audited revision the unused `getSimpleHealth()` helper still
requests `/health`; use the documented `/health/status` probe directly rather
than that helper for monitoring.

## Development and verification

From `frontend/`, use `npm run dev` for local UI work, `npm run lint` to lint and
`npm run build` for TypeScript and production-build validation. A normal install
from `main` already contains the CI-built UI and does not need Node.js.

When modifying this page, check that:

1. Signed-in users can load metrics and signed-out requests are refused.
2. Manual refresh works, auto-refresh can be toggled, and background tabs stop
   polling.
3. Both charts resize, retain their data on a theme change and label time in IST.
4. Process and thread details tolerate missing values, including Windows handles
   without a POSIX descriptor limit.
5. Acknowledging an alert refreshes the panel and CSV export downloads data.
6. A failed request is visible to the user without discarding existing metrics.

A metrics snapshot reports infrastructure resources. It is not a confirmation
of broker connectivity, market-data completeness or order execution.
