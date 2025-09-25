# OpenAlgo Component Library Reference

## Overview
This document provides a comprehensive reference for all UI components in the new professional trading terminal theme. Each component includes HTML structure, CSS classes, JavaScript initialization, and usage examples.

## 🎨 Component Categories

### 1. Navigation Components

#### Professional Navbar
```html
<!-- Professional Navigation Bar -->
<nav class="navbar-pro">
    <div class="navbar-container">
        <!-- Brand -->
        <div class="navbar-brand">
            <img src="/static/favicon/logo.png" alt="OpenAlgo" class="navbar-logo">
            <span class="navbar-title">OpenAlgo</span>
        </div>

        <!-- Main Navigation -->
        <div class="navbar-nav">
            <a href="/dashboard" class="nav-item active">Dashboard</a>
            <a href="/orders" class="nav-item">Orders</a>
            <a href="/positions" class="nav-item">Positions</a>
        </div>

        <!-- Market Ticker -->
        <div class="market-ticker">
            <div class="ticker-item">
                <span class="ticker-label">NIFTY</span>
                <span class="ticker-value">19,425.35</span>
                <span class="ticker-change positive">+0.58%</span>
            </div>
        </div>

        <!-- User Actions -->
        <div class="navbar-actions">
            <button class="nav-action-btn">
                <svg class="icon"><!-- notification icon --></svg>
                <span class="notification-badge">3</span>
            </button>
        </div>
    </div>
</nav>
```

**CSS Classes:**
- `navbar-pro` - Main navbar container
- `nav-item` - Navigation link
- `nav-item.active` - Active navigation state
- `market-ticker` - Real-time market data display
- `ticker-change.positive/negative` - Price change indicators

#### Collapsible Sidebar
```html
<!-- Collapsible Sidebar -->
<aside class="sidebar" data-collapsed="false">
    <div class="sidebar-header">
        <button class="sidebar-toggle">
            <svg class="icon"><!-- menu icon --></svg>
        </button>
    </div>

    <div class="sidebar-content">
        <div class="sidebar-section">
            <h3 class="sidebar-section-title">Trading</h3>
            <nav class="sidebar-nav">
                <a href="/orders" class="sidebar-link">
                    <svg class="sidebar-icon"><!-- icon --></svg>
                    <span class="sidebar-label">Orders</span>
                </a>
            </nav>
        </div>
    </div>

    <div class="sidebar-footer">
        <!-- Quick actions -->
    </div>
</aside>
```

### 2. Data Display Components

#### Professional Data Table
```html
<!-- Professional Data Table -->
<div class="data-table-container">
    <!-- Table Controls -->
    <div class="table-controls">
        <div class="table-search">
            <input type="text" class="search-input" placeholder="Search...">
        </div>
        <div class="table-filters">
            <select class="filter-select">
                <option>All</option>
                <option>Buy</option>
                <option>Sell</option>
            </select>
        </div>
        <div class="table-actions">
            <button class="btn-icon" title="Export">
                <svg class="icon"><!-- export icon --></svg>
            </button>
        </div>
    </div>

    <!-- Table -->
    <div class="table-wrapper">
        <table class="data-table-pro">
            <thead class="table-header">
                <tr>
                    <th class="sortable" data-sort="symbol">
                        Symbol
                        <svg class="sort-icon"><!-- sort icon --></svg>
                    </th>
                    <th class="sortable numeric" data-sort="price">Price</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody class="table-body">
                <tr class="table-row" data-id="1">
                    <td class="table-cell">
                        <div class="symbol-cell">
                            <span class="symbol-name">RELIANCE</span>
                            <span class="symbol-exchange">NSE</span>
                        </div>
                    </td>
                    <td class="table-cell numeric price-cell" data-value="2450.50">
                        2,450.50
                    </td>
                    <td class="table-cell actions-cell">
                        <div class="table-actions">
                            <button class="action-btn buy">Buy</button>
                            <button class="action-btn sell">Sell</button>
                        </div>
                    </td>
                </tr>
            </tbody>
        </table>
    </div>

    <!-- Pagination -->
    <div class="table-pagination">
        <div class="pagination-info">
            Showing 1-10 of 100 results
        </div>
        <div class="pagination-controls">
            <button class="pagination-btn" disabled>Previous</button>
            <button class="pagination-btn active">1</button>
            <button class="pagination-btn">2</button>
            <button class="pagination-btn">3</button>
            <button class="pagination-btn">Next</button>
        </div>
    </div>
</div>
```

**JavaScript Initialization:**
```javascript
// Initialize data table
const table = new DataTable('#orders-table', {
    sortable: true,
    searchable: true,
    pagination: true,
    virtualScroll: true,
    rowsPerPage: 50,
    onRowClick: (row) => console.log('Row clicked:', row),
    onSort: (column, direction) => console.log('Sorted:', column, direction)
});
```

#### Metric Cards
```html
<!-- Metric Card Component -->
<div class="metric-card">
    <div class="metric-header">
        <span class="metric-label">Total P&L</span>
        <svg class="metric-icon"><!-- trending icon --></svg>
    </div>
    <div class="metric-value positive">
        ₹ 25,450.00
    </div>
    <div class="metric-change">
        <span class="change-value positive">+12.5%</span>
        <span class="change-label">vs yesterday</span>
    </div>
    <div class="metric-chart">
        <canvas class="sparkline" data-values="[10,20,15,30,25,40,35]"></canvas>
    </div>
</div>
```

**CSS Modifiers:**
- `.metric-value.positive` - Green color for profits
- `.metric-value.negative` - Red color for losses
- `.metric-card.loading` - Loading state with skeleton

### 3. Trading Components

#### Quick Order Widget
```html
<!-- Quick Order Widget -->
<div class="order-widget" id="quick-order">
    <!-- Widget Header -->
    <div class="widget-header">
        <h3 class="widget-title">Quick Order</h3>
        <button class="widget-close">
            <svg class="icon"><!-- close icon --></svg>
        </button>
    </div>

    <!-- Symbol Search -->
    <div class="widget-body">
        <div class="symbol-search-container">
            <input type="text"
                   class="symbol-search-input"
                   placeholder="Search symbol..."
                   autocomplete="off">
            <div class="symbol-search-results">
                <!-- Dynamic results -->
            </div>
        </div>

        <!-- Order Type Toggle -->
        <div class="order-type-toggle">
            <button class="order-btn buy active">BUY</button>
            <button class="order-btn sell">SELL</button>
        </div>

        <!-- Order Form -->
        <div class="order-form">
            <div class="form-row">
                <div class="form-group">
                    <label class="form-label">Quantity</label>
                    <input type="number" class="form-input" value="1">
                </div>
                <div class="form-group">
                    <label class="form-label">Price</label>
                    <input type="number" class="form-input" value="0.00">
                </div>
            </div>

            <!-- Order Type Selection -->
            <div class="order-type-selector">
                <label class="radio-option">
                    <input type="radio" name="order-type" value="market" checked>
                    <span>Market</span>
                </label>
                <label class="radio-option">
                    <input type="radio" name="order-type" value="limit">
                    <span>Limit</span>
                </label>
                <label class="radio-option">
                    <input type="radio" name="order-type" value="sl">
                    <span>SL</span>
                </label>
            </div>
        </div>

        <!-- Market Depth -->
        <div class="market-depth">
            <div class="depth-header">
                <span>Market Depth</span>
            </div>
            <div class="depth-content">
                <div class="depth-side bid">
                    <div class="depth-row">
                        <span class="depth-qty">500</span>
                        <span class="depth-price">2,450.00</span>
                    </div>
                </div>
                <div class="depth-side ask">
                    <div class="depth-row">
                        <span class="depth-price">2,451.00</span>
                        <span class="depth-qty">750</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- Submit Button -->
        <button class="order-submit-btn buy">
            Place Buy Order
        </button>
    </div>
</div>
```

**JavaScript Usage:**
```javascript
// Initialize order widget
const orderWidget = new OrderWidget('#quick-order', {
    symbol: 'RELIANCE',
    exchange: 'NSE',
    onSubmit: (order) => {
        console.log('Order placed:', order);
    }
});
```

#### Position Card
```html
<!-- Position Card -->
<div class="position-card" data-symbol="RELIANCE">
    <div class="position-header">
        <div class="position-symbol">
            <span class="symbol">RELIANCE</span>
            <span class="exchange">NSE</span>
        </div>
        <div class="position-status">
            <span class="status-badge long">LONG</span>
        </div>
    </div>

    <div class="position-metrics">
        <div class="metric">
            <span class="label">Qty</span>
            <span class="value">100</span>
        </div>
        <div class="metric">
            <span class="label">Avg Price</span>
            <span class="value">2,400.00</span>
        </div>
        <div class="metric">
            <span class="label">LTP</span>
            <span class="value">2,450.00</span>
        </div>
        <div class="metric highlight">
            <span class="label">P&L</span>
            <span class="value positive">+5,000.00</span>
        </div>
    </div>

    <div class="position-actions">
        <button class="btn-sm exit">Exit</button>
        <button class="btn-sm modify">Modify</button>
        <button class="btn-sm add">Add</button>
    </div>
</div>
```

### 4. Form Components

#### Professional Form Elements
```html
<!-- Text Input -->
<div class="form-group">
    <label class="form-label" for="username">
        Username
        <span class="required">*</span>
    </label>
    <input type="text"
           id="username"
           class="form-input"
           placeholder="Enter username"
           required>
    <span class="form-hint">Minimum 3 characters</span>
    <span class="form-error">Username is required</span>
</div>

<!-- Select Dropdown -->
<div class="form-group">
    <label class="form-label">Exchange</label>
    <select class="form-select">
        <option value="">Select Exchange</option>
        <option value="NSE">NSE</option>
        <option value="BSE">BSE</option>
        <option value="MCX">MCX</option>
    </select>
</div>

<!-- Radio Group -->
<div class="form-group">
    <label class="form-label">Order Type</label>
    <div class="radio-group">
        <label class="radio-option">
            <input type="radio" name="order-type" value="buy">
            <span class="radio-label">Buy</span>
        </label>
        <label class="radio-option">
            <input type="radio" name="order-type" value="sell">
            <span class="radio-label">Sell</span>
        </label>
    </div>
</div>

<!-- Checkbox -->
<div class="form-group">
    <label class="checkbox-option">
        <input type="checkbox" name="terms">
        <span class="checkbox-label">I agree to terms</span>
    </label>
</div>

<!-- Toggle Switch -->
<div class="form-group">
    <div class="toggle-container">
        <label class="form-label">Enable Notifications</label>
        <label class="toggle-switch">
            <input type="checkbox">
            <span class="toggle-slider"></span>
        </label>
    </div>
</div>
```

### 5. Modal & Overlay Components

#### Modal Dialog
```html
<!-- Modal Component -->
<div class="modal" id="order-modal" data-open="false">
    <div class="modal-backdrop"></div>
    <div class="modal-container">
        <div class="modal-content">
            <div class="modal-header">
                <h2 class="modal-title">Place Order</h2>
                <button class="modal-close">
                    <svg class="icon"><!-- close icon --></svg>
                </button>
            </div>

            <div class="modal-body">
                <!-- Modal content here -->
            </div>

            <div class="modal-footer">
                <button class="btn btn-secondary">Cancel</button>
                <button class="btn btn-primary">Confirm</button>
            </div>
        </div>
    </div>
</div>
```

**JavaScript Usage:**
```javascript
// Open modal
Modal.open('#order-modal', {
    onClose: () => console.log('Modal closed'),
    closeOnBackdrop: true,
    closeOnEscape: true
});
```

### 6. Notification Components

#### Toast Notifications
```html
<!-- Toast Notification -->
<div class="toast-container">
    <div class="toast success">
        <div class="toast-icon">
            <svg class="icon"><!-- success icon --></svg>
        </div>
        <div class="toast-content">
            <div class="toast-title">Order Executed</div>
            <div class="toast-message">Buy 100 RELIANCE @ 2,450.00</div>
        </div>
        <button class="toast-close">
            <svg class="icon"><!-- close icon --></svg>
        </button>
    </div>
</div>
```

**JavaScript Usage:**
```javascript
// Show toast notification
Toast.show({
    type: 'success', // success, error, warning, info
    title: 'Order Executed',
    message: 'Buy 100 RELIANCE @ 2,450.00',
    duration: 5000,
    position: 'top-right'
});
```

### 7. Chart Components

#### Trading Chart
```html
<!-- Trading Chart Container -->
<div class="chart-container">
    <div class="chart-header">
        <div class="chart-controls">
            <div class="timeframe-selector">
                <button class="timeframe-btn">1m</button>
                <button class="timeframe-btn active">5m</button>
                <button class="timeframe-btn">15m</button>
                <button class="timeframe-btn">1h</button>
                <button class="timeframe-btn">1d</button>
            </div>
            <div class="chart-tools">
                <button class="tool-btn" title="Crosshair">
                    <svg class="icon"><!-- crosshair icon --></svg>
                </button>
                <button class="tool-btn" title="Draw">
                    <svg class="icon"><!-- draw icon --></svg>
                </button>
            </div>
        </div>
    </div>
    <div class="chart-body">
        <canvas id="trading-chart"></canvas>
    </div>
</div>
```

**JavaScript Initialization:**
```javascript
// Initialize trading chart
const chart = new TradingChart('#trading-chart', {
    symbol: 'RELIANCE',
    interval: '5m',
    type: 'candlestick',
    indicators: ['EMA20', 'RSI'],
    theme: 'dark'
});
```

### 8. Loading & Skeleton Components

#### Skeleton Loader
```html
<!-- Skeleton Loader for Table -->
<div class="skeleton-table">
    <div class="skeleton-row">
        <div class="skeleton-cell w-32"></div>
        <div class="skeleton-cell w-24"></div>
        <div class="skeleton-cell w-20"></div>
        <div class="skeleton-cell w-28"></div>
    </div>
    <!-- Repeat rows -->
</div>

<!-- Skeleton Loader for Card -->
<div class="skeleton-card">
    <div class="skeleton-line w-3/4"></div>
    <div class="skeleton-line w-1/2"></div>
    <div class="skeleton-line w-full"></div>
</div>
```

### 9. Badge & Status Components

#### Status Badges
```html
<!-- Status Badges -->
<span class="badge">Default</span>
<span class="badge success">Success</span>
<span class="badge warning">Warning</span>
<span class="badge error">Error</span>
<span class="badge info">Info</span>

<!-- Animated Status Indicators -->
<span class="status-indicator online">
    <span class="status-dot"></span>
    <span class="status-text">Online</span>
</span>

<!-- Trade Status -->
<span class="trade-status executed">EXECUTED</span>
<span class="trade-status pending">PENDING</span>
<span class="trade-status rejected">REJECTED</span>
```

### 10. Button Components

#### Button Variants
```html
<!-- Primary Buttons -->
<button class="btn btn-primary">Primary Action</button>
<button class="btn btn-primary btn-lg">Large Button</button>
<button class="btn btn-primary btn-sm">Small Button</button>

<!-- Secondary Buttons -->
<button class="btn btn-secondary">Secondary</button>

<!-- Success/Error Buttons -->
<button class="btn btn-success">Buy</button>
<button class="btn btn-error">Sell</button>

<!-- Icon Buttons -->
<button class="btn btn-icon">
    <svg class="icon"><!-- icon --></svg>
</button>

<!-- Loading Button -->
<button class="btn btn-primary loading">
    <span class="spinner"></span>
    Processing...
</button>

<!-- Button Group -->
<div class="btn-group">
    <button class="btn active">All</button>
    <button class="btn">Buy</button>
    <button class="btn">Sell</button>
</div>
```

## 🎯 Component States

### Interactive States
```css
/* Hover State */
.component:hover { }

/* Active State */
.component:active { }
.component.active { }

/* Focus State */
.component:focus { }
.component:focus-visible { }

/* Disabled State */
.component:disabled { }
.component.disabled { }

/* Loading State */
.component.loading { }

/* Error State */
.component.error { }

/* Success State */
.component.success { }
```

## 📱 Responsive Utilities

### Breakpoints
```css
/* Mobile First Approach */
/* Default: 0-639px */

/* sm: 640px and up */
@media (min-width: 640px) { }

/* md: 768px and up */
@media (min-width: 768px) { }

/* lg: 1024px and up */
@media (min-width: 1024px) { }

/* xl: 1280px and up */
@media (min-width: 1280px) { }

/* 2xl: 1536px and up */
@media (min-width: 1536px) { }
```

### Responsive Classes
```html
<!-- Hide/Show -->
<div class="hidden sm:block">Hidden on mobile</div>
<div class="block sm:hidden">Visible on mobile only</div>

<!-- Responsive Grid -->
<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
    <!-- Grid items -->
</div>

<!-- Responsive Padding -->
<div class="p-2 sm:p-4 lg:p-6">Content</div>
```

## 🛠️ JavaScript API

### Component Initialization
```javascript
// Auto-initialize all components
document.addEventListener('DOMContentLoaded', () => {
    ComponentLibrary.initAll();
});

// Manual initialization
ComponentLibrary.init('.data-table-pro', DataTable);
ComponentLibrary.init('.order-widget', OrderWidget);
ComponentLibrary.init('.trading-chart', TradingChart);
```

### Event Handling
```javascript
// Global event bus
EventBus.on('order:executed', (data) => {
    Toast.show({
        type: 'success',
        title: 'Order Executed',
        message: data.message
    });
});

// Component events
table.on('row:click', (row) => { });
table.on('sort', (column, direction) => { });
widget.on('order:submit', (order) => { });
```

### Utility Functions
```javascript
// Format currency
Utils.formatCurrency(1234.56); // "₹1,234.56"

// Format number
Utils.formatNumber(1234567.89); // "1,234,567.89"

// Format percentage
Utils.formatPercentage(0.1234); // "12.34%"

// Format date/time
Utils.formatDateTime(new Date()); // "Oct 25, 2024 10:30 AM"
```

## 🎨 Theming

### Theme Variables
```css
/* Light Theme */
[data-theme="light"] {
    --color-primary: #1E40AF;
    --color-background: #FFFFFF;
    --color-text: #111827;
}

/* Dark Theme */
[data-theme="dark"] {
    --color-primary: #3B82F6;
    --color-background: #0A0A0A;
    --color-text: #F3F4F6;
}

/* Analytics Theme */
[data-theme="analytics"] {
    --color-primary: #059669;
    --color-background: #F0FDF4;
    --color-text: #064E3B;
}
```

### Theme Switching
```javascript
// Switch theme
ThemeManager.setTheme('dark');

// Get current theme
const theme = ThemeManager.getTheme();

// Toggle theme
ThemeManager.toggle();
```

## 📋 Best Practices

### Performance
1. Use virtual scrolling for large datasets
2. Implement lazy loading for images
3. Debounce search inputs
4. Throttle scroll events
5. Use CSS transforms for animations

### Accessibility
1. Provide keyboard navigation
2. Include ARIA labels
3. Ensure color contrast ratios
4. Support screen readers
5. Provide focus indicators

### Code Organization
```javascript
// Component structure
class ComponentName {
    constructor(element, options = {}) {
        this.element = element;
        this.options = { ...this.defaults, ...options };
        this.init();
    }

    init() {
        this.bindEvents();
        this.render();
    }

    bindEvents() { }
    render() { }
    destroy() { }
}
```

## 🔧 Troubleshooting

### Common Issues

1. **Component not initializing**
   - Check if element exists in DOM
   - Verify JavaScript is loaded
   - Check console for errors

2. **Styling not applied**
   - Ensure CSS is loaded
   - Check class names
   - Verify theme is set

3. **Events not firing**
   - Check event listeners are bound
   - Verify element selectors
   - Check event propagation

## 📚 Additional Resources

- [Design System Documentation](./TRADING_TERMINAL_REDESIGN_PLAN.md)
- [Implementation Guide](./THEME_IMPLEMENTATION_GUIDE.md)
- [Migration Checklist](./MIGRATION_CHECKLIST.md)
- [Template Transformation List](./TEMPLATE_TRANSFORMATION_LIST.md)