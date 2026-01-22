# 01 - Frontend Architecture

## Overview

OpenAlgo features a modern React 19 Single Page Application (SPA) built with TypeScript, Vite, and Tailwind CSS 4. The frontend provides a responsive trading interface with real-time market data, visual workflow automation, and comprehensive strategy management.

## Technology Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| React | 19.2.3 | UI framework |
| TypeScript | 5.9.3 | Type safety |
| Vite | 7.2.4 | Build tool & dev server |
| Tailwind CSS | 4.1.18 | Utility-first styling |
| React Router | 7.12.0 | Client-side routing |
| Zustand | 5.0.9 | Client state management |
| TanStack Query | 5.90.16 | Server state & caching |
| Axios | 1.13.2 | HTTP client |
| Socket.IO Client | 4.8.3 | Real-time events |
| @xyflow/react | 12.3.6 | Flow editor canvas |
| Radix UI | Latest | Accessible UI primitives |

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           React Application                                   │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                      React Router v7.12                                 │  │
│  │                                                                         │  │
│  │   Public Routes          Protected Routes         Full-Width Routes     │  │
│  │   /, /login, /setup      /dashboard, /positions   /flow/editor/:id      │  │
│  │   /broker, /download     /orderbook, /strategy    /playground           │  │
│  └────────────────────────────────┬───────────────────────────────────────┘  │
│                                   │                                           │
│                                   ▼                                           │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                         Component Layer                                 │  │
│  │                                                                         │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │  │
│  │  │   Layouts    │  │    Pages     │  │     UI       │  │    Flow    │  │  │
│  │  │  - Standard  │  │  (50+ lazy   │  │  (30+ shadcn │  │  (50+ node │  │  │
│  │  │  - FullWidth │  │   loaded)    │  │   components)│  │   types)   │  │  │
│  │  │  - Public    │  │              │  │              │  │            │  │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  └────────────┘  │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                   │                                           │
│                                   ▼                                           │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                      State Management Layer                             │  │
│  │                                                                         │  │
│  │  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────────────┐ │  │
│  │  │     Zustand     │  │  TanStack Query  │  │       Context          │ │  │
│  │  │  (Client State) │  │  (Server State)  │  │  (Component Scope)     │ │  │
│  │  │                 │  │                  │  │                        │ │  │
│  │  │  - authStore    │  │  - positions     │  │  - SocketProvider      │ │  │
│  │  │  - themeStore   │  │  - orders        │  │  - ThemeProvider       │ │  │
│  │  │  - flowStore    │  │  - strategies    │  │                        │ │  │
│  │  └─────────────────┘  └──────────────────┘  └────────────────────────┘ │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                   │                                           │
│                                   ▼                                           │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                          API Layer                                      │  │
│  │                                                                         │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                  │  │
│  │  │  apiClient   │  │  webClient   │  │  authClient  │                  │  │
│  │  │  /api/v1/*   │  │  Session +   │  │  Form data + │                  │  │
│  │  │  API Key     │  │  CSRF        │  │  CSRF        │                  │  │
│  │  └──────────────┘  └──────────────┘  └──────────────┘                  │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
              ┌─────────────────────┴─────────────────────┐
              ▼                                           ▼
    ┌─────────────────┐                         ┌─────────────────┐
    │   Socket.IO     │                         │    WebSocket    │
    │ (Flask Events)  │                         │  (Market Data)  │
    │  :5000          │                         │    :8765        │
    └─────────────────┘                         └─────────────────┘
```

## Directory Structure

```
frontend/
├── src/
│   ├── api/                    # API integration modules
│   │   ├── client.ts           # Axios clients (apiClient, webClient, authClient)
│   │   ├── auth.ts             # Authentication API
│   │   ├── trading.ts          # Trading operations API
│   │   ├── strategy.ts         # Strategy management API
│   │   ├── flow.ts             # Flow workflow API
│   │   └── ...                 # Other API modules
│   │
│   ├── app/
│   │   └── providers.tsx       # TanStack Query & theme providers
│   │
│   ├── components/
│   │   ├── auth/
│   │   │   └── AuthSync.tsx    # Flask session ↔ Zustand sync
│   │   ├── flow/
│   │   │   ├── nodes/          # 50+ flow node components
│   │   │   ├── edges/          # Edge components
│   │   │   └── panels/         # Config, Palette, Execution panels
│   │   ├── layout/
│   │   │   ├── Layout.tsx      # Main protected layout
│   │   │   ├── FullWidthLayout.tsx
│   │   │   ├── Navbar.tsx
│   │   │   ├── Footer.tsx
│   │   │   └── MobileBottomNav.tsx
│   │   ├── socket/
│   │   │   └── SocketProvider.tsx
│   │   └── ui/                 # 30+ shadcn/ui components
│   │
│   ├── hooks/                  # Custom React hooks
│   │   ├── useSocket.ts        # Socket.IO connection
│   │   ├── useMarketData.ts    # WebSocket market data
│   │   └── ...
│   │
│   ├── pages/                  # Page components (all lazy-loaded)
│   │   ├── Dashboard.tsx
│   │   ├── Positions.tsx
│   │   ├── strategy/           # Strategy pages
│   │   ├── flow/               # Flow editor pages
│   │   ├── admin/              # Admin pages
│   │   └── ...
│   │
│   ├── stores/                 # Zustand state stores
│   │   ├── authStore.ts        # Authentication state
│   │   ├── themeStore.ts       # Theme preferences
│   │   └── flowWorkflowStore.ts
│   │
│   ├── types/                  # TypeScript type definitions
│   │
│   ├── App.tsx                 # Route definitions
│   ├── main.tsx                # Entry point
│   └── index.css               # Global styles + CSS variables
│
├── vite.config.ts              # Vite configuration
├── tsconfig.app.json           # TypeScript config
├── biome.json                  # Linter/formatter config
└── package.json
```

## State Management

### 1. Zustand (Client State)

Lightweight state management for UI state that persists across sessions.

```typescript
// stores/authStore.ts
interface AuthStore {
  user: User | null
  apiKey: string | null
  isAuthenticated: boolean

  login: (username: string, broker: string) => void
  logout: () => void
  checkSession: () => boolean  // 3 AM IST expiry
}

// Usage in component
const { user, isAuthenticated } = useAuthStore()
```

**Stores:**
- `authStore` - User session, API key, authentication state
- `themeStore` - Dark/light mode, analyzer mode toggle
- `flowWorkflowStore` - Flow editor nodes, edges, selection state

### 2. TanStack Query (Server State)

Handles all server data fetching with automatic caching and refetching.

```typescript
// Configuration (app/providers.tsx)
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60 * 1000,      // 1 minute
      refetchOnWindowFocus: true,
      retry: 1,
    },
  },
})

// Usage in component
const { data: positions, isLoading } = useQuery({
  queryKey: ['positions'],
  queryFn: () => tradingApi.getPositions()
})
```

## API Integration

### Three Axios Clients

```typescript
// 1. apiClient - For /api/v1/* endpoints (API key auth)
const apiClient = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' }
})

// 2. webClient - For session-based routes (CSRF required)
const webClient = axios.create({
  baseURL: '',
  withCredentials: true
})

// 3. authClient - For login/setup (form data + CSRF)
const authClient = axios.create({
  baseURL: '',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' }
})
```

### CSRF Protection

```typescript
// Automatic CSRF token injection
webClient.interceptors.request.use(async (config) => {
  if (['post', 'put', 'delete'].includes(config.method)) {
    const csrfToken = await fetchCSRFToken()
    config.headers['X-CSRFToken'] = csrfToken
  }
  return config
})
```

## Routing Structure

### Route Categories

| Category | Example Routes | Layout |
|----------|---------------|--------|
| Public | `/`, `/login`, `/setup`, `/download` | None |
| Broker Auth | `/broker`, `/broker/:broker/totp` | None |
| Protected | `/dashboard`, `/positions`, `/strategy` | Standard Layout |
| Full-Width | `/flow/editor/:id`, `/playground` | Full-Width Layout |

### Code Splitting

All pages are lazy-loaded for optimal bundle size:

```typescript
const Dashboard = lazy(() => import('@/pages/Dashboard'))
const Positions = lazy(() => import('@/pages/Positions'))

// With Suspense fallback
<Suspense fallback={<PageLoader />}>
  <Routes>
    <Route path="/dashboard" element={<Dashboard />} />
  </Routes>
</Suspense>
```

## Real-Time Communication

### Socket.IO (Order Events)

```typescript
// hooks/useSocket.ts
socket.on('order_event', (data) => {
  playAlertSound()
  toast.success(`Order ${data.status}: ${data.symbol}`)
  queryClient.invalidateQueries(['orders'])
})
```

**Events:** `order_event`, `cancel_order_event`, `modify_order_event`, `close_position_event`

### WebSocket (Market Data)

```typescript
// hooks/useMarketData.ts
const ws = new WebSocket('ws://localhost:8765')
ws.send(JSON.stringify({
  action: 'subscribe',
  symbols: ['NSE:SBIN-EQ'],
  mode: 'ltp'
}))

ws.onmessage = (event) => {
  const data = JSON.parse(event.data)
  // Update price state
}
```

## Component Library (shadcn/ui)

Built on Radix UI primitives with Tailwind styling:

| Category | Components |
|----------|------------|
| Form | Button, Input, Select, Checkbox, Switch, Label |
| Display | Card, Table, Badge, Avatar, Skeleton |
| Overlay | Dialog, Sheet, Popover, Tooltip, DropdownMenu |
| Custom | JsonEditor, PythonEditor, LogViewer, PageLoader |

## Build & Development

```bash
# Development
npm run dev          # Vite dev server on :5173

# Production build
npm run build        # Output to /frontend/dist/

# Testing
npm test             # Vitest watch mode
npm run e2e          # Playwright E2E tests

# Code quality
npm run lint         # Biome linting
npm run format       # Biome formatting
```

## Bundle Optimization

Vite splits the bundle into chunks:

| Chunk | Contents |
|-------|----------|
| vendor-react | React, ReactDOM |
| vendor-router | React Router |
| vendor-radix | Radix UI components |
| vendor-icons | Lucide React icons |
| vendor-syntax | Code highlighter (loaded on demand) |

## Key Files Reference

| File | Purpose |
|------|---------|
| `src/App.tsx` | Route definitions |
| `src/api/client.ts` | Axios clients configuration |
| `src/stores/authStore.ts` | Authentication state |
| `src/components/layout/Layout.tsx` | Main layout with Navbar/Footer |
| `src/components/auth/AuthSync.tsx` | Flask session sync |
| `vite.config.ts` | Build configuration |
