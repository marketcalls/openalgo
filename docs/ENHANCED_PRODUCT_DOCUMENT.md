# OpenAlgo Enhanced - Professional Multi-Account Trading Platform
## Product Requirements Document v2.0

### Executive Summary

OpenAlgo Enhanced is a complete rebuild of the original OpenAlgo platform, transforming it from a single-user trading bridge into a comprehensive multi-account trading execution platform. Built with modern technologies (FastAPI, NextJS, PostgreSQL, Redis, QuestDB, Docker), it provides institutional-grade trading infrastructure for individual traders managing multiple accounts across different brokers. The platform focuses on real-time trade execution, advanced option strategy deployment, risk controls, and professional-grade automation capabilities.

### Technology Stack

#### Backend
- **Framework**: FastAPI (Python 3.11+)
- **Primary Database**: PostgreSQL 15+
- **Cache Layer**: Redis 7+
- **Time-Series Database**: QuestDB
- **Message Queue**: Redis Streams / Apache Kafka
- **WebSocket**: FastAPI WebSockets with Redis Pub/Sub
- **Task Queue**: Celery with Redis backend
- **API Documentation**: OpenAPI 3.0 (Swagger/ReDoc)

#### Frontend
- **Framework**: Next.js 14+ (App Router)
- **UI Components**: Shadcn/ui + Tailwind CSS
- **State Management**: Zustand / TanStack Query
- **Real-time Updates**: Socket.io Client
- **Charts**: Lightweight Charts (TradingView) + Recharts
- **Forms**: React Hook Form + Zod validation

#### Infrastructure
- **Containerization**: Docker + Docker Compose
- **Reverse Proxy**: Nginx / Traefik
- **Monitoring**: Built-in performance metrics
- **Logging**: Application-level logging system
- **Deployment**: Single-node and multi-node support

### Core Features

#### 1. Multi-User & Multi-Account Management

- **User Roles**:
  - Super Admin: Platform management, system configuration
  - Admin: User management, broker configuration
  - Trader: Full trading capabilities with multi-account support
  - Viewer: Read-only access for monitoring

- **Multi-Account Features**:
  - Support for 3-4+ trading accounts per user
  - Different broker integration per account
  - Master-slave account configuration
  - Account grouping and labeling
  - Individual account authentication
  - Consolidated portfolio view

- **Self Copy Trading**:
  - One-click signal replication across accounts
  - Proportional position sizing
  - Account-specific risk multipliers
  - Cross-broker symbol mapping
  - Selective account trading
  - Real-time sync status

#### 2. Enhanced Security Architecture

- **Authentication & Authorization**:
  - JWT-based authentication with refresh tokens
  - OAuth2 social login (Google, GitHub)
  - Session management with Redis
  - IP whitelisting per user/role
  - Rate limiting per user/IP/endpoint
  - API key management with scopes

- **Broker Credentials Management**:
  - User-configured broker credentials (not in .env)
  - End-to-end encryption for credentials
  - Per-account encrypted vault using AES-256-GCM
  - Key derivation from user password + server secret
  - Automatic credential rotation reminders
  - Secure credential storage per account

- **Security Features**:
  - CSRF protection with double-submit cookies
  - XSS prevention with CSP headers
  - SQL injection prevention
  - Input validation and sanitization
  - Request signing for critical operations
  - Comprehensive audit logging

#### 3. Multi-Broker Support (Enhanced)

- **Supported Brokers** (21+):
  - All original brokers with unified interface
  - Adapter pattern for easy integration
  - Broker-specific configuration UI
  - Health monitoring per broker
  - Automatic reconnection logic
  - Performance metrics tracking

- **Broker Features**:
  - Dynamic broker addition/removal
  - Real-time broker status dashboard
  - Rate limit management
  - Error handling with retry logic
  - Latency monitoring per broker
  - Master contract auto-download
  - Real API integration for testing
  - Virtual execution mode for walk forward testing

#### 4. Advanced Order Management

- **Order Types**:
  - Market, Limit, SL, SL-M
  - GTT (Good Till Triggered) orders
  - Bracket and Cover orders
  - AMO (After Market Orders)
  - Iceberg orders with disclosure
  - Multi-leg option orders

- **Order Features**:
  - Smart order routing
  - Order slicing for large quantities
  - Basket order execution
  - Order templates
  - Quick order modifications
  - Bulk order operations

- **Position Management**:
  - Real-time P&L calculation
  - Multi-account aggregation
  - Position sizing algorithms
  - Auto stop-loss placement
  - Trailing stop-loss
  - Position analytics

#### 5. Professional Strategy Management

- **Strategy Templates**:
  - Pre-built strategy templates
  - Visual strategy builder
  - Multi-leg option strategies
  - Strategy versioning
  - Template marketplace
  - Custom strategy creation

- **TradingView Indicator Automation**:
  - **Signal-Based Trading**:
    - Direct indicator-to-trade automation
    - No Pine Script strategy required
    - Support for any TradingView indicator
    - Multiple signal groups per indicator
    - Entry/Exit signal mapping
    - Real-time webhook reception
  
  - **Alert Configuration**:
    - Visual alert setup wizard
    - Auto-generated JSON payloads
    - Unique webhook URLs per strategy
    - Multi-condition alert support
    - Bar close vs real-time triggers
    - Alert history and analytics
  
  - **Strategy Types**:
    - Simple crossover strategies (MA, EMA)
    - Oscillator-based (RSI, MACD, Stochastic)
    - Volume-based indicators
    - Custom indicator support
    - Multi-timeframe strategies
    - Complex condition combinations

- **Option Strategy Builder**:
  - Visual option chain interface
  - Multi-leg strategy creation (Iron Condor, Butterfly, etc.)
  - Strike selection helpers (ATM/OTM/ITM)
  - Dynamic strike selection based on spot/premium
  - Greeks calculation and visualization
  - Payoff diagrams with break-even points
  - Quick adjustments feature
  - Pre-defined templates (Straddle, Strangle, Spreads)

- **Algo Trading Configuration**:
  - **Algo Creation**:
    - Multi-leg order support
    - Options/Futures/Equity selection
    - Strike selection logic (OTM±X, ATM±X)
    - Quantity management
    - Product type mapping
    - Signal-driven execution mode
  
  - **Signal Mapping**:
    - One-to-many algo mapping
    - Entry/Exit signal separation
    - Max signals per day limit
    - Signal expiry management
    - Cross-strategy signal routing
    - Conditional signal processing

- **Strategy Risk Controls**:
  - **Strategy-Level Controls**:
    - Individual stop-loss per strategy
    - Target profit per strategy
    - Trailing stop-loss per strategy
    - Max positions per strategy
    - Time-based entry/exit
    - Strategy-level panic button
    - Signal-based exits (no fixed SL/TP)
  
  - **Portfolio-Level Controls**:
    - Overall portfolio stop-loss
    - Overall portfolio target
    - Daily loss limits
    - Exposure limits
    - Overall panic button
    - Auto square-off settings

- **Position Builder Interface**:
  - Drag-and-drop position creation
  - Real-time margin calculation
  - Risk-reward visualization
  - One-click position entry
  - Multi-leg order placement

#### 6. Advanced Testing & Walk Forward Testing

- **Walk Forward Testing System**:
  - Real-time strategy validation without capital risk
  - Live market data from real broker APIs (real-time)
  - Virtual order execution with real market prices
  - Strategy execution testing before live deployment
  - Confidence building for strategy deployment
  - Real-time behavior observation using actual market conditions

- **Core Testing Features**:
  - **Strategy Activation**:
    - One-click deployment from created strategies
    - Real-time performance monitoring during market hours
    - Multiple strategy concurrent testing
    - Strategy search and filtering
    - Quick activation/deactivation controls
  
  - **Real-time Monitoring**:
    - Mark-to-Market (MTM) calculation on candle close
    - Individual and combined strategy MTM tracking
    - Margin approximation for capital requirements
    - Live position tracking
    - Real-time P&L updates
  
  - **Cost Simulation**:
    - Optional brokerage and tax inclusion
    - Customizable brokerage rate settings
    - Net P&L calculation with realistic costs
    - Margin requirement estimation
    - Slippage impact modeling

- **Walk Forward Testing Workflow**:
  ```
  1. Navigate to Walk Forward Testing Dashboard
     ├── View available created strategies
     ├── Search and filter strategies
     └── Review strategy execution history

  2. Strategy Activation
     ├── Select strategy from list
     ├── Click "Activate" button
     ├── Confirm deployment in popup
     └── Receive deployment confirmation

  3. Real-time Monitoring
     ├── Monitor deployed strategies section
     ├── Track total and individual MTM
     ├── View margin requirements
     └── Observe real-time trade execution

  4. Manual Intervention
     ├── Square-off individual strategies
     ├── Emergency stop all strategies
     ├── Modify strategy parameters
     └── Review trade analytics
  ```

- **Dashboard Components**:
  - **Performance Metrics**:
    - Total MTM across all strategies
    - Individual strategy MTM tracking
    - Margin blocked approximation
    - Daily/cumulative P&L
    - Win rate and trade statistics
  
  - **Control Panel**:
    - Strategy activation/deactivation
    - Manual square-off controls
    - Emergency stop button
    - Parameter adjustment tools
    - Real-time alerts configuration
  
  - **Analytics Dashboard**:
    - Detailed performance analytics
    - Payoff charts and Greeks
    - Trade execution logs
    - Risk metrics visualization
    - Strategy comparison tools

- **Advanced Features**:
  - **Multi-Strategy Testing**:
    - Portfolio-level walk forward testing
    - Strategy correlation analysis
    - Combined risk assessment
    - Resource allocation optimization
    - Performance comparison matrix
  
  - **TradingView Integration**:
    - Walk forward test TradingView strategies
    - Real-time signal validation
    - Alert-based strategy testing
    - Performance verification before live deployment
    - Signal accuracy measurement
  
  - **Option Strategy Testing**:
    - Multi-leg option strategy validation
    - Greeks behavior monitoring
    - Payoff diagram real-time updates
    - Volatility impact analysis
    - Time decay observation

- **Data & Accuracy**:
  - **Market Data Feed**:
    - Real-time market data from live broker APIs
    - Live bid-ask spread and market depth
    - Actual volume and liquidity data
    - Real market microstructure effects
    - Live corporate action updates
    - Direct connection to exchange data via brokers
  
  - **Virtual Execution Engine**:
    - Internal order simulation with real market data
    - Real market condition replication
    - Actual broker API latency simulation
    - Live slippage calculation based on market depth
    - Market impact estimation using real order book

- **Reporting & Analysis**:
  - **Real-time Reports**:
    - Live strategy performance
    - Trade execution details
    - Risk exposure monitoring
    - Margin utilization tracking
    - Alert and notification logs
  
  - **Historical Analysis**:
    - Past walk forward test results
    - Strategy execution comparison
    - Trade-by-trade analysis
    - Return metrics
    - Performance comparisons
  
  - **Export Capabilities**:
    - Detailed trade logs
    - Performance reports
    - Risk analysis reports
    - Custom date range exports
    - Multi-format downloads

- **Safety & Risk Controls**:
  - **Built-in Safeguards**:
    - No real money at risk
    - Virtual order execution only
    - Real market data with simulated trades
    - Strategy validation checks
    - Real risk limit testing
  
  - **Virtual Trading Engine**:
    - Internal order matching using real market data
    - No actual orders sent to broker/exchange
    - Real-time price discovery simulation
    - Actual margin requirement calculations
    - Live market condition replication
  
  - **Manual Controls**:
    - Individual strategy square-off
    - Portfolio-wide stop
    - Emergency halt button
    - Real-time parameter adjustments
    - Alert threshold modifications

#### 7. Signal & Execution Management

- **Signal Generation**:
  - Webhook-based signals
  - API signal endpoints
  - Manual signal creation
  - Signal validation rules
  - Duplicate detection
  - Signal queuing

- **Signal Distribution**:
  - Account-wise routing
  - Conditional execution
  - Signal transformation
  - Priority-based execution
  - Emergency override
  - Signal analytics

- **Comprehensive Logging**:
  - **Signal Logs**: All incoming signals with timestamps
  - **Sandbox Logs**: Test execution details
  - **Order/Event Logs**: Complete order lifecycle
  - **Execution Analytics**: Success/failure analysis

#### 8. Risk Management & Safety Features

- **Panic Button System**:
  - **Overall Panic Button**:
    - Instant trading halt across all accounts
    - All positions square-off
    - All pending orders cancelled
    - API signal rejection mode
    - Manual restart required
  
  - **Strategy-Level Panic**:
    - Individual strategy disable
    - Strategy positions exit
    - Strategy order cancellation
    - Cooldown period enforcement
    - Auto-disable on breach

- **MTM (Mark-to-Market) Controls**:
  - **Instrument-Level MTM**:
    - Real-time MTM tracking
    - Stop-loss (SL) per instrument
    - Target profit (TP) per instrument
    - Trailing stop-loss (TSL)
    - Auto square-off on breach
  
  - **Strategy-Level MTM**:
    - Aggregate MTM per strategy
    - Strategy stop-loss limits
    - Strategy profit targets
    - Time-based MTM rules
    - Alert notifications
  
  - **Overall Intraday MTM**:
    - Portfolio-wide MTM limits
    - Daily loss prevention
    - Profit booking rules
    - End-of-day square-off
    - Next-day carry rules

#### 9. Analytics & Reporting

- **Real-time Analytics**:
  - Live P&L dashboard
  - Strategy performance metrics
  - Account-wise analytics
  - Risk exposure monitoring
  - Order execution analysis
  - Slippage tracking

- **Comprehensive Reports**:
  - Daily/Weekly/Monthly P&L
  - Tax computation reports
  - Brokerage analysis
  - Strategy performance
  - Custom date ranges
  - Multi-format exports

- **Performance Metrics**:
  - Sharpe ratio
  - Maximum drawdown
  - Win rate analysis
  - Average trade metrics
  - Risk-adjusted returns
  - Benchmark comparison

#### 10. Built-in Monitoring & Analytics

- **Performance Monitoring**:
  - End-to-end latency tracking
  - Stage-wise breakdown analysis
  - Broker API response times
  - WebSocket connection monitoring
  - Database query performance
  - Real-time performance alerts

- **Usage Analytics**:
  - API endpoint usage patterns
  - User activity tracking
  - Resource utilization metrics
  - Trading volume analysis
  - Strategy performance metrics
  - System capacity monitoring

- **Health Dashboard**:
  - Real-time system status
  - Service health indicators
  - Error rate monitoring
  - Connection status tracking
  - Memory and CPU usage
  - Custom alert thresholds

#### 11. Market Data Management

- **Master Contract Management**:
  - Automated weekly/monthly downloads
  - Symbol mapping across brokers
  - Contract rollover handling
  - Corporate action adjustments
  - Custom symbol creation
  - Expiry management

- **Real-time Data**:
  - Multi-source data aggregation
  - Tick-by-tick storage in QuestDB
  - Market depth tracking
  - Option chain updates
  - Index tracking
  - Custom indicators

- **Historical Data**:
  - Efficient time-series storage
  - Fast data retrieval APIs
  - Data export capabilities
  - Backup and archival
  - Data quality checks
  - Missing data handling

#### 12. Communication & Alerts

- **Telegram Bot Integration**:
  - Trade execution alerts
  - P&L updates
  - Risk breach notifications
  - Strategy performance
  - Quick commands
  - Two-way communication

- **Alert System**:
  - Multi-channel alerts (Email, SMS, Push)
  - Customizable alert rules
  - Priority-based routing
  - Alert aggregation
  - Do-not-disturb modes
  - Alert history

#### 13. TradingView Strategy Management System

This comprehensive system automates trading strategies based on TradingView indicator alerts without requiring Pine Script knowledge.

- **Core Components**:
  - **Trading Algos**: Pre-configured trading instructions (buy/sell, instrument, quantity)
  - **Signal Groups**: Receivers for TradingView alerts linked to specific algos
  - **Webhook URLs**: Unique endpoints for each signal group
  - **JSON Payloads**: Auto-generated entry/exit messages

- **Algo Configuration Workflow**:
  ```
  1. Create Trading Algo
     ├── Define instrument (Options CE/PE, Futures, Equity)
     ├── Set strike selection logic (ATM±X, OTM±X)
     ├── Configure quantity and product type
     ├── Set type to "Signal" (no fixed SL/TP)
     └── Link to broker account

  2. Create Signal Group
     ├── Name the indicator strategy (e.g., "EMA Crossover")
     ├── Set signal limits (max per day)
     ├── Configure expiry settings
     ├── Link to trading algo(s)
     └── Generate webhook URL & JSON codes

  3. Setup TradingView Alerts
     ├── Configure indicator conditions
     ├── Set trigger (once per bar close)
     ├── Paste JSON payload from signal group
     ├── Add webhook URL
     └── Activate alert
  ```

- **Strategy Examples**:
  - **EMA Crossover Strategy**:
    ```
    Indicator: 3-period EMA
    Long Entry: Price crosses above EMA → Buy CE
    Long Exit: Price crosses below EMA → Close CE
    Short Entry: Price crosses below EMA → Buy PE  
    Short Exit: Price crosses above EMA → Close PE
    
    Required Setup:
    - 2 Algos: Buy CE, Buy PE
    - 2 Signal Groups: Long signals, Short signals
    - 4 TradingView Alerts: Long entry/exit, Short entry/exit
    ```
  
  - **RSI Oversold/Overbought**:
    ```
    Indicator: RSI (14)
    Long Entry: RSI < 30 → Buy CE
    Long Exit: RSI > 70 → Close CE
    Short Entry: RSI > 70 → Buy PE
    Short Exit: RSI < 30 → Close PE
    ```

- **Advanced Features**:
  - **Multi-Leg Strategies**:
    - Iron Condor automation
    - Butterfly spread signals
    - Calendar spread management
    - Hedge position triggers
  
  - **Dynamic Strike Selection**:
    - Spot-based selection (ATM+50, ATM-100)
    - Premium-based selection (₹15 OTM, ₹25 OTM)
    - Delta-based selection (0.3 delta, 0.7 delta)
    - Time-based adjustments
  
  - **Signal Processing**:
    - Duplicate signal filtering
    - Time-based signal validation
    - Market hours restriction
    - Signal priority queuing
    - Failed signal retry mechanism

- **User Interface**:
  - **Strategy Builder**:
    - Drag-and-drop algo creation
    - Visual signal flow mapping
    - Real-time testing interface
    - Strategy performance preview
    - One-click TradingView setup
  
  - **Alert Management**:
    - Visual alert configurator
    - JSON payload generator
    - Webhook URL manager
    - Alert history tracking
    - Performance analytics
  
  - **Monitoring Dashboard**:
    - Real-time signal status
    - Alert trigger logs
    - Execution success rates
    - Strategy P&L tracking
    - Error notification system

- **JSON Payload Structure**:
  ```json
  {
    "strategy_id": "uuid",
    "signal_type": "entry|exit",
    "symbol": "NIFTY",
    "action": "buy|sell",
    "quantity": 100,
    "price": "market|limit",
    "trigger_price": 18500,
    "account_id": "uuid",
    "timestamp": "2024-01-01T10:30:00Z",
    "alert_name": "EMA_Crossover_Long_Entry"
  }
  ```

- **Webhook Security**:
  - Unique webhook URLs per strategy
  - Request signing with secret keys
  - IP whitelisting for TradingView
  - Rate limiting per webhook
  - Payload encryption option
  - Alert authentication tokens

#### 14. API & Integration Features

- **RESTful API v2**:
  ```
  /api/v2/
  ├── auth/          # Authentication endpoints
  ├── accounts/      # Multi-account management
  ├── trading/       # Order & position management
  ├── strategies/    # Strategy CRUD & execution
  ├── signals/       # TradingView signal management
  ├── algos/         # Trading algo configuration
  ├── walkforward/   # Walk forward testing management
  ├── market/        # Market data endpoints
  ├── risk/          # Risk management
  ├── analytics/     # Reports & analytics
  └── webhooks/      # Signal reception & processing
  ```

### Complete API Functions List

#### Authentication & User Management
```
POST   /api/v2/auth/login
POST   /api/v2/auth/logout
POST   /api/v2/auth/refresh
POST   /api/v2/auth/register
POST   /api/v2/auth/forgot-password
POST   /api/v2/auth/reset-password
POST   /api/v2/auth/verify-email
GET    /api/v2/auth/profile
PUT    /api/v2/auth/profile
POST   /api/v2/auth/change-password
POST   /api/v2/auth/enable-2fa
POST   /api/v2/auth/verify-2fa
DELETE /api/v2/auth/disable-2fa
```

#### Multi-Account Management
```
GET    /api/v2/accounts/
POST   /api/v2/accounts/
GET    /api/v2/accounts/{account_id}
PUT    /api/v2/accounts/{account_id}
DELETE /api/v2/accounts/{account_id}
POST   /api/v2/accounts/{account_id}/test-connection
POST   /api/v2/accounts/{account_id}/credentials
PUT    /api/v2/accounts/{account_id}/credentials
GET    /api/v2/accounts/{account_id}/status
POST   /api/v2/accounts/{account_id}/activate
POST   /api/v2/accounts/{account_id}/deactivate
GET    /api/v2/accounts/brokers/supported
```

#### Trading Operations
```
POST   /api/v2/trading/orders/place
POST   /api/v2/trading/orders/modify
POST   /api/v2/trading/orders/cancel
POST   /api/v2/trading/orders/cancel-all
GET    /api/v2/trading/orders/
GET    /api/v2/trading/orders/{order_id}
GET    /api/v2/trading/orders/{order_id}/status
POST   /api/v2/trading/orders/basket
POST   /api/v2/trading/orders/bracket
POST   /api/v2/trading/orders/cover
POST   /api/v2/trading/orders/gtt

GET    /api/v2/trading/positions/
GET    /api/v2/trading/positions/{account_id}
POST   /api/v2/trading/positions/close
POST   /api/v2/trading/positions/close-all
POST   /api/v2/trading/positions/convert
GET    /api/v2/trading/positions/pnl

GET    /api/v2/trading/holdings/
GET    /api/v2/trading/holdings/{account_id}
GET    /api/v2/trading/tradebook/
GET    /api/v2/trading/tradebook/{account_id}
GET    /api/v2/trading/funds/
GET    /api/v2/trading/funds/{account_id}
```

#### Strategy Management
```
GET    /api/v2/strategies/
POST   /api/v2/strategies/
GET    /api/v2/strategies/{strategy_id}
PUT    /api/v2/strategies/{strategy_id}
DELETE /api/v2/strategies/{strategy_id}
POST   /api/v2/strategies/{strategy_id}/activate
POST   /api/v2/strategies/{strategy_id}/deactivate
POST   /api/v2/strategies/{strategy_id}/panic
GET    /api/v2/strategies/{strategy_id}/performance
GET    /api/v2/strategies/{strategy_id}/positions
GET    /api/v2/strategies/{strategy_id}/orders
POST   /api/v2/strategies/{strategy_id}/clone
GET    /api/v2/strategies/templates/
POST   /api/v2/strategies/templates/
```

#### TradingView Signal Management
```
GET    /api/v2/signals/
POST   /api/v2/signals/
GET    /api/v2/signals/{signal_id}
PUT    /api/v2/signals/{signal_id}
DELETE /api/v2/signals/{signal_id}
POST   /api/v2/signals/{signal_id}/activate
POST   /api/v2/signals/{signal_id}/deactivate
GET    /api/v2/signals/{signal_id}/logs
GET    /api/v2/signals/{signal_id}/analytics
POST   /api/v2/signals/{signal_id}/test
```

#### Trading Algo Configuration
```
GET    /api/v2/algos/
POST   /api/v2/algos/
GET    /api/v2/algos/{algo_id}
PUT    /api/v2/algos/{algo_id}
DELETE /api/v2/algos/{algo_id}
POST   /api/v2/algos/{algo_id}/activate
POST   /api/v2/algos/{algo_id}/deactivate
GET    /api/v2/algos/{algo_id}/performance
POST   /api/v2/algos/{algo_id}/test
GET    /api/v2/algos/strike-helpers
```

#### Walk Forward Testing
```
GET    /api/v2/walkforward/sessions/
POST   /api/v2/walkforward/sessions/
GET    /api/v2/walkforward/sessions/{session_id}
DELETE /api/v2/walkforward/sessions/{session_id}
POST   /api/v2/walkforward/sessions/{session_id}/start
POST   /api/v2/walkforward/sessions/{session_id}/stop
POST   /api/v2/walkforward/sessions/{session_id}/square-off
GET    /api/v2/walkforward/sessions/{session_id}/trades
GET    /api/v2/walkforward/sessions/{session_id}/positions
GET    /api/v2/walkforward/sessions/{session_id}/analytics
GET    /api/v2/walkforward/sessions/{session_id}/export
```

#### Market Data
```
GET    /api/v2/market/quotes/{symbol}
POST   /api/v2/market/quotes/bulk
GET    /api/v2/market/depth/{symbol}
GET    /api/v2/market/history/{symbol}
GET    /api/v2/market/option-chain/{symbol}
GET    /api/v2/market/contracts/search
GET    /api/v2/market/contracts/download
GET    /api/v2/market/exchanges
GET    /api/v2/market/indices
GET    /api/v2/market/intervals
```

#### Risk Management
```
GET    /api/v2/risk/limits/
POST   /api/v2/risk/limits/
PUT    /api/v2/risk/limits/{limit_id}
DELETE /api/v2/risk/limits/{limit_id}
GET    /api/v2/risk/exposure/
GET    /api/v2/risk/exposure/{account_id}
POST   /api/v2/risk/panic/global
POST   /api/v2/risk/panic/strategy/{strategy_id}
POST   /api/v2/risk/panic/account/{account_id}
GET    /api/v2/risk/violations/
POST   /api/v2/risk/limits/validate
```

#### Analytics & Reporting
```
GET    /api/v2/analytics/dashboard/
GET    /api/v2/analytics/pnl/{account_id}
GET    /api/v2/analytics/performance/{strategy_id}
GET    /api/v2/analytics/reports/daily
GET    /api/v2/analytics/reports/monthly
GET    /api/v2/analytics/reports/custom
POST   /api/v2/analytics/export/trades
POST   /api/v2/analytics/export/pnl
GET    /api/v2/analytics/metrics/latency
GET    /api/v2/analytics/metrics/execution
```

#### Webhook Endpoints
```
POST   /api/v2/webhooks/tradingview
POST   /api/v2/webhooks/custom/{webhook_id}
GET    /api/v2/webhooks/logs/
GET    /api/v2/webhooks/{webhook_id}/test
POST   /api/v2/webhooks/{webhook_id}/replay
```

#### System & Admin
```
GET    /api/v2/system/health
GET    /api/v2/system/status
GET    /api/v2/system/version
GET    /api/v2/system/brokers/status
GET    /api/v2/system/performance
POST   /api/v2/system/restart-services
GET    /api/v2/admin/users/
GET    /api/v2/admin/users/{user_id}
PUT    /api/v2/admin/users/{user_id}
POST   /api/v2/admin/users/{user_id}/suspend
GET    /api/v2/admin/logs/
```

- **WebSocket Streams**:
  - Real-time order updates
  - Position changes
  - Market data feed
  - Strategy alerts
  - Signal notifications
  - Account updates
  - System notifications

- **Webhook Support**:
  - TradingView integration
  - Custom webhook formats
  - Webhook authentication
  - Payload transformation
  - Retry mechanisms
  - Webhook analytics
  - Multi-source webhook support

### Technical Architecture

#### 1. Microservices Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Load Balancer (Traefik)                   │
└─────────────────┬───────────────────────┬──────────────────┘
                  │                       │
        ┌─────────▼──────────┐  ┌────────▼──────────┐
        │   NextJS Frontend  │  │  FastAPI Gateway  │
        │   (Shadcn/ui)      │  │   (API Router)    │
        └─────────┬──────────┘  └────────┬──────────┘
                  │                       │
                  └───────────┬───────────┘
                              │
                ┌─────────────▼────────────────┐
                │      Service Mesh            │
                └──┬──────┬──────┬──────┬─────┘
                   │      │      │      │
        ┌──────────▼──┐ ┌─▼────┐ ┌─────▼─────┐ ┌─────▼──────┐
        │Trading      │ │Risk  │ │Strategy   │ │Market Data │
        │Service      │ │Service│ │Service    │ │Service     │
        └──────┬──────┘ └──┬───┘ └─────┬─────┘ └─────┬──────┘
               │           │            │              │
        ┌──────▼──────────▼────────────▼──────────────▼──────┐
        │                   Data Layer                        │
        │  PostgreSQL │ Redis │ QuestDB │ Message Queue      │
        └─────────────────────────────────────────────────────┘
```

#### 2. Database Schema (Key Tables)

```sql
-- Users and Authentication
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    mfa_secret VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Trading Accounts
CREATE TABLE trading_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    broker VARCHAR(50) NOT NULL,
    account_name VARCHAR(100) NOT NULL,
    encrypted_credentials JSONB NOT NULL,
    is_master BOOLEAN DEFAULT false,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Strategy Templates
CREATE TABLE strategy_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL, -- 'option', 'equity', 'future'
    template_config JSONB NOT NULL,
    risk_params JSONB NOT NULL,
    is_active BOOLEAN DEFAULT true,
    version INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Strategy Instances
CREATE TABLE strategy_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id UUID REFERENCES strategy_templates(id),
    user_id UUID REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    config JSONB NOT NULL,
    stop_loss DECIMAL(10,2),
    target_profit DECIMAL(10,2),
    trailing_sl_config JSONB,
    is_active BOOLEAN DEFAULT true,
    panic_triggered BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Orders with Enhanced Tracking
CREATE TABLE orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    account_id UUID REFERENCES trading_accounts(id),
    strategy_id UUID REFERENCES strategy_instances(id),
    symbol VARCHAR(100) NOT NULL,
    order_type VARCHAR(20) NOT NULL,
    product_type VARCHAR(20) NOT NULL,
    quantity INTEGER NOT NULL,
    price DECIMAL(10,2),
    trigger_price DECIMAL(10,2),
    status VARCHAR(50) NOT NULL,
    broker_order_id VARCHAR(255),
    parent_order_id UUID,
    is_gtt BOOLEAN DEFAULT false,
    execution_time BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Position Tracking
CREATE TABLE positions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    account_id UUID REFERENCES trading_accounts(id),
    strategy_id UUID REFERENCES strategy_instances(id),
    symbol VARCHAR(100) NOT NULL,
    quantity INTEGER NOT NULL,
    average_price DECIMAL(10,2),
    current_price DECIMAL(10,2),
    pnl DECIMAL(10,2),
    mtm DECIMAL(10,2),
    stop_loss DECIMAL(10,2),
    target DECIMAL(10,2),
    trailing_sl_trigger DECIMAL(10,2),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Trading Algos for TradingView Integration
CREATE TABLE trading_algos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    instrument_type VARCHAR(50) NOT NULL, -- 'options', 'futures', 'equity'
    legs JSONB NOT NULL, -- Multi-leg configuration
    strike_selection_logic JSONB, -- ATM±X, OTM±X, delta-based
    quantity INTEGER NOT NULL,
    product_type VARCHAR(20) NOT NULL,
    algo_type VARCHAR(20) DEFAULT 'signal', -- 'signal', 'scheduled', 'manual'
    is_active BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Signal Groups for TradingView Alerts
CREATE TABLE signal_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    source VARCHAR(50) DEFAULT 'tradingview',
    webhook_url VARCHAR(500) UNIQUE NOT NULL,
    webhook_secret VARCHAR(255) NOT NULL,
    max_signals_per_day INTEGER DEFAULT 10,
    expiry_date DATE,
    is_active BOOLEAN DEFAULT false,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Algo-Signal Mappings
CREATE TABLE algo_signal_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_group_id UUID REFERENCES signal_groups(id),
    algo_id UUID REFERENCES trading_algos(id),
    entry_json_template JSONB NOT NULL,
    exit_json_template JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Signal Reception Logs
CREATE TABLE signal_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_group_id UUID REFERENCES signal_groups(id),
    payload JSONB NOT NULL,
    signal_type VARCHAR(20) NOT NULL, -- 'entry', 'exit'
    processed BOOLEAN DEFAULT false,
    success BOOLEAN,
    error_message TEXT,
    processing_time_ms INTEGER,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- TradingView Alert Tracking
CREATE TABLE tradingview_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_group_id UUID REFERENCES signal_groups(id),
    alert_name VARCHAR(255) NOT NULL,
    condition_text TEXT,
    trigger_type VARCHAR(50), -- 'once_per_bar_close', 'once_per_bar'
    last_triggered TIMESTAMP,
    trigger_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Walk Forward Testing Sessions
CREATE TABLE walkforward_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    strategy_id UUID REFERENCES strategy_instances(id),
    session_name VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'running', -- 'running', 'stopped', 'completed'
    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP,
    initial_capital DECIMAL(15,2) DEFAULT 1000000,
    current_mtm DECIMAL(15,2) DEFAULT 0,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    max_drawdown DECIMAL(15,2) DEFAULT 0,
    include_costs BOOLEAN DEFAULT false,
    brokerage_rate DECIMAL(5,4) DEFAULT 0.0003,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Walk Forward Test Trades
CREATE TABLE walkforward_trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES walkforward_sessions(id),
    trade_id VARCHAR(100) NOT NULL,
    symbol VARCHAR(100) NOT NULL,
    side VARCHAR(10) NOT NULL, -- 'buy', 'sell'
    quantity INTEGER NOT NULL,
    entry_price DECIMAL(10,2) NOT NULL,
    exit_price DECIMAL(10,2),
    entry_time TIMESTAMP NOT NULL,
    exit_time TIMESTAMP,
    pnl DECIMAL(10,2) DEFAULT 0,
    gross_pnl DECIMAL(10,2) DEFAULT 0,
    brokerage DECIMAL(10,2) DEFAULT 0,
    taxes DECIMAL(10,2) DEFAULT 0,
    status VARCHAR(50) DEFAULT 'open', -- 'open', 'closed', 'partial'
    order_type VARCHAR(20), -- 'market', 'limit', 'sl', 'sl-m'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Walk Forward Test Analytics
CREATE TABLE walkforward_analytics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES walkforward_sessions(id),
    date DATE NOT NULL,
    daily_pnl DECIMAL(15,2) DEFAULT 0,
    cumulative_pnl DECIMAL(15,2) DEFAULT 0,
    trades_count INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    max_drawdown DECIMAL(15,2) DEFAULT 0,
    margin_used DECIMAL(15,2) DEFAULT 0,
    volatility DECIMAL(8,4) DEFAULT 0,
    sharpe_ratio DECIMAL(8,4) DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, date)
);

-- Walk Forward Test Positions
CREATE TABLE walkforward_positions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES walkforward_sessions(id),
    symbol VARCHAR(100) NOT NULL,
    quantity INTEGER NOT NULL,
    average_price DECIMAL(10,2) NOT NULL,
    current_price DECIMAL(10,2) NOT NULL,
    unrealized_pnl DECIMAL(10,2) DEFAULT 0,
    margin_required DECIMAL(15,2) DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, symbol)
);
```

### Deployment Architecture

#### Docker Compose Configuration

```yaml
version: '3.8'

services:
  # Frontend
  frontend:
    build: ./frontend
    environment:
      - NEXT_PUBLIC_API_URL=http://api:8000
    ports:
      - "3000:3000"
    depends_on:
      - api

  # API Gateway
  api:
    build: ./backend
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/openalgo
      - REDIS_URL=redis://redis:6379
      - QUESTDB_URL=http://questdb:9000
    ports:
      - "8000:8000"
    depends_on:
      - postgres
      - redis
      - questdb

  # Databases
  postgres:
    image: postgres:15-alpine
    environment:
      - POSTGRES_DB=openalgo
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data

  questdb:
    image: questdb/questdb:latest
    ports:
      - "9000:9000"
      - "9009:9009"
    volumes:
      - questdb_data:/var/lib/questdb

  # Reverse Proxy
  traefik:
    image: traefik:v2.10
    command:
      - "--api.insecure=true"
      - "--providers.docker=true"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
    ports:
      - "80:80"
      - "443:443"
      - "8080:8080"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      - "./traefik/certs:/certs"
    depends_on:
      - frontend
      - api

volumes:
  postgres_data:
  redis_data:
  questdb_data:
```

### Key Differentiators

1. **Multi-Account Self Trading**:
   - Manage 3-4+ accounts seamlessly
   - Cross-broker order replication
   - Account-specific risk management
   - Consolidated reporting

2. **Professional Option Trading**:
   - Visual strategy builder
   - Multi-leg order support
   - Greeks-based analytics
   - Real-time payoff diagrams

3. **Advanced Risk Controls**:
   - Multi-level stop-loss system
   - Strategy and portfolio limits
   - Panic button at every level
   - Real-time MTM tracking

4. **Professional Walk Forward Testing**:
   - Real-time market data from live broker APIs
   - Virtual execution with actual market conditions
   - MTM calculation on real market movements
   - Actual margin requirement calculation
   - Zero-risk validation before live deployment

5. **Enterprise-Grade Infrastructure**:
   - Sub-50ms latency
   - 99.9% uptime SLA
   - Horizontal scalability
   - Professional monitoring

### Performance Targets

1. **Latency**:
   - Order placement: <100ms (95th percentile)
   - WebSocket updates: <50ms
   - Cross-account replication: <200ms
   - API response time: <150ms

2. **Throughput**:
   - 10,000+ concurrent users
   - 100,000+ orders per minute
   - 1M+ WebSocket messages per minute
   - 50+ strategies per user

3. **Reliability**:
   - 99.9% uptime SLA
   - Zero data loss guarantee
   - Automatic failover
   - Self-healing systems

### Success Metrics

1. **User Experience**:
   - Setup time < 5 minutes
   - Strategy creation < 2 minutes
   - Order execution success > 99.5%
   - User satisfaction > 4.5/5

2. **Platform Performance**:
   - System uptime > 99.9%
   - Order latency < 100ms
   - Data accuracy > 99.99%
   - Error rate < 0.1%

3. **Business Metrics**:
   - User retention > 80%
   - Daily active users growth
   - Strategy adoption rate
   - Trading volume growth

### Migration Strategy

1. **Phase 1: Core Platform** (Month 1-2)
   - Multi-account architecture
   - Authentication system
   - Basic trading APIs
   - Broker integrations

2. **Phase 2: Advanced Features** (Month 3-4)
   - Strategy builder
   - Risk management
   - Paper trading
   - Real-time analytics

3. **Phase 3: Professional Tools** (Month 5-6)
   - Option strategies
   - Advanced monitoring
   - Reporting system
   - Performance optimization

4. **Phase 4: Production Ready** (Month 7-8)
   - Security audit
   - Load testing
   - Documentation
   - Deployment automation

### Conclusion

OpenAlgo Enhanced represents a significant evolution from a single-user trading bridge to a professional multi-account trading platform. By focusing on the needs of serious individual traders managing multiple accounts, implementing advanced option strategies, and providing institutional-grade risk controls, the platform will empower traders to execute sophisticated strategies with confidence. The modern architecture ensures scalability, reliability, and performance that matches professional trading desks while remaining accessible to individual traders.