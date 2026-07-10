# 15 - React UI And Analytics Surfaces

## Application Shell

`frontend/src/App.tsx` defines public, authenticated, standard-layout, and full-width routes. `frontend/src/components/layout/Layout.tsx` owns the standard navigation shell; `FullWidthLayout.tsx` is used for dense workspaces. `frontend/src/config/navigation.ts` determines visible navigation groups.

## Operational Pages

| Area | Routes/pages |
|---|---|
| Account | Dashboard, OrderBook, TradeBook, Positions, Holdings |
| Automation | Strategy, Chartink, Python Strategy Host, Flow |
| Execution | Action Center, Analyzer, Sandbox, Scalping |
| Monitoring | PnL Tracker, Latency, Traffic, Health, Security, Logs |
| Configuration | API key, broker credentials, admin, Telegram, WhatsApp |
| Data | Search, Historify, Download, Master Contract |

Account pages combine TanStack Query with Socket.IO-triggered refreshes. The active broker capability store controls exchange/feature options; app mode comes from the backend analyzer setting.

## Analytics And Trading Tools

Current routed tools include:

| Route | Purpose | Backend source |
|---|---|---|
| `/strategybuilder` | Multi-leg payoff, Greeks, P&L, strategy chart, OI | Multiple strategy services |
| `/optionchain` | Live option chain and quick execution | `option_chain_service.py` |
| `/ivchart` | Historical IV/Greeks charts | `iv_chart_service.py` |
| `/ivsmile` | Call/put IV smile and skew | `iv_smile_service.py` |
| `/volsurface` | 3D volatility surface | `vol_surface_service.py` |
| `/gex` | Gamma exposure by strike | `gex_service.py` |
| `/gammadensity` | Gamma-times-OI and convexity zones | `gamma_density_service.py` |
| `/oitracker` | OI bars and PCR | `oi_tracker_service.py` |
| `/oirange` | Client-side strike-range OI view | Option-chain API |
| `/oiprofile` | Candles plus OI profile | `oi_profile_service.py` |
| `/maxpain` | Max-pain distribution | OI tracker max-pain route |
| `/straddle` | ATM straddle chart | `straddle_chart_service.py` |
| `/customstraddle` | Custom multi-leg straddle chart | `custom_straddle_service.py` |
| `/arbitrage` | Futures calendar-spread scanner | `arbitrage_service.py` |
| `/scalping` | Keyboard execution and server-side stop risk | `scalping.py`, risk monitor |

The tool list is not fixed at twelve; navigation and routes are the current source of truth.

## Live Data

Tools use the shared `MarketDataManager` through hooks rather than opening ad hoc browser feeds. Continuous option-chain or price views merge initial REST snapshots with WebSocket ticks. Pages use visibility controls and stale-data fallbacks to avoid unnecessary broker traffic.

## Shared Components

- `components/trading/`: order dialog, market depth, quote header, GTT and basket execution.
- `components/strategy-builder/`: leg editor, payoff, Greeks, P&L, strategy charts, portfolio save.
- `components/option-chain/`: column configuration and bar settings.
- `components/scalping/`: chart and stop-loss dialog.
- `components/ui/`: local Radix/shadcn-style primitives.

## Error And Loading Behavior

TanStack Query owns request states. Route modules are lazy-loaded, `ErrorBoundary.tsx` handles render failures, `PageLoader` covers route loading, and Sonner-based helpers in `frontend/src/utils/toast.ts` expose categorized user feedback.

## Key Files

| File | Purpose |
|---|---|
| `frontend/src/App.tsx` | Route inventory |
| `frontend/src/config/navigation.ts` | Navigation inventory |
| `frontend/src/api/trading.ts` | Account/trading client |
| `frontend/src/hooks/useOrderEventRefresh.ts` | Event-driven account refresh |
| `frontend/src/lib/MarketDataManager.ts` | Shared market-data subscriptions |
| `blueprints/react_app.py` | Production SPA route serving |
