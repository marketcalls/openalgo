# 01 - Frontend Architecture

## Stack

The frontend is a React 19 TypeScript SPA built with Vite 8. Current package constraints are read from `frontend/package.json`.

| Concern | Implementation |
|---|---|
| Routing | `react-router-dom` 7.15 |
| Server state | TanStack Query 5 |
| Client state | Zustand 5 |
| Styling | Tailwind CSS 4 and local shadcn-style components |
| Icons | Lucide React |
| Forms/editors | Radix primitives, CodeMirror |
| Flow canvas | XYFlow 12 |
| Charts | Plotly 3 and Lightweight Charts 5 |
| Live app events | Socket.IO client |
| Tests | Vitest 4, Testing Library, axe, Playwright |
| Formatting/lint | Biome 2 |

Supported Node versions are `>=20.20.0 || >=22.22.0 || >=24.13.0`.

## Composition

`frontend/src/main.tsx` mounts the app. `frontend/src/app/providers.tsx` composes TanStack Query, theme, tooltips, Socket.IO, market-data state, and browser toasts. `frontend/src/App.tsx` lazy-loads route modules and applies public/authenticated/full-width layout boundaries.

The Flask backend serves the production bundle through `blueprints/react_app.py` when `frontend/dist` exists. Vite's development server runs on port 5173 and proxies backend requests according to `frontend/vite.config.ts`.

## Route Families

| Family | Examples |
|---|---|
| Public/auth | `/login`, `/setup`, `/reset-password`, broker callbacks |
| Trading state | `/dashboard`, `/orderbook`, `/tradebook`, `/positions`, `/holdings` |
| Automation | `/strategy`, `/chartink`, `/python`, `/flow` |
| Tools | `/optionchain`, `/strategybuilder`, `/ivchart`, `/oitracker`, `/gex`, `/gammadensity`, `/oirange`, `/arbitrage`, `/scalping` |
| Monitoring | `/pnltracker`, `/latency`, `/traffic`, `/health`, `/security` |
| Admin/integrations | `/admin`, `/apikey`, `/playground`, `/telegram`, `/whatsapp` |

The exact route list is in `frontend/src/App.tsx`; navigation visibility is defined separately in `frontend/src/config/navigation.ts`.

## State Boundaries

| Store/context | Responsibility |
|---|---|
| `authStore.ts` | User and OpenAlgo API key for client calls |
| `brokerStore.ts` | Active broker capability metadata |
| `sessionStore.ts` | Active app-session count |
| `themeStore.ts` | Theme, accent, live/analyzer presentation mode |
| `flowWorkflowStore.ts` | Flow editor graph state |
| `MarketDataContext.tsx` | Shared market-data manager lifecycle |

TanStack Query owns fetched server data. Zustand is reserved for cross-page client state; feature-local state remains in components.

## Data And Live Updates

Feature clients under `frontend/src/api/` call Flask blueprint or REST resources with credentials. `AuthSync` reads `/auth/session-status`, restores user/broker/API-key state, synchronizes analyzer mode, and records the active-session count.

Market data uses `MarketDataManager` and hooks such as `useLivePrice`, `useLiveQuote`, `useMarketData`, and `useOptionChainLive`. Order lifecycle refreshes are triggered by Socket.IO events through `useOrderEventRefresh`, avoiding high-frequency account polling where an event is available.

## Build And Test Commands

Run from `frontend/`:

```bash
npm ci
npm run lint
npm run test:run
npm run build
npm run e2e -- --project=chromium
```

`npm run build` runs TypeScript project builds before Vite. CI uploads `frontend/dist`, and main-branch automation rebuilds and commits the production bundle.

## Key Files

| File | Purpose |
|---|---|
| `frontend/src/App.tsx` | Route graph and lazy modules |
| `frontend/src/app/providers.tsx` | Global providers |
| `frontend/src/config/navigation.ts` | Sidebar/tool navigation |
| `frontend/src/api/client.ts` | Shared HTTP client behavior |
| `frontend/src/components/auth/AuthSync.tsx` | Flask session synchronization |
| `frontend/src/lib/MarketDataManager.ts` | Shared WebSocket market-data lifecycle |
| `frontend/vite.config.ts` | Build and development proxy |
