# OpenAlgo Theme Implementation Guide

## Quick Start

This guide provides step-by-step instructions for implementing the new professional trading terminal theme for OpenAlgo.

## Prerequisites

- Node.js 16+ installed
- Python 3.8+ environment
- Access to modify Flask templates and static files
- Understanding of Tailwind CSS and DaisyUI

## Step 1: Update Tailwind Configuration

### 1.1 Install Required Packages

```bash
npm install -D @tailwindcss/forms @tailwindcss/typography
npm install inter-ui @fontsource/jetbrains-mono @fontsource/roboto-mono
```

### 1.2 Update tailwind.config.js

```javascript
/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/**/*.js",
  ],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        // Trading specific colors
        'trade': {
          'buy': '#10B981',
          'sell': '#EF4444',
          'primary': '#1E40AF',
          'secondary': '#64748B',
        },
        // Professional theme colors
        'pro': {
          50: '#F8FAFC',
          100: '#F1F5F9',
          200: '#E2E8F0',
          300: '#CBD5E1',
          400: '#94A3B8',
          500: '#64748B',
          600: '#475569',
          700: '#334155',
          800: '#1E293B',
          900: '#0F172A',
          950: '#020617',
        }
      },
      fontFamily: {
        'sans': ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        'mono': ['JetBrains Mono', 'monospace'],
        'data': ['Roboto Mono', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '0.75rem' }],
        'xs': ['0.75rem', { lineHeight: '1rem' }],
        'sm': ['0.875rem', { lineHeight: '1.25rem' }],
        'base': ['1rem', { lineHeight: '1.5rem' }],
      },
      height: {
        'navbar': '44px',
        'row': '32px',
      },
      width: {
        'sidebar': '240px',
        'sidebar-collapsed': '60px',
        'order-widget': '280px',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'slide-up': 'slideUp 0.2s ease-out',
        'slide-down': 'slideDown 0.2s ease-out',
        'fade-in': 'fadeIn 0.15s ease-in',
        'price-update': 'priceFlash 0.3s ease-out',
      },
      keyframes: {
        slideUp: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        slideDown: {
          '0%': { transform: 'translateY(-10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        priceFlash: {
          '0%': { backgroundColor: 'transparent' },
          '50%': { backgroundColor: 'rgba(34, 197, 94, 0.2)' },
          '100%': { backgroundColor: 'transparent' },
        },
      },
      gridTemplateColumns: {
        'trading-layout': '240px 1fr 280px',
        'trading-compact': '60px 1fr 280px',
      },
    },
  },
  daisyui: {
    themes: [
      {
        professional: {
          "primary": "#1E40AF",
          "secondary": "#64748B",
          "accent": "#F59E0B",
          "neutral": "#1F2937",
          "base-100": "#FFFFFF",
          "base-200": "#F9FAFB",
          "base-300": "#F3F4F6",
          "info": "#0891B2",
          "success": "#10B981",
          "warning": "#F59E0B",
          "error": "#EF4444",
        },
        dark_professional: {
          "primary": "#3B82F6",
          "secondary": "#64748B",
          "accent": "#FBBF24",
          "neutral": "#E5E7EB",
          "base-100": "#0A0A0A",
          "base-200": "#171717",
          "base-300": "#262626",
          "info": "#06B6D4",
          "success": "#34D399",
          "warning": "#FBBF24",
          "error": "#F87171",
        },
        analytics: {
          "primary": "#059669",
          "secondary": "#10B981",
          "accent": "#84CC16",
          "neutral": "#065F46",
          "base-100": "#F0FDF4",
          "base-200": "#FFFFFF",
          "base-300": "#ECFDF5",
          "info": "#06B6D4",
          "success": "#34D399",
          "warning": "#FCD34D",
          "error": "#F87171",
        }
      }
    ],
    darkTheme: "dark_professional",
    base: true,
    styled: true,
    utils: true,
    prefix: "",
    logs: false,
  },
  plugins: [
    require("daisyui"),
    require('@tailwindcss/forms')({
      strategy: 'class',
    }),
    require('@tailwindcss/typography'),
  ]
}
```

## Step 2: Create New CSS Structure

### 2.1 Create Theme Variables CSS

Create `static/css/theme/variables.css`:

```css
/* Root Theme Variables */
:root {
  /* Colors */
  --color-buy: 34 197 94;     /* green-500 */
  --color-sell: 239 68 68;    /* red-500 */
  --color-primary: 30 64 175; /* blue-800 */

  /* Spacing */
  --space-navbar: 44px;
  --space-row: 32px;

  /* Transitions */
  --transition-fast: 150ms ease;
  --transition-normal: 200ms ease;
  --transition-slow: 300ms ease;

  /* Z-Index */
  --z-dropdown: 1000;
  --z-modal: 2000;
  --z-tooltip: 3000;
  --z-notification: 4000;
}

/* Professional Light Theme */
[data-theme="professional"] {
  --bg-primary: 255 255 255;
  --bg-secondary: 249 250 251;
  --bg-tertiary: 243 244 246;

  --text-primary: 17 24 39;
  --text-secondary: 75 85 99;
  --text-muted: 156 163 175;

  --border-default: 229 231 235;
  --border-strong: 209 213 219;
}

/* Professional Dark Theme */
[data-theme="dark_professional"] {
  --bg-primary: 10 10 10;
  --bg-secondary: 23 23 23;
  --bg-tertiary: 38 38 38;

  --text-primary: 249 250 251;
  --text-secondary: 209 213 219;
  --text-muted: 107 114 128;

  --border-default: 64 64 64;
  --border-strong: 82 82 82;
}

/* Analytics Theme */
[data-theme="analytics"] {
  --bg-primary: 240 253 244;
  --bg-secondary: 255 255 255;
  --bg-tertiary: 236 253 245;

  --text-primary: 6 78 59;
  --text-secondary: 4 120 87;
  --text-muted: 107 114 128;

  --border-default: 187 247 208;
  --border-strong: 134 239 172;
}
```

### 2.2 Create Component Styles

Create `static/css/components/navbar.css`:

```css
/* Professional Navigation Bar */
.navbar-pro {
  @apply fixed top-0 left-0 right-0 z-50;
  height: var(--space-navbar);
  background: rgb(var(--bg-primary));
  border-bottom: 1px solid rgb(var(--border-default));
}

.navbar-brand {
  @apply flex items-center gap-2 px-4 h-full;
}

.navbar-nav {
  @apply flex items-center h-full;
}

.nav-item {
  @apply relative flex items-center h-full px-4 text-sm font-medium;
  color: rgb(var(--text-secondary));
  transition: var(--transition-fast);
}

.nav-item:hover {
  color: rgb(var(--text-primary));
  background: rgb(var(--bg-secondary));
}

.nav-item.active {
  color: rgb(var(--color-primary));
}

.nav-item.active::after {
  content: '';
  @apply absolute bottom-0 left-0 right-0 h-0.5;
  background: rgb(var(--color-primary));
}

/* Market Ticker */
.market-ticker {
  @apply flex items-center gap-4 px-4 text-xs;
  font-family: var(--font-mono);
}

.ticker-item {
  @apply flex items-center gap-2;
}

.ticker-value {
  @apply font-semibold;
}

.ticker-change.positive {
  color: rgb(var(--color-buy));
}

.ticker-change.negative {
  color: rgb(var(--color-sell));
}
```

Create `static/css/components/tables.css`:

```css
/* Professional Data Tables */
.data-table-pro {
  @apply w-full;
  font-family: var(--font-data);
  font-size: 0.875rem;
}

.table-header {
  @apply sticky top-0 z-10;
  background: rgb(var(--bg-secondary));
  border-bottom: 1px solid rgb(var(--border-strong));
}

.table-header th {
  @apply px-3 py-2 text-left font-semibold;
  color: rgb(var(--text-primary));
  white-space: nowrap;
}

.table-header th.sortable {
  @apply cursor-pointer select-none;
}

.table-header th.sortable:hover {
  background: rgb(var(--bg-tertiary));
}

.table-row {
  height: var(--space-row);
  border-bottom: 1px solid rgb(var(--border-default));
  transition: var(--transition-fast);
}

.table-row:hover {
  background: rgb(var(--bg-secondary) / 0.5);
}

.table-row.selected {
  background: rgb(var(--color-primary) / 0.05);
}

.table-cell {
  @apply px-3 py-1;
  white-space: nowrap;
}

.table-cell.numeric {
  @apply text-right;
  font-variant-numeric: tabular-nums;
}

.table-cell.buy {
  color: rgb(var(--color-buy));
  font-weight: 500;
}

.table-cell.sell {
  color: rgb(var(--color-sell));
  font-weight: 500;
}

.table-cell.price-update {
  animation: priceFlash 0.3s ease-out;
}

/* Inline Actions */
.table-actions {
  @apply opacity-0 flex gap-1;
  transition: var(--transition-fast);
}

.table-row:hover .table-actions {
  @apply opacity-100;
}

.action-btn {
  @apply px-2 py-0.5 text-xs rounded;
  background: rgb(var(--bg-tertiary));
  color: rgb(var(--text-secondary));
}

.action-btn:hover {
  background: rgb(var(--color-primary));
  color: white;
}
```

Create `static/css/components/order-widget.css`:

```css
/* Quick Order Widget */
.order-widget {
  @apply fixed right-4 top-16 z-40;
  width: var(--order-widget-width, 280px);
  background: rgb(var(--bg-primary));
  border: 1px solid rgb(var(--border-strong));
  border-radius: 8px;
  box-shadow: 0 10px 25px rgb(0 0 0 / 0.1);
}

.order-widget-header {
  @apply flex items-center justify-between p-3;
  border-bottom: 1px solid rgb(var(--border-default));
}

.order-widget-body {
  @apply p-3 space-y-3;
}

/* Symbol Search */
.symbol-search {
  @apply relative;
}

.symbol-input {
  @apply w-full px-3 py-2 text-sm rounded;
  background: rgb(var(--bg-secondary));
  border: 1px solid rgb(var(--border-default));
}

.symbol-input:focus {
  border-color: rgb(var(--color-primary));
  outline: none;
  box-shadow: 0 0 0 3px rgb(var(--color-primary) / 0.1);
}

/* Order Type Toggle */
.order-type-toggle {
  @apply grid grid-cols-2 gap-1 p-1 rounded;
  background: rgb(var(--bg-secondary));
}

.order-type-btn {
  @apply py-2 text-sm font-semibold rounded transition-all;
}

.order-type-btn.buy {
  background: rgb(var(--color-buy));
  color: white;
}

.order-type-btn.sell {
  background: rgb(var(--color-sell));
  color: white;
}

.order-type-btn:not(.active) {
  @apply opacity-30;
  background: transparent;
  color: rgb(var(--text-secondary));
}

/* Price and Quantity */
.input-group {
  @apply space-y-1;
}

.input-label {
  @apply text-xs font-medium;
  color: rgb(var(--text-secondary));
}

.input-field {
  @apply w-full px-3 py-2 text-sm rounded;
  background: rgb(var(--bg-secondary));
  border: 1px solid rgb(var(--border-default));
  font-family: var(--font-mono);
}

/* Market Depth */
.market-depth {
  @apply grid grid-cols-2 gap-2 p-2 rounded;
  background: rgb(var(--bg-secondary));
  font-family: var(--font-mono);
  font-size: 0.75rem;
}

.depth-side {
  @apply space-y-1;
}

.depth-row {
  @apply flex justify-between px-2 py-0.5 rounded;
}

.depth-row.bid {
  background: rgb(var(--color-buy) / 0.1);
}

.depth-row.ask {
  background: rgb(var(--color-sell) / 0.1);
}

.depth-qty {
  @apply font-semibold;
}

/* Submit Button */
.order-submit {
  @apply w-full py-2 font-semibold rounded transition-all;
}

.order-submit.buy {
  background: rgb(var(--color-buy));
  color: white;
}

.order-submit.sell {
  background: rgb(var(--color-sell));
  color: white;
}

.order-submit:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgb(0 0 0 / 0.15);
}

.order-submit:active {
  transform: translateY(0);
}
```

## Step 3: Update Base Template

### 3.1 Update templates/base.html

```html
<!DOCTYPE html>
<html lang="en" data-theme="professional">
<head>
    <!-- Critical CSS inline for faster initial render -->
    <style>
        [data-theme="professional"] {
            --bg-primary: 255 255 255;
            --text-primary: 17 24 39;
        }
        body {
            background: rgb(var(--bg-primary));
            color: rgb(var(--text-primary));
        }
        .skeleton {
            background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
            background-size: 200% 100%;
            animation: loading 1.5s infinite;
        }
        @keyframes loading {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
        }
    </style>

    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="description" content="Professional Trading Terminal - OpenAlgo">
    <meta name="csrf-token" content="{{ csrf_token() }}">

    <title>{% block title %}OpenAlgo Trading Terminal{% endblock %}</title>

    <!-- Preload critical fonts -->
    <link rel="preload" href="{{ url_for('static', filename='fonts/Inter-Variable.woff2') }}" as="font" type="font/woff2" crossorigin>
    <link rel="preload" href="{{ url_for('static', filename='fonts/JetBrainsMono.woff2') }}" as="font" type="font/woff2" crossorigin>

    <!-- Favicon -->
    <link rel="icon" type="image/png" sizes="32x32" href="{{ url_for('static', filename='favicon/favicon-32x32.png') }}">

    <!-- Compiled CSS -->
    <link rel="stylesheet" href="{{ url_for('static', filename='css/main.css') }}">

    <!-- Theme initialization -->
    <script>
        (function() {
            const theme = localStorage.getItem('theme') || 'professional';
            document.documentElement.setAttribute('data-theme', theme);
        })();
    </script>

    {% block head %}{% endblock %}
</head>
<body class="min-h-screen font-sans antialiased">
    <!-- Loading skeleton while app initializes -->
    <div id="app-skeleton" class="fixed inset-0 z-50 bg-white dark:bg-black">
        <div class="h-11 skeleton"></div>
        <div class="flex">
            <div class="w-60 h-screen skeleton"></div>
            <div class="flex-1 p-4 space-y-4">
                <div class="h-32 skeleton rounded"></div>
                <div class="h-64 skeleton rounded"></div>
            </div>
        </div>
    </div>

    <!-- Main App Container -->
    <div id="app" class="hidden">
        <!-- Professional Navbar -->
        <nav class="navbar-pro">
            <div class="flex items-center justify-between h-full">
                <!-- Left: Brand and Main Nav -->
                <div class="flex items-center h-full">
                    <div class="navbar-brand">
                        <img src="{{ url_for('static', filename='favicon/logo.png') }}" alt="OpenAlgo" class="h-6 w-6">
                        <span class="font-semibold">OpenAlgo</span>
                    </div>

                    <div class="navbar-nav hidden lg:flex">
                        <a href="{{ url_for('dashboard_bp.dashboard') }}"
                           class="nav-item {{ 'active' if request.endpoint == 'dashboard_bp.dashboard' }}">
                            Dashboard
                        </a>
                        <a href="{{ url_for('orders_bp.orderbook') }}"
                           class="nav-item {{ 'active' if request.endpoint == 'orders_bp.orderbook' }}">
                            Orders
                        </a>
                        <a href="{{ url_for('orders_bp.positions') }}"
                           class="nav-item {{ 'active' if request.endpoint == 'orders_bp.positions' }}">
                            Positions
                        </a>
                        <a href="{{ url_for('orders_bp.holdings') }}"
                           class="nav-item {{ 'active' if request.endpoint == 'orders_bp.holdings' }}">
                            Holdings
                        </a>
                        <a href="{{ url_for('tv_json_bp.tradingview_json') }}"
                           class="nav-item {{ 'active' if request.endpoint == 'tv_json_bp.tradingview_json' }}">
                            Charts
                        </a>
                        <a href="{{ url_for('strategy_bp.index') }}"
                           class="nav-item {{ 'active' if request.endpoint.startswith('strategy_bp.') }}">
                            Strategies
                        </a>
                    </div>
                </div>

                <!-- Center: Market Ticker -->
                <div class="market-ticker hidden xl:flex">
                    <div class="ticker-item">
                        <span class="text-muted">NIFTY</span>
                        <span class="ticker-value">19,425.35</span>
                        <span class="ticker-change positive">+0.58%</span>
                    </div>
                    <div class="ticker-item">
                        <span class="text-muted">SENSEX</span>
                        <span class="ticker-value">65,259.45</span>
                        <span class="ticker-change positive">+0.42%</span>
                    </div>
                    <div class="ticker-item">
                        <span class="text-muted">BANKNIFTY</span>
                        <span class="ticker-value">44,532.20</span>
                        <span class="ticker-change negative">-0.23%</span>
                    </div>
                </div>

                <!-- Right: User Actions -->
                <div class="flex items-center gap-2 pr-4">
                    <!-- Mode Toggle -->
                    <div class="flex items-center gap-2">
                        <span id="mode-badge" class="px-2 py-1 text-xs font-semibold rounded bg-green-100 text-green-800">
                            LIVE
                        </span>
                        <label class="relative inline-flex items-center cursor-pointer">
                            <input type="checkbox" class="sr-only mode-controller">
                            <div class="w-9 h-5 bg-gray-200 rounded-full"></div>
                        </label>
                    </div>

                    <!-- Theme Toggle -->
                    <button id="theme-toggle" class="p-2 rounded hover:bg-gray-100">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                  d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z">
                            </path>
                        </svg>
                    </button>

                    <!-- Notifications -->
                    <button class="relative p-2 rounded hover:bg-gray-100">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                  d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9">
                            </path>
                        </svg>
                        <span class="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full"></span>
                    </button>

                    <!-- User Menu -->
                    <div class="relative">
                        <button class="flex items-center gap-2 p-2 rounded hover:bg-gray-100">
                            <div class="w-8 h-8 rounded-full bg-gray-300"></div>
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                            </svg>
                        </button>
                    </div>
                </div>
            </div>
        </nav>

        <!-- Main Content Area -->
        <div class="flex pt-11">
            <!-- Sidebar (collapsible) -->
            <aside id="sidebar" class="w-60 h-[calc(100vh-44px)] bg-gray-50 border-r border-gray-200 transition-all">
                <!-- Sidebar content -->
            </aside>

            <!-- Content Area -->
            <main class="flex-1 p-4">
                {% block content %}{% endblock %}
            </main>

            <!-- Quick Order Widget (if enabled) -->
            <div id="quick-order" class="order-widget hidden">
                <!-- Order widget content -->
            </div>
        </div>
    </div>

    <!-- Notification Container -->
    <div id="notifications" class="fixed top-16 right-4 z-50 space-y-2"></div>

    <!-- Core JavaScript -->
    <script src="{{ url_for('static', filename='js/core/app.js') }}"></script>
    <script>
        // Remove skeleton after app loads
        window.addEventListener('DOMContentLoaded', function() {
            document.getElementById('app-skeleton').style.display = 'none';
            document.getElementById('app').classList.remove('hidden');
        });
    </script>

    {% block scripts %}{% endblock %}
</body>
</html>
```

## Step 4: Create Core JavaScript Modules

### 4.1 Create app.js

Create `static/js/core/app.js`:

```javascript
// Core Application Module
class TradingTerminal {
    constructor() {
        this.theme = new ThemeManager();
        this.navigation = new NavigationManager();
        this.shortcuts = new ShortcutManager();
        this.websocket = new WebSocketManager();
        this.notifications = new NotificationManager();

        this.init();
    }

    init() {
        this.setupEventListeners();
        this.initializeModules();
        this.loadUserPreferences();
        this.connectWebSocket();
    }

    setupEventListeners() {
        // Global event listeners
        document.addEventListener('keydown', (e) => this.shortcuts.handle(e));
        window.addEventListener('resize', () => this.handleResize());
        document.addEventListener('visibilitychange', () => this.handleVisibilityChange());
    }

    initializeModules() {
        // Initialize data tables
        document.querySelectorAll('.data-table-pro').forEach(table => {
            new DataTable(table);
        });

        // Initialize order widgets
        const orderWidget = document.getElementById('quick-order');
        if (orderWidget) {
            new OrderWidget(orderWidget);
        }

        // Initialize charts
        document.querySelectorAll('.trading-chart').forEach(chart => {
            new TradingChart(chart);
        });
    }

    loadUserPreferences() {
        const preferences = JSON.parse(localStorage.getItem('userPreferences') || '{}');
        this.applyPreferences(preferences);
    }

    connectWebSocket() {
        this.websocket.connect('/ws/market-data');
        this.websocket.on('price-update', (data) => this.handlePriceUpdate(data));
        this.websocket.on('order-update', (data) => this.handleOrderUpdate(data));
    }

    handlePriceUpdate(data) {
        // Update price displays
        const elements = document.querySelectorAll(`[data-symbol="${data.symbol}"]`);
        elements.forEach(el => {
            el.textContent = data.price;
            el.classList.add('price-update');
            setTimeout(() => el.classList.remove('price-update'), 300);
        });
    }

    handleOrderUpdate(data) {
        this.notifications.show({
            type: data.status === 'executed' ? 'success' : 'info',
            title: 'Order Update',
            message: `${data.symbol} ${data.action} ${data.quantity} @ ${data.price}`,
            duration: 5000
        });
    }

    handleResize() {
        // Handle responsive layout changes
        if (window.innerWidth < 1024) {
            document.getElementById('sidebar')?.classList.add('collapsed');
        }
    }

    handleVisibilityChange() {
        if (document.hidden) {
            this.websocket.pause();
        } else {
            this.websocket.resume();
        }
    }

    applyPreferences(preferences) {
        // Apply user preferences
        if (preferences.sidebarCollapsed) {
            document.getElementById('sidebar')?.classList.add('collapsed');
        }
        if (preferences.quickOrderVisible) {
            document.getElementById('quick-order')?.classList.remove('hidden');
        }
    }
}

// Initialize the application
document.addEventListener('DOMContentLoaded', () => {
    window.tradingTerminal = new TradingTerminal();
});

// Theme Manager
class ThemeManager {
    constructor() {
        this.themes = ['professional', 'dark_professional', 'analytics'];
        this.currentTheme = this.loadTheme();
        this.init();
    }

    init() {
        this.bindEvents();
    }

    bindEvents() {
        const toggle = document.getElementById('theme-toggle');
        toggle?.addEventListener('click', () => this.cycleTheme());
    }

    loadTheme() {
        return localStorage.getItem('theme') || 'professional';
    }

    setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);
        this.currentTheme = theme;
        this.updateThemeUI();
    }

    cycleTheme() {
        const currentIndex = this.themes.indexOf(this.currentTheme);
        const nextIndex = (currentIndex + 1) % this.themes.length;
        this.setTheme(this.themes[nextIndex]);
    }

    updateThemeUI() {
        // Update theme toggle icon based on current theme
        const toggle = document.getElementById('theme-toggle');
        if (toggle) {
            const icon = this.currentTheme.includes('dark') ? '🌙' : '☀️';
            toggle.innerHTML = icon;
        }
    }
}

// Shortcut Manager
class ShortcutManager {
    constructor() {
        this.shortcuts = {
            'ctrl+k': () => this.openCommandPalette(),
            'ctrl+b': () => this.openBuyOrder(),
            'ctrl+s': () => this.openSellOrder(),
            'ctrl+/': () => this.openSearch(),
            'alt+d': () => window.location.href = '/dashboard',
            'alt+o': () => window.location.href = '/orders',
            'alt+p': () => window.location.href = '/positions',
            'escape': () => this.closeAllModals(),
            '?': () => this.showHelp(),
        };
    }

    handle(event) {
        const key = this.getKey(event);
        const handler = this.shortcuts[key];

        if (handler) {
            event.preventDefault();
            handler();
        }
    }

    getKey(event) {
        const keys = [];
        if (event.ctrlKey) keys.push('ctrl');
        if (event.altKey) keys.push('alt');
        if (event.shiftKey) keys.push('shift');
        if (event.key && event.key !== 'Control' && event.key !== 'Alt' && event.key !== 'Shift') {
            keys.push(event.key.toLowerCase());
        }
        return keys.join('+');
    }

    openCommandPalette() {
        console.log('Opening command palette...');
        // Implementation for command palette
    }

    openBuyOrder() {
        const orderWidget = document.getElementById('quick-order');
        orderWidget?.classList.remove('hidden');
        // Set to buy mode
    }

    openSellOrder() {
        const orderWidget = document.getElementById('quick-order');
        orderWidget?.classList.remove('hidden');
        // Set to sell mode
    }

    openSearch() {
        document.getElementById('global-search')?.focus();
    }

    closeAllModals() {
        document.querySelectorAll('.modal.open').forEach(modal => {
            modal.classList.remove('open');
        });
    }

    showHelp() {
        console.log('Showing keyboard shortcuts help...');
        // Show help modal with all shortcuts
    }
}

// WebSocket Manager
class WebSocketManager {
    constructor() {
        this.ws = null;
        this.url = null;
        this.reconnectInterval = 5000;
        this.handlers = {};
    }

    connect(url) {
        this.url = url;
        this.ws = new WebSocket(this.url);

        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.onConnect();
        };

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleMessage(data);
        };

        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            this.reconnect();
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    reconnect() {
        setTimeout(() => {
            console.log('Reconnecting WebSocket...');
            this.connect(this.url);
        }, this.reconnectInterval);
    }

    on(event, handler) {
        if (!this.handlers[event]) {
            this.handlers[event] = [];
        }
        this.handlers[event].push(handler);
    }

    handleMessage(data) {
        const handlers = this.handlers[data.type];
        if (handlers) {
            handlers.forEach(handler => handler(data));
        }
    }

    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
    }

    onConnect() {
        // Subscribe to market data
        this.send({
            type: 'subscribe',
            channels: ['market-data', 'order-updates']
        });
    }

    pause() {
        this.send({ type: 'pause' });
    }

    resume() {
        this.send({ type: 'resume' });
    }
}

// Notification Manager
class NotificationManager {
    constructor() {
        this.container = document.getElementById('notifications');
    }

    show(options) {
        const notification = this.createNotification(options);
        this.container.appendChild(notification);

        // Animate in
        setTimeout(() => {
            notification.classList.add('show');
        }, 10);

        // Auto remove
        if (options.duration) {
            setTimeout(() => {
                this.remove(notification);
            }, options.duration);
        }

        return notification;
    }

    createNotification(options) {
        const div = document.createElement('div');
        div.className = `notification ${options.type}`;

        div.innerHTML = `
            <div class="notification-content">
                <div class="notification-title">${options.title}</div>
                <div class="notification-message">${options.message}</div>
            </div>
            <button class="notification-close" onclick="this.parentElement.remove()">×</button>
        `;

        return div;
    }

    remove(notification) {
        notification.classList.remove('show');
        setTimeout(() => {
            notification.remove();
        }, 300);
    }
}
```

## Step 5: Build Process

### 5.1 Update package.json

```json
{
  "name": "openalgo-terminal",
  "version": "2.0.0",
  "scripts": {
    "dev": "npm run build:css -- --watch",
    "build": "npm run build:css && npm run build:js",
    "build:css": "tailwindcss -i ./static/css/src/main.css -o ./static/css/main.css",
    "build:js": "webpack --mode production",
    "watch": "concurrently \"npm run build:css -- --watch\" \"webpack --watch\""
  },
  "devDependencies": {
    "@tailwindcss/forms": "^0.5.7",
    "@tailwindcss/typography": "^0.5.10",
    "autoprefixer": "^10.4.16",
    "concurrently": "^8.2.2",
    "cssnano": "^6.0.2",
    "daisyui": "^4.4.24",
    "postcss": "^8.4.32",
    "tailwindcss": "^3.4.0",
    "webpack": "^5.89.0",
    "webpack-cli": "^5.1.4"
  },
  "dependencies": {
    "@fontsource/inter": "^5.0.16",
    "@fontsource/jetbrains-mono": "^5.0.18",
    "@fontsource/roboto-mono": "^5.0.16",
    "chart.js": "^4.4.1",
    "lightweight-charts": "^4.1.1"
  }
}
```

### 5.2 Build Commands

```bash
# Install dependencies
npm install

# Build CSS
npm run build:css

# Watch for changes during development
npm run watch

# Build for production
npm run build
```

## Step 6: Migration Checklist

### Before Migration
1. ✅ Backup current templates and static files
2. ✅ Test in development environment
3. ✅ Review all custom CSS and JavaScript
4. ✅ Document current customizations

### During Migration
1. ✅ Update Tailwind configuration
2. ✅ Install new dependencies
3. ✅ Create new CSS structure
4. ✅ Update base template
5. ✅ Migrate page templates one by one
6. ✅ Test each page thoroughly
7. ✅ Update JavaScript modules
8. ✅ Test WebSocket connections

### After Migration
1. ✅ Performance testing
2. ✅ Cross-browser testing
3. ✅ Mobile responsiveness check
4. ✅ Accessibility audit
5. ✅ User acceptance testing
6. ✅ Documentation update
7. ✅ Training materials

## Troubleshooting

### Common Issues

1. **CSS not updating**
   ```bash
   # Clear build cache
   rm -rf node_modules/.cache
   npm run build:css
   ```

2. **JavaScript errors**
   ```bash
   # Check browser console
   # Ensure all modules are loaded in correct order
   ```

3. **Theme not persisting**
   ```javascript
   // Check localStorage
   console.log(localStorage.getItem('theme'));
   ```

4. **WebSocket connection issues**
   ```python
   # Ensure Flask-SocketIO is configured correctly
   # Check CORS settings
   ```

## Support

For questions or issues with the implementation:
1. Check the documentation in `/docs`
2. Review the example implementations in `/templates/examples`
3. Submit issues to the GitHub repository

## License

This theme implementation is part of the OpenAlgo project and follows the same license terms.