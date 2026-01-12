# OpenAlgo v2.0.0.0 - React Migration Plan

## Executive Summary

Migration from Flask/Jinja2 frontend to a modern **React 19 + TypeScript + Vite 6** stack while **preserving the existing folder structure and startup command** for 60,000+ existing users. The React frontend will be embedded within the existing `openalgo/` directory and served by Flask.

**Version**: OpenAlgo 2.0.0.0
**Codename**: Terminal Edition

### Critical Constraints
- **No folder structure changes** - External apps depend on current paths
- **Startup command unchanged** - `uv run app.py` must continue to work
- **API endpoints unchanged** - All `/api/v1/*` routes preserved
- **Database unchanged** - SQLite databases remain as-is
- **Backward compatible** - Existing integrations (TradingView, Amibroker, etc.) unaffected

### Design Requirements (Based on User Input)
- **Complete replacement** - Jinja2 templates will be removed after migration
- **Theme System** - Light theme default, Dark mode toggle, Special Analyzer/Sandbox theme, Multiple shadcn color themes
- **Priority** - Dashboard + Orders + Positions first
- **Responsive** - Full responsive design (Desktop → Tablet → Mobile)

---

## 1. Proposed Tech Stack

### Frontend Core
| Technology | Version | Purpose |
|------------|---------|---------|
| **React** | 19.x | Latest with React Compiler, no vulnerabilities |
| **TypeScript** | 5.7+ | Type safety, better DX, fewer runtime errors |
| **Vite** | 6.x | Lightning-fast HMR, optimized builds |
| **React Router** | 7.x | File-based routing, type-safe navigation |

### UI Framework
| Technology | Version | Purpose |
|------------|---------|---------|
| **Tailwind CSS** | 4.x | Utility-first CSS, already familiar |
| **shadcn/ui** | Latest | Beautiful, accessible components |
| **Radix UI** | Latest | Headless primitives (shadcn foundation) |
| **Lucide React** | Latest | Consistent icon library |
| **Recharts** | 2.x | Trading charts & visualizations |
| **TradingView Lightweight Charts** | 4.x | Professional candlestick charts |

### State Management (Critical for 10x-100x Performance)
| Technology | Purpose |
|------------|---------|
| **TanStack Query v5** | Server state, caching, real-time sync |
| **Zustand** | Client state, minimal boilerplate |
| **Jotai** | Atomic state for complex UI interactions |

### Real-Time & Data
| Technology | Purpose |
|------------|---------|
| **Socket.IO Client** | WebSocket connection to Flask-SocketIO |
| **TanStack Table** | High-performance data tables |
| **React Virtual** | Virtualized lists for large datasets |

### Development & Quality
| Technology | Purpose |
|------------|---------|
| **Biome** | Fast linting + formatting (replaces ESLint/Prettier) |
| **Vitest** | Unit testing |
| **Playwright** | E2E testing |
| **MSW** | API mocking for development |

---

## 2. Architecture Overview (Preserving Existing Structure)

```
openalgo/                           # EXISTING - NO CHANGES TO ROOT STRUCTURE
├── app.py                          # EXISTING - Modified to serve React build
├── extensions.py                   # EXISTING - UNCHANGED
├── cors.py                         # EXISTING - UNCHANGED
├── csp.py                          # EXISTING - UNCHANGED
├── limiter.py                      # EXISTING - UNCHANGED
├── start.sh                        # EXISTING - Modified to build React first
│
├── blueprints/                     # EXISTING - UNCHANGED (All 30+ blueprints)
├── restx_api/                      # EXISTING - UNCHANGED (All 30+ API endpoints)
├── broker/                         # EXISTING - UNCHANGED (24+ brokers)
├── services/                       # EXISTING - UNCHANGED (48 services)
├── database/                       # EXISTING - UNCHANGED (25+ modules)
├── utils/                          # EXISTING - UNCHANGED
├── websocket_proxy/                # EXISTING - UNCHANGED
├── sandbox/                        # EXISTING - UNCHANGED
├── mcp/                            # EXISTING - UNCHANGED
│
├── templates/                      # EXISTING - Keep for backward compatibility
│   └── (59+ files)                 # Legacy Jinja2 templates (fallback mode)
│
├── static/                         # EXISTING - Keep for backward compatibility
│   └── (existing assets)           # Legacy static files
│
├── db/                             # EXISTING - UNCHANGED
├── log/                            # EXISTING - UNCHANGED
├── keys/                           # EXISTING - UNCHANGED
├── strategies/                     # EXISTING - UNCHANGED
│
├── frontend/                       # NEW - React Frontend (Embedded)
│   ├── src/
│   │   ├── app/                   # App configuration
│   │   │   ├── providers.tsx      # All providers wrapped
│   │   │   ├── router.tsx         # React Router config
│   │   │   └── App.tsx            # Root component
│   │   │
│   │   ├── components/            # Reusable UI components
│   │   │   ├── ui/                # shadcn/ui components
│   │   │   ├── trading/           # Trading-specific components
│   │   │   │   ├── OrderPanel.tsx
│   │   │   │   ├── PositionTable.tsx
│   │   │   │   ├── Watchlist.tsx
│   │   │   │   ├── MarketDepth.tsx
│   │   │   │   ├── OptionChain.tsx
│   │   │   │   └── PnLTracker.tsx
│   │   │   ├── charts/            # Chart components
│   │   │   │   ├── CandlestickChart.tsx
│   │   │   │   ├── PnLChart.tsx
│   │   │   │   └── GreeksChart.tsx
│   │   │   └── layout/            # Layout components
│   │   │       ├── Sidebar.tsx
│   │   │       ├── Header.tsx
│   │   │       ├── Terminal.tsx
│   │   │       └── ResizablePanels.tsx
│   │   │
│   │   ├── features/              # Feature modules
│   │   │   ├── auth/
│   │   │   │   ├── components/
│   │   │   │   ├── hooks/
│   │   │   │   ├── api.ts
│   │   │   │   └── store.ts
│   │   │   ├── dashboard/
│   │   │   ├── orders/
│   │   │   ├── positions/
│   │   │   ├── holdings/
│   │   │   ├── watchlist/
│   │   │   ├── options/
│   │   │   ├── strategy/
│   │   │   ├── sandbox/
│   │   │   ├── analyzer/
│   │   │   └── settings/
│   │   │
│   │   ├── hooks/                 # Global custom hooks
│   │   │   ├── useWebSocket.ts
│   │   │   ├── useMarketData.ts
│   │   │   ├── useOrders.ts
│   │   │   └── useAuth.ts
│   │   │
│   │   ├── stores/                # Zustand stores
│   │   │   ├── authStore.ts
│   │   │   ├── marketStore.ts
│   │   │   ├── orderStore.ts
│   │   │   ├── watchlistStore.ts
│   │   │   └── settingsStore.ts
│   │   │
│   │   ├── api/                   # API layer
│   │   │   ├── client.ts          # Axios/fetch config
│   │   │   ├── queries/           # TanStack Query definitions
│   │   │   │   ├── orders.ts
│   │   │   │   ├── positions.ts
│   │   │   │   ├── quotes.ts
│   │   │   │   └── options.ts
│   │   │   └── mutations/         # TanStack mutations
│   │   │       ├── placeOrder.ts
│   │   │       ├── modifyOrder.ts
│   │   │       └── cancelOrder.ts
│   │   │
│   │   ├── lib/                   # Utilities
│   │   │   ├── utils.ts           # shadcn utils
│   │   │   ├── formatters.ts      # Number/date formatters
│   │   │   ├── validators.ts      # Zod schemas
│   │   │   └── constants.ts       # App constants
│   │   │
│   │   ├── types/                 # TypeScript types
│   │   │   ├── api.ts             # API response types
│   │   │   ├── order.ts           # Order types
│   │   │   ├── position.ts        # Position types
│   │   │   ├── quote.ts           # Market data types
│   │   │   └── broker.ts          # Broker types
│   │   │
│   │   ├── pages/                 # Route pages
│   │   │   ├── index.tsx          # Dashboard
│   │   │   ├── login.tsx
│   │   │   ├── orders.tsx
│   │   │   ├── positions.tsx
│   │   │   ├── holdings.tsx
│   │   │   ├── watchlist.tsx
│   │   │   ├── options.tsx
│   │   │   ├── strategy.tsx
│   │   │   ├── sandbox.tsx
│   │   │   ├── analyzer.tsx
│   │   │   └── settings.tsx
│   │   │
│   │   ├── styles/
│   │   │   └── globals.css        # Tailwind + custom styles
│   │   │
│   │   └── main.tsx               # Entry point
│   │
│   ├── dist/                      # BUILD OUTPUT → Served by Flask
│   │   ├── index.html
│   │   └── assets/
│   │
│   ├── public/
│   ├── index.html
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   ├── components.json           # shadcn config
│   └── package.json
│
├── .env                           # EXISTING - UNCHANGED (NO MODIFICATIONS)
├── pyproject.toml                 # EXISTING - UNCHANGED
├── requirements.txt               # EXISTING - UNCHANGED
├── package.json                   # EXISTING - UNCHANGED (frontend has its own)
├── Dockerfile                     # EXISTING - Add Node.js for build step
└── docker-compose.yaml            # EXISTING - UNCHANGED
```

### Key Integration Points

**1. Flask serves React build from `frontend/dist/`**
**2. API routes (`/api/v1/*`) remain unchanged**
**3. WebSocket events remain unchanged**
**4. `uv run app.py` auto-builds React if needed**

---

## 3. State Management Strategy (10x-100x Performance)

### Why This Stack Achieves 10x-100x Performance

#### A. TanStack Query (Server State)
```typescript
// Automatic caching, background refetching, stale-while-revalidate
const { data: positions } = useQuery({
  queryKey: ['positions'],
  queryFn: fetchPositions,
  staleTime: 1000,           // Consider fresh for 1s
  refetchInterval: 5000,     // Auto-refresh every 5s
  refetchOnWindowFocus: true,
});

// Optimistic updates for instant UI feedback
const placeOrderMutation = useMutation({
  mutationFn: placeOrder,
  onMutate: async (newOrder) => {
    // Cancel outgoing refetches
    await queryClient.cancelQueries({ queryKey: ['orders'] });

    // Snapshot previous value
    const previousOrders = queryClient.getQueryData(['orders']);

    // Optimistically update
    queryClient.setQueryData(['orders'], (old) => [...old, newOrder]);

    return { previousOrders };
  },
  onError: (err, newOrder, context) => {
    // Rollback on error
    queryClient.setQueryData(['orders'], context.previousOrders);
  },
  onSettled: () => {
    queryClient.invalidateQueries({ queryKey: ['orders'] });
  },
});
```

#### B. Zustand (Client State)
```typescript
// Minimal, fast, no boilerplate
interface MarketStore {
  watchlist: string[];
  selectedSymbol: string | null;
  theme: 'light' | 'dark';
  layout: LayoutConfig;

  // Actions
  addToWatchlist: (symbol: string) => void;
  selectSymbol: (symbol: string) => void;
  setTheme: (theme: 'light' | 'dark') => void;
}

const useMarketStore = create<MarketStore>()(
  devtools(
    persist(
      (set) => ({
        watchlist: [],
        selectedSymbol: null,
        theme: 'dark',
        layout: defaultLayout,

        addToWatchlist: (symbol) =>
          set((state) => ({
            watchlist: [...state.watchlist, symbol],
          })),
        selectSymbol: (symbol) => set({ selectedSymbol: symbol }),
        setTheme: (theme) => set({ theme }),
      }),
      { name: 'market-store' }
    )
  )
);
```

#### C. Real-Time WebSocket Integration
```typescript
// WebSocket store with Zustand
interface WebSocketStore {
  socket: Socket | null;
  isConnected: boolean;
  quotes: Map<string, Quote>;

  connect: () => void;
  subscribe: (symbols: string[]) => void;
  unsubscribe: (symbols: string[]) => void;
}

const useWebSocketStore = create<WebSocketStore>((set, get) => ({
  socket: null,
  isConnected: false,
  quotes: new Map(),

  connect: () => {
    const socket = io('http://localhost:5000', {
      transports: ['websocket'],
    });

    socket.on('connect', () => set({ isConnected: true }));
    socket.on('disconnect', () => set({ isConnected: false }));

    socket.on('quote_update', (data: Quote) => {
      set((state) => {
        const newQuotes = new Map(state.quotes);
        newQuotes.set(data.symbol, data);
        return { quotes: newQuotes };
      });
    });

    set({ socket });
  },

  subscribe: (symbols) => {
    get().socket?.emit('subscribe', { symbols, mode: 'QUOTE' });
  },

  unsubscribe: (symbols) => {
    get().socket?.emit('unsubscribe', { symbols });
  },
}));
```

### Performance Optimizations

| Technique | Impact | Implementation |
|-----------|--------|----------------|
| **Virtual scrolling** | 100x for large lists | `@tanstack/react-virtual` for 1000+ rows |
| **Selective subscriptions** | 10x less re-renders | Zustand selectors with shallow comparison |
| **Memoization** | 5x faster renders | `React.memo`, `useMemo`, `useCallback` |
| **Code splitting** | 50% faster initial load | Dynamic imports per route |
| **WebSocket batching** | 10x less updates | Batch quote updates every 100ms |
| **Web Workers** | Non-blocking UI | Heavy calculations off main thread |

---

## 4. Trading Terminal UI Design

### Layout Structure (Professional Trading Terminal)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Header: Logo | Search | Notifications | Account | Settings | Theme     │
├────────┬────────────────────────────────────────────────────────────────┤
│        │  ┌─────────────────────────────────┬──────────────────────────┐│
│        │  │                                 │                          ││
│        │  │         CHART AREA              │      ORDER PANEL         ││
│  S     │  │    (TradingView Lightweight)    │   ┌────────────────────┐ ││
│  I     │  │                                 │   │ Buy  │  Sell       │ ││
│  D     │  │   Candlesticks, Indicators      │   ├────────────────────┤ ││
│  E     │  │   Drawing tools, Studies        │   │ Qty: [________]    │ ││
│  B     │  │                                 │   │ Price: [________]  │ ││
│  A     │  │                                 │   │ Type: [Dropdown]   │ ││
│  R     │  │                                 │   │ [Place Order]      │ ││
│        │  └─────────────────────────────────┴──────────────────────────┘│
│  Nav   │  ┌─────────────────────────────────────────────────────────────┤
│        │  │  TABS: Positions | Orders | Holdings | Watchlist | Trades  ││
│ 📊 Dash│  ├─────────────────────────────────────────────────────────────┤
│ 📈 Chart│ │                                                             ││
│ 💼 Pos │  │  DATA TABLE (Virtual Scrolling)                            ││
│ 📋 Ord │  │  ┌──────┬──────┬──────┬──────┬──────┬──────┬──────┐        ││
│ 💰 Hold│  │  │Symbol│Qty   │Avg   │LTP   │P&L   │P&L % │Action│        ││
│ 👁 Watch│ │  ├──────┼──────┼──────┼──────┼──────┼──────┼──────┤        ││
│ ⚡ Opt │  │  │RELIAN│ 100  │2450  │2480  │+3000 │+1.22%│[Exit]│        ││
│ 🤖 Strat│ │  │TATAM │ 50   │850   │835   │-750  │-0.88%│[Exit]│        ││
│ 🧪 Sand│  │  │...   │...   │...   │...   │...   │...   │...   │        ││
│ ⚙ Set │  │  └──────┴──────┴──────┴──────┴──────┴──────┴──────┘        ││
│        │  └─────────────────────────────────────────────────────────────┤
├────────┴────────────────────────────────────────────────────────────────┤
│  Footer: Connected: ● Zerodha | API Calls: 1,234 | Latency: 45ms       │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key UI Components (shadcn/ui Based)

#### 1. Resizable Panel Layout
```typescript
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from "@/components/ui/resizable"

function TradingTerminal() {
  return (
    <ResizablePanelGroup direction="horizontal">
      <ResizablePanel defaultSize={15} minSize={10}>
        <Sidebar />
      </ResizablePanel>
      <ResizableHandle />
      <ResizablePanel defaultSize={85}>
        <ResizablePanelGroup direction="vertical">
          <ResizablePanel defaultSize={60}>
            <ResizablePanelGroup direction="horizontal">
              <ResizablePanel defaultSize={70}>
                <ChartArea />
              </ResizablePanel>
              <ResizableHandle />
              <ResizablePanel defaultSize={30}>
                <OrderPanel />
              </ResizablePanel>
            </ResizablePanelGroup>
          </ResizablePanel>
          <ResizableHandle />
          <ResizablePanel defaultSize={40}>
            <DataTables />
          </ResizablePanel>
        </ResizablePanelGroup>
      </ResizablePanel>
    </ResizablePanelGroup>
  )
}
```

#### 2. Order Panel Component
```typescript
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

function OrderPanel() {
  return (
    <Card className="h-full border-0 rounded-none">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2">
          <span className="text-lg font-bold">RELIANCE</span>
          <span className="text-green-500 text-xl">₹2,480.50</span>
          <span className="text-green-500 text-sm">+1.22%</span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="regular">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="regular">Regular</TabsTrigger>
            <TabsTrigger value="bracket">Bracket</TabsTrigger>
            <TabsTrigger value="cover">Cover</TabsTrigger>
          </TabsList>

          <TabsContent value="regular" className="space-y-4">
            <div className="grid grid-cols-2 gap-2">
              <Button className="bg-green-600 hover:bg-green-700">BUY</Button>
              <Button className="bg-red-600 hover:bg-red-700">SELL</Button>
            </div>

            <div className="space-y-3">
              <div className="flex gap-2">
                <Input placeholder="Qty" type="number" />
                <Input placeholder="Price" type="number" />
              </div>

              <Select>
                <SelectTrigger>
                  <SelectValue placeholder="Order Type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="MARKET">Market</SelectItem>
                  <SelectItem value="LIMIT">Limit</SelectItem>
                  <SelectItem value="SL">Stop Loss</SelectItem>
                  <SelectItem value="SL-M">SL-Market</SelectItem>
                </SelectContent>
              </Select>

              <Select>
                <SelectTrigger>
                  <SelectValue placeholder="Product" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="MIS">MIS (Intraday)</SelectItem>
                  <SelectItem value="NRML">NRML (F&O)</SelectItem>
                  <SelectItem value="CNC">CNC (Delivery)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <Button className="w-full" size="lg">
              Place Order
            </Button>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}
```

#### 3. Position Table with Virtual Scrolling
```typescript
import { useVirtualizer } from '@tanstack/react-virtual'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

function PositionsTable() {
  const { data: positions } = usePositions()
  const parentRef = useRef<HTMLDivElement>(null)

  const virtualizer = useVirtualizer({
    count: positions?.length ?? 0,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 48,
    overscan: 5,
  })

  return (
    <div ref={parentRef} className="h-full overflow-auto">
      <Table>
        <TableHeader className="sticky top-0 bg-background">
          <TableRow>
            <TableHead>Symbol</TableHead>
            <TableHead className="text-right">Qty</TableHead>
            <TableHead className="text-right">Avg</TableHead>
            <TableHead className="text-right">LTP</TableHead>
            <TableHead className="text-right">P&L</TableHead>
            <TableHead className="text-right">P&L %</TableHead>
            <TableHead>Action</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const position = positions[virtualRow.index]
            const pnl = (position.ltp - position.avgPrice) * position.quantity
            const pnlPercent = ((position.ltp - position.avgPrice) / position.avgPrice) * 100

            return (
              <TableRow
                key={position.symbol}
                style={{
                  height: `${virtualRow.size}px`,
                  transform: `translateY(${virtualRow.start}px)`,
                }}
              >
                <TableCell className="font-medium">{position.symbol}</TableCell>
                <TableCell className="text-right">{position.quantity}</TableCell>
                <TableCell className="text-right">₹{position.avgPrice}</TableCell>
                <TableCell className="text-right">₹{position.ltp}</TableCell>
                <TableCell className={`text-right ${pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                  {pnl >= 0 ? '+' : ''}₹{pnl.toFixed(2)}
                </TableCell>
                <TableCell className={`text-right ${pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
                  {pnlPercent >= 0 ? '+' : ''}{pnlPercent.toFixed(2)}%
                </TableCell>
                <TableCell>
                  <Button variant="destructive" size="sm">Exit</Button>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
```

### Theme System (Multi-Theme with Mode Detection)

```typescript
// lib/themes.ts
export type ThemeMode = 'light' | 'dark' | 'analyzer' | 'sandbox';
export type ThemeColor = 'zinc' | 'slate' | 'stone' | 'gray' | 'neutral' |
                         'red' | 'rose' | 'orange' | 'green' | 'blue' |
                         'yellow' | 'violet';

// Theme configuration supporting all shadcn themes + custom modes
export const themeConfig = {
  modes: {
    light: { label: 'Light', class: '' },
    dark: { label: 'Dark', class: 'dark' },
    analyzer: { label: 'Analyzer', class: 'analyzer' },  // Purple/violet tint
    sandbox: { label: 'Sandbox', class: 'sandbox' },    // Amber/orange tint
  },
  colors: [
    'zinc', 'slate', 'stone', 'gray', 'neutral',
    'red', 'rose', 'orange', 'green', 'blue', 'yellow', 'violet'
  ]
};
```

```typescript
// tailwind.config.ts
const config = {
  darkMode: ['class', '[data-mode="dark"]'],
  theme: {
    extend: {
      colors: {
        // Trading-specific colors (work in all themes)
        profit: {
          DEFAULT: 'hsl(var(--profit))',
          foreground: 'hsl(var(--profit-foreground))',
        },
        loss: {
          DEFAULT: 'hsl(var(--loss))',
          foreground: 'hsl(var(--loss-foreground))',
        },
        buy: {
          DEFAULT: 'hsl(var(--buy))',
          foreground: 'hsl(var(--buy-foreground))',
        },
        sell: {
          DEFAULT: 'hsl(var(--sell))',
          foreground: 'hsl(var(--sell-foreground))',
        },
      },
    },
  },
}
```

```css
/* styles/globals.css - Theme Variables */

/* Light Mode (Default) */
:root {
  --profit: 142 76% 36%;          /* Green */
  --profit-foreground: 0 0% 100%;
  --loss: 0 84% 60%;              /* Red */
  --loss-foreground: 0 0% 100%;
  --buy: 217 91% 60%;             /* Blue */
  --buy-foreground: 0 0% 100%;
  --sell: 25 95% 53%;             /* Orange */
  --sell-foreground: 0 0% 100%;
}

/* Dark Mode */
.dark {
  --profit: 142 69% 58%;
  --loss: 0 91% 71%;
  --buy: 217 91% 65%;
  --sell: 25 95% 63%;
}

/* Analyzer Mode - Purple/Violet tint to differentiate from live */
.analyzer {
  --background: 270 50% 98%;
  --foreground: 270 50% 10%;
  --card: 270 50% 100%;
  --primary: 270 70% 50%;
  --accent: 270 50% 95%;
  /* Visual indicator that this is NOT live trading */
}

.analyzer.dark {
  --background: 270 30% 8%;
  --foreground: 270 10% 95%;
  --card: 270 30% 12%;
  --primary: 270 70% 60%;
}

/* Sandbox Mode - Amber/Orange tint for paper trading */
.sandbox {
  --background: 45 50% 98%;
  --foreground: 45 50% 10%;
  --card: 45 50% 100%;
  --primary: 45 90% 50%;
  --accent: 45 50% 95%;
}

.sandbox.dark {
  --background: 45 30% 8%;
  --foreground: 45 10% 95%;
  --card: 45 30% 12%;
  --primary: 45 90% 55%;
}
```

```typescript
// stores/themeStore.ts
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface ThemeStore {
  mode: 'light' | 'dark';
  color: string;

  // Auto-detected based on current page/mode
  appMode: 'live' | 'analyzer' | 'sandbox';

  setMode: (mode: 'light' | 'dark') => void;
  setColor: (color: string) => void;
  setAppMode: (mode: 'live' | 'analyzer' | 'sandbox') => void;
}

export const useThemeStore = create<ThemeStore>()(
  persist(
    (set) => ({
      mode: 'light',  // Light by default
      color: 'zinc',
      appMode: 'live',

      setMode: (mode) => {
        set({ mode });
        document.documentElement.classList.toggle('dark', mode === 'dark');
      },
      setColor: (color) => {
        set({ color });
        document.documentElement.setAttribute('data-theme', color);
      },
      setAppMode: (appMode) => {
        set({ appMode });
        document.documentElement.classList.remove('analyzer', 'sandbox');
        if (appMode !== 'live') {
          document.documentElement.classList.add(appMode);
        }
      },
    }),
    { name: 'openalgo-theme' }
  )
);
```

### Mode Indicator Component
```typescript
// components/layout/ModeIndicator.tsx
import { useThemeStore } from '@/stores/themeStore';
import { Badge } from '@/components/ui/badge';
import { FlaskConical, TestTube2 } from 'lucide-react';

export function ModeIndicator() {
  const appMode = useThemeStore((s) => s.appMode);

  if (appMode === 'live') return null;

  return (
    <Badge
      variant="outline"
      className={cn(
        'animate-pulse',
        appMode === 'analyzer' && 'border-violet-500 text-violet-600 bg-violet-50',
        appMode === 'sandbox' && 'border-amber-500 text-amber-600 bg-amber-50'
      )}
    >
      {appMode === 'analyzer' ? (
        <>
          <FlaskConical className="w-3 h-3 mr-1" />
          ANALYZER MODE
        </>
      ) : (
        <>
          <TestTube2 className="w-3 h-3 mr-1" />
          SANDBOX MODE
        </>
      )}
    </Badge>
  );
}
```

---

## 5. API Integration Layer

### Type Definitions
```typescript
// types/api.ts
export interface ApiResponse<T> {
  status: 'success' | 'error';
  data?: T;
  message?: string;
}

// types/order.ts
export interface Order {
  orderId: string;
  symbol: string;
  exchange: 'NSE' | 'NFO' | 'BSE' | 'BFO' | 'MCX' | 'CDS';
  action: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  priceType: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M';
  product: 'MIS' | 'NRML' | 'CNC';
  status: 'PENDING' | 'COMPLETED' | 'REJECTED' | 'CANCELLED';
  timestamp: string;
}

export interface PlaceOrderRequest {
  apikey: string;
  strategy: string;
  symbol: string;
  exchange: string;
  action: 'BUY' | 'SELL';
  quantity: number;
  price_type: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M';
  product: 'MIS' | 'NRML' | 'CNC';
  price?: number;
  trigger_price?: number;
  disclosed_quantity?: number;
}

// types/position.ts
export interface Position {
  symbol: string;
  exchange: string;
  product: string;
  quantity: number;
  avgPrice: number;
  ltp: number;
  pnl: number;
  pnlPercent: number;
}

// types/quote.ts
export interface Quote {
  symbol: string;
  exchange: string;
  ltp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  bid: number;
  ask: number;
  timestamp: number;
}
```

### API Client Setup
```typescript
// api/client.ts
import axios from 'axios';
import { useAuthStore } from '@/stores/authStore';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

export const apiClient = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true,
});

// Request interceptor for API key
apiClient.interceptors.request.use((config) => {
  const apiKey = useAuthStore.getState().apiKey;
  if (apiKey) {
    config.headers['X-API-Key'] = apiKey;
  }
  return config;
});

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      useAuthStore.getState().logout();
    }
    return Promise.reject(error);
  }
);
```

### TanStack Query Setup
```typescript
// api/queries/positions.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../client';
import type { Position, ApiResponse } from '@/types';

export const positionKeys = {
  all: ['positions'] as const,
  list: () => [...positionKeys.all, 'list'] as const,
};

export function usePositions() {
  return useQuery({
    queryKey: positionKeys.list(),
    queryFn: async () => {
      const { data } = await apiClient.get<ApiResponse<Position[]>>('/positionbook');
      return data.data;
    },
    refetchInterval: 5000, // Auto-refresh every 5s
    staleTime: 1000,
  });
}

export function useClosePosition() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (params: { symbol: string; exchange: string; product: string }) => {
      const { data } = await apiClient.post('/closeposition', params);
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: positionKeys.all });
    },
  });
}
```

---

## 6. Flask Integration (Critical - Preserves `uv run app.py`)

### Auto-Build React on Startup

The key requirement is that `uv run app.py` continues to work seamlessly. React will be built automatically if needed.

#### 1. Updated `app.py` (Serve React from Flask)
```python
# app.py - Add at the TOP of the file (after imports)
import os
import subprocess
import sys
from pathlib import Path

# ============================================
# REACT FRONTEND AUTO-BUILD & SERVING
# ============================================

FRONTEND_DIR = Path(__file__).parent / 'frontend'
FRONTEND_DIST = FRONTEND_DIR / 'dist'

def ensure_frontend_built():
    """Auto-build React frontend if dist doesn't exist or source is newer."""
    if not FRONTEND_DIR.exists():
        print("⚠️  Frontend directory not found. Running in API-only mode.")
        return False

    package_json = FRONTEND_DIR / 'package.json'
    if not package_json.exists():
        print("⚠️  No package.json found. Running in API-only mode.")
        return False

    # Check if build is needed
    needs_build = False

    if not FRONTEND_DIST.exists():
        print("📦 Frontend build not found. Building...")
        needs_build = True
    else:
        # Check if source files are newer than build
        src_dir = FRONTEND_DIR / 'src'
        if src_dir.exists():
            src_mtime = max(f.stat().st_mtime for f in src_dir.rglob('*') if f.is_file())
            dist_mtime = FRONTEND_DIST.stat().st_mtime
            if src_mtime > dist_mtime:
                print("📦 Frontend source changed. Rebuilding...")
                needs_build = True

    if needs_build:
        try:
            # Check if node_modules exists
            node_modules = FRONTEND_DIR / 'node_modules'
            if not node_modules.exists():
                print("📥 Installing frontend dependencies...")
                subprocess.run(
                    ['npm', 'install'],
                    cwd=FRONTEND_DIR,
                    check=True,
                    capture_output=True
                )

            # Build frontend
            print("🔨 Building frontend...")
            result = subprocess.run(
                ['npm', 'run', 'build'],
                cwd=FRONTEND_DIR,
                check=True,
                capture_output=True,
                text=True
            )
            print("✅ Frontend build complete!")
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ Frontend build failed: {e.stderr}")
            print("⚠️  Running in API-only mode.")
            return False
        except FileNotFoundError:
            print("⚠️  Node.js not found. Running in API-only mode.")
            return False

    return True

# Build frontend on startup
FRONTEND_ENABLED = ensure_frontend_built()

# ... rest of existing app.py code ...
```

#### 2. React Static File Serving Blueprint
```python
# blueprints/react_frontend.py (NEW FILE)
"""
React Frontend Serving Blueprint
Serves the built React app for all non-API routes.
"""

import os
from pathlib import Path
from flask import Blueprint, send_from_directory, current_app

react_bp = Blueprint('react', __name__)

FRONTEND_DIST = Path(__file__).parent.parent / 'frontend' / 'dist'

@react_bp.route('/', defaults={'path': ''})
@react_bp.route('/<path:path>')
def serve_react(path):
    """
    Serve React app for all frontend routes.
    - Static files (JS, CSS, images) served directly
    - All other routes serve index.html (React Router handles routing)
    """
    if not FRONTEND_DIST.exists():
        return "Frontend not built. Run 'npm run build' in frontend/", 503

    # Try to serve static file first
    file_path = FRONTEND_DIST / path
    if path and file_path.exists() and file_path.is_file():
        return send_from_directory(FRONTEND_DIST, path)

    # Otherwise serve index.html (React Router will handle the route)
    return send_from_directory(FRONTEND_DIST, 'index.html')


# Asset routes with proper cache headers
@react_bp.route('/assets/<path:filename>')
def serve_assets(filename):
    """Serve static assets with long cache headers."""
    response = send_from_directory(FRONTEND_DIST / 'assets', filename)
    # Cache assets for 1 year (they have content hashes)
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response
```

#### 3. Register Blueprint in `app.py`
```python
# app.py - Add after other blueprint registrations

# Register React frontend (MUST BE LAST - catch-all route)
if FRONTEND_ENABLED:
    from blueprints.react_frontend import react_bp
    app.register_blueprint(react_bp)
    print("🚀 React frontend enabled at /")
else:
    # Fallback: Legacy Jinja2 templates (temporary during migration)
    print("📄 Legacy Jinja2 templates enabled")
```

#### 4. Route Priority Configuration
```python
# app.py - Ensure API routes take priority

# API routes are registered BEFORE React blueprint
# This ensures /api/* routes work correctly

# 1. Authentication blueprint
app.register_blueprint(auth_bp, url_prefix='/auth')

# 2. API v1 routes (Flask-RESTX)
api.init_app(app)  # Registers /api/v1/*

# 3. Other blueprints (dashboard, orders, etc. - DEPRECATED after migration)
# Keep for backward compatibility during migration, remove after

# 4. React frontend (LAST - catch-all for SPA routing)
if FRONTEND_ENABLED:
    from blueprints.react_frontend import react_bp
    app.register_blueprint(react_bp)
```

### Development Mode (Hot Reload)

For development, run Vite dev server separately for hot module replacement:

```bash
# Terminal 1: Flask backend
uv run app.py

# Terminal 2: Vite dev server (with proxy to Flask)
cd frontend && npm run dev
```

#### Vite Config for Development Proxy
```typescript
// frontend/vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // Proxy API requests to Flask
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
      // Proxy WebSocket
      '/socket.io': {
        target: 'http://localhost:5000',
        ws: true,
      },
      // Proxy auth routes
      '/auth': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router'],
          ui: ['@radix-ui/react-dialog', '@radix-ui/react-dropdown-menu'],
          charts: ['lightweight-charts', 'recharts'],
          state: ['zustand', '@tanstack/react-query'],
        },
      },
    },
  },
});
```

### Updated `start.sh`
```bash
#!/bin/bash
# start.sh - Updated for React frontend

set -e

echo "🚀 Starting OpenAlgo..."

# Check for Node.js (required for frontend build)
if ! command -v node &> /dev/null; then
    echo "⚠️  Node.js not found. Frontend features will be disabled."
    echo "   Install Node.js 20+ for full functionality."
fi

# Frontend build check is handled by app.py automatically
# No need to manually build here

# Existing ngrok setup (if any)
if [ -n "$NGROK_AUTH_TOKEN" ]; then
    echo "🌐 Setting up ngrok..."
    # ... existing ngrok code ...
fi

# Start Flask application
echo "🔥 Starting Flask server..."
exec python app.py
```

### CORS Update for Development
```python
# cors.py - Add Vite dev server origin
CORS_ALLOWED_ORIGINS = os.getenv(
    'CORS_ALLOWED_ORIGINS',
    'http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173'
)
```

### WebSocket Events (Already Exist - No Changes)
The existing Flask-SocketIO events work seamlessly:
- `order_update` - Order status changes
- `trade_update` - New trade executions
- `position_update` - Position changes
- `quote_update` - Market data updates
- `analyzer_update` - Analyzer mode events
- `strategy_log` - Strategy execution logs

---

## 7. Migration Phases

### Phase 1: Foundation Setup
**Goal**: Set up React project with all tooling, theme system, and authentication

- [ ] Initialize Vite 6 + React 19 + TypeScript project in `frontend/`
- [ ] Configure Tailwind CSS v4 + shadcn/ui
- [ ] Set up folder structure (components, features, hooks, stores, api, types)
- [ ] Configure path aliases (`@/` for src)
- [ ] Set up Biome for linting/formatting
- [ ] Implement theme system (Light default + Dark + Analyzer + Sandbox themes)
- [ ] Add all shadcn color themes (zinc, slate, stone, etc.)
- [ ] Configure API client (axios with interceptors)
- [ ] Set up TanStack Query provider with devtools
- [ ] Set up Zustand stores (auth, theme, settings)
- [ ] Create responsive base layout (Sidebar, Header, Main content)
- [ ] Implement authentication flow (login, 2FA, broker connection)
- [ ] Flask integration: Auto-build on `uv run app.py`
- [ ] Flask integration: React blueprint for serving SPA

### Phase 2: Core Trading UI (Priority #1)
**Goal**: Dashboard + Orders + Positions - The most used features

- [ ] **Dashboard Page**
  - [ ] Portfolio overview card (total value, day P&L)
  - [ ] Account funds summary
  - [ ] Quick stats (positions, orders, trades)
  - [ ] Recent activity feed
  - [ ] Connection status indicator

- [ ] **Positions Page**
  - [ ] Virtual scrolling table for 1000+ positions
  - [ ] Real-time LTP updates via WebSocket
  - [ ] P&L calculation (realized + unrealized)
  - [ ] Color-coded profit/loss
  - [ ] Exit position button with confirmation
  - [ ] Position filters (product, exchange)
  - [ ] Export to CSV

- [ ] **Orders Page**
  - [ ] Order book table (pending orders)
  - [ ] Trade book table (executed trades)
  - [ ] Order status badges
  - [ ] Modify order dialog
  - [ ] Cancel order with confirmation
  - [ ] Cancel all orders button
  - [ ] Order history tabs

- [ ] **Order Panel Component**
  - [ ] Buy/Sell toggle
  - [ ] Quantity input with lot size handling
  - [ ] Price input (for limit orders)
  - [ ] Order type selector (Market, Limit, SL, SL-M)
  - [ ] Product selector (MIS, NRML, CNC)
  - [ ] Place order mutation with optimistic UI
  - [ ] Order confirmation toast

### Phase 3: Holdings & Watchlist
**Goal**: Complete portfolio management features

- [ ] **Holdings Page**
  - [ ] Holdings table with virtual scrolling
  - [ ] Average cost, current value, P&L
  - [ ] Day change display
  - [ ] Holdings value chart (pie chart)

- [ ] **Watchlist Feature**
  - [ ] Multiple watchlist support
  - [ ] Symbol search with autocomplete
  - [ ] Real-time quote updates
  - [ ] Quick trade buttons
  - [ ] Drag-and-drop reordering
  - [ ] Watchlist persistence (localStorage + API)

- [ ] **Symbol Search**
  - [ ] Debounced search input
  - [ ] Autocomplete dropdown
  - [ ] Exchange filtering
  - [ ] Recent searches

### Phase 4: Charts & Market Data
**Goal**: Professional charting and market depth

- [ ] **TradingView Lightweight Charts Integration**
  - [ ] Candlestick chart component
  - [ ] Multiple timeframes (1m, 5m, 15m, 1h, 1D)
  - [ ] Volume bars
  - [ ] Real-time updates
  - [ ] Drawing tools (lines, fibonacci)
  - [ ] Technical indicators

- [ ] **Market Depth (Level 5)**
  - [ ] Bid/Ask ladder
  - [ ] Volume visualization
  - [ ] Real-time updates

- [ ] **Quotes Panel**
  - [ ] Full quote display
  - [ ] OHLC, volume, change
  - [ ] 52-week high/low

### Phase 5: Options Trading
**Goal**: Complete options trading interface

- [ ] **Option Chain Page**
  - [ ] Strike price grid
  - [ ] Call/Put columns
  - [ ] Greeks display (Delta, Gamma, Theta, Vega)
  - [ ] Expiry selector
  - [ ] ATM highlighting
  - [ ] Quick trade from chain

- [ ] **Option Greeks Calculator**
  - [ ] Input form (spot, strike, expiry, IV)
  - [ ] Greeks display
  - [ ] P&L payoff chart

- [ ] **Options Order Panel**
  - [ ] Strike selection
  - [ ] CE/PE toggle
  - [ ] Expiry dropdown
  - [ ] Multi-leg order support

### Phase 6: Strategy & Automation
**Goal**: Python strategy execution and management

- [ ] **Strategy Management Page**
  - [ ] Strategy list with status
  - [ ] Start/Stop controls
  - [ ] Monaco code editor
  - [ ] Environment variables (encrypted)
  - [ ] Schedule configuration
  - [ ] Strategy logs viewer (real-time)

- [x] **Sandbox/Analyzer Mode**
  - [x] Distinct theme (purple/violet tint)
  - [x] Mode indicator banner
  - [x] Mode toggle with backend sync

- [x] **Action Center** (Completed in Phase 7)
  - [x] Pending approval queue
  - [x] Approve/Reject buttons
  - [x] Bulk actions

### Phase 7: Logs, Monitoring & Profile ✓ COMPLETE
**Goal**: Logs landing page, monitoring dashboards, profile/theme customization, action center

- [x] **Logs Landing Page**
  - [x] LogsIndex.tsx with 6 grouped cards (like old HTML)
  - [x] Routes: /logs/live, /logs/sandbox, /logs/latency, /logs/traffic, /logs/security
  - [x] Documentation external link

- [x] **Monitoring Dashboard**
  - [x] SecurityDashboard.tsx - Failed logins, blocked IPs
  - [x] TrafficDashboard.tsx - Requests/min, API stats
  - [x] LatencyDashboard.tsx - Response times, slow endpoints
  - [x] Real-time data refresh with auto-refresh toggle

- [x] **Profile Page**
  - [x] Theme selector (light/dark mode toggle)
  - [x] Accent color selection (7 colors)
  - [x] Reset to default button
  - [x] Analyzer mode protection

- [x] **Action Center (Semi-Auto Mode)**
  - [x] Pending order queue management
  - [x] Approve/Reject/Delete individual orders
  - [x] Batch operations (Approve All, Reject All)
  - [x] Socket.IO real-time notifications
  - [x] Audio alerts for new queued orders

- [x] **Backend Updates**
  - [x] Analyzer mode toggle/sync endpoints
  - [x] Pending order management endpoints
  - [x] Security metrics endpoint
  - [x] Werkzeug error filter for dev server

### Phase 8: Mobile Responsiveness & Polish
**Goal**: Full responsive design and production readiness

- [ ] **Mobile Layout**
  - [ ] Bottom navigation for mobile
  - [ ] Collapsible sidebar
  - [ ] Touch-friendly buttons
  - [ ] Swipe gestures

- [ ] **Tablet Layout**
  - [ ] Optimized panel sizes
  - [ ] Side-by-side views

- [ ] **Performance Optimization**
  - [ ] Code splitting per route
  - [ ] Lazy loading components
  - [ ] Image optimization
  - [ ] Bundle analysis

- [ ] **Testing**
  - [ ] Unit tests (Vitest)
  - [ ] E2E tests (Playwright)
  - [ ] Accessibility audit (axe)

- [ ] **Production**
  - [ ] Docker build optimization
  - [ ] Error boundary components
  - [ ] Analytics integration
  - [ ] Documentation

### Phase 9: Cleanup & Deprecation
**Goal**: Remove legacy Jinja2 templates

- [ ] Verify all features migrated
- [ ] User acceptance testing
- [ ] Remove `templates/` directory
- [ ] Remove legacy static files
- [ ] Update documentation
- [ ] Release v2.0

---

## 8. Cross-Platform Deployment

### Supported Platforms
- **Docker** (Recommended for production)
- **Ubuntu/Debian Linux**
- **macOS (Intel & Apple Silicon)**
- **Windows (WSL2 recommended)**
- **Other Linux distributions**

### Prerequisites (All Platforms)
| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.11+ | Already required |
| Node.js | 20 LTS+ | For React build |
| npm | 10+ | Comes with Node.js |

### Platform-Specific Installation

#### Docker (All Platforms)
```dockerfile
# Dockerfile - Updated for React frontend
FROM python:3.12-slim AS base

# Install Node.js for frontend build
RUN apt-get update && apt-get install -y \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy frontend and build
COPY frontend/package*.json frontend/
RUN cd frontend && npm ci --production=false

COPY frontend/ frontend/
RUN cd frontend && npm run build

# Copy Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Set environment
ENV TZ=Asia/Kolkata
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python", "app.py"]
```

#### Ubuntu/Debian Linux
```bash
# Install Node.js 20 LTS
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Verify installation
node --version  # Should be v20.x.x
npm --version   # Should be 10.x.x

# Clone and setup
git clone https://github.com/your-repo/openalgo.git
cd openalgo

# Python dependencies (existing)
pip install -r requirements.txt

# Frontend will auto-build on first run
uv run app.py
```

#### macOS (Homebrew)
```bash
# Install Node.js via Homebrew
brew install node@20

# Or using nvm (recommended)
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
nvm install 20
nvm use 20

# Clone and setup
git clone https://github.com/your-repo/openalgo.git
cd openalgo

# Python dependencies
pip install -r requirements.txt

# Run (frontend auto-builds)
uv run app.py
```

#### Windows (WSL2 Recommended)
```powershell
# In WSL2 Ubuntu terminal
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Rest same as Ubuntu
```

### Graceful Degradation (No Node.js)
If Node.js is not installed, OpenAlgo will:
1. Print a warning message
2. Run in **API-only mode**
3. All REST API endpoints work normally
4. External apps (TradingView, Amibroker, etc.) continue to work
5. Only the web UI will be unavailable

```python
# app.py - Graceful handling
def ensure_frontend_built():
    try:
        # Check Node.js availability
        result = subprocess.run(['node', '--version'], capture_output=True)
        if result.returncode != 0:
            raise FileNotFoundError
    except FileNotFoundError:
        print("⚠️  Node.js not found. Running in API-only mode.")
        print("   Web UI disabled. API endpoints available at /api/v1/")
        print("   Install Node.js 20+ for web interface.")
        return False
    # ... rest of build logic
```

---

## 9. Development Setup Commands

```bash
# Navigate to openalgo directory
cd openalgo

# Create frontend directory
mkdir -p frontend
cd frontend

# Initialize Vite 6 + React 19 + TypeScript
npm create vite@latest . -- --template react-ts

# Install core dependencies
npm install react@19 react-dom@19
npm install react-router@7
npm install @tanstack/react-query@5
npm install zustand
npm install jotai
npm install socket.io-client
npm install axios
npm install zod

# Install UI dependencies
npm install tailwindcss@4 @tailwindcss/vite
npm install class-variance-authority clsx tailwind-merge
npm install lucide-react
npm install @radix-ui/react-slot

# Install shadcn/ui
npx shadcn@latest init

# Install additional shadcn components
npx shadcn@latest add button card input select tabs table dialog sheet toast resizable dropdown-menu avatar badge separator scroll-area command popover

# Install chart libraries
npm install recharts
npm install lightweight-charts

# Install table virtualization
npm install @tanstack/react-table @tanstack/react-virtual

# Install dev dependencies
npm install -D @types/react @types/react-dom
npm install -D typescript
npm install -D @biomejs/biome
npm install -D vitest @testing-library/react
```

---

## 9. Environment Variables

```env
# frontend/.env
VITE_API_URL=http://localhost:5000
VITE_WS_URL=ws://localhost:5000
VITE_APP_NAME=OpenAlgo
VITE_APP_VERSION=2.0.0
```

---

## 10. Docker Compose Update

```yaml
# docker-compose.yaml
version: '3.8'

services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "5000:5000"
    volumes:
      - ./db:/app/db
      - ./log:/app/log
      - ./keys:/app/keys
      - ./strategies:/app/strategies
    environment:
      - FLASK_ENV=production
      - TZ=Asia/Kolkata
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:80"
    depends_on:
      - backend
    environment:
      - VITE_API_URL=http://backend:5000
    restart: unless-stopped

# Optional: Nginx reverse proxy for production
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - backend
      - frontend
    restart: unless-stopped
```

---

## 11. Key Benefits of This Stack

| Benefit | Description |
|---------|-------------|
| **Type Safety** | Full TypeScript coverage eliminates runtime type errors |
| **Performance** | Virtual scrolling, optimistic updates, smart caching |
| **Developer Experience** | Hot module replacement, instant feedback loop |
| **Maintainability** | Feature-based architecture, clear separation |
| **Scalability** | Lazy loading, code splitting per route |
| **Real-time** | WebSocket integration with efficient state updates |
| **Accessibility** | shadcn/ui components are WCAG compliant |
| **Testing** | Vitest + React Testing Library + Playwright |
| **Security** | Latest React 19 with no known vulnerabilities |
| **Bundle Size** | Tree-shaking, minimal runtime overhead |

---

## 12. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Learning curve | Team training, comprehensive documentation |
| Migration bugs | Parallel running of old/new UI during transition |
| Performance regression | Lighthouse CI, bundle analysis in CI/CD |
| WebSocket compatibility | Keep Flask-SocketIO, proven integration |
| Data inconsistency | TanStack Query handles cache invalidation |

---

## Summary

### OpenAlgo v2.0.0.0 - Terminal Edition

This migration plan transforms OpenAlgo into a **professional-grade trading terminal** with:

| Feature | Description |
|---------|-------------|
| **Modern Stack** | React 19 + TypeScript + Vite 6 (latest, no vulnerabilities) |
| **Rich UI** | shadcn/ui + Tailwind CSS v4 (12+ color themes) |
| **State Management** | TanStack Query + Zustand (10x-100x performance) |
| **Theme System** | Light default + Dark mode + Analyzer/Sandbox themes |
| **Responsive** | Desktop + Tablet + Mobile (full responsive) |
| **Trading Terminal UX** | Resizable panels, real-time data, professional charts |
| **Cross-Platform** | Docker, Ubuntu, macOS, Windows (WSL2) |
| **Backward Compatible** | All API endpoints unchanged, `uv run app.py` works |
| **Graceful Degradation** | Works without Node.js (API-only mode) |

### What Changes
- New `frontend/` directory inside `openalgo/`
- React frontend served by Flask
- Auto-build on startup

### What Stays The Same
- All 30+ API endpoints (`/api/v1/*`)
- All 24+ broker integrations
- Database structure (SQLite)
- `.env` configuration
- Folder structure
- External app integrations (TradingView, Amibroker, etc.)
- `uv run app.py` startup command

### Performance Targets
| Metric | Current | Target |
|--------|---------|--------|
| Initial Load | ~3s | <1s |
| Route Navigation | ~500ms | <100ms |
| Table Render (1000 rows) | ~2s | <50ms |
| Real-time Updates | ~100ms | <16ms |
| Bundle Size | N/A | <500KB gzipped |

### Migration Phases Summary
1. **Foundation** ✓ - React setup, auth, base layout
2. **Core Trading** ✓ - Dashboard, Orders, Positions (Priority)
3. **Search & Symbol** ✓ - Token search, API playground
4. **Charts & Data** ✓ - TradingView charts, WebSocket, Sandbox
5. **Options** - Option chain, Greeks (Skipped - New Feature)
6. **Strategy** ✓ - Webhook, Python, Chartink strategies
7. **Logs & Monitoring** ✓ - Logs, monitoring dashboards, profile, action center
8. **Polish** - Mobile responsive, testing
9. **Cleanup** - Remove legacy templates

### Result
A world-class algo trading interface rivaling:
- Bloomberg Terminal
- Refinitiv Eikon
- Zerodha Kite Pro
- TradingView

Built for 60,000+ traders. Ready for scale.
