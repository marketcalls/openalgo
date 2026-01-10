# OpenAlgo v2.0 Migration Tracker

> **Last Updated**: 2026-01-10
> **Status**: Phase 1 Complete

---

## Quick Status

| Phase | Status | Progress |
|-------|--------|----------|
| Phase 1: Foundation | **Complete** | 14/14 |
| Phase 2: Core Trading | Not Started | 0/28 |
| Phase 3: Holdings & Watchlist | Not Started | 0/14 |
| Phase 4: Charts & Market Data | Not Started | 0/10 |
| Phase 5: Options Trading | Not Started | 0/12 |
| Phase 6: Strategy & Automation | Not Started | 0/14 |
| Phase 7: Settings & Admin | Not Started | 0/16 |
| Phase 8: Mobile & Polish | Not Started | 0/14 |
| Phase 9: Cleanup | Not Started | 0/6 |

**Overall Progress**: 14/128 tasks (11%)

---

## Template Migration Status

**Total Jinja2 Templates**: 77 | **Migrated**: 0 | **Remaining**: 66 pages

### Phase 2: Auth & Core Trading (24 templates)

#### Authentication (4)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `login.html` | `pages/Login.tsx` | [ ] |
| `broker.html` | `pages/BrokerSelect.tsx` | [ ] |
| `setup.html` | `pages/Setup.tsx` | [ ] |
| `reset_password.html` | `pages/ResetPassword.tsx` | [ ] |

#### Core Trading (5)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `dashboard.html` | `pages/Dashboard.tsx` | [ ] |
| `positions.html` | `pages/Positions.tsx` | [ ] |
| `orderbook.html` | `pages/OrderBook.tsx` | [ ] |
| `tradebook.html` | `pages/TradeBook.tsx` | [ ] |
| `holdings.html` | `pages/Holdings.tsx` | [ ] |

#### Broker TOTP Forms (13)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `5paisa.html` | `components/broker-totp/FivePaisa.tsx` | [ ] |
| `aliceblue.html` | `components/broker-totp/AliceBlue.tsx` | [ ] |
| `angel.html` | `components/broker-totp/Angel.tsx` | [ ] |
| `definedgeotp.html` | `components/broker-totp/Definedge.tsx` | [ ] |
| `firstock.html` | `components/broker-totp/Firstock.tsx` | [ ] |
| `kotak.html` | `components/broker-totp/Kotak.tsx` | [ ] |
| `motilal.html` | `components/broker-totp/Motilal.tsx` | [ ] |
| `mstock.html` | `components/broker-totp/MStock.tsx` | [ ] |
| `nubra.html` | `components/broker-totp/Nubra.tsx` | [ ] |
| `samco.html` | `components/broker-totp/Samco.tsx` | [ ] |
| `shoonya.html` | `components/broker-totp/Shoonya.tsx` | [ ] |
| `tradejini.html` | `components/broker-totp/Tradejini.tsx` | [ ] |
| `zebu.html` | `components/broker-totp/Zebu.tsx` | [ ] |

#### Layout Components (2)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `layout.html` + `navbar.html` | `components/Layout.tsx` | [ ] |
| `footer.html` | `components/Footer.tsx` | [ ] |

### Phase 3: Holdings & Search (2 templates)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `holdings.html` | (covered in Phase 2) | [ ] |
| `search.html` | `pages/Search.tsx` | [ ] |

### Phase 4: Charts & Market Data (4 templates)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `tradingview.html` | `pages/TradingView.tsx` | [ ] |
| `gocharting.html` | `pages/GoCharting.tsx` | [ ] |
| `pnltracker.html` | `pages/PnLTracker.tsx` | [ ] |
| `websocket/test_market_data.html` | `pages/WebSocket/MarketData.tsx` | [ ] |

### Phase 6: Strategy & Automation (15 templates)

#### Strategy (4)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `strategy/index.html` | `pages/Strategy/Index.tsx` | [ ] |
| `strategy/new_strategy.html` | `pages/Strategy/New.tsx` | [ ] |
| `strategy/view_strategy.html` | `pages/Strategy/View.tsx` | [ ] |
| `strategy/configure_symbols.html` | `pages/Strategy/Configure.tsx` | [ ] |

#### Chartink (4)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `chartink/index.html` | `pages/Chartink/Index.tsx` | [ ] |
| `chartink/new_strategy.html` | `pages/Chartink/New.tsx` | [ ] |
| `chartink/view_strategy.html` | `pages/Chartink/View.tsx` | [ ] |
| `chartink/configure_symbols.html` | `pages/Chartink/Configure.tsx` | [ ] |

#### Python Strategy (4)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `python_strategy/index.html` | `pages/PythonStrategy/Index.tsx` | [ ] |
| `python_strategy/new.html` | `pages/PythonStrategy/New.tsx` | [ ] |
| `python_strategy/edit.html` | `pages/PythonStrategy/Edit.tsx` | [ ] |
| `python_strategy/logs.html` | `pages/PythonStrategy/Logs.tsx` | [ ] |

#### Analyzer/Sandbox (3)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `analyzer.html` | `pages/Analyzer.tsx` | [ ] |
| `sandbox.html` | `pages/Sandbox.tsx` | [ ] |
| `sandbox_mypnl.html` | `pages/SandboxPnL.tsx` | [ ] |

### Phase 7: Settings & Admin (19 templates)

#### Admin (4)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `admin/index.html` | `pages/Admin/Index.tsx` | [ ] |
| `admin/freeze.html` | `pages/Admin/Freeze.tsx` | [ ] |
| `admin/holidays.html` | `pages/Admin/Holidays.tsx` | [ ] |
| `admin/timings.html` | `pages/Admin/Timings.tsx` | [ ] |

#### Telegram (4)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `telegram/index.html` | `pages/Telegram/Index.tsx` | [ ] |
| `telegram/config.html` | `pages/Telegram/Config.tsx` | [ ] |
| `telegram/users.html` | `pages/Telegram/Users.tsx` | [ ] |
| `telegram/analytics.html` | `pages/Telegram/Analytics.tsx` | [ ] |

#### Monitoring (3)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `security/dashboard.html` | `pages/Security/Dashboard.tsx` | [ ] |
| `traffic/dashboard.html` | `pages/Traffic/Dashboard.tsx` | [ ] |
| `latency/dashboard.html` | `pages/Latency/Dashboard.tsx` | [ ] |

#### Settings & Features (8)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `apikey.html` | `pages/ApiKey.tsx` | [ ] |
| `logs.html` | `pages/Logs.tsx` | [ ] |
| `platforms.html` | `pages/Platforms.tsx` | [ ] |
| `token.html` | `pages/Token.tsx` | [ ] |
| `profile.html` | `pages/Profile.tsx` | [ ] |
| `action_center.html` | `pages/ActionCenter.tsx` | [ ] |
| `playground.html` | `pages/Playground.tsx` | [ ] |
| `logging.html` | `pages/Logging.tsx` | [ ] |

### Public Pages & Error Pages (5 templates)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `index.html` | `pages/Home.tsx` | [ ] |
| `download.html` | `pages/Download.tsx` | [ ] |
| `faq.html` | `pages/FAQ.tsx` | [ ] |
| `404.html` | `pages/NotFound.tsx` | [ ] |
| `500.html` | `pages/ServerError.tsx` | [ ] |

### Component Templates (6 - will become shared components)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `components/loading_spinner.html` | `components/ui/spinner.tsx` | [ ] |
| `components/log_entry.html` | `components/LogEntry.tsx` | [ ] |
| `components/logs_filters.html` | `components/LogsFilters.tsx` | [ ] |
| `components/logs_scripts.html` | (merged into React) | [ ] |
| `components/logs_styles.html` | (merged into Tailwind) | [ ] |
| `components/pagination.html` | `components/ui/pagination.tsx` | [ ] |

---

## Phase 1: Foundation Setup

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

## Phase 2: Core Trading (Priority)

### Authentication (Must Match Current Flow)
- [ ] Login page (username/password)
- [ ] Session management (match Flask sessions)
- [ ] Broker selection page
- [ ] Broker OAuth redirect handling
- [ ] 2FA/TOTP support
- [ ] Logout with token revocation
- [ ] Session expiry handling (3 AM IST)
- [ ] Password reset flow

### Dashboard
- [ ] Portfolio overview card
- [ ] Account funds summary
- [ ] Quick stats (positions, orders, trades)
- [ ] Recent activity feed
- [ ] Connection status indicator
- [ ] Broker info display

### Positions Page
- [ ] Positions table (virtual scrolling)
- [ ] Real-time LTP updates (WebSocket)
- [ ] P&L calculation
- [ ] Color-coded profit/loss
- [ ] Exit position button
- [ ] Position filters
- [ ] Export to CSV

### Orders Page
- [ ] Order book table
- [ ] Trade book table
- [ ] Order status badges
- [ ] Modify order dialog
- [ ] Cancel order confirmation
- [ ] Cancel all orders
- [ ] Order history tabs

### Order Panel
- [ ] Buy/Sell toggle
- [ ] Quantity input
- [ ] Price input
- [ ] Order type selector
- [ ] Product selector
- [ ] Place order with toast

---

## Phase 3: Holdings & Watchlist

### Holdings
- [ ] Holdings table
- [ ] Average cost, P&L display
- [ ] Day change
- [ ] Holdings pie chart

### Watchlist
- [ ] Multiple watchlist support
- [ ] Symbol search autocomplete
- [ ] Real-time quotes
- [ ] Quick trade buttons
- [ ] Drag-and-drop reorder
- [ ] Persistence (localStorage + API)

### Symbol Search
- [ ] Debounced search
- [ ] Autocomplete dropdown
- [ ] Exchange filtering
- [ ] Recent searches

---

## Phase 4: Charts & Market Data

### TradingView Charts
- [ ] Candlestick chart component
- [ ] Multiple timeframes
- [ ] Volume bars
- [ ] Real-time updates
- [ ] Drawing tools
- [ ] Technical indicators

### Market Depth
- [ ] Bid/Ask ladder
- [ ] Volume visualization
- [ ] Real-time updates

### Quotes Panel
- [ ] Full quote display

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
- [ ] Distinct theme applied
- [ ] Mode indicator banner
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

## Current Login Flow (Must Preserve)

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

**Security Features to Maintain**:
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
│   ├── app/
│   ├── components/
│   ├── features/
│   ├── hooks/
│   ├── stores/
│   ├── api/
│   ├── lib/
│   ├── types/
│   ├── pages/
│   └── styles/
├── package.json
├── vite.config.ts
├── tsconfig.json
└── tailwind.config.ts
```

### Modified Files
```
openalgo/
├── app.py                  # Register react_bp blueprint
├── blueprints/
│   └── react_app.py        # NEW - Serve React SPA
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

- **Priority**: Phase 2 (Core Trading) is the most important
- **Auth Flow**: Must exactly match current Flask session behavior
- **API Keys**: REST API authentication unchanged
- **WebSocket**: Use existing Flask-SocketIO events
- **Backward Compatible**: External apps (TradingView, Amibroker) unaffected
