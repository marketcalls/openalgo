# OpenAlgo v2.0 Migration Tracker

> **Last Updated**: 2026-01-12
> **Status**: Phase 4 Complete ✓

---

## Quick Status

| Phase | Status | Progress |
|-------|--------|----------|
| Phase 1: Foundation | **Complete** ✓ | 14/14 |
| Phase 2: Core Trading | **Complete** ✓ | 22/28 |
| Phase 3: Search & Symbol | **Complete** ✓ | 14/14 |
| Phase 4: Charts & WebSocket | **Complete** ✓ | 12/12 |
| Phase 5: Options Trading | Not Started | 0/12 |
| Phase 6: Strategy & Automation | Not Started | 0/14 |
| Phase 7: Settings & Admin | Not Started | 0/16 |
| Phase 8: Mobile & Polish | Not Started | 0/14 |
| Phase 9: Cleanup | Not Started | 0/6 |

**Overall Progress**: 62/128 tasks (48%)

---

## Template Migration Status

**Total Jinja2 Templates**: 77 | **Migrated**: 29 | **Remaining**: 37 pages

### Phase 2: Auth & Core Trading (24 templates)

#### Authentication (4)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `login.html` | `pages/Login.tsx` | [x] Complete |
| `broker.html` | `pages/BrokerSelect.tsx` | [x] Complete |
| `setup.html` | `pages/Setup.tsx` | [x] Complete |
| `reset_password.html` | `pages/ResetPassword.tsx` | [ ] Pending |

#### Core Trading (5)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `dashboard.html` | `pages/Dashboard.tsx` | [x] Complete |
| `positions.html` | `pages/Positions.tsx` | [x] Complete |
| `orderbook.html` | `pages/OrderBook.tsx` | [x] Complete |
| `tradebook.html` | `pages/TradeBook.tsx` | [x] Complete |
| `holdings.html` | `pages/Holdings.tsx` | [x] Complete |

#### Broker TOTP Forms (13)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `5paisa.html` | `components/broker-totp/FivePaisa.tsx` | [ ] Pending |
| `aliceblue.html` | `components/broker-totp/AliceBlue.tsx` | [ ] Pending |
| `angel.html` | `components/broker-totp/Angel.tsx` | [ ] Pending |
| `definedgeotp.html` | `components/broker-totp/Definedge.tsx` | [ ] Pending |
| `firstock.html` | `components/broker-totp/Firstock.tsx` | [ ] Pending |
| `kotak.html` | `components/broker-totp/Kotak.tsx` | [ ] Pending |
| `motilal.html` | `components/broker-totp/Motilal.tsx` | [ ] Pending |
| `mstock.html` | `components/broker-totp/MStock.tsx` | [ ] Pending |
| `nubra.html` | `components/broker-totp/Nubra.tsx` | [ ] Pending |
| `samco.html` | `components/broker-totp/Samco.tsx` | [ ] Pending |
| `shoonya.html` | `components/broker-totp/Shoonya.tsx` | [ ] Pending |
| `tradejini.html` | `components/broker-totp/Tradejini.tsx` | [ ] Pending |
| `zebu.html` | `components/broker-totp/Zebu.tsx` | [ ] Pending |

#### Layout Components (2)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `layout.html` + `navbar.html` | `components/layout/Layout.tsx`, `Navbar.tsx` | [x] Complete |
| `footer.html` | `components/layout/Footer.tsx` | [x] Complete |

### Phase 3: Search & Symbol (2 templates)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `token.html` | `pages/Token.tsx` | [x] Complete |
| `search.html` | `pages/Search.tsx` | [x] Complete |

### Phase 4: Charts & WebSocket (8 templates) - COMPLETE ✓
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `platforms.html` | `pages/Platforms.tsx` | [x] Complete |
| `tradingview.html` | `pages/TradingView.tsx` | [x] Complete |
| `gocharting.html` | `pages/GoCharting.tsx` | [x] Complete |
| `pnltracker.html` | `pages/PnLTracker.tsx` | [x] Complete |
| `websocket/test_market_data.html` | `pages/WebSocketTest.tsx` | [x] Complete |
| `sandbox.html` | `pages/Sandbox.tsx` | [x] Complete |
| `sandbox_mypnl.html` | `pages/SandboxPnL.tsx` | [x] Complete |
| `analyzer.html` | `pages/Analyzer.tsx` | [x] Complete |

### Phase 6: Strategy & Automation (15 templates)

#### Strategy (4)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `strategy/index.html` | `pages/Strategy/Index.tsx` | [ ] Pending |
| `strategy/new_strategy.html` | `pages/Strategy/New.tsx` | [ ] Pending |
| `strategy/view_strategy.html` | `pages/Strategy/View.tsx` | [ ] Pending |
| `strategy/configure_symbols.html` | `pages/Strategy/Configure.tsx` | [ ] Pending |

#### Chartink (4)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `chartink/index.html` | `pages/Chartink/Index.tsx` | [ ] Pending |
| `chartink/new_strategy.html` | `pages/Chartink/New.tsx` | [ ] Pending |
| `chartink/view_strategy.html` | `pages/Chartink/View.tsx` | [ ] Pending |
| `chartink/configure_symbols.html` | `pages/Chartink/Configure.tsx` | [ ] Pending |

#### Python Strategy (4)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `python_strategy/index.html` | `pages/PythonStrategy/Index.tsx` | [ ] Pending |
| `python_strategy/new.html` | `pages/PythonStrategy/New.tsx` | [ ] Pending |
| `python_strategy/edit.html` | `pages/PythonStrategy/Edit.tsx` | [ ] Pending |
| `python_strategy/logs.html` | `pages/PythonStrategy/Logs.tsx` | [ ] Pending |

#### Analyzer/Sandbox (3) - Moved to Phase 4 ✓
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `analyzer.html` | `pages/Analyzer.tsx` | [x] Complete (Phase 4) |
| `sandbox.html` | `pages/Sandbox.tsx` | [x] Complete (Phase 4) |
| `sandbox_mypnl.html` | `pages/SandboxPnL.tsx` | [x] Complete (Phase 4) |

### Phase 7: Settings & Admin (19 templates)

#### Admin (4)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `admin/index.html` | `pages/Admin/Index.tsx` | [ ] Pending |
| `admin/freeze.html` | `pages/Admin/Freeze.tsx` | [ ] Pending |
| `admin/holidays.html` | `pages/Admin/Holidays.tsx` | [ ] Pending |
| `admin/timings.html` | `pages/Admin/Timings.tsx` | [ ] Pending |

#### Telegram (4)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `telegram/index.html` | `pages/Telegram/Index.tsx` | [ ] Pending |
| `telegram/config.html` | `pages/Telegram/Config.tsx` | [ ] Pending |
| `telegram/users.html` | `pages/Telegram/Users.tsx` | [ ] Pending |
| `telegram/analytics.html` | `pages/Telegram/Analytics.tsx` | [ ] Pending |

#### Monitoring (3)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `security/dashboard.html` | `pages/Security/Dashboard.tsx` | [ ] Pending |
| `traffic/dashboard.html` | `pages/Traffic/Dashboard.tsx` | [ ] Pending |
| `latency/dashboard.html` | `pages/Latency/Dashboard.tsx` | [ ] Pending |

#### Settings & Features (8)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `apikey.html` | `pages/ApiKey.tsx` | [x] Complete |
| `logs.html` | `pages/Logs.tsx` | [ ] Pending |
| `platforms.html` | `pages/Platforms.tsx` | [x] Complete (Phase 4) |
| `token.html` | `pages/Token.tsx` | [x] Complete |
| `profile.html` | `pages/Profile.tsx` | [ ] Pending |
| `action_center.html` | `pages/ActionCenter.tsx` | [ ] Pending |
| `playground.html` | `pages/Playground.tsx` | [x] Complete |
| `logging.html` | `pages/Logging.tsx` | [ ] Pending |

### Public Pages & Error Pages (5 templates)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `index.html` | `pages/Home.tsx` | [x] Complete |
| `download.html` | `pages/Download.tsx` | [ ] Pending |
| `faq.html` | `pages/FAQ.tsx` | [ ] Pending |
| `404.html` | `pages/NotFound.tsx` | [ ] Pending |
| `500.html` | `pages/ServerError.tsx` | [ ] Pending |

### Component Templates (6 - will become shared components)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `components/loading_spinner.html` | `components/ui/spinner.tsx` | [ ] Pending |
| `components/log_entry.html` | `components/LogEntry.tsx` | [ ] Pending |
| `components/logs_filters.html` | `components/LogsFilters.tsx` | [ ] Pending |
| `components/logs_scripts.html` | (merged into React) | [ ] Pending |
| `components/logs_styles.html` | (merged into Tailwind) | [ ] Pending |
| `components/pagination.html` | `components/ui/pagination.tsx` | [ ] Pending |

---

## Phase 1: Foundation Setup - COMPLETE

### React Project Setup
- [x] Initialize Vite 7 + React 19 + TypeScript in `frontend/`
- [x] Configure Tailwind CSS v4
- [x] Install and configure shadcn/ui (22 components)
- [x] Set up folder structure
- [x] Configure path aliases (`@/`)
- [x] Set up ESLint (TypeScript + React)

### Theme System
- [x] Light theme (default)
- [x] Dark mode toggle
- [x] Analyzer mode theme (purple tint)
- [x] Sandbox mode theme (amber tint)
- [x] Theme CSS variables configured

### State & API
- [x] Configure TanStack Query
- [x] Set up Zustand stores (authStore, themeStore)
- [x] Create API client with interceptors

### Flask Integration
- [x] Pre-built dist included (community ready)
- [x] Create React serving blueprint (`blueprints/react_app.py`)

### Installed Packages
```
react: 19.2.3
vite: 7.3.1
tailwindcss: 4.1.18
shadcn/ui: 22 components
zustand: latest
@tanstack/react-query: latest
react-router-dom: latest
axios: latest
lucide-react: latest
```

---

## Phase 2: Core Trading - COMPLETE

### Authentication
- [x] Login page (username/password)
- [x] Session management (match Flask sessions)
- [x] Broker selection page
- [x] Broker OAuth redirect handling
- [x] Logout with token revocation
- [x] Session expiry handling (3 AM IST)
- [ ] 2FA/TOTP support (pending broker-specific forms)
- [ ] Password reset flow

### Dashboard
- [x] Portfolio overview card
- [x] Account funds summary
- [x] Quick stats (positions, orders, trades)
- [x] Connection status indicator
- [x] Broker info display
- [x] Indian number formatting (Cr/L suffixes)

### Positions Page
- [x] Positions table
- [x] P&L calculation
- [x] Color-coded profit/loss
- [x] Exit position button
- [ ] Real-time LTP updates (WebSocket) - Phase 4
- [ ] Position filters
- [ ] Export to CSV

### Orders Page
- [x] Order book table
- [x] Trade book table
- [x] Order status badges
- [ ] Modify order dialog
- [ ] Cancel order confirmation
- [ ] Cancel all orders
- [ ] Order history tabs

### Holdings Page
- [x] Holdings table
- [x] Average cost display
- [x] Current value / P&L

### Theme & Mode
- [x] Live/Analyzer mode toggle
- [x] Analyzer purple theme
- [x] Mode persistence
- [x] Backend API integration for mode

### Security
- [x] CSRF protection for all mutations
- [x] Session-based auth (Flask managed)
- [x] HttpOnly cookies
- [x] Auto-logout on 401
- [x] Logout CSRF exemption

---

## Phase 3: Search & Symbol - COMPLETE ✓

### Symbol Search
- [x] Token page (search form with F&O filters)
- [x] Search results page with sortable table
- [x] Debounced autocomplete search
- [x] Exchange filtering
- [x] F&O filters (underlying, expiry, strike range)
- [x] Pagination controls
- [x] Native HTML selects for large datasets (performance)
- [x] Click-outside dropdown handling

### API Key & Playground
- [x] API key display with show/hide toggle
- [x] Copy to clipboard functionality
- [x] Regenerate API key with confirmation
- [x] Order execution mode toggle (Auto/Semi-Auto)
- [x] API Playground with Bruno-inspired full-width UI
- [x] Endpoint sidebar with categories and search
- [x] Request body editor with line numbers
- [x] Response viewer with syntax highlighting
- [x] Copy cURL command
- [x] FullWidthLayout component for full-width pages

### Socket.IO Integration
- [x] useSocket.ts hook for real-time notifications
- [x] SocketProvider component
- [x] Order event notifications with sound alerts
- [x] Position close notifications
- [x] Audio throttling to prevent spam

### Trading Page Enhancements
- [x] OrderBook: Cancel order dialog with confirmation
- [x] OrderBook: Modify order dialog with quote
- [x] OrderBook: Status filter (complete, open, rejected, cancelled)
- [x] Positions: Close position functionality
- [x] Positions: Filter by exchange, product, action
- [x] Positions: Fixed header alignment for right-aligned columns
- [x] TradeBook: Filter by action, exchange, product
- [x] Fixed double toast notification issues

### Backend Updates for Phase 3
- [x] react_app.py: Routes for /search/token, /search, /apikey, /playground
- [x] search.py: Added brexchange and lotsize to API response
- [x] orders.py: Cancel order and modify order web routes

---

## Phase 4: Charts, WebSocket & Sandbox - COMPLETE ✓

### Trading Platforms
- [x] Platforms.tsx - Overview page with TradingView, GoCharting, Chartink cards
- [x] TradingView.tsx - Webhook URL and JSON payload generator
- [x] GoCharting.tsx - Webhook URL and JSON payload generator
- [x] Default values: NHPC symbol, NSE exchange, quantity 1
- [x] Auto-generate JSON on page load

### P&L Tracker
- [x] PnLTracker.tsx - Real-time P&L chart with lightweight-charts
- [x] Metrics cards: Current MTM, Max MTM, Min MTM, Max Drawdown
- [x] Screenshot functionality with html2canvas-pro (oklch support)
- [x] Dark/Light theme support for chart
- [x] OpenAlgo watermark on chart

### WebSocket & Market Data
- [x] WebSocketTest.tsx - Market data streaming test page
- [x] Symbol subscription/unsubscription
- [x] Real-time LTP, bid/ask display
- [x] Connection status indicators

### Sandbox & Analyzer
- [x] Sandbox.tsx - Configuration management page
- [x] SandboxPnL.tsx - P&L history with chart
- [x] Analyzer.tsx - API request analyzer with filters
- [x] Backend API endpoints for sandbox configs

### Backend Updates
- [x] react_app.py - Added routes for all Phase 4 pages
- [x] sandbox.py - Added /sandbox/api/configs endpoint with defaults
- [x] sandbox.py - Added /sandbox/mypnl/api/data endpoint
- [x] analyzer.py - Added /analyzer/api/data endpoint
- [x] pnltracker.py - Renamed legacy route to avoid conflict

### Technical Fixes
- [x] Fixed route conflicts between Flask blueprints and React
- [x] Fixed CSRF token handling (fetchCSRFToken API)
- [x] html2canvas-pro for oklch color support in screenshots
- [x] Fixed PnL Tracker navigation (route mismatch)

---

## Phase 5: Options Trading

### Option Chain
- [ ] Strike price grid
- [ ] Call/Put columns
- [ ] Greeks display
- [ ] Expiry selector
- [ ] ATM highlighting
- [ ] Quick trade from chain

### Greeks Calculator
- [ ] Input form
- [ ] Greeks display
- [ ] P&L payoff chart

### Options Order Panel
- [ ] Strike selection
- [ ] CE/PE toggle
- [ ] Multi-leg support

---

## Phase 6: Strategy & Automation

### Strategy Management
- [ ] Strategy list
- [ ] Start/Stop controls
- [ ] Monaco code editor
- [ ] Environment variables
- [ ] Schedule configuration
- [ ] Strategy logs (real-time)

### Sandbox/Analyzer Mode
- [x] Distinct theme applied
- [x] Mode indicator banner
- [ ] Virtual fund display
- [ ] All trading features
- [ ] Performance metrics

### Action Center
- [ ] Pending approval queue
- [ ] Approve/Reject buttons
- [ ] Bulk actions

---

## Phase 7: Settings & Admin

### Settings
- [ ] Theme selector
- [ ] Notification preferences
- [ ] API key management
- [ ] Session management

### Broker Config
- [ ] Broker selection
- [ ] API credentials form
- [ ] OAuth flow
- [ ] Connection status

### Telegram
- [ ] Bot configuration
- [ ] Alert preferences
- [ ] Test notification

### Monitoring
- [ ] API latency charts
- [ ] Traffic statistics
- [ ] Error logs
- [ ] Security events (IP bans)

---

## Phase 8: Mobile & Polish

### Responsive Layout
- [ ] Mobile bottom navigation
- [ ] Collapsible sidebar
- [ ] Touch-friendly buttons
- [ ] Tablet layout

### Performance
- [ ] Code splitting
- [ ] Lazy loading
- [ ] Bundle analysis

### Testing
- [ ] Unit tests (Vitest)
- [ ] E2E tests (Playwright)
- [ ] Accessibility audit

### Production
- [ ] Docker optimization
- [ ] Error boundaries
- [ ] Documentation

---

## Phase 9: Cleanup

- [ ] Verify all features migrated
- [ ] User acceptance testing
- [ ] Remove `templates/` directory
- [ ] Remove legacy static files
- [ ] Update documentation
- [ ] Release v2.0

---

## Current Login Flow (Preserved)

```
1. User → Login Page (username + password)
         ↓
2. Validate credentials (Argon2 + pepper)
         ↓
3. Broker Selection Page
         ↓
4. Broker Auth (OAuth or Form + TOTP)
         ↓
5. Store encrypted token in DB
         ↓
6. Set session flags:
   - session['logged_in'] = True
   - session['AUTH_TOKEN'] = encrypted
   - session['broker'] = broker_name
         ↓
7. Redirect to Dashboard
```

**Session Expiry**: Daily at 3 AM IST (configurable)

**Security Features Maintained**:
- Argon2 password hashing with pepper
- Fernet encryption for tokens
- TOTP 2FA support
- Rate limiting (5/min, 25/hr for login)
- CSRF protection (non-API routes)
- API key authentication for REST API

---

## State Management (Current → New)

| Current (Flask) | New (React) | Notes |
|-----------------|-------------|-------|
| Flask Session | Zustand + Cookies | Session flags in Zustand |
| TTL Cache (auth) | TanStack Query | Auto-refresh, stale handling |
| TTL Cache (feed) | TanStack Query | WebSocket integration |
| Database lookups | TanStack Query | Cached with invalidation |
| No client state | Zustand stores | Theme, watchlist, UI state |

**New Stores**:
- `authStore` - Login state, user info, broker
- `themeStore` - Light/dark, color theme, app mode
- `marketStore` - Watchlist, selected symbol
- `orderStore` - Order panel state
- `settingsStore` - User preferences

---

## Files Changed Summary

### New Files (frontend/)
```
frontend/
├── src/
│   ├── api/
│   │   ├── auth.ts
│   │   ├── client.ts
│   │   └── trading.ts
│   ├── components/
│   │   ├── auth/
│   │   │   └── AuthSync.tsx
│   │   ├── layout/
│   │   │   ├── Footer.tsx
│   │   │   ├── FullWidthLayout.tsx  # Phase 3
│   │   │   ├── Layout.tsx
│   │   │   └── Navbar.tsx
│   │   ├── socket/
│   │   │   └── SocketProvider.tsx   # Phase 3
│   │   └── ui/ (shadcn components)
│   ├── hooks/
│   │   └── useSocket.ts             # Phase 3
│   ├── pages/
│   │   ├── Analyzer.tsx             # Phase 4
│   │   ├── ApiKey.tsx               # Phase 3
│   │   ├── BrokerSelect.tsx
│   │   ├── BrokerTOTP.tsx
│   │   ├── Dashboard.tsx
│   │   ├── GoCharting.tsx           # Phase 4
│   │   ├── Holdings.tsx
│   │   ├── Home.tsx
│   │   ├── Login.tsx
│   │   ├── OrderBook.tsx            # Enhanced: cancel/modify/filters
│   │   ├── Platforms.tsx            # Phase 4
│   │   ├── Playground.tsx           # Phase 3
│   │   ├── PnLTracker.tsx           # Phase 4
│   │   ├── Positions.tsx            # Enhanced: close/filters
│   │   ├── Sandbox.tsx              # Phase 4
│   │   ├── SandboxPnL.tsx           # Phase 4
│   │   ├── Search.tsx               # Phase 3
│   │   ├── Setup.tsx
│   │   ├── Token.tsx                # Phase 3
│   │   ├── TradeBook.tsx            # Enhanced: filters
│   │   ├── TradingView.tsx          # Phase 4
│   │   └── WebSocketTest.tsx        # Phase 4
│   ├── stores/
│   │   ├── authStore.ts
│   │   └── themeStore.ts
│   └── types/
│       ├── auth.ts
│       └── trading.ts
├── package.json
├── vite.config.ts
├── tsconfig.json
└── tailwind.config.ts
```

### Modified Files
```
openalgo/
├── app.py                  # Register react_bp, CSRF exemptions
├── blueprints/
│   ├── analyzer.py         # Added /analyzer/api/data endpoint (Phase 4)
│   ├── apikey.py           # API key management endpoints (Phase 3)
│   ├── auth.py             # Added check-setup, session-status, JSON logout
│   ├── orders.py           # Cancel/modify order web routes (Phase 3)
│   ├── pnltracker.py       # Renamed legacy route (Phase 4)
│   ├── react_app.py        # Serve React SPA + Phase 3/4 routes
│   ├── sandbox.py          # Added /sandbox/api/configs, /sandbox/mypnl/api/data (Phase 4)
│   └── search.py           # Added brexchange/lotsize to response (Phase 3)
├── .gitignore              # Include frontend/dist
└── frontend/.gitignore     # Include dist for community
```

### Unchanged Files
```
- .env (NO CHANGES)
- All API endpoints (/api/v1/*)
- All broker integrations
- All database modules
- All services
- pyproject.toml
- requirements.txt
```

---

## Notes

- **Priority**: Phase 6 (Strategy & Automation) is next
- **Auth Flow**: Matches current Flask session behavior
- **API Keys**: REST API authentication unchanged
- **WebSocket**: Using existing Flask-SocketIO events
- **Backward Compatible**: External apps (TradingView, Amibroker) unaffected
- **No Broker Logos**: Using text/initials only for broker identification
- **CSRF**: All mutations protected except logout and /api/v1/* endpoints
- **html2canvas-pro**: Required for oklch color support in screenshots
