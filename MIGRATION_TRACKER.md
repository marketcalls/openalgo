# OpenAlgo v2.0 Migration Tracker

> **Last Updated**: 2026-01-10
> **Status**: Phase 2 Complete

---

## Quick Status

| Phase | Status | Progress |
|-------|--------|----------|
| Phase 1: Foundation | **Complete** | 14/14 |
| Phase 2: Core Trading | **Complete** | 22/28 |
| Phase 3: Search & Symbol | Not Started | 0/14 |
| Phase 4: Charts & Market Data | Not Started | 0/10 |
| Phase 5: Options Trading | Not Started | 0/12 |
| Phase 6: Strategy & Automation | Not Started | 0/14 |
| Phase 7: Settings & Admin | Not Started | 0/16 |
| Phase 8: Mobile & Polish | Not Started | 0/14 |
| Phase 9: Cleanup | Not Started | 0/6 |

**Overall Progress**: 36/128 tasks (28%)

---

## Template Migration Status

**Total Jinja2 Templates**: 77 | **Migrated**: 15 | **Remaining**: 51 pages

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
| `search.html` | `pages/Search.tsx` | [ ] Pending |

### Phase 4: Charts & Market Data (4 templates)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `tradingview.html` | `pages/TradingView.tsx` | [ ] Pending |
| `gocharting.html` | `pages/GoCharting.tsx` | [ ] Pending |
| `pnltracker.html` | `pages/PnLTracker.tsx` | [ ] Pending |
| `websocket/test_market_data.html` | `pages/WebSocket/MarketData.tsx` | [ ] Pending |

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

#### Analyzer/Sandbox (3)
| Jinja2 Template | React Component | Status |
|-----------------|-----------------|--------|
| `analyzer.html` | `pages/Analyzer.tsx` | [ ] Pending |
| `sandbox.html` | `pages/Sandbox.tsx` | [ ] Pending |
| `sandbox_mypnl.html` | `pages/SandboxPnL.tsx` | [ ] Pending |

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
| `apikey.html` | `pages/ApiKey.tsx` | [ ] Pending |
| `logs.html` | `pages/Logs.tsx` | [ ] Pending |
| `platforms.html` | `pages/Platforms.tsx` | [ ] Pending |
| `token.html` | `pages/Token.tsx` | [ ] Pending |
| `profile.html` | `pages/Profile.tsx` | [ ] Pending |
| `action_center.html` | `pages/ActionCenter.tsx` | [ ] Pending |
| `playground.html` | `pages/Playground.tsx` | [ ] Pending |
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

## Phase 3: Search & Symbol (Next)

### Symbol Search
- [ ] Search page
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
│   │   │   ├── Layout.tsx
│   │   │   └── Navbar.tsx
│   │   └── ui/ (shadcn components)
│   ├── pages/
│   │   ├── BrokerSelect.tsx
│   │   ├── BrokerTOTP.tsx
│   │   ├── Dashboard.tsx
│   │   ├── Holdings.tsx
│   │   ├── Home.tsx
│   │   ├── Login.tsx
│   │   ├── OrderBook.tsx
│   │   ├── Positions.tsx
│   │   ├── Setup.tsx
│   │   └── TradeBook.tsx
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
│   ├── auth.py             # Added check-setup, session-status, JSON logout
│   └── react_app.py        # Serve React SPA
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

- **Priority**: Phase 3 (Search) is next
- **Auth Flow**: Matches current Flask session behavior
- **API Keys**: REST API authentication unchanged
- **WebSocket**: Will use existing Flask-SocketIO events (Phase 4)
- **Backward Compatible**: External apps (TradingView, Amibroker) unaffected
- **No Broker Logos**: Using text/initials only for broker identification
