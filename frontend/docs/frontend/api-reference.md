# API Reference

This document covers the API modules, stores, and hooks used in the OpenAlgo frontend.

## API Modules

All API modules are located in `src/api/` and follow a consistent pattern.

### Authentication API

```tsx
// src/api/auth.ts
import { authApi } from '@/api/auth'

// Login
await authApi.login(username, password)

// Logout
await authApi.logout()

// Get session status
const session = await authApi.getSessionStatus()
// Returns: { status, logged_in, authenticated, broker, username }

// Check if setup is needed
const setup = await authApi.checkSetup()
// Returns: { needs_setup: boolean }

// Reset password
await authApi.resetPassword(currentPassword, newPassword)
```

### Broker API

```tsx
// src/api/broker.ts
import { brokerApi } from '@/api/broker'

// Get available brokers
const brokers = await brokerApi.getBrokers()
// Returns: string[] e.g., ['angel', 'zerodha', 'fyers']

// Login to broker
await brokerApi.loginBroker(broker, credentials)

// Logout from broker
await brokerApi.logoutBroker()

// Get broker status
const status = await brokerApi.getBrokerStatus()
```

### Orders API

```tsx
// src/api/orders.ts
import { ordersApi } from '@/api/orders'

// Get order book
const orders = await ordersApi.getOrderBook()

// Get trade book
const trades = await ordersApi.getTradeBook()

// Get positions
const positions = await ordersApi.getPositions()

// Get holdings
const holdings = await ordersApi.getHoldings()

// Place order
await ordersApi.placeOrder({
  symbol: 'RELIANCE',
  exchange: 'NSE',
  action: 'BUY',
  quantity: 1,
  product: 'MIS',
  pricetype: 'MARKET',
})

// Cancel order
await ordersApi.cancelOrder(orderId)

// Modify order
await ordersApi.modifyOrder(orderId, modifications)
```

### Strategy API

```tsx
// src/api/strategy.ts
import { strategyApi } from '@/api/strategy'

// Get all strategies
const strategies = await strategyApi.getStrategies()

// Get single strategy
const strategy = await strategyApi.getStrategy(strategyId)

// Create strategy
const newStrategy = await strategyApi.createStrategy({
  name: 'My Strategy',
  description: 'Strategy description',
})

// Update strategy
await strategyApi.updateStrategy(strategyId, updates)

// Delete strategy
await strategyApi.deleteStrategy(strategyId)

// Get webhook URL
const webhookUrl = strategyApi.getWebhookUrl(webhookId)

// Configure symbols
await strategyApi.configureSymbols(strategyId, symbols)
```

### Chartink API

```tsx
// src/api/chartink.ts
import { chartinkApi } from '@/api/chartink'

// Get all Chartink strategies
const strategies = await chartinkApi.getStrategies()

// Get single strategy
const strategy = await chartinkApi.getStrategy(strategyId)

// Create Chartink strategy
const newStrategy = await chartinkApi.createStrategy({
  name: 'Chartink Strategy',
  is_intraday: true,
  start_time: '09:15',
  end_time: '15:15',
})

// Update strategy
await chartinkApi.updateStrategy(strategyId, updates)

// Delete strategy
await chartinkApi.deleteStrategy(strategyId)

// Get webhook URL
const webhookUrl = chartinkApi.getWebhookUrl(webhookId)
```

### Python Strategy API

```tsx
// src/api/pythonStrategy.ts
import { pythonStrategyApi } from '@/api/pythonStrategy'

// Get all Python strategies
const strategies = await pythonStrategyApi.getStrategies()

// Get strategy with code
const strategy = await pythonStrategyApi.getStrategy(strategyId)

// Create strategy
const newStrategy = await pythonStrategyApi.createStrategy({
  name: 'My Python Strategy',
  code: 'def execute(): pass',
})

// Update strategy code
await pythonStrategyApi.updateStrategy(strategyId, { code: newCode })

// Start strategy
await pythonStrategyApi.startStrategy(strategyId)

// Stop strategy
await pythonStrategyApi.stopStrategy(strategyId)

// Get logs
const logs = await pythonStrategyApi.getLogs(strategyId)
```

### Search API

```tsx
// src/api/search.ts
import { searchApi } from '@/api/search'

// Search symbols
const results = await searchApi.search(query, exchange)
// Returns: { symbol, name, exchange, token }[]

// Get token for symbol
const token = await searchApi.getToken(symbol, exchange)
```

### Telegram API

```tsx
// src/api/telegram.ts
import { telegramApi } from '@/api/telegram'

// Get config
const config = await telegramApi.getConfig()

// Update config
await telegramApi.updateConfig({ bot_token, chat_id })

// Get users
const users = await telegramApi.getUsers()

// Get analytics
const analytics = await telegramApi.getAnalytics()
```

### Admin API

```tsx
// src/api/admin.ts
import { adminApi } from '@/api/admin'

// Get freeze quantities
const freezeQty = await adminApi.getFreezeQty()

// Update freeze quantities
await adminApi.updateFreezeQty(data)

// Get holidays
const holidays = await adminApi.getHolidays()

// Get market timings
const timings = await adminApi.getMarketTimings()
```

## State Stores (Zustand)

### Auth Store

Manages authentication state.

```tsx
// src/stores/authStore.ts
import { useAuthStore } from '@/stores/authStore'

// Access state
const { user, isAuthenticated } = useAuthStore()

// Actions
const { login, logout, setUser } = useAuthStore()

// Login
login(username, broker)

// Logout
logout()

// Check auth
if (isAuthenticated) {
  // User is logged in
}
```

**State Shape:**
```tsx
interface AuthState {
  user: {
    username: string
    broker: string
  } | null
  isAuthenticated: boolean
  login: (username: string, broker: string) => void
  logout: () => void
  setUser: (user: User | null) => void
}
```

### Theme Store

Manages theme and app mode.

```tsx
// src/stores/themeStore.ts
import { useThemeStore } from '@/stores/themeStore'

// Access state
const { mode, appMode } = useThemeStore()

// Actions
const { toggleMode, toggleAppMode, setMode } = useThemeStore()

// Toggle light/dark
toggleMode()

// Toggle live/analyzer mode
const result = await toggleAppMode()
if (result.success) {
  // Mode toggled
}

// Set specific mode
setMode('dark')
```

**State Shape:**
```tsx
interface ThemeState {
  mode: 'light' | 'dark'
  appMode: 'live' | 'analyzer'
  isTogglingMode: boolean
  toggleMode: () => void
  toggleAppMode: () => Promise<{ success: boolean; message?: string }>
  setMode: (mode: 'light' | 'dark') => void
  setAppMode: (mode: 'live' | 'analyzer') => void
}
```

## Custom Hooks

### useAuth

Authentication hook with loading state.

```tsx
import { useAuth } from '@/hooks/useAuth'

function MyComponent() {
  const { user, isLoading, isAuthenticated, login, logout } = useAuth()

  if (isLoading) return <PageLoader />
  if (!isAuthenticated) return <Navigate to="/login" />

  return <div>Welcome, {user.username}</div>
}
```

### useLocalStorage

Persist state to localStorage.

```tsx
import { useLocalStorage } from '@/hooks/useLocalStorage'

function MyComponent() {
  const [value, setValue] = useLocalStorage('my-key', defaultValue)

  return (
    <input
      value={value}
      onChange={(e) => setValue(e.target.value)}
    />
  )
}
```

### useMediaQuery

Responsive breakpoint detection.

```tsx
import { useMediaQuery } from '@/hooks/useMediaQuery'

function MyComponent() {
  const isMobile = useMediaQuery('(max-width: 768px)')

  return isMobile ? <MobileView /> : <DesktopView />
}
```

### useDebounce

Debounce value changes.

```tsx
import { useDebounce } from '@/hooks/useDebounce'

function SearchComponent() {
  const [query, setQuery] = useState('')
  const debouncedQuery = useDebounce(query, 300)

  useEffect(() => {
    if (debouncedQuery) {
      performSearch(debouncedQuery)
    }
  }, [debouncedQuery])

  return <input value={query} onChange={(e) => setQuery(e.target.value)} />
}
```

## TanStack Query Patterns

### Basic Query

```tsx
import { useQuery } from '@tanstack/react-query'

function OrderBook() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['orderbook'],
    queryFn: () => ordersApi.getOrderBook(),
    refetchInterval: 5000, // Auto-refresh every 5s
  })

  if (isLoading) return <Skeleton />
  if (error) return <ErrorAlert error={error} />

  return <OrderTable orders={data} />
}
```

### Mutation

```tsx
import { useMutation, useQueryClient } from '@tanstack/react-query'

function PlaceOrderForm() {
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: (order) => ordersApi.placeOrder(order),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['orderbook'] })
      toast.success('Order placed successfully')
    },
    onError: (error) => {
      toast.error(error.message)
    },
  })

  const handleSubmit = (data) => {
    mutation.mutate(data)
  }

  return (
    <form onSubmit={handleSubmit}>
      {/* Form fields */}
      <Button type="submit" disabled={mutation.isPending}>
        {mutation.isPending ? 'Placing...' : 'Place Order'}
      </Button>
    </form>
  )
}
```

### Dependent Queries

```tsx
function StrategyDetails({ strategyId }) {
  // First query
  const strategyQuery = useQuery({
    queryKey: ['strategy', strategyId],
    queryFn: () => strategyApi.getStrategy(strategyId),
  })

  // Dependent query
  const symbolsQuery = useQuery({
    queryKey: ['strategy-symbols', strategyId],
    queryFn: () => strategyApi.getSymbols(strategyId),
    enabled: !!strategyQuery.data, // Only run when strategy is loaded
  })

  // ...
}
```

### Optimistic Updates

```tsx
const mutation = useMutation({
  mutationFn: updateTodo,
  onMutate: async (newTodo) => {
    // Cancel outgoing refetches
    await queryClient.cancelQueries({ queryKey: ['todos'] })

    // Snapshot previous value
    const previousTodos = queryClient.getQueryData(['todos'])

    // Optimistically update
    queryClient.setQueryData(['todos'], (old) =>
      old.map((todo) => (todo.id === newTodo.id ? newTodo : todo))
    )

    return { previousTodos }
  },
  onError: (err, newTodo, context) => {
    // Rollback on error
    queryClient.setQueryData(['todos'], context.previousTodos)
  },
  onSettled: () => {
    // Always refetch after error or success
    queryClient.invalidateQueries({ queryKey: ['todos'] })
  },
})
```

## WebSocket Integration

### Socket.IO Connection

```tsx
import { io } from 'socket.io-client'

// Connect
const socket = io('/', {
  path: '/socket.io',
  transports: ['websocket', 'polling'],
})

// Listen for events
socket.on('connect', () => {
  console.log('Connected')
})

socket.on('order_update', (data) => {
  // Handle order update
})

socket.on('position_update', (data) => {
  // Handle position update
})

// Disconnect
socket.disconnect()
```

### Real-time Hook Pattern

```tsx
function useRealTimeOrders() {
  const queryClient = useQueryClient()

  useEffect(() => {
    const socket = io('/')

    socket.on('order_update', (order) => {
      queryClient.setQueryData(['orderbook'], (old) => {
        // Update order in cache
        return old.map((o) => (o.id === order.id ? order : o))
      })
    })

    return () => {
      socket.disconnect()
    }
  }, [queryClient])
}
```

## Type Definitions

### Common Types

```tsx
// src/types/common.ts

interface ApiResponse<T> {
  status: 'success' | 'error'
  data?: T
  message?: string
}

interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  pageSize: number
}
```

### Order Types

```tsx
// src/types/orders.ts

interface Order {
  id: string
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  price: number
  product: 'MIS' | 'NRML' | 'CNC'
  pricetype: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
  status: 'PENDING' | 'OPEN' | 'COMPLETE' | 'CANCELLED' | 'REJECTED'
  timestamp: string
}

interface Position {
  symbol: string
  exchange: string
  quantity: number
  averagePrice: number
  ltp: number
  pnl: number
  product: string
}
```

### Strategy Types

```tsx
// src/types/strategy.ts

interface Strategy {
  id: string
  name: string
  description?: string
  webhook_id: string
  is_active: boolean
  created_at: string
  updated_at: string
}

interface ChartinkStrategy extends Strategy {
  is_intraday: boolean
  start_time?: string
  end_time?: string
  squareoff_time?: string
}
```

## Error Handling

### API Error Pattern

```tsx
class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function fetchWithError(url: string, options?: RequestInit) {
  const response = await fetch(url, {
    ...options,
    credentials: 'include',
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new ApiError(
      error.message || 'Request failed',
      response.status,
      error.code
    )
  }

  return response.json()
}
```

### Error Boundary

```tsx
import { ErrorBoundary } from 'react-error-boundary'

function ErrorFallback({ error, resetErrorBoundary }) {
  return (
    <Alert variant="destructive">
      <AlertTitle>Something went wrong</AlertTitle>
      <AlertDescription>{error.message}</AlertDescription>
      <Button onClick={resetErrorBoundary}>Try again</Button>
    </Alert>
  )
}

// Usage
<ErrorBoundary FallbackComponent={ErrorFallback}>
  <MyComponent />
</ErrorBoundary>
```
