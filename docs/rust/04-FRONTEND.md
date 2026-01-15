# OpenAlgo Desktop - Frontend Design

**Version:** 1.0.0
**Date:** December 2024

---

## 1. Technology Stack

| Technology | Purpose |
|------------|---------|
| **Svelte 5** | UI framework (reactive, compiled) |
| **TypeScript** | Type safety |
| **Tailwind CSS** | Utility-first styling |
| **DaisyUI** | Component library |
| **Vite** | Build tool |
| **@tauri-apps/api** | Tauri IPC bridge |

---

## 2. Project Structure

```
src/
├── lib/
│   ├── components/           # Reusable UI components
│   │   ├── common/
│   │   │   ├── Button.svelte
│   │   │   ├── Input.svelte
│   │   │   ├── Modal.svelte
│   │   │   ├── Table.svelte
│   │   │   ├── Toast.svelte
│   │   │   └── Loading.svelte
│   │   ├── trading/
│   │   │   ├── OrderForm.svelte
│   │   │   ├── OrderBook.svelte
│   │   │   ├── PositionCard.svelte
│   │   │   ├── HoldingCard.svelte
│   │   │   ├── QuoteCard.svelte
│   │   │   └── DepthChart.svelte
│   │   ├── options/
│   │   │   ├── OptionChain.svelte
│   │   │   ├── GreeksDisplay.svelte
│   │   │   └── StrikeSelector.svelte
│   │   ├── charts/
│   │   │   ├── PriceChart.svelte
│   │   │   ├── PnLChart.svelte
│   │   │   └── MiniChart.svelte
│   │   └── layout/
│   │       ├── Sidebar.svelte
│   │       ├── Header.svelte
│   │       ├── Footer.svelte
│   │       └── TabBar.svelte
│   ├── stores/               # Svelte stores (state management)
│   │   ├── auth.ts
│   │   ├── broker.ts
│   │   ├── orders.ts
│   │   ├── positions.ts
│   │   ├── quotes.ts
│   │   ├── settings.ts
│   │   └── notifications.ts
│   ├── services/             # Tauri command wrappers
│   │   ├── authService.ts
│   │   ├── orderService.ts
│   │   ├── marketService.ts
│   │   ├── portfolioService.ts
│   │   └── settingsService.ts
│   ├── utils/
│   │   ├── formatters.ts     # Number, date formatting
│   │   ├── validators.ts     # Input validation
│   │   ├── constants.ts      # App constants
│   │   └── helpers.ts        # Utility functions
│   └── types/
│       ├── order.ts
│       ├── position.ts
│       ├── quote.ts
│       └── broker.ts
├── routes/                   # SvelteKit routes (pages)
│   ├── +layout.svelte
│   ├── +page.svelte          # Dashboard
│   ├── login/
│   │   └── +page.svelte
│   ├── broker/
│   │   └── +page.svelte
│   ├── orders/
│   │   └── +page.svelte
│   ├── positions/
│   │   └── +page.svelte
│   ├── holdings/
│   │   └── +page.svelte
│   ├── options/
│   │   └── +page.svelte
│   ├── strategies/
│   │   └── +page.svelte
│   ├── action-center/
│   │   └── +page.svelte
│   └── settings/
│       └── +page.svelte
├── app.html
├── app.css                   # Global styles + Tailwind imports
└── hooks.client.ts           # Client-side hooks
```

---

## 3. Component Specifications

### 3.1 Layout Components

#### `Sidebar.svelte`

```svelte
<script lang="ts">
  import { page } from '$app/stores';
  import { brokerStore } from '$lib/stores/broker';

  const menuItems = [
    { path: '/', label: 'Dashboard', icon: 'home' },
    { path: '/orders', label: 'Orders', icon: 'list' },
    { path: '/positions', label: 'Positions', icon: 'trending-up' },
    { path: '/holdings', label: 'Holdings', icon: 'briefcase' },
    { path: '/options', label: 'Options', icon: 'layers' },
    { path: '/strategies', label: 'Strategies', icon: 'zap' },
    { path: '/action-center', label: 'Action Center', icon: 'check-circle' },
    { path: '/settings', label: 'Settings', icon: 'settings' },
  ];
</script>

<aside class="w-64 bg-base-200 h-screen fixed left-0 top-0 flex flex-col">
  <!-- Logo -->
  <div class="p-4 border-b border-base-300">
    <h1 class="text-xl font-bold">OpenAlgo</h1>
    <p class="text-xs text-base-content/60">Desktop</p>
  </div>

  <!-- Broker Status -->
  <div class="p-4 border-b border-base-300">
    {#if $brokerStore.isConnected}
      <div class="flex items-center gap-2">
        <span class="w-2 h-2 rounded-full bg-success"></span>
        <span class="text-sm">{$brokerStore.broker}</span>
        <span class="text-xs text-base-content/60">{$brokerStore.clientId}</span>
      </div>
    {:else}
      <a href="/broker" class="btn btn-primary btn-sm w-full">
        Connect Broker
      </a>
    {/if}
  </div>

  <!-- Navigation -->
  <nav class="flex-1 p-4">
    <ul class="menu">
      {#each menuItems as item}
        <li>
          <a
            href={item.path}
            class:active={$page.url.pathname === item.path}
          >
            <Icon name={item.icon} />
            {item.label}
          </a>
        </li>
      {/each}
    </ul>
  </nav>

  <!-- User Info -->
  <div class="p-4 border-t border-base-300">
    <div class="flex items-center justify-between">
      <span class="text-sm">{$authStore.username}</span>
      <button onclick={logout} class="btn btn-ghost btn-xs">
        Logout
      </button>
    </div>
  </div>
</aside>
```

### 3.2 Trading Components

#### `OrderForm.svelte`

```svelte
<script lang="ts">
  import { createEventDispatcher } from 'svelte';
  import { placeOrder } from '$lib/services/orderService';
  import { quotesStore } from '$lib/stores/quotes';

  export let symbol: string = '';
  export let exchange: string = 'NSE';

  let action: 'BUY' | 'SELL' = 'BUY';
  let quantity: number = 1;
  let product: 'MIS' | 'CNC' | 'NRML' = 'MIS';
  let priceType: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M' = 'MARKET';
  let price: number | null = null;
  let triggerPrice: number | null = null;
  let isSubmitting = false;

  const dispatch = createEventDispatcher();

  $: quote = $quotesStore[`${exchange}:${symbol}`];
  $: isLimitOrder = priceType === 'LIMIT' || priceType === 'SL';
  $: isSLOrder = priceType === 'SL' || priceType === 'SL-M';

  async function handleSubmit() {
    if (isSubmitting) return;

    isSubmitting = true;
    try {
      const result = await placeOrder({
        symbol,
        exchange,
        action,
        quantity,
        product,
        priceType,
        price: isLimitOrder ? price : undefined,
        triggerPrice: isSLOrder ? triggerPrice : undefined,
      });

      dispatch('success', result);
    } catch (error) {
      dispatch('error', error);
    } finally {
      isSubmitting = false;
    }
  }
</script>

<form onsubmit={handleSubmit} class="card bg-base-100 shadow-lg">
  <div class="card-body">
    <h2 class="card-title">Place Order</h2>

    <!-- Symbol Display -->
    <div class="flex items-center justify-between mb-4">
      <div>
        <span class="text-lg font-bold">{symbol}</span>
        <span class="badge badge-outline ml-2">{exchange}</span>
      </div>
      {#if quote}
        <div class="text-right">
          <span class="text-xl font-mono">{quote.ltp.toFixed(2)}</span>
          <span class:text-success={quote.change >= 0} class:text-error={quote.change < 0}>
            ({quote.changePercent.toFixed(2)}%)
          </span>
        </div>
      {/if}
    </div>

    <!-- Action Toggle -->
    <div class="btn-group w-full mb-4">
      <button
        type="button"
        class="btn flex-1"
        class:btn-success={action === 'BUY'}
        onclick={() => action = 'BUY'}
      >
        BUY
      </button>
      <button
        type="button"
        class="btn flex-1"
        class:btn-error={action === 'SELL'}
        onclick={() => action = 'SELL'}
      >
        SELL
      </button>
    </div>

    <!-- Product Type -->
    <div class="form-control mb-4">
      <label class="label">
        <span class="label-text">Product</span>
      </label>
      <select bind:value={product} class="select select-bordered">
        <option value="MIS">MIS (Intraday)</option>
        <option value="CNC">CNC (Delivery)</option>
        <option value="NRML">NRML (F&O)</option>
      </select>
    </div>

    <!-- Quantity -->
    <div class="form-control mb-4">
      <label class="label">
        <span class="label-text">Quantity</span>
      </label>
      <input
        type="number"
        bind:value={quantity}
        min="1"
        class="input input-bordered"
        required
      />
    </div>

    <!-- Price Type -->
    <div class="form-control mb-4">
      <label class="label">
        <span class="label-text">Order Type</span>
      </label>
      <select bind:value={priceType} class="select select-bordered">
        <option value="MARKET">Market</option>
        <option value="LIMIT">Limit</option>
        <option value="SL">Stop Loss Limit</option>
        <option value="SL-M">Stop Loss Market</option>
      </select>
    </div>

    <!-- Price (for Limit orders) -->
    {#if isLimitOrder}
      <div class="form-control mb-4">
        <label class="label">
          <span class="label-text">Price</span>
        </label>
        <input
          type="number"
          bind:value={price}
          step="0.05"
          class="input input-bordered"
          required
        />
      </div>
    {/if}

    <!-- Trigger Price (for SL orders) -->
    {#if isSLOrder}
      <div class="form-control mb-4">
        <label class="label">
          <span class="label-text">Trigger Price</span>
        </label>
        <input
          type="number"
          bind:value={triggerPrice}
          step="0.05"
          class="input input-bordered"
          required
        />
      </div>
    {/if}

    <!-- Submit Button -->
    <button
      type="submit"
      class="btn w-full"
      class:btn-success={action === 'BUY'}
      class:btn-error={action === 'SELL'}
      class:loading={isSubmitting}
      disabled={isSubmitting}
    >
      {isSubmitting ? 'Placing...' : `${action} ${symbol}`}
    </button>
  </div>
</form>
```

#### `PositionCard.svelte`

```svelte
<script lang="ts">
  import type { Position } from '$lib/types/position';
  import { formatCurrency, formatPercent } from '$lib/utils/formatters';
  import { closePosition } from '$lib/services/orderService';

  export let position: Position;

  let isClosing = false;

  $: isLong = position.quantity > 0;
  $: isProfitable = position.pnl >= 0;

  async function handleClose() {
    if (isClosing) return;

    isClosing = true;
    try {
      await closePosition({
        symbol: position.symbol,
        exchange: position.exchange,
        product: position.product,
      });
    } finally {
      isClosing = false;
    }
  }
</script>

<div class="card bg-base-100 shadow">
  <div class="card-body p-4">
    <div class="flex items-start justify-between">
      <!-- Symbol Info -->
      <div>
        <h3 class="font-bold">{position.symbol}</h3>
        <div class="flex gap-2 mt-1">
          <span class="badge badge-sm">{position.exchange}</span>
          <span class="badge badge-sm badge-outline">{position.product}</span>
        </div>
      </div>

      <!-- P&L -->
      <div class="text-right">
        <div class:text-success={isProfitable} class:text-error={!isProfitable}>
          <span class="text-lg font-bold">{formatCurrency(position.pnl)}</span>
        </div>
        <div class="text-sm text-base-content/60">
          {formatPercent(position.pnlPercent)}
        </div>
      </div>
    </div>

    <!-- Position Details -->
    <div class="grid grid-cols-3 gap-4 mt-4 text-sm">
      <div>
        <div class="text-base-content/60">Qty</div>
        <div class:text-success={isLong} class:text-error={!isLong}>
          {position.quantity > 0 ? '+' : ''}{position.quantity}
        </div>
      </div>
      <div>
        <div class="text-base-content/60">Avg</div>
        <div>{position.averagePrice.toFixed(2)}</div>
      </div>
      <div>
        <div class="text-base-content/60">LTP</div>
        <div>{position.ltp.toFixed(2)}</div>
      </div>
    </div>

    <!-- Close Button -->
    <button
      onclick={handleClose}
      class="btn btn-outline btn-sm mt-4"
      class:loading={isClosing}
      disabled={isClosing}
    >
      {isClosing ? 'Closing...' : 'Close Position'}
    </button>
  </div>
</div>
```

### 3.3 Options Components

#### `OptionChain.svelte`

```svelte
<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { getOptionChain, subscribeQuotes } from '$lib/services/marketService';
  import type { OptionChain, OptionStrike } from '$lib/types/options';

  export let symbol: string;
  export let expiry: string;

  let chain: OptionChain | null = null;
  let loading = true;
  let selectedStrike: number | null = null;

  onMount(async () => {
    await loadChain();
  });

  async function loadChain() {
    loading = true;
    try {
      chain = await getOptionChain(symbol, expiry);

      // Subscribe to quote updates for all options
      const symbols = chain.strikes.flatMap(s => [
        s.call && { symbol: s.call.symbol, exchange: 'NFO', mode: 'LTP' },
        s.put && { symbol: s.put.symbol, exchange: 'NFO', mode: 'LTP' },
      ]).filter(Boolean);

      await subscribeQuotes(symbols);
    } finally {
      loading = false;
    }
  }

  function getStrikeClass(strike: number, spotPrice: number) {
    if (Math.abs(strike - spotPrice) < spotPrice * 0.01) {
      return 'bg-warning/20'; // ATM
    }
    return '';
  }
</script>

<div class="overflow-x-auto">
  {#if loading}
    <div class="flex justify-center p-8">
      <span class="loading loading-spinner loading-lg"></span>
    </div>
  {:else if chain}
    <!-- Spot Price Header -->
    <div class="text-center mb-4">
      <span class="text-lg">Spot:</span>
      <span class="text-2xl font-bold ml-2">{chain.spotPrice.toFixed(2)}</span>
    </div>

    <table class="table table-zebra w-full">
      <thead>
        <tr>
          <th colspan="5" class="text-center bg-success/20">CALLS</th>
          <th class="text-center">Strike</th>
          <th colspan="5" class="text-center bg-error/20">PUTS</th>
        </tr>
        <tr>
          <th>OI</th>
          <th>Volume</th>
          <th>IV</th>
          <th>LTP</th>
          <th>Delta</th>
          <th></th>
          <th>Delta</th>
          <th>LTP</th>
          <th>IV</th>
          <th>Volume</th>
          <th>OI</th>
        </tr>
      </thead>
      <tbody>
        {#each chain.strikes as strike}
          <tr class={getStrikeClass(strike.strikePrice, chain.spotPrice)}>
            <!-- Call Data -->
            {#if strike.call}
              <td>{(strike.call.oi / 1000).toFixed(0)}K</td>
              <td>{strike.call.volume.toLocaleString()}</td>
              <td>{strike.call.iv.toFixed(1)}%</td>
              <td class="font-mono">{strike.call.ltp.toFixed(2)}</td>
              <td>{strike.call.delta.toFixed(2)}</td>
            {:else}
              <td colspan="5">-</td>
            {/if}

            <!-- Strike Price -->
            <td class="font-bold text-center">{strike.strikePrice}</td>

            <!-- Put Data -->
            {#if strike.put}
              <td>{strike.put.delta.toFixed(2)}</td>
              <td class="font-mono">{strike.put.ltp.toFixed(2)}</td>
              <td>{strike.put.iv.toFixed(1)}%</td>
              <td>{strike.put.volume.toLocaleString()}</td>
              <td>{(strike.put.oi / 1000).toFixed(0)}K</td>
            {:else}
              <td colspan="5">-</td>
            {/if}
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</div>
```

---

## 4. State Management

### 4.1 Store Definitions

#### `stores/auth.ts`

```typescript
import { writable, derived } from 'svelte/store';
import { invoke } from '@tauri-apps/api/core';

interface AuthState {
  isAuthenticated: boolean;
  user: User | null;
  loading: boolean;
}

function createAuthStore() {
  const { subscribe, set, update } = writable<AuthState>({
    isAuthenticated: false,
    user: null,
    loading: true,
  });

  return {
    subscribe,

    async init() {
      try {
        const session = await invoke<Session | null>('get_session');
        if (session) {
          set({
            isAuthenticated: true,
            user: session.user,
            loading: false,
          });
        } else {
          set({ isAuthenticated: false, user: null, loading: false });
        }
      } catch {
        set({ isAuthenticated: false, user: null, loading: false });
      }
    },

    async login(username: string, password: string) {
      const response = await invoke<LoginResponse>('login', { username, password });
      set({
        isAuthenticated: true,
        user: response.user,
        loading: false,
      });
      return response;
    },

    async logout() {
      await invoke('logout');
      set({ isAuthenticated: false, user: null, loading: false });
    },
  };
}

export const authStore = createAuthStore();
```

#### `stores/quotes.ts`

```typescript
import { writable } from 'svelte/store';
import { listen } from '@tauri-apps/api/event';
import type { Quote } from '$lib/types/quote';

function createQuotesStore() {
  const { subscribe, update } = writable<Record<string, Quote>>({});

  // Set up event listeners
  async function init() {
    // Listen for all quote events
    await listen<Quote>('quote:*', (event) => {
      const quote = event.payload;
      const key = `${quote.exchange}:${quote.symbol}`;
      update(quotes => ({ ...quotes, [key]: quote }));
    });
  }

  return {
    subscribe,
    init,

    updateQuote(quote: Quote) {
      const key = `${quote.exchange}:${quote.symbol}`;
      update(quotes => ({ ...quotes, [key]: quote }));
    },

    getQuote(symbol: string, exchange: string): Quote | undefined {
      let quote: Quote | undefined;
      subscribe(quotes => {
        quote = quotes[`${exchange}:${symbol}`];
      })();
      return quote;
    },
  };
}

export const quotesStore = createQuotesStore();
```

#### `stores/positions.ts`

```typescript
import { writable, derived } from 'svelte/store';
import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import type { Position } from '$lib/types/position';

function createPositionsStore() {
  const { subscribe, set, update } = writable<Position[]>([]);

  return {
    subscribe,

    async refresh() {
      const positions = await invoke<Position[]>('get_positions');
      set(positions);
    },

    async init() {
      await this.refresh();

      // Listen for position updates
      await listen<Position>('position:updated', (event) => {
        update(positions => {
          const idx = positions.findIndex(
            p => p.symbol === event.payload.symbol &&
                 p.exchange === event.payload.exchange
          );
          if (idx >= 0) {
            positions[idx] = event.payload;
          } else {
            positions.push(event.payload);
          }
          return [...positions];
        });
      });

      await listen<{ symbol: string; exchange: string }>('position:closed', (event) => {
        update(positions =>
          positions.filter(
            p => !(p.symbol === event.payload.symbol && p.exchange === event.payload.exchange)
          )
        );
      });
    },
  };
}

export const positionsStore = createPositionsStore();

// Derived stores
export const totalPnL = derived(positionsStore, $positions =>
  $positions.reduce((sum, p) => sum + p.pnl, 0)
);

export const openPositionsCount = derived(positionsStore, $positions =>
  $positions.filter(p => p.quantity !== 0).length
);
```

---

## 5. Pages

### 5.1 Dashboard (`routes/+page.svelte`)

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { positionsStore, totalPnL, openPositionsCount } from '$lib/stores/positions';
  import { ordersStore } from '$lib/stores/orders';
  import { brokerStore } from '$lib/stores/broker';
  import PositionCard from '$lib/components/trading/PositionCard.svelte';
  import OrderBook from '$lib/components/trading/OrderBook.svelte';
  import PnLChart from '$lib/components/charts/PnLChart.svelte';
  import { formatCurrency } from '$lib/utils/formatters';

  onMount(() => {
    positionsStore.refresh();
    ordersStore.refresh();
  });
</script>

<svelte:head>
  <title>Dashboard | OpenAlgo</title>
</svelte:head>

<div class="p-6">
  <h1 class="text-2xl font-bold mb-6">Dashboard</h1>

  <!-- Stats Cards -->
  <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
    <div class="stat bg-base-100 rounded-lg shadow">
      <div class="stat-title">Total P&L</div>
      <div class="stat-value" class:text-success={$totalPnL >= 0} class:text-error={$totalPnL < 0}>
        {formatCurrency($totalPnL)}
      </div>
      <div class="stat-desc">Today</div>
    </div>

    <div class="stat bg-base-100 rounded-lg shadow">
      <div class="stat-title">Open Positions</div>
      <div class="stat-value">{$openPositionsCount}</div>
      <div class="stat-desc">Active</div>
    </div>

    <div class="stat bg-base-100 rounded-lg shadow">
      <div class="stat-title">Today's Orders</div>
      <div class="stat-value">{$ordersStore.length}</div>
      <div class="stat-desc">Placed</div>
    </div>

    <div class="stat bg-base-100 rounded-lg shadow">
      <div class="stat-title">Broker</div>
      <div class="stat-value text-lg">{$brokerStore.broker || '-'}</div>
      <div class="stat-desc" class:text-success={$brokerStore.isConnected}>
        {$brokerStore.isConnected ? 'Connected' : 'Disconnected'}
      </div>
    </div>
  </div>

  <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
    <!-- Positions -->
    <div>
      <h2 class="text-xl font-semibold mb-4">Open Positions</h2>
      <div class="space-y-3">
        {#each $positionsStore.filter(p => p.quantity !== 0) as position}
          <PositionCard {position} />
        {:else}
          <div class="text-center text-base-content/60 py-8">
            No open positions
          </div>
        {/each}
      </div>
    </div>

    <!-- Recent Orders -->
    <div>
      <h2 class="text-xl font-semibold mb-4">Recent Orders</h2>
      <OrderBook orders={$ordersStore.slice(0, 10)} compact />
    </div>
  </div>

  <!-- P&L Chart -->
  <div class="mt-6">
    <h2 class="text-xl font-semibold mb-4">P&L Timeline</h2>
    <div class="bg-base-100 rounded-lg shadow p-4">
      <PnLChart />
    </div>
  </div>
</div>
```

---

## 6. Styling

### 6.1 Tailwind Configuration (`tailwind.config.js`)

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [require('daisyui')],
  daisyui: {
    themes: [
      {
        openalgo: {
          primary: '#3b82f6',
          secondary: '#8b5cf6',
          accent: '#06b6d4',
          neutral: '#1f2937',
          'base-100': '#111827',
          'base-200': '#1f2937',
          'base-300': '#374151',
          info: '#3b82f6',
          success: '#22c55e',
          warning: '#f59e0b',
          error: '#ef4444',
        },
      },
      'light',
      'dark',
    ],
    darkTheme: 'openalgo',
  },
};
```

### 6.2 Global Styles (`app.css`)

```css
@import 'tailwindcss/base';
@import 'tailwindcss/components';
@import 'tailwindcss/utilities';

@layer base {
  :root {
    --animation-duration: 150ms;
  }

  body {
    @apply bg-base-100 text-base-content;
    font-feature-settings: 'cv02', 'cv03', 'cv04', 'cv11';
  }

  /* Scrollbar styling */
  ::-webkit-scrollbar {
    @apply w-2 h-2;
  }

  ::-webkit-scrollbar-track {
    @apply bg-base-200;
  }

  ::-webkit-scrollbar-thumb {
    @apply bg-base-300 rounded-full;
  }

  ::-webkit-scrollbar-thumb:hover {
    @apply bg-base-content/30;
  }
}

@layer components {
  /* Price display */
  .price-up {
    @apply text-success;
  }

  .price-down {
    @apply text-error;
  }

  /* Flashing animation for price changes */
  .flash-green {
    animation: flash-green var(--animation-duration) ease-out;
  }

  .flash-red {
    animation: flash-red var(--animation-duration) ease-out;
  }

  @keyframes flash-green {
    0% { @apply bg-success/30; }
    100% { @apply bg-transparent; }
  }

  @keyframes flash-red {
    0% { @apply bg-error/30; }
    100% { @apply bg-transparent; }
  }

  /* Order status badges */
  .status-pending { @apply badge-warning; }
  .status-complete { @apply badge-success; }
  .status-cancelled { @apply badge-neutral; }
  .status-rejected { @apply badge-error; }
}
```

---

## 7. Responsive Design

### 7.1 Breakpoints

| Breakpoint | Width | Usage |
|------------|-------|-------|
| `sm` | 640px | Mobile landscape |
| `md` | 768px | Tablet |
| `lg` | 1024px | Desktop |
| `xl` | 1280px | Large desktop |
| `2xl` | 1536px | Wide screens |

### 7.2 Layout Adaptations

```svelte
<!-- Responsive sidebar -->
<div class="lg:ml-64">
  <!-- Sidebar hidden on mobile, shown on desktop -->
  <aside class="hidden lg:block fixed left-0 top-0 w-64 h-screen">
    <Sidebar />
  </aside>

  <!-- Mobile header with hamburger menu -->
  <header class="lg:hidden sticky top-0 z-50 bg-base-100 border-b">
    <MobileHeader />
  </header>

  <!-- Main content -->
  <main class="min-h-screen">
    <slot />
  </main>
</div>
```

---

## Document References

- [00-PRODUCT-DESIGN.md](./00-PRODUCT-DESIGN.md) - Product overview
- [01-ARCHITECTURE.md](./01-ARCHITECTURE.md) - System architecture
- [02-DATABASE.md](./02-DATABASE.md) - Database schema
- [03-TAURI-COMMANDS.md](./03-TAURI-COMMANDS.md) - Command reference
- [05-BROKER-INTEGRATION.md](./05-BROKER-INTEGRATION.md) - Broker patterns
- [06-ROADMAP.md](./06-ROADMAP.md) - Implementation plan

---

*Last updated: December 2024*
