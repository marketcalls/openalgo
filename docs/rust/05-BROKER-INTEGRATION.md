# OpenAlgo Desktop - Broker Integration Guide

**Version:** 1.0.0
**Date:** December 2024

---

## 1. Supported Brokers

### 1.1 Priority Tiers

| Tier | Brokers | Priority | Notes |
|------|---------|----------|-------|
| **Tier 1** | Angel One, Zerodha, Dhan, Fyers | P0 | Most popular, implement first |
| **Tier 2** | Upstox, Kotak, IIFL, Groww | P1 | High volume brokers |
| **Tier 3** | Alice Blue, Flattrade, Firstock, Shoonya | P2 | Regional popularity |
| **Tier 4** | Others (14+) | P3 | Complete coverage |

### 1.2 Broker Feature Matrix

| Broker | OAuth | API Keys | WebSocket | Options | History |
|--------|-------|----------|-----------|---------|---------|
| Angel One | Yes | Yes | Yes | Yes | Yes |
| Zerodha | Yes | No | Yes | Yes | Yes |
| Dhan | Yes | Yes | Yes | Yes | Yes |
| Fyers | Yes | Yes | Yes | Yes | Yes |
| Upstox | Yes | Yes | Yes | Yes | Yes |
| Kotak | Yes | Yes | No | Yes | Limited |
| Alice Blue | Yes | Yes | Yes | Yes | Yes |
| Flattrade | Yes | Yes | Yes | Yes | Yes |

---

## 2. Integration Architecture

### 2.1 Broker Adapter Trait

```rust
// brokers/mod.rs

use async_trait::async_trait;
use crate::models::*;
use crate::error::AppResult;

/// Core trait that all broker adapters must implement
#[async_trait]
pub trait BrokerAdapter: Send + Sync {
    // ═══════════════════════════════════════════════════════════════
    // METADATA
    // ═══════════════════════════════════════════════════════════════

    /// Unique broker identifier (lowercase, no spaces)
    fn id(&self) -> &'static str;

    /// Display name for UI
    fn name(&self) -> &'static str;

    /// Broker logo asset path
    fn logo(&self) -> &'static str { "default-broker.png" }

    /// Supported exchanges
    fn supported_exchanges(&self) -> &[&'static str] {
        &["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"]
    }

    /// Whether broker supports WebSocket streaming
    fn supports_websocket(&self) -> bool { true }

    // ═══════════════════════════════════════════════════════════════
    // AUTHENTICATION
    // ═══════════════════════════════════════════════════════════════

    /// Get the OAuth/login URL
    fn get_login_url(&self, redirect_uri: &str) -> String;

    /// Process OAuth callback and establish session
    async fn authenticate(&mut self, params: AuthParams) -> AppResult<BrokerSession>;

    /// Check if current session is valid
    async fn validate_session(&self) -> AppResult<bool>;

    /// Refresh expired token
    async fn refresh_token(&mut self) -> AppResult<()>;

    /// Revoke session
    async fn logout(&mut self) -> AppResult<()>;

    // ═══════════════════════════════════════════════════════════════
    // ORDERS
    // ═══════════════════════════════════════════════════════════════

    /// Place a new order
    async fn place_order(&self, order: OrderRequest) -> AppResult<OrderResponse>;

    /// Modify an existing order
    async fn modify_order(&self, order_id: &str, order: OrderRequest) -> AppResult<OrderResponse>;

    /// Cancel an order
    async fn cancel_order(&self, order_id: &str) -> AppResult<()>;

    // ═══════════════════════════════════════════════════════════════
    // PORTFOLIO
    // ═══════════════════════════════════════════════════════════════

    /// Get order book for the day
    async fn get_orders(&self) -> AppResult<Vec<Order>>;

    /// Get executed trades
    async fn get_trades(&self) -> AppResult<Vec<Trade>>;

    /// Get current positions
    async fn get_positions(&self) -> AppResult<Vec<Position>>;

    /// Get demat holdings
    async fn get_holdings(&self) -> AppResult<Vec<Holding>>;

    /// Get account funds/margins
    async fn get_funds(&self) -> AppResult<Funds>;

    // ═══════════════════════════════════════════════════════════════
    // MARKET DATA
    // ═══════════════════════════════════════════════════════════════

    /// Get real-time quote
    async fn get_quote(&self, symbol: &str, exchange: &str) -> AppResult<Quote>;

    /// Get market depth
    async fn get_depth(&self, symbol: &str, exchange: &str) -> AppResult<Depth>;

    /// Get historical candles
    async fn get_history(&self, req: HistoryRequest) -> AppResult<Vec<Candle>>;

    // ═══════════════════════════════════════════════════════════════
    // WEBSOCKET
    // ═══════════════════════════════════════════════════════════════

    /// Create WebSocket connection for streaming
    async fn create_stream(&self) -> AppResult<Box<dyn BrokerStream>>;

    // ═══════════════════════════════════════════════════════════════
    // SYMBOL MAPPING
    // ═══════════════════════════════════════════════════════════════

    /// Download master contract file
    async fn download_contracts(&self) -> AppResult<Vec<Contract>>;

    /// Convert OpenAlgo symbol to broker format
    fn to_broker_symbol(&self, symbol: &str, exchange: &str) -> AppResult<String>;

    /// Convert broker symbol to OpenAlgo format
    fn to_openalgo_symbol(&self, broker_symbol: &str) -> AppResult<(String, String)>;

    /// Get token for symbol
    fn get_token(&self, symbol: &str, exchange: &str) -> AppResult<String>;
}

/// WebSocket streaming trait
#[async_trait]
pub trait BrokerStream: Send {
    /// Subscribe to symbol updates
    async fn subscribe(&mut self, subscriptions: Vec<Subscription>) -> AppResult<()>;

    /// Unsubscribe from symbols
    async fn unsubscribe(&mut self, symbols: Vec<(String, String)>) -> AppResult<()>;

    /// Receive next message (blocking)
    async fn next(&mut self) -> Option<AppResult<StreamMessage>>;

    /// Close connection
    async fn close(&mut self) -> AppResult<()>;

    /// Check if connected
    fn is_connected(&self) -> bool;
}
```

---

## 3. Broker Implementation Examples

### 3.1 Angel One (SmartAPI)

```rust
// brokers/angel/mod.rs

pub mod api;
pub mod websocket;
pub mod mapping;

use crate::brokers::{BrokerAdapter, BrokerStream};
use crate::models::*;
use crate::error::AppResult;
use reqwest::Client;
use std::sync::Arc;
use tokio::sync::RwLock;

pub struct AngelBroker {
    client: Client,
    config: AngelConfig,
    session: Arc<RwLock<Option<AngelSession>>>,
    contracts: Arc<RwLock<ContractCache>>,
}

#[derive(Clone)]
struct AngelConfig {
    api_key: String,
    base_url: String,
    ws_url: String,
}

#[derive(Clone)]
struct AngelSession {
    client_code: String,
    access_token: String,
    refresh_token: String,
    feed_token: String,
    expires_at: chrono::DateTime<chrono::Utc>,
}

impl AngelBroker {
    const BASE_URL: &'static str = "https://apiconnect.angelbroking.com";
    const WS_URL: &'static str = "wss://smartapisocket.angelone.in/smart-stream";

    pub fn new(api_key: String) -> Self {
        Self {
            client: Client::builder()
                .timeout(std::time::Duration::from_secs(30))
                .build()
                .unwrap(),
            config: AngelConfig {
                api_key,
                base_url: Self::BASE_URL.to_string(),
                ws_url: Self::WS_URL.to_string(),
            },
            session: Arc::new(RwLock::new(None)),
            contracts: Arc::new(RwLock::new(ContractCache::new())),
        }
    }

    fn get_headers(&self, session: &AngelSession) -> reqwest::header::HeaderMap {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert("Content-Type", "application/json".parse().unwrap());
        headers.insert("X-PrivateKey", self.config.api_key.parse().unwrap());
        headers.insert("X-ClientLocalIP", "127.0.0.1".parse().unwrap());
        headers.insert("X-ClientPublicIP", "127.0.0.1".parse().unwrap());
        headers.insert("X-MACAddress", "00:00:00:00:00:00".parse().unwrap());
        headers.insert("X-UserType", "USER".parse().unwrap());
        headers.insert("X-SourceID", "WEB".parse().unwrap());
        headers.insert(
            "Authorization",
            format!("Bearer {}", session.access_token).parse().unwrap(),
        );
        headers
    }
}

#[async_trait::async_trait]
impl BrokerAdapter for AngelBroker {
    fn id(&self) -> &'static str { "angel" }
    fn name(&self) -> &'static str { "Angel One" }
    fn logo(&self) -> &'static str { "angel.png" }

    fn get_login_url(&self, redirect_uri: &str) -> String {
        format!(
            "https://smartapi.angelone.in/publisher-login?api_key={}",
            self.config.api_key
        )
    }

    async fn authenticate(&mut self, params: AuthParams) -> AppResult<BrokerSession> {
        #[derive(serde::Serialize)]
        struct LoginRequest {
            clientcode: String,
            password: String,
            totp: String,
        }

        #[derive(serde::Deserialize)]
        struct LoginResponse {
            status: bool,
            message: String,
            data: Option<LoginData>,
        }

        #[derive(serde::Deserialize)]
        #[serde(rename_all = "camelCase")]
        struct LoginData {
            jwt_token: String,
            refresh_token: String,
            feed_token: String,
        }

        let request = LoginRequest {
            clientcode: params.client_code.clone(),
            password: params.password.unwrap_or_default(),
            totp: params.totp.unwrap_or_default(),
        };

        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert("Content-Type", "application/json".parse().unwrap());
        headers.insert("X-PrivateKey", self.config.api_key.parse().unwrap());

        let response: LoginResponse = self.client
            .post(format!("{}/rest/auth/angelbroking/user/v1/loginByPassword", self.config.base_url))
            .headers(headers)
            .json(&request)
            .send()
            .await?
            .json()
            .await?;

        if !response.status {
            return Err(AppError::AuthError(response.message));
        }

        let data = response.data.ok_or(AppError::AuthError("No data".into()))?;

        let session = AngelSession {
            client_code: params.client_code.clone(),
            access_token: data.jwt_token.clone(),
            refresh_token: data.refresh_token,
            feed_token: data.feed_token,
            expires_at: chrono::Utc::now() + chrono::Duration::hours(24),
        };

        *self.session.write().await = Some(session.clone());

        // Download master contracts
        self.download_contracts().await?;

        Ok(BrokerSession {
            broker: "angel".to_string(),
            client_id: params.client_code,
            access_token: data.jwt_token,
            expires_at: session.expires_at,
        })
    }

    async fn place_order(&self, order: OrderRequest) -> AppResult<OrderResponse> {
        let session = self.session.read().await;
        let session = session.as_ref().ok_or(AppError::NotAuthenticated)?;

        #[derive(serde::Serialize)]
        struct AngelOrder {
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

        let token = self.get_token(&order.symbol, &order.exchange)?;

        let angel_order = AngelOrder {
            variety: "NORMAL".to_string(),
            tradingsymbol: self.to_broker_symbol(&order.symbol, &order.exchange)?,
            symboltoken: token,
            transactiontype: order.action.to_string(),
            exchange: order.exchange.clone(),
            ordertype: self.map_price_type(&order.price_type),
            producttype: self.map_product(&order.product),
            duration: "DAY".to_string(),
            price: order.price.map(|p| p.to_string()).unwrap_or("0".to_string()),
            triggerprice: order.trigger_price.map(|p| p.to_string()).unwrap_or("0".to_string()),
            quantity: order.quantity.to_string(),
        };

        #[derive(serde::Deserialize)]
        struct Response {
            status: bool,
            message: String,
            data: Option<ResponseData>,
        }

        #[derive(serde::Deserialize)]
        struct ResponseData {
            orderid: String,
        }

        let response: Response = self.client
            .post(format!("{}/rest/secure/angelbroking/order/v1/placeOrder", self.config.base_url))
            .headers(self.get_headers(session))
            .json(&angel_order)
            .send()
            .await?
            .json()
            .await?;

        if !response.status {
            return Err(AppError::OrderError(response.message));
        }

        let data = response.data.ok_or(AppError::OrderError("No order ID".into()))?;

        Ok(OrderResponse {
            order_id: data.orderid,
            status: OrderStatus::Pending,
            message: response.message,
        })
    }

    async fn get_positions(&self) -> AppResult<Vec<Position>> {
        let session = self.session.read().await;
        let session = session.as_ref().ok_or(AppError::NotAuthenticated)?;

        #[derive(serde::Deserialize)]
        struct Response {
            status: bool,
            data: Option<Vec<AngelPosition>>,
        }

        #[derive(serde::Deserialize)]
        struct AngelPosition {
            tradingsymbol: String,
            symboltoken: String,
            exchange: String,
            producttype: String,
            netqty: String,
            avgnetprice: String,
            ltp: String,
            pnl: String,
            // ... other fields
        }

        let response: Response = self.client
            .get(format!("{}/rest/secure/angelbroking/order/v1/getPosition", self.config.base_url))
            .headers(self.get_headers(session))
            .send()
            .await?
            .json()
            .await?;

        let positions = response.data.unwrap_or_default()
            .into_iter()
            .map(|p| Position {
                symbol: p.tradingsymbol,
                exchange: p.exchange,
                product: self.map_product_reverse(&p.producttype),
                quantity: p.netqty.parse().unwrap_or(0),
                average_price: p.avgnetprice.parse().unwrap_or(0.0),
                ltp: p.ltp.parse().unwrap_or(0.0),
                pnl: p.pnl.parse().unwrap_or(0.0),
                ..Default::default()
            })
            .collect();

        Ok(positions)
    }

    async fn create_stream(&self) -> AppResult<Box<dyn BrokerStream>> {
        let session = self.session.read().await;
        let session = session.as_ref().ok_or(AppError::NotAuthenticated)?;

        let stream = websocket::AngelStream::connect(
            &self.config.ws_url,
            &session.client_code,
            &session.feed_token,
            &self.config.api_key,
        ).await?;

        Ok(Box::new(stream))
    }

    async fn download_contracts(&self) -> AppResult<Vec<Contract>> {
        // Angel provides a JSON file with all contracts
        let url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json";

        let contracts: Vec<AngelContract> = self.client
            .get(url)
            .send()
            .await?
            .json()
            .await?;

        let mapped: Vec<Contract> = contracts
            .into_iter()
            .map(|c| Contract {
                symbol: c.symbol,
                token: c.token,
                exchange: c.exch_seg,
                name: c.name,
                instrument_type: c.instrumenttype,
                lot_size: c.lotsize.parse().unwrap_or(1),
                tick_size: c.tick_size.parse().unwrap_or(0.05),
                expiry: c.expiry,
                strike: c.strike.parse().ok(),
            })
            .collect();

        // Cache contracts
        let mut cache = self.contracts.write().await;
        cache.load(mapped.clone());

        Ok(mapped)
    }

    // Helper methods
    fn map_price_type(&self, price_type: &PriceType) -> String {
        match price_type {
            PriceType::Market => "MARKET",
            PriceType::Limit => "LIMIT",
            PriceType::Sl => "STOPLOSS_LIMIT",
            PriceType::SlM => "STOPLOSS_MARKET",
        }.to_string()
    }

    fn map_product(&self, product: &ProductType) -> String {
        match product {
            ProductType::Mis => "INTRADAY",
            ProductType::Cnc => "DELIVERY",
            ProductType::Nrml => "CARRYFORWARD",
        }.to_string()
    }

    // ... implement remaining methods
}
```

### 3.2 WebSocket Streaming (Angel)

```rust
// brokers/angel/websocket.rs

use tokio_tungstenite::{connect_async, MaybeTlsStream, WebSocketStream};
use tokio::net::TcpStream;
use futures_util::{SinkExt, StreamExt};
use crate::brokers::BrokerStream;
use crate::models::*;
use crate::error::AppResult;

pub struct AngelStream {
    ws: WebSocketStream<MaybeTlsStream<TcpStream>>,
    client_code: String,
    subscriptions: Vec<Subscription>,
}

impl AngelStream {
    pub async fn connect(
        url: &str,
        client_code: &str,
        feed_token: &str,
        api_key: &str,
    ) -> AppResult<Self> {
        let (ws, _) = connect_async(url).await?;

        let mut stream = Self {
            ws,
            client_code: client_code.to_string(),
            subscriptions: vec![],
        };

        // Send authentication
        stream.authenticate(client_code, feed_token, api_key).await?;

        Ok(stream)
    }

    async fn authenticate(&mut self, client_code: &str, feed_token: &str, api_key: &str) -> AppResult<()> {
        #[derive(serde::Serialize)]
        struct AuthRequest {
            task: String,
            channel: String,
            token: String,
            user: String,
            acctid: String,
        }

        let auth = AuthRequest {
            task: "cn".to_string(),
            channel: "".to_string(),
            token: feed_token.to_string(),
            user: client_code.to_string(),
            acctid: client_code.to_string(),
        };

        let msg = serde_json::to_string(&auth)?;
        self.ws.send(tokio_tungstenite::tungstenite::Message::Text(msg)).await?;

        Ok(())
    }

    fn parse_message(&self, data: &[u8]) -> AppResult<StreamMessage> {
        // Angel sends binary messages with specific format
        // Parse based on subscription mode

        if data.len() < 2 {
            return Err(AppError::WebSocketError("Invalid message".into()));
        }

        let subscription_mode = data[0];
        let exchange_type = data[1];

        match subscription_mode {
            1 => self.parse_ltp(data),      // LTP mode
            2 => self.parse_quote(data),    // Quote mode
            3 => self.parse_depth(data),    // Snap Quote (Depth)
            _ => Err(AppError::WebSocketError("Unknown mode".into())),
        }
    }

    fn parse_ltp(&self, data: &[u8]) -> AppResult<StreamMessage> {
        // Binary parsing for LTP message
        // Format: mode(1) | exchange(1) | token(25) | seq(8) | ltp(8) | ...

        let token = String::from_utf8_lossy(&data[2..27]).trim().to_string();
        let ltp = f64::from_le_bytes(data[35..43].try_into().unwrap()) / 100.0;

        Ok(StreamMessage::Quote(QuoteUpdate {
            symbol: token.clone(),
            exchange: self.get_exchange(data[1])?,
            ltp,
            ..Default::default()
        }))
    }

    fn get_exchange(&self, code: u8) -> AppResult<String> {
        match code {
            1 => Ok("NSE".to_string()),
            2 => Ok("NFO".to_string()),
            3 => Ok("BSE".to_string()),
            5 => Ok("MCX".to_string()),
            _ => Ok("NSE".to_string()),
        }
    }
}

#[async_trait::async_trait]
impl BrokerStream for AngelStream {
    async fn subscribe(&mut self, subscriptions: Vec<Subscription>) -> AppResult<()> {
        #[derive(serde::Serialize)]
        struct SubscribeRequest {
            action: i32,
            params: SubscribeParams,
        }

        #[derive(serde::Serialize)]
        struct SubscribeParams {
            mode: i32,
            tokenlist: Vec<TokenList>,
        }

        #[derive(serde::Serialize)]
        struct TokenList {
            exchangetype: i32,
            tokens: Vec<String>,
        }

        // Group by exchange
        let mut exchange_tokens: std::collections::HashMap<String, Vec<String>> = std::collections::HashMap::new();

        for sub in &subscriptions {
            let tokens = exchange_tokens.entry(sub.exchange.clone()).or_default();
            tokens.push(sub.token.clone());
        }

        let tokenlist: Vec<TokenList> = exchange_tokens
            .into_iter()
            .map(|(exchange, tokens)| TokenList {
                exchangetype: self.get_exchange_code(&exchange),
                tokens,
            })
            .collect();

        let mode = subscriptions.first()
            .map(|s| match s.mode {
                SubscriptionMode::Ltp => 1,
                SubscriptionMode::Quote => 2,
                SubscriptionMode::Depth => 3,
            })
            .unwrap_or(1);

        let request = SubscribeRequest {
            action: 1,
            params: SubscribeParams {
                mode,
                tokenlist,
            },
        };

        let msg = serde_json::to_string(&request)?;
        self.ws.send(tokio_tungstenite::tungstenite::Message::Text(msg)).await?;

        self.subscriptions.extend(subscriptions);

        Ok(())
    }

    async fn unsubscribe(&mut self, symbols: Vec<(String, String)>) -> AppResult<()> {
        // Similar to subscribe with action: 0
        Ok(())
    }

    async fn next(&mut self) -> Option<AppResult<StreamMessage>> {
        while let Some(msg) = self.ws.next().await {
            match msg {
                Ok(tokio_tungstenite::tungstenite::Message::Binary(data)) => {
                    return Some(self.parse_message(&data));
                }
                Ok(tokio_tungstenite::tungstenite::Message::Ping(data)) => {
                    let _ = self.ws.send(tokio_tungstenite::tungstenite::Message::Pong(data)).await;
                }
                Err(e) => {
                    return Some(Err(AppError::WebSocketError(e.to_string())));
                }
                _ => {}
            }
        }
        None
    }

    async fn close(&mut self) -> AppResult<()> {
        self.ws.close(None).await?;
        Ok(())
    }

    fn is_connected(&self) -> bool {
        // Check WebSocket state
        true
    }
}
```

---

## 4. Broker Router

### 4.1 Router Implementation

```rust
// brokers/router.rs

use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;
use crate::brokers::BrokerAdapter;

pub struct BrokerRouter {
    brokers: HashMap<String, Arc<RwLock<Box<dyn BrokerAdapter>>>>,
    active_broker: Option<String>,
}

impl BrokerRouter {
    pub fn new() -> Self {
        let mut brokers: HashMap<String, Arc<RwLock<Box<dyn BrokerAdapter>>>> = HashMap::new();

        // Register all brokers
        // In production, load from config/plugins
        brokers.insert("angel".to_string(), Arc::new(RwLock::new(
            Box::new(super::angel::AngelBroker::new(String::new()))
        )));
        brokers.insert("zerodha".to_string(), Arc::new(RwLock::new(
            Box::new(super::zerodha::ZerodhaBroker::new(String::new()))
        )));
        // ... add other brokers

        Self {
            brokers,
            active_broker: None,
        }
    }

    pub fn list_brokers(&self) -> Vec<BrokerInfo> {
        self.brokers.iter().map(|(id, broker)| {
            let broker = broker.blocking_read();
            BrokerInfo {
                id: id.clone(),
                name: broker.name().to_string(),
                logo: broker.logo().to_string(),
                is_active: self.active_broker.as_ref() == Some(id),
            }
        }).collect()
    }

    pub fn set_active(&mut self, broker_id: &str) -> AppResult<()> {
        if !self.brokers.contains_key(broker_id) {
            return Err(AppError::BrokerNotFound(broker_id.to_string()));
        }
        self.active_broker = Some(broker_id.to_string());
        Ok(())
    }

    pub fn get_active(&self) -> AppResult<Arc<RwLock<Box<dyn BrokerAdapter>>>> {
        let id = self.active_broker.as_ref()
            .ok_or(AppError::NoBrokerSelected)?;
        self.brokers.get(id)
            .cloned()
            .ok_or(AppError::BrokerNotFound(id.clone()))
    }

    pub fn get_broker(&self, id: &str) -> AppResult<Arc<RwLock<Box<dyn BrokerAdapter>>>> {
        self.brokers.get(id)
            .cloned()
            .ok_or(AppError::BrokerNotFound(id.to_string()))
    }
}
```

---

## 5. Master Contract Management

### 5.1 Contract Cache

```rust
// brokers/contracts.rs

use std::collections::HashMap;
use dashmap::DashMap;

#[derive(Clone)]
pub struct Contract {
    pub symbol: String,
    pub token: String,
    pub exchange: String,
    pub name: String,
    pub instrument_type: String,
    pub lot_size: i32,
    pub tick_size: f64,
    pub expiry: Option<String>,
    pub strike: Option<f64>,
}

pub struct ContractCache {
    // Primary index: (symbol, exchange) -> Contract
    by_symbol: DashMap<(String, String), Contract>,

    // Secondary index: token -> Contract
    by_token: DashMap<String, Contract>,

    // Search index: lowercase name -> Vec<Contract>
    by_name: DashMap<String, Vec<Contract>>,

    // Stats
    pub count: usize,
    pub last_updated: chrono::DateTime<chrono::Utc>,
}

impl ContractCache {
    pub fn new() -> Self {
        Self {
            by_symbol: DashMap::new(),
            by_token: DashMap::new(),
            by_name: DashMap::new(),
            count: 0,
            last_updated: chrono::Utc::now(),
        }
    }

    pub fn load(&mut self, contracts: Vec<Contract>) {
        self.by_symbol.clear();
        self.by_token.clear();
        self.by_name.clear();

        for contract in contracts {
            // Primary index
            self.by_symbol.insert(
                (contract.symbol.clone(), contract.exchange.clone()),
                contract.clone()
            );

            // Token index
            self.by_token.insert(contract.token.clone(), contract.clone());

            // Name search index
            let name_key = contract.name.to_lowercase();
            self.by_name.entry(name_key)
                .or_default()
                .push(contract.clone());

            self.count += 1;
        }

        self.last_updated = chrono::Utc::now();
    }

    pub fn get_by_symbol(&self, symbol: &str, exchange: &str) -> Option<Contract> {
        self.by_symbol.get(&(symbol.to_string(), exchange.to_string()))
            .map(|r| r.clone())
    }

    pub fn get_by_token(&self, token: &str) -> Option<Contract> {
        self.by_token.get(token).map(|r| r.clone())
    }

    pub fn search(&self, query: &str, exchange: Option<&str>, limit: usize) -> Vec<Contract> {
        let query_lower = query.to_lowercase();
        let mut results = Vec::new();

        for entry in self.by_symbol.iter() {
            let contract = entry.value();

            // Filter by exchange if specified
            if let Some(exch) = exchange {
                if contract.exchange != exch {
                    continue;
                }
            }

            // Match by symbol or name
            if contract.symbol.to_lowercase().contains(&query_lower) ||
               contract.name.to_lowercase().contains(&query_lower) {
                results.push(contract.clone());
                if results.len() >= limit {
                    break;
                }
            }
        }

        results
    }

    pub fn get_token(&self, symbol: &str, exchange: &str) -> Option<String> {
        self.get_by_symbol(symbol, exchange).map(|c| c.token)
    }
}
```

---

## 6. Adding a New Broker

### 6.1 Checklist

1. **Create broker module**: `brokers/<broker_name>/mod.rs`
2. **Implement BrokerAdapter trait**
3. **Implement WebSocket streaming** (if supported)
4. **Add symbol mapping logic**
5. **Register in BrokerRouter**
6. **Add broker logo to assets**
7. **Create login UI component** (if custom OAuth flow)
8. **Write integration tests**
9. **Update documentation**

### 6.2 Template

```rust
// brokers/newbroker/mod.rs

pub struct NewBroker {
    // Configuration
    // Session state
    // HTTP client
    // Contract cache
}

impl NewBroker {
    pub fn new(api_key: String) -> Self {
        // Initialize
    }
}

#[async_trait]
impl BrokerAdapter for NewBroker {
    fn id(&self) -> &'static str { "newbroker" }
    fn name(&self) -> &'static str { "New Broker" }

    // Implement all required methods...
}
```

---

## Document References

- [00-PRODUCT-DESIGN.md](./00-PRODUCT-DESIGN.md) - Product overview
- [01-ARCHITECTURE.md](./01-ARCHITECTURE.md) - System architecture
- [02-DATABASE.md](./02-DATABASE.md) - Database schema
- [03-TAURI-COMMANDS.md](./03-TAURI-COMMANDS.md) - Command reference
- [04-FRONTEND.md](./04-FRONTEND.md) - Frontend design
- [06-ROADMAP.md](./06-ROADMAP.md) - Implementation plan

---

*Last updated: December 2024*
