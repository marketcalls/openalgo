# OpenAlgo Desktop - Architecture Design

**Version:** 1.0.0
**Date:** December 2025

---

## 1. System Architecture

### 1.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         OpenAlgo Desktop App                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                         PRESENTATION LAYER                          │ │
│  │  ┌──────────────────────────────────────────────────────────────┐  │ │
│  │  │                    Tauri WebView (WebKit/WebView2)            │  │ │
│  │  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌───────────┐  │  │ │
│  │  │  │ Dashboard  │ │   Orders   │ │  Options   │ │ Settings  │  │  │ │
│  │  │  │   View     │ │   View     │ │   Chain    │ │   View    │  │  │ │
│  │  │  └────────────┘ └────────────┘ └────────────┘ └───────────┘  │  │ │
│  │  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌───────────┐  │  │ │
│  │  │  │ Positions  │ │  Holdings  │ │  Strategy  │ │  Broker   │  │  │ │
│  │  │  │   View     │ │   View     │ │   View     │ │  Login    │  │  │ │
│  │  │  └────────────┘ └────────────┘ └────────────┘ └───────────┘  │  │ │
│  │  └──────────────────────────────────────────────────────────────┘  │ │
│  │                              │                                      │ │
│  │                    Tauri IPC (invoke/listen)                        │ │
│  │                              │                                      │ │
│  └──────────────────────────────┼──────────────────────────────────────┘ │
│                                 │                                        │
│  ┌──────────────────────────────┼──────────────────────────────────────┐ │
│  │                         COMMAND LAYER                               │ │
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐           │ │
│  │  │   Auth    │ │  Orders   │ │  Market   │ │ Portfolio │           │ │
│  │  │ Commands  │ │ Commands  │ │ Commands  │ │ Commands  │           │ │
│  │  └─────┬─────┘ └─────┬─────┘ └─────┬─────┘ └─────┬─────┘           │ │
│  │        │             │             │             │                  │ │
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐           │ │
│  │  │ Strategy  │ │ Settings  │ │  Telegram │ │  Sandbox  │           │ │
│  │  │ Commands  │ │ Commands  │ │ Commands  │ │ Commands  │           │ │
│  │  └─────┬─────┘ └─────┬─────┘ └─────┬─────┘ └─────┬─────┘           │ │
│  └────────┼─────────────┼─────────────┼─────────────┼──────────────────┘ │
│           │             │             │             │                    │
│  ┌────────┴─────────────┴─────────────┴─────────────┴──────────────────┐ │
│  │                         SERVICE LAYER                               │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                │ │
│  │  │ OrderService │ │ MarketService│ │PortfolioSvc  │                │ │
│  │  │  - place     │ │  - quotes    │ │  - positions │                │ │
│  │  │  - modify    │ │  - depth     │ │  - holdings  │                │ │
│  │  │  - cancel    │ │  - history   │ │  - funds     │                │ │
│  │  │  - smart     │ │  - chain     │ │  - orders    │                │ │
│  │  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘                │ │
│  │         │                │                │                         │ │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                │ │
│  │  │ StrategyServ │ │ TelegramServ │ │  AuthService │                │ │
│  │  │  - scheduler │ │  - bot       │ │  - login     │                │ │
│  │  │  - runner    │ │  - commands  │ │  - session   │                │ │
│  │  │  - state     │ │  - alerts    │ │  - tokens    │                │ │
│  │  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘                │ │
│  └─────────┼────────────────┼────────────────┼─────────────────────────┘ │
│            │                │                │                           │
│  ┌─────────┴────────────────┴────────────────┴─────────────────────────┐ │
│  │                         BROKER LAYER                                │ │
│  │  ┌─────────────────────────────────────────────────────────────┐   │ │
│  │  │                     BrokerRouter                             │   │ │
│  │  │  - select_broker(user) -> impl BrokerAdapter                 │   │ │
│  │  │  - route_order(order) -> BrokerResponse                      │   │ │
│  │  └─────────────────────────────────────────────────────────────┘   │ │
│  │                              │                                      │ │
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐          │ │
│  │  │   Angel   │ │  Zerodha  │ │    Dhan   │ │   Fyers   │ ...24+   │ │
│  │  │  Adapter  │ │  Adapter  │ │  Adapter  │ │  Adapter  │          │ │
│  │  └───────────┘ └───────────┘ └───────────┘ └───────────┘          │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│            │                │                │                           │
│  ┌─────────┴────────────────┴────────────────┴─────────────────────────┐ │
│  │                         DATA LAYER                                  │ │
│  │  ┌──────────────────────┐    ┌──────────────────────────────────┐  │ │
│  │  │    SQLite + SQLCipher │    │      WebSocket Connection Pool    │  │ │
│  │  │  ┌────────────────┐  │    │  ┌────────────────────────────┐  │  │ │
│  │  │  │  auth.db       │  │    │  │  Angel WS   Zerodha WS     │  │  │ │
│  │  │  │  orders.db     │  │    │  │  Dhan WS    Fyers WS       │  │  │ │
│  │  │  │  settings.db   │  │    │  │  ...                       │  │  │ │
│  │  │  │  strategies.db │  │    │  └────────────────────────────┘  │  │ │
│  │  │  └────────────────┘  │    └──────────────────────────────────┘  │ │
│  │  └──────────────────────┘                                          │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Module Specifications

### 2.1 Commands Module (`src/commands/`)

Each command module exposes Tauri IPC handlers:

```rust
// commands/mod.rs
pub mod auth;
pub mod orders;
pub mod market_data;
pub mod portfolio;
pub mod strategy;
pub mod settings;
pub mod telegram;
pub mod sandbox;

// Re-export all command handlers for registration
pub use auth::*;
pub use orders::*;
pub use market_data::*;
pub use portfolio::*;
pub use strategy::*;
pub use settings::*;
pub use telegram::*;
pub use sandbox::*;
```

#### 2.1.1 Auth Commands (`commands/auth.rs`)

```rust
use tauri::State;
use crate::services::AuthService;
use crate::error::AppResult;

#[tauri::command]
pub async fn login(
    username: String,
    password: String,
    auth_service: State<'_, AuthService>,
) -> AppResult<LoginResponse> {
    auth_service.login(&username, &password).await
}

#[tauri::command]
pub async fn logout(
    auth_service: State<'_, AuthService>,
) -> AppResult<()> {
    auth_service.logout().await
}

#[tauri::command]
pub async fn get_session(
    auth_service: State<'_, AuthService>,
) -> AppResult<Option<Session>> {
    auth_service.get_current_session().await
}

#[tauri::command]
pub async fn broker_login(
    broker: String,
    credentials: BrokerCredentials,
    auth_service: State<'_, AuthService>,
) -> AppResult<BrokerSession> {
    auth_service.broker_login(&broker, credentials).await
}

#[tauri::command]
pub async fn broker_callback(
    broker: String,
    request_token: String,
    auth_service: State<'_, AuthService>,
) -> AppResult<BrokerSession> {
    auth_service.handle_broker_callback(&broker, &request_token).await
}
```

#### 2.1.2 Order Commands (`commands/orders.rs`)

```rust
#[tauri::command]
pub async fn place_order(
    order: PlaceOrderRequest,
    order_service: State<'_, OrderService>,
) -> AppResult<OrderResponse> {
    // Validation
    order.validate()?;

    // Execute
    order_service.place_order(order).await
}

#[tauri::command]
pub async fn place_smart_order(
    order: SmartOrderRequest,
    order_service: State<'_, OrderService>,
) -> AppResult<OrderResponse> {
    order_service.place_smart_order(order).await
}

#[tauri::command]
pub async fn modify_order(
    order_id: String,
    modifications: ModifyOrderRequest,
    order_service: State<'_, OrderService>,
) -> AppResult<OrderResponse> {
    order_service.modify_order(&order_id, modifications).await
}

#[tauri::command]
pub async fn cancel_order(
    order_id: String,
    order_service: State<'_, OrderService>,
) -> AppResult<CancelResponse> {
    order_service.cancel_order(&order_id).await
}

#[tauri::command]
pub async fn cancel_all_orders(
    order_service: State<'_, OrderService>,
) -> AppResult<BulkCancelResponse> {
    order_service.cancel_all_orders().await
}

#[tauri::command]
pub async fn close_position(
    symbol: String,
    exchange: String,
    product: String,
    order_service: State<'_, OrderService>,
) -> AppResult<ClosePositionResponse> {
    order_service.close_position(&symbol, &exchange, &product).await
}
```

#### 2.1.3 Market Data Commands (`commands/market_data.rs`)

```rust
#[tauri::command]
pub async fn get_quotes(
    symbol: String,
    exchange: String,
    market_service: State<'_, MarketService>,
) -> AppResult<QuoteData> {
    market_service.get_quotes(&symbol, &exchange).await
}

#[tauri::command]
pub async fn get_depth(
    symbol: String,
    exchange: String,
    market_service: State<'_, MarketService>,
) -> AppResult<DepthData> {
    market_service.get_depth(&symbol, &exchange).await
}

#[tauri::command]
pub async fn get_history(
    symbol: String,
    exchange: String,
    interval: String,
    start_date: String,
    end_date: String,
    market_service: State<'_, MarketService>,
) -> AppResult<Vec<Candle>> {
    market_service.get_history(&symbol, &exchange, &interval, &start_date, &end_date).await
}

#[tauri::command]
pub async fn get_option_chain(
    symbol: String,
    expiry: String,
    market_service: State<'_, MarketService>,
) -> AppResult<OptionChainData> {
    market_service.get_option_chain(&symbol, &expiry).await
}

#[tauri::command]
pub async fn subscribe_quotes(
    symbols: Vec<SubscriptionRequest>,
    window: tauri::Window,
    market_service: State<'_, MarketService>,
) -> AppResult<()> {
    market_service.subscribe(symbols, window).await
}

#[tauri::command]
pub async fn unsubscribe_quotes(
    symbols: Vec<String>,
    market_service: State<'_, MarketService>,
) -> AppResult<()> {
    market_service.unsubscribe(symbols).await
}
```

---

### 2.2 Services Module (`src/services/`)

#### 2.2.1 Service Architecture

```rust
// services/mod.rs
use std::sync::Arc;
use tokio::sync::RwLock;

pub mod auth_service;
pub mod order_service;
pub mod market_service;
pub mod portfolio_service;
pub mod strategy_service;
pub mod telegram_service;

pub use auth_service::AuthService;
pub use order_service::OrderService;
pub use market_service::MarketService;
pub use portfolio_service::PortfolioService;
pub use strategy_service::StrategyService;
pub use telegram_service::TelegramService;

/// Application state containing all services
pub struct AppState {
    pub auth: Arc<AuthService>,
    pub orders: Arc<OrderService>,
    pub market: Arc<MarketService>,
    pub portfolio: Arc<PortfolioService>,
    pub strategy: Arc<StrategyService>,
    pub telegram: Arc<TelegramService>,
    pub db: Arc<Database>,
    pub broker_router: Arc<RwLock<BrokerRouter>>,
}

impl AppState {
    pub async fn new(config: AppConfig) -> Result<Self> {
        let db = Arc::new(Database::new(&config.database_path)?);
        let broker_router = Arc::new(RwLock::new(BrokerRouter::new()));

        Ok(Self {
            auth: Arc::new(AuthService::new(db.clone())),
            orders: Arc::new(OrderService::new(db.clone(), broker_router.clone())),
            market: Arc::new(MarketService::new(broker_router.clone())),
            portfolio: Arc::new(PortfolioService::new(db.clone(), broker_router.clone())),
            strategy: Arc::new(StrategyService::new(db.clone())),
            telegram: Arc::new(TelegramService::new(db.clone())),
            db,
            broker_router,
        })
    }
}
```

#### 2.2.2 Order Service (`services/order_service.rs`)

```rust
use crate::brokers::{BrokerRouter, BrokerAdapter};
use crate::database::Database;
use crate::models::*;

pub struct OrderService {
    db: Arc<Database>,
    broker_router: Arc<RwLock<BrokerRouter>>,
}

impl OrderService {
    pub fn new(db: Arc<Database>, broker_router: Arc<RwLock<BrokerRouter>>) -> Self {
        Self { db, broker_router }
    }

    pub async fn place_order(&self, request: PlaceOrderRequest) -> AppResult<OrderResponse> {
        // 1. Validate request
        self.validate_order(&request)?;

        // 2. Get broker adapter
        let router = self.broker_router.read().await;
        let broker = router.get_current_broker()?;

        // 3. Transform to broker-specific format
        let broker_request = broker.transform_order_request(&request)?;

        // 4. Place order via broker API
        let broker_response = broker.place_order(broker_request).await?;

        // 5. Transform response to unified format
        let response = broker.transform_order_response(broker_response)?;

        // 6. Store in local database
        self.db.insert_order(&response).await?;

        // 7. Return response
        Ok(response)
    }

    pub async fn place_smart_order(&self, request: SmartOrderRequest) -> AppResult<OrderResponse> {
        // Calculate position size based on risk parameters
        let position_size = self.calculate_position_size(&request)?;

        // Convert to regular order
        let order = PlaceOrderRequest {
            symbol: request.symbol,
            exchange: request.exchange,
            action: request.action,
            quantity: position_size,
            product: request.product,
            price_type: request.price_type,
            price: request.price,
            trigger_price: request.trigger_price,
            strategy: request.strategy,
        };

        self.place_order(order).await
    }

    fn validate_order(&self, request: &PlaceOrderRequest) -> AppResult<()> {
        // Validate exchange
        if !VALID_EXCHANGES.contains(&request.exchange.as_str()) {
            return Err(AppError::ValidationError(
                format!("Invalid exchange: {}", request.exchange)
            ));
        }

        // Validate action
        if !["BUY", "SELL"].contains(&request.action.as_str()) {
            return Err(AppError::ValidationError(
                format!("Invalid action: {}", request.action)
            ));
        }

        // Validate quantity
        if request.quantity <= 0 {
            return Err(AppError::ValidationError(
                "Quantity must be positive".to_string()
            ));
        }

        // Validate symbol exists in master contract
        // (implementation depends on cached master contracts)

        Ok(())
    }

    fn calculate_position_size(&self, request: &SmartOrderRequest) -> AppResult<i32> {
        // Smart order position sizing logic
        // Based on: position_size, current_holdings, risk_per_trade

        let current_position = self.get_current_position(&request.symbol, &request.exchange).await?;
        let target_size = request.position_size;

        let quantity = match request.action.as_str() {
            "BUY" => target_size - current_position,
            "SELL" => current_position - target_size,
            _ => return Err(AppError::ValidationError("Invalid action".to_string())),
        };

        Ok(quantity.abs())
    }
}
```

#### 2.2.3 Market Service (`services/market_service.rs`)

```rust
use tokio::sync::broadcast;
use dashmap::DashMap;

pub struct MarketService {
    broker_router: Arc<RwLock<BrokerRouter>>,
    subscriptions: Arc<DashMap<String, broadcast::Sender<QuoteUpdate>>>,
    quote_cache: Arc<DashMap<String, QuoteData>>,
}

impl MarketService {
    pub async fn get_quotes(&self, symbol: &str, exchange: &str) -> AppResult<QuoteData> {
        // Check cache first
        let cache_key = format!("{}:{}", exchange, symbol);
        if let Some(cached) = self.quote_cache.get(&cache_key) {
            if cached.is_fresh() {
                return Ok(cached.clone());
            }
        }

        // Fetch from broker
        let router = self.broker_router.read().await;
        let broker = router.get_current_broker()?;
        let quote = broker.get_quotes(symbol, exchange).await?;

        // Update cache
        self.quote_cache.insert(cache_key, quote.clone());

        Ok(quote)
    }

    pub async fn subscribe(
        &self,
        symbols: Vec<SubscriptionRequest>,
        window: tauri::Window,
    ) -> AppResult<()> {
        let router = self.broker_router.read().await;
        let broker = router.get_current_broker()?;

        // Create subscription with broker's WebSocket
        let mut ws = broker.create_websocket_connection().await?;

        for sub in symbols {
            let key = format!("{}:{}", sub.exchange, sub.symbol);

            // Create broadcast channel for this symbol
            let (tx, _rx) = broadcast::channel(100);
            self.subscriptions.insert(key.clone(), tx.clone());

            // Subscribe via WebSocket
            ws.subscribe(&sub.symbol, &sub.exchange, sub.mode).await?;
        }

        // Spawn task to receive and broadcast updates
        let subscriptions = self.subscriptions.clone();
        let window_clone = window.clone();

        tokio::spawn(async move {
            while let Some(update) = ws.next().await {
                if let Ok(quote) = update {
                    let key = format!("{}:{}", quote.exchange, quote.symbol);

                    // Emit to frontend
                    let _ = window_clone.emit(&format!("quote:{}", key), &quote);

                    // Broadcast to internal subscribers
                    if let Some(tx) = subscriptions.get(&key) {
                        let _ = tx.send(quote.into());
                    }
                }
            }
        });

        Ok(())
    }
}
```

---

### 2.3 Brokers Module (`src/brokers/`)

#### 2.3.1 Broker Trait Definition

```rust
// brokers/mod.rs
use async_trait::async_trait;
use crate::models::*;
use crate::error::AppResult;

/// Trait that all broker adapters must implement
#[async_trait]
pub trait BrokerAdapter: Send + Sync {
    /// Get broker identifier
    fn broker_id(&self) -> &str;

    /// Get broker display name
    fn broker_name(&self) -> &str;

    // ═══════════════════════════════════════════════════════════════
    // AUTHENTICATION
    // ═══════════════════════════════════════════════════════════════

    /// Get OAuth login URL
    fn get_login_url(&self) -> String;

    /// Handle OAuth callback and get access token
    async fn handle_callback(&mut self, request_token: &str) -> AppResult<BrokerSession>;

    /// Check if session is valid
    async fn is_session_valid(&self) -> bool;

    /// Refresh session if expired
    async fn refresh_session(&mut self) -> AppResult<()>;

    // ═══════════════════════════════════════════════════════════════
    // ORDER MANAGEMENT
    // ═══════════════════════════════════════════════════════════════

    /// Place a new order
    async fn place_order(&self, order: BrokerOrderRequest) -> AppResult<BrokerOrderResponse>;

    /// Modify an existing order
    async fn modify_order(&self, order_id: &str, order: BrokerOrderRequest) -> AppResult<BrokerOrderResponse>;

    /// Cancel an order
    async fn cancel_order(&self, order_id: &str) -> AppResult<BrokerCancelResponse>;

    // ═══════════════════════════════════════════════════════════════
    // PORTFOLIO
    // ═══════════════════════════════════════════════════════════════

    /// Get order book
    async fn get_orderbook(&self) -> AppResult<Vec<BrokerOrder>>;

    /// Get trade book
    async fn get_tradebook(&self) -> AppResult<Vec<BrokerTrade>>;

    /// Get positions
    async fn get_positions(&self) -> AppResult<Vec<BrokerPosition>>;

    /// Get holdings
    async fn get_holdings(&self) -> AppResult<Vec<BrokerHolding>>;

    /// Get funds/margins
    async fn get_funds(&self) -> AppResult<BrokerFunds>;

    // ═══════════════════════════════════════════════════════════════
    // MARKET DATA
    // ═══════════════════════════════════════════════════════════════

    /// Get real-time quote
    async fn get_quotes(&self, symbol: &str, exchange: &str) -> AppResult<QuoteData>;

    /// Get market depth
    async fn get_depth(&self, symbol: &str, exchange: &str) -> AppResult<DepthData>;

    /// Get historical candles
    async fn get_history(
        &self,
        symbol: &str,
        exchange: &str,
        interval: &str,
        start: &str,
        end: &str,
    ) -> AppResult<Vec<Candle>>;

    // ═══════════════════════════════════════════════════════════════
    // WEBSOCKET STREAMING
    // ═══════════════════════════════════════════════════════════════

    /// Create WebSocket connection for streaming
    async fn create_websocket(&self) -> AppResult<Box<dyn BrokerWebSocket>>;

    // ═══════════════════════════════════════════════════════════════
    // SYMBOL MAPPING
    // ═══════════════════════════════════════════════════════════════

    /// Download and parse master contracts
    async fn download_master_contracts(&self) -> AppResult<Vec<MasterContract>>;

    /// Convert OpenAlgo symbol to broker symbol
    fn to_broker_symbol(&self, symbol: &str, exchange: &str) -> AppResult<String>;

    /// Convert broker symbol to OpenAlgo symbol
    fn to_openalgo_symbol(&self, broker_symbol: &str) -> AppResult<(String, String)>;

    // ═══════════════════════════════════════════════════════════════
    // DATA TRANSFORMATION
    // ═══════════════════════════════════════════════════════════════

    /// Transform unified order request to broker format
    fn transform_order_request(&self, order: &PlaceOrderRequest) -> AppResult<BrokerOrderRequest>;

    /// Transform broker order response to unified format
    fn transform_order_response(&self, response: BrokerOrderResponse) -> AppResult<OrderResponse>;

    /// Transform broker position to unified format
    fn transform_position(&self, position: BrokerPosition) -> Position;
}

/// WebSocket trait for streaming market data
#[async_trait]
pub trait BrokerWebSocket: Send {
    async fn subscribe(&mut self, symbol: &str, exchange: &str, mode: SubscriptionMode) -> AppResult<()>;
    async fn unsubscribe(&mut self, symbol: &str, exchange: &str) -> AppResult<()>;
    async fn next(&mut self) -> Option<AppResult<QuoteUpdate>>;
    async fn close(&mut self) -> AppResult<()>;
}
```

#### 2.3.2 Broker Router

```rust
// brokers/router.rs
use std::collections::HashMap;
use parking_lot::RwLock;

pub struct BrokerRouter {
    adapters: HashMap<String, Box<dyn BrokerAdapter>>,
    current_broker: Option<String>,
    sessions: HashMap<String, BrokerSession>,
}

impl BrokerRouter {
    pub fn new() -> Self {
        let mut adapters: HashMap<String, Box<dyn BrokerAdapter>> = HashMap::new();

        // Register all broker adapters
        adapters.insert("angel".to_string(), Box::new(AngelAdapter::new()));
        adapters.insert("zerodha".to_string(), Box::new(ZerodhaAdapter::new()));
        adapters.insert("dhan".to_string(), Box::new(DhanAdapter::new()));
        adapters.insert("fyers".to_string(), Box::new(FyersAdapter::new()));
        // ... register all 24+ brokers

        Self {
            adapters,
            current_broker: None,
            sessions: HashMap::new(),
        }
    }

    pub fn set_current_broker(&mut self, broker: &str) -> AppResult<()> {
        if !self.adapters.contains_key(broker) {
            return Err(AppError::BrokerNotFound(broker.to_string()));
        }
        self.current_broker = Some(broker.to_string());
        Ok(())
    }

    pub fn get_current_broker(&self) -> AppResult<&dyn BrokerAdapter> {
        let broker_id = self.current_broker.as_ref()
            .ok_or(AppError::NoBrokerSelected)?;

        self.adapters.get(broker_id)
            .map(|b| b.as_ref())
            .ok_or(AppError::BrokerNotFound(broker_id.clone()))
    }

    pub fn get_broker(&self, broker_id: &str) -> AppResult<&dyn BrokerAdapter> {
        self.adapters.get(broker_id)
            .map(|b| b.as_ref())
            .ok_or(AppError::BrokerNotFound(broker_id.to_string()))
    }

    pub fn list_brokers(&self) -> Vec<BrokerInfo> {
        self.adapters.values()
            .map(|adapter| BrokerInfo {
                id: adapter.broker_id().to_string(),
                name: adapter.broker_name().to_string(),
                is_connected: self.sessions.contains_key(adapter.broker_id()),
            })
            .collect()
    }
}
```

#### 2.3.3 Angel Broker Implementation (Example)

```rust
// brokers/angel/mod.rs
use reqwest::Client;
use serde::{Deserialize, Serialize};

pub struct AngelAdapter {
    client: Client,
    api_key: String,
    client_code: Option<String>,
    access_token: Option<String>,
    refresh_token: Option<String>,
    feed_token: Option<String>,
}

impl AngelAdapter {
    const BASE_URL: &'static str = "https://apiconnect.angelbroking.com";
    const WS_URL: &'static str = "wss://smartapisocket.angelone.in/smart-stream";

    pub fn new() -> Self {
        Self {
            client: Client::builder()
                .timeout(Duration::from_secs(30))
                .build()
                .unwrap(),
            api_key: String::new(),
            client_code: None,
            access_token: None,
            refresh_token: None,
            feed_token: None,
        }
    }
}

#[async_trait]
impl BrokerAdapter for AngelAdapter {
    fn broker_id(&self) -> &str { "angel" }
    fn broker_name(&self) -> &str { "Angel One" }

    fn get_login_url(&self) -> String {
        format!(
            "https://smartapi.angelone.in/publisher-login?api_key={}",
            self.api_key
        )
    }

    async fn handle_callback(&mut self, request_token: &str) -> AppResult<BrokerSession> {
        #[derive(Serialize)]
        struct LoginRequest {
            clientcode: String,
            password: String,
            totp: String,
        }

        #[derive(Deserialize)]
        struct LoginResponse {
            status: bool,
            message: String,
            data: Option<LoginData>,
        }

        #[derive(Deserialize)]
        struct LoginData {
            jwtToken: String,
            refreshToken: String,
            feedToken: String,
        }

        // Parse request_token (contains client_code, password, totp)
        let creds: LoginCredentials = serde_json::from_str(request_token)?;

        let response: LoginResponse = self.client
            .post(format!("{}/rest/auth/angelbroking/user/v1/loginByPassword", Self::BASE_URL))
            .header("X-PrivateKey", &self.api_key)
            .header("Content-Type", "application/json")
            .json(&LoginRequest {
                clientcode: creds.client_code.clone(),
                password: creds.password,
                totp: creds.totp,
            })
            .send()
            .await?
            .json()
            .await?;

        if !response.status {
            return Err(AppError::AuthError(response.message));
        }

        let data = response.data.ok_or(AppError::AuthError("No data in response".into()))?;

        self.client_code = Some(creds.client_code.clone());
        self.access_token = Some(data.jwtToken.clone());
        self.refresh_token = Some(data.refreshToken);
        self.feed_token = Some(data.feedToken);

        Ok(BrokerSession {
            broker_id: "angel".to_string(),
            client_id: creds.client_code,
            access_token: data.jwtToken,
            expires_at: chrono::Utc::now() + chrono::Duration::hours(24),
        })
    }

    async fn place_order(&self, order: BrokerOrderRequest) -> AppResult<BrokerOrderResponse> {
        #[derive(Serialize)]
        struct AngelOrderRequest {
            variety: String,
            tradingsymbol: String,
            symboltoken: String,
            transactiontype: String,
            exchange: String,
            ordertype: String,
            producttype: String,
            duration: String,
            price: String,
            triggerprice: String,
            quantity: String,
        }

        let access_token = self.access_token.as_ref()
            .ok_or(AppError::NotAuthenticated)?;

        let request = AngelOrderRequest {
            variety: "NORMAL".to_string(),
            tradingsymbol: order.symbol.clone(),
            symboltoken: order.token.clone(),
            transactiontype: order.action.clone(),
            exchange: order.exchange.clone(),
            ordertype: self.map_order_type(&order.price_type),
            producttype: self.map_product_type(&order.product),
            duration: "DAY".to_string(),
            price: order.price.to_string(),
            triggerprice: order.trigger_price.to_string(),
            quantity: order.quantity.to_string(),
        };

        let response = self.client
            .post(format!("{}/rest/secure/angelbroking/order/v1/placeOrder", Self::BASE_URL))
            .header("Authorization", format!("Bearer {}", access_token))
            .header("X-PrivateKey", &self.api_key)
            .json(&request)
            .send()
            .await?
            .json::<AngelPlaceOrderResponse>()
            .await?;

        if !response.status {
            return Err(AppError::OrderError(response.message));
        }

        Ok(BrokerOrderResponse {
            order_id: response.data.map(|d| d.orderid).unwrap_or_default(),
            status: "PLACED".to_string(),
            message: response.message,
        })
    }

    async fn get_positions(&self) -> AppResult<Vec<BrokerPosition>> {
        let access_token = self.access_token.as_ref()
            .ok_or(AppError::NotAuthenticated)?;

        let response = self.client
            .get(format!("{}/rest/secure/angelbroking/order/v1/getPosition", Self::BASE_URL))
            .header("Authorization", format!("Bearer {}", access_token))
            .header("X-PrivateKey", &self.api_key)
            .send()
            .await?
            .json::<AngelPositionResponse>()
            .await?;

        Ok(response.data.unwrap_or_default())
    }

    async fn create_websocket(&self) -> AppResult<Box<dyn BrokerWebSocket>> {
        let feed_token = self.feed_token.as_ref()
            .ok_or(AppError::NotAuthenticated)?;
        let client_code = self.client_code.as_ref()
            .ok_or(AppError::NotAuthenticated)?;

        let ws = AngelWebSocket::connect(
            Self::WS_URL,
            client_code,
            feed_token,
            &self.api_key,
        ).await?;

        Ok(Box::new(ws))
    }

    // ... implement remaining trait methods
}
```

---

## 3. Data Flow Diagrams

### 3.1 Order Placement Flow

```
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│   UI    │────►│ Command │────►│ Service │────►│ Router  │────►│ Broker  │
│ (Click) │     │ Handler │     │  Layer  │     │         │     │ Adapter │
└─────────┘     └────┬────┘     └────┬────┘     └────┬────┘     └────┬────┘
                     │               │               │               │
                     │  Validate     │  Business     │  Select       │  HTTP
                     │  Params       │  Logic        │  Broker       │  Request
                     │               │               │               │
                     ▼               ▼               ▼               ▼
              ┌─────────────────────────────────────────────────────────┐
              │                    Broker API                           │
              └─────────────────────────────────────────────────────────┘
                     │               │               │               │
                     │               │               │               │
                     ▼               ▼               ▼               ▼
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│   UI    │◄────│  Event  │◄────│   DB    │◄────│Transform│◄────│Response │
│ Update  │     │  Emit   │     │  Store  │     │ Response│     │         │
└─────────┘     └─────────┘     └─────────┘     └─────────┘     └─────────┘
```

### 3.2 Real-time Quote Subscription Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              SUBSCRIPTION                                 │
└──────────────────────────────────────────────────────────────────────────┘

  UI                    Tauri                  Service                Broker WS
   │                      │                      │                        │
   │  subscribe_quotes    │                      │                        │
   ├─────────────────────►│                      │                        │
   │                      │  MarketService       │                        │
   │                      ├─────────────────────►│                        │
   │                      │                      │  create_websocket()   │
   │                      │                      ├───────────────────────►│
   │                      │                      │                        │
   │                      │                      │  ◄─────WS Connected────│
   │                      │                      │                        │
   │                      │                      │  subscribe(symbols)    │
   │                      │                      ├───────────────────────►│
   │                      │                      │                        │
   │                      │                      │  ◄──ACK (subscribed)───│
   │  ◄───Ok()────────────│◄─────Ok()───────────│                        │
   │                      │                      │                        │

┌──────────────────────────────────────────────────────────────────────────┐
│                              STREAMING                                    │
└──────────────────────────────────────────────────────────────────────────┘

   │                      │                      │                        │
   │                      │                      │  ◄────Quote Update─────│
   │                      │                      │                        │
   │                      │  emit("quote:NSE:    │                        │
   │  ◄───Event───────────│  SBIN", data)        │                        │
   │                      │◄─────────────────────│                        │
   │                      │                      │  ◄────Quote Update─────│
   │  ◄───Event───────────│◄─────────────────────│                        │
   │                      │                      │                        │
   ▼                      ▼                      ▼                        ▼
```

---

## 4. Error Handling

### 4.1 Error Types

```rust
// error.rs
use thiserror::Error;

#[derive(Error, Debug)]
pub enum AppError {
    // Authentication Errors
    #[error("Not authenticated")]
    NotAuthenticated,

    #[error("Authentication failed: {0}")]
    AuthError(String),

    #[error("Session expired")]
    SessionExpired,

    // Broker Errors
    #[error("Broker not found: {0}")]
    BrokerNotFound(String),

    #[error("No broker selected")]
    NoBrokerSelected,

    #[error("Broker API error: {0}")]
    BrokerApiError(String),

    // Order Errors
    #[error("Order validation failed: {0}")]
    ValidationError(String),

    #[error("Order placement failed: {0}")]
    OrderError(String),

    #[error("Order not found: {0}")]
    OrderNotFound(String),

    // Market Data Errors
    #[error("Symbol not found: {0}")]
    SymbolNotFound(String),

    #[error("Market data unavailable: {0}")]
    MarketDataError(String),

    // Database Errors
    #[error("Database error: {0}")]
    DatabaseError(#[from] rusqlite::Error),

    // Network Errors
    #[error("Network error: {0}")]
    NetworkError(#[from] reqwest::Error),

    // WebSocket Errors
    #[error("WebSocket error: {0}")]
    WebSocketError(String),

    // Serialization Errors
    #[error("Serialization error: {0}")]
    SerializationError(#[from] serde_json::Error),

    // Generic Errors
    #[error("Internal error: {0}")]
    InternalError(String),
}

pub type AppResult<T> = Result<T, AppError>;

// Convert AppError to Tauri-compatible error
impl From<AppError> for tauri::Error {
    fn from(err: AppError) -> Self {
        tauri::Error::Anyhow(anyhow::anyhow!(err.to_string()))
    }
}

// Serialize error for frontend
impl serde::Serialize for AppError {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        use serde::ser::SerializeStruct;
        let mut state = serializer.serialize_struct("AppError", 2)?;
        state.serialize_field("code", &self.error_code())?;
        state.serialize_field("message", &self.to_string())?;
        state.end()
    }
}

impl AppError {
    pub fn error_code(&self) -> &'static str {
        match self {
            AppError::NotAuthenticated => "NOT_AUTHENTICATED",
            AppError::AuthError(_) => "AUTH_ERROR",
            AppError::SessionExpired => "SESSION_EXPIRED",
            AppError::BrokerNotFound(_) => "BROKER_NOT_FOUND",
            AppError::NoBrokerSelected => "NO_BROKER_SELECTED",
            AppError::BrokerApiError(_) => "BROKER_API_ERROR",
            AppError::ValidationError(_) => "VALIDATION_ERROR",
            AppError::OrderError(_) => "ORDER_ERROR",
            AppError::OrderNotFound(_) => "ORDER_NOT_FOUND",
            AppError::SymbolNotFound(_) => "SYMBOL_NOT_FOUND",
            AppError::MarketDataError(_) => "MARKET_DATA_ERROR",
            AppError::DatabaseError(_) => "DATABASE_ERROR",
            AppError::NetworkError(_) => "NETWORK_ERROR",
            AppError::WebSocketError(_) => "WEBSOCKET_ERROR",
            AppError::SerializationError(_) => "SERIALIZATION_ERROR",
            AppError::InternalError(_) => "INTERNAL_ERROR",
        }
    }
}
```

---

## 5. Configuration

### 5.1 Tauri Configuration (`tauri.conf.json`)

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "OpenAlgo",
  "version": "1.0.0",
  "identifier": "in.openalgo.desktop",
  "build": {
    "beforeBuildCommand": "npm run build",
    "beforeDevCommand": "npm run dev",
    "devUrl": "http://localhost:5173",
    "frontendDist": "../dist"
  },
  "app": {
    "windows": [
      {
        "title": "OpenAlgo",
        "width": 1400,
        "height": 900,
        "minWidth": 1024,
        "minHeight": 768,
        "resizable": true,
        "fullscreen": false,
        "center": true
      }
    ],
    "security": {
      "csp": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self' wss: https:"
    }
  },
  "bundle": {
    "active": true,
    "targets": ["msi", "dmg", "deb", "appimage"],
    "icon": [
      "icons/32x32.png",
      "icons/128x128.png",
      "icons/128x128@2x.png",
      "icons/icon.icns",
      "icons/icon.ico"
    ],
    "windows": {
      "certificateThumbprint": null,
      "digestAlgorithm": "sha256"
    }
  },
  "plugins": {
    "updater": {
      "active": true,
      "endpoints": ["https://releases.openalgo.in/{{target}}/{{arch}}/{{current_version}}"],
      "pubkey": "..."
    }
  }
}
```

---

## Document References

- [00-PRODUCT-DESIGN.md](./00-PRODUCT-DESIGN.md) - Product overview
- [02-DATABASE.md](./02-DATABASE.md) - Database schema
- [03-TAURI-COMMANDS.md](./03-TAURI-COMMANDS.md) - Command reference
- [04-FRONTEND.md](./04-FRONTEND.md) - Frontend design
- [05-BROKER-INTEGRATION.md](./05-BROKER-INTEGRATION.md) - Broker patterns
- [06-ROADMAP.md](./06-ROADMAP.md) - Implementation plan

---

*Last updated: December 2024*
