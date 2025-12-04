# OpenAlgo Desktop - WebSocket Streaming Architecture

## Overview

This document defines the WebSocket streaming architecture for real-time market data in the Rust/Tauri desktop application. The design maintains 100% protocol compatibility with the existing Python implementation.

---

## Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Tauri Desktop App                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────────────┐ │
│  │   Frontend   │     │   Frontend   │     │     External Clients         │ │
│  │  (Svelte)    │     │  (Charts)    │     │  (Python SDK, Custom Apps)   │ │
│  └──────┬───────┘     └──────┬───────┘     └──────────────┬───────────────┘ │
│         │                    │                            │                  │
│         │ Tauri Events       │ Tauri Events              │ WebSocket        │
│         │                    │                            │ Port 8765        │
│         ▼                    ▼                            ▼                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                    WebSocket Proxy Server                                ││
│  │                    (tokio-tungstenite)                                   ││
│  │                                                                          ││
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────────────┐ ││
│  │  │ Client Manager   │  │ Subscription Mgr │  │ Message Router         │ ││
│  │  │ - connections    │  │ - symbol index   │  │ - topic parsing        │ ││
│  │  │ - authentication │  │ - mode tracking  │  │ - client dispatch      │ ││
│  │  └──────────────────┘  └──────────────────┘  └────────────────────────┘ ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                    Internal Message Bus                                  ││
│  │                    (tokio::broadcast)                                    ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                    Broker Adapter Manager                                ││
│  │                                                                          ││
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────────────┐ ││
│  │  │ Angel One  │  │  Zerodha   │  │   Dhan     │  │  Other Brokers...  │ ││
│  │  │  Adapter   │  │  Adapter   │  │  Adapter   │  │                    │ ││
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────────────┘ ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                    │                                         │
└────────────────────────────────────┼─────────────────────────────────────────┘
                                     │
                                     ▼
                    ┌────────────────────────────────┐
                    │   Broker WebSocket Servers     │
                    │   (External - Internet)        │
                    └────────────────────────────────┘
```

---

## WebSocket Protocol

### Connection

**Endpoint**: `ws://127.0.0.1:8765`

**Configuration**:
```rust
pub struct WebSocketConfig {
    pub host: String,           // Default: "127.0.0.1"
    pub port: u16,              // Default: 8765
    pub ping_interval: u64,     // Default: 5 seconds
    pub ping_timeout: u64,      // Default: 10 seconds
    pub max_clients: usize,     // Default: 1000
}
```

### Message Format

All messages are JSON encoded.

#### Authentication Request

```json
{
    "action": "authenticate",
    "api_key": "your-openalgo-api-key"
}
```

#### Authentication Response

```json
{
    "type": "auth_response",
    "status": "success",
    "message": "Authentication successful"
}
```

```json
{
    "type": "auth_response",
    "status": "error",
    "message": "Invalid API key"
}
```

#### Subscribe Request

```json
{
    "action": "subscribe",
    "symbols": [
        {"symbol": "RELIANCE", "exchange": "NSE"},
        {"symbol": "TCS", "exchange": "NSE"},
        {"symbol": "NIFTY28DEC2425000CE", "exchange": "NFO"}
    ],
    "mode": "Quote"
}
```

#### Unsubscribe Request

```json
{
    "action": "unsubscribe",
    "symbols": [
        {"symbol": "RELIANCE", "exchange": "NSE"}
    ]
}
```

#### Market Data Response

```json
{
    "type": "market_data",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "mode": 2,
    "data": {
        "ltp": 2850.50,
        "open": 2820.00,
        "high": 2860.00,
        "low": 2815.00,
        "close": 2848.25,
        "volume": 1500000,
        "bid": 2850.45,
        "ask": 2850.55,
        "bid_qty": 500,
        "ask_qty": 750,
        "oi": 0,
        "prev_oi": 0,
        "timestamp": "2024-12-04T10:30:00"
    }
}
```

---

## Subscription Modes

| Mode | Value | Data Included | Throttle |
|------|-------|---------------|----------|
| LTP | 1 | Last traded price only | 50ms |
| Quote | 2 | Full quote (bid/ask, OHLCV) | None |
| Depth | 3 | Market depth (5/20/30 levels) | None |

### Mode Enum

```rust
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub enum SubscriptionMode {
    #[serde(rename = "LTP")]
    Ltp = 1,
    #[serde(rename = "Quote")]
    Quote = 2,
    #[serde(rename = "Depth")]
    Depth = 3,
}
```

---

## Topic Format

Topics follow a standardized format for routing:

```
BROKER_EXCHANGE_SYMBOL_MODE
```

**Examples**:
- `angelone_NSE_RELIANCE_QUOTE`
- `zerodha_NFO_NIFTY24DEC19500CE_LTP`
- `dhan_NSE_INDEX_NIFTY_50_DEPTH`

### Special Cases

For index symbols with underscores:

```rust
fn parse_topic(topic: &str) -> TopicInfo {
    let parts: Vec<&str> = topic.split('_').collect();

    // Handle NSE_INDEX and BSE_INDEX
    if parts.len() >= 4 && (parts[1] == "NSE" || parts[1] == "BSE") && parts[2] == "INDEX" {
        TopicInfo {
            broker: parts[0].to_string(),
            exchange: format!("{}_INDEX", parts[1]),
            symbol: parts[3].to_string(),
            mode: parse_mode(parts[4]),
        }
    } else {
        TopicInfo {
            broker: parts[0].to_string(),
            exchange: parts[1].to_string(),
            symbol: parts[2].to_string(),
            mode: parse_mode(parts[3]),
        }
    }
}
```

---

## Rust Implementation

### Client Connection State

```rust
use std::collections::{HashMap, HashSet};
use tokio::sync::RwLock;

pub type ClientId = u64;

pub struct ClientState {
    pub id: ClientId,
    pub user_id: Option<String>,
    pub authenticated: bool,
    pub subscriptions: HashSet<SubscriptionKey>,
    pub broker_adapter: Option<Arc<dyn BrokerWebSocketAdapter>>,
}

pub struct SubscriptionKey {
    pub symbol: String,
    pub exchange: String,
    pub mode: SubscriptionMode,
}

pub struct WebSocketServer {
    clients: RwLock<HashMap<ClientId, ClientState>>,
    subscription_index: RwLock<HashMap<SubscriptionKey, HashSet<ClientId>>>,
    message_tx: broadcast::Sender<MarketDataMessage>,
}
```

### WebSocket Handler

```rust
use tokio_tungstenite::{accept_async, tungstenite::Message};
use futures_util::{StreamExt, SinkExt};

impl WebSocketServer {
    pub async fn handle_connection(
        &self,
        stream: TcpStream,
    ) -> Result<(), WebSocketError> {
        let ws_stream = accept_async(stream).await?;
        let (mut write, mut read) = ws_stream.split();

        let client_id = self.generate_client_id();
        self.register_client(client_id).await;

        // Spawn message receiver
        let mut rx = self.message_tx.subscribe();
        let write_handle = tokio::spawn(async move {
            while let Ok(msg) = rx.recv().await {
                if self.should_send_to_client(client_id, &msg).await {
                    let json = serde_json::to_string(&msg)?;
                    write.send(Message::Text(json)).await?;
                }
            }
        });

        // Process incoming messages
        while let Some(msg) = read.next().await {
            match msg? {
                Message::Text(text) => {
                    self.process_message(client_id, &text).await?;
                }
                Message::Close(_) => break,
                Message::Ping(data) => {
                    write.send(Message::Pong(data)).await?;
                }
                _ => {}
            }
        }

        self.cleanup_client(client_id).await;
        write_handle.abort();
        Ok(())
    }

    async fn process_message(
        &self,
        client_id: ClientId,
        text: &str,
    ) -> Result<(), WebSocketError> {
        let request: ClientMessage = serde_json::from_str(text)?;

        match request {
            ClientMessage::Authenticate { api_key } => {
                self.handle_authenticate(client_id, &api_key).await
            }
            ClientMessage::Subscribe { symbols, mode } => {
                self.handle_subscribe(client_id, symbols, mode).await
            }
            ClientMessage::Unsubscribe { symbols } => {
                self.handle_unsubscribe(client_id, symbols).await
            }
        }
    }
}
```

### Subscription Index (O(1) Lookup)

```rust
impl WebSocketServer {
    async fn handle_subscribe(
        &self,
        client_id: ClientId,
        symbols: Vec<SymbolExchange>,
        mode: SubscriptionMode,
    ) -> Result<(), WebSocketError> {
        let mut clients = self.clients.write().await;
        let mut index = self.subscription_index.write().await;

        let client = clients.get_mut(&client_id)
            .ok_or(WebSocketError::ClientNotFound)?;

        if !client.authenticated {
            return Err(WebSocketError::NotAuthenticated);
        }

        for sym in symbols {
            let key = SubscriptionKey {
                symbol: sym.symbol.clone(),
                exchange: sym.exchange.clone(),
                mode,
            };

            // Add to client's subscriptions
            client.subscriptions.insert(key.clone());

            // Update subscription index for O(1) lookup
            index.entry(key)
                .or_insert_with(HashSet::new)
                .insert(client_id);

            // Subscribe via broker adapter
            if let Some(adapter) = &client.broker_adapter {
                adapter.subscribe(&sym.symbol, &sym.exchange, mode).await?;
            }
        }

        Ok(())
    }

    async fn should_send_to_client(
        &self,
        client_id: ClientId,
        msg: &MarketDataMessage,
    ) -> bool {
        let index = self.subscription_index.read().await;
        let key = SubscriptionKey {
            symbol: msg.symbol.clone(),
            exchange: msg.exchange.clone(),
            mode: msg.mode,
        };

        index.get(&key)
            .map(|clients| clients.contains(&client_id))
            .unwrap_or(false)
    }
}
```

### LTP Throttling

```rust
use std::time::{Duration, Instant};

pub struct LtpThrottler {
    last_update: RwLock<HashMap<(String, String), Instant>>,
    min_interval: Duration,
}

impl LtpThrottler {
    pub fn new() -> Self {
        Self {
            last_update: RwLock::new(HashMap::new()),
            min_interval: Duration::from_millis(50),
        }
    }

    pub async fn should_send(
        &self,
        symbol: &str,
        exchange: &str,
        mode: SubscriptionMode,
    ) -> bool {
        // Only throttle LTP mode
        if mode != SubscriptionMode::Ltp {
            return true;
        }

        let key = (symbol.to_string(), exchange.to_string());
        let now = Instant::now();

        let mut last = self.last_update.write().await;
        if let Some(last_time) = last.get(&key) {
            if now.duration_since(*last_time) < self.min_interval {
                return false;
            }
        }

        last.insert(key, now);
        true
    }
}
```

---

## Broker Adapter Trait

```rust
use async_trait::async_trait;

#[async_trait]
pub trait BrokerWebSocketAdapter: Send + Sync {
    /// Initialize the adapter with credentials
    async fn initialize(
        &mut self,
        broker_name: &str,
        user_id: &str,
        auth_data: Option<AuthData>,
    ) -> Result<(), AdapterError>;

    /// Connect to broker's WebSocket server
    async fn connect(&mut self) -> Result<(), AdapterError>;

    /// Subscribe to market data
    async fn subscribe(
        &self,
        symbol: &str,
        exchange: &str,
        mode: SubscriptionMode,
    ) -> Result<(), AdapterError>;

    /// Unsubscribe from market data
    async fn unsubscribe(
        &self,
        symbol: &str,
        exchange: &str,
        mode: SubscriptionMode,
    ) -> Result<(), AdapterError>;

    /// Disconnect from broker
    async fn disconnect(&mut self) -> Result<(), AdapterError>;

    /// Get broker name
    fn broker_name(&self) -> &str;

    /// Check if connected
    fn is_connected(&self) -> bool;
}
```

### Broker Adapter Factory

```rust
pub struct BrokerAdapterFactory;

impl BrokerAdapterFactory {
    pub fn create(broker_name: &str) -> Option<Box<dyn BrokerWebSocketAdapter>> {
        match broker_name.to_lowercase().as_str() {
            "angelone" => Some(Box::new(AngelOneWebSocketAdapter::new())),
            "zerodha" => Some(Box::new(ZerodhaWebSocketAdapter::new())),
            "dhan" => Some(Box::new(DhanWebSocketAdapter::new())),
            "fyers" => Some(Box::new(FyersWebSocketAdapter::new())),
            "upstox" => Some(Box::new(UpstoxWebSocketAdapter::new())),
            // ... other brokers
            _ => None,
        }
    }
}
```

---

## Data Normalization

All broker data is normalized to a common format:

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MarketDataMessage {
    #[serde(rename = "type")]
    pub msg_type: String,       // "market_data"
    pub symbol: String,
    pub exchange: String,
    pub mode: u8,               // 1=LTP, 2=Quote, 3=Depth
    pub data: MarketData,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MarketData {
    pub ltp: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub open: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub high: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub low: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub close: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub volume: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bid: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ask: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bid_qty: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ask_qty: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub oi: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub prev_oi: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub timestamp: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MarketDepth {
    pub bids: Vec<DepthLevel>,
    pub asks: Vec<DepthLevel>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DepthLevel {
    pub price: f64,
    pub quantity: u32,
    pub orders: Option<u32>,
}
```

---

## Tauri Integration

### IPC Events for Frontend

```rust
use tauri::{AppHandle, Manager};

pub struct TauriWebSocketBridge {
    app_handle: AppHandle,
}

impl TauriWebSocketBridge {
    pub fn emit_market_data(&self, data: &MarketDataMessage) {
        self.app_handle.emit_all("market_data", data).ok();
    }

    pub fn emit_connection_status(&self, status: &ConnectionStatus) {
        self.app_handle.emit_all("ws_connection_status", status).ok();
    }

    pub fn emit_subscription_update(&self, update: &SubscriptionUpdate) {
        self.app_handle.emit_all("ws_subscription_update", update).ok();
    }
}

#[derive(Serialize)]
pub struct ConnectionStatus {
    pub connected: bool,
    pub broker: String,
    pub subscriptions_count: usize,
}

#[derive(Serialize)]
pub struct SubscriptionUpdate {
    pub action: String,         // "subscribed" or "unsubscribed"
    pub symbol: String,
    pub exchange: String,
    pub mode: String,
}
```

### Tauri Commands for WebSocket

```rust
#[tauri::command]
pub async fn ws_connect(
    state: State<'_, AppState>,
    api_key: String,
) -> Result<ConnectionStatus, String> {
    let mut ws_state = state.websocket.lock().await;
    ws_state.connect(&api_key).await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn ws_subscribe(
    state: State<'_, AppState>,
    symbols: Vec<SymbolExchange>,
    mode: String,
) -> Result<(), String> {
    let ws_state = state.websocket.lock().await;
    let mode = SubscriptionMode::from_str(&mode)?;
    ws_state.subscribe(symbols, mode).await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn ws_unsubscribe(
    state: State<'_, AppState>,
    symbols: Vec<SymbolExchange>,
) -> Result<(), String> {
    let ws_state = state.websocket.lock().await;
    ws_state.unsubscribe(symbols).await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn ws_disconnect(
    state: State<'_, AppState>,
) -> Result<(), String> {
    let mut ws_state = state.websocket.lock().await;
    ws_state.disconnect().await
        .map_err(|e| e.to_string())
}
```

---

## Frontend Integration (Svelte)

### WebSocket Store

```typescript
// src/lib/stores/websocket.ts
import { writable, derived } from 'svelte/store';
import { listen } from '@tauri-apps/api/event';
import { invoke } from '@tauri-apps/api/tauri';

interface MarketData {
    symbol: string;
    exchange: string;
    mode: number;
    data: {
        ltp: number;
        open?: number;
        high?: number;
        low?: number;
        close?: number;
        volume?: number;
        bid?: number;
        ask?: number;
    };
}

interface ConnectionStatus {
    connected: boolean;
    broker: string;
    subscriptions_count: number;
}

// Stores
export const marketData = writable<Map<string, MarketData>>(new Map());
export const connectionStatus = writable<ConnectionStatus>({
    connected: false,
    broker: '',
    subscriptions_count: 0
});

// Key generator
function getKey(symbol: string, exchange: string): string {
    return `${exchange}:${symbol}`;
}

// Initialize event listeners
export async function initWebSocket() {
    // Listen for market data updates
    await listen<MarketData>('market_data', (event) => {
        marketData.update(map => {
            const key = getKey(event.payload.symbol, event.payload.exchange);
            map.set(key, event.payload);
            return new Map(map);
        });
    });

    // Listen for connection status
    await listen<ConnectionStatus>('ws_connection_status', (event) => {
        connectionStatus.set(event.payload);
    });
}

// Actions
export async function connect(apiKey: string) {
    return invoke<ConnectionStatus>('ws_connect', { apiKey });
}

export async function subscribe(
    symbols: Array<{symbol: string, exchange: string}>,
    mode: 'LTP' | 'Quote' | 'Depth'
) {
    return invoke('ws_subscribe', { symbols, mode });
}

export async function unsubscribe(
    symbols: Array<{symbol: string, exchange: string}>
) {
    return invoke('ws_unsubscribe', { symbols });
}

export async function disconnect() {
    return invoke('ws_disconnect');
}

// Derived stores
export function getSymbolData(symbol: string, exchange: string) {
    return derived(marketData, $data => {
        const key = getKey(symbol, exchange);
        return $data.get(key);
    });
}
```

### Usage in Components

```svelte
<script lang="ts">
import { onMount, onDestroy } from 'svelte';
import { getSymbolData, subscribe, unsubscribe } from '$lib/stores/websocket';

export let symbol: string;
export let exchange: string;

const data = getSymbolData(symbol, exchange);

onMount(async () => {
    await subscribe([{ symbol, exchange }], 'Quote');
});

onDestroy(async () => {
    await unsubscribe([{ symbol, exchange }]);
});
</script>

{#if $data}
<div class="quote-card">
    <div class="symbol">{symbol}</div>
    <div class="ltp">{$data.data.ltp.toFixed(2)}</div>
    <div class="change" class:positive={$data.data.ltp > $data.data.close}>
        {(($data.data.ltp - $data.data.close) / $data.data.close * 100).toFixed(2)}%
    </div>
</div>
{/if}
```

---

## Error Handling

```rust
#[derive(Debug, thiserror::Error)]
pub enum WebSocketError {
    #[error("Client not found")]
    ClientNotFound,

    #[error("Not authenticated")]
    NotAuthenticated,

    #[error("Invalid API key")]
    InvalidApiKey,

    #[error("Broker adapter not available")]
    AdapterNotAvailable,

    #[error("Connection failed: {0}")]
    ConnectionFailed(String),

    #[error("Subscription failed: {0}")]
    SubscriptionFailed(String),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("WebSocket error: {0}")]
    Tungstenite(#[from] tokio_tungstenite::tungstenite::Error),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
}
```

---

## Performance Metrics

| Metric | Target | Description |
|--------|--------|-------------|
| LTP Updates | 20/second | 50ms throttle per symbol |
| Quote/Depth Updates | Unlimited | No throttling |
| Max Clients | 1000+ | Per server instance |
| Subscription Lookup | O(1) | Using subscription index |
| Message Buffer | 1000 | Broadcast channel capacity |
| Reconnect Backoff | Exponential | Max 5 attempts |

---

## Conclusion

This WebSocket streaming architecture provides:

1. **Protocol Compatibility** - Same message format as Python implementation
2. **High Performance** - O(1) subscription lookups, efficient broadcasting
3. **Multi-Broker Support** - Pluggable adapter architecture
4. **Tauri Integration** - Seamless frontend communication via events
5. **Throttling** - LTP rate limiting to prevent UI overload
6. **Error Recovery** - Automatic reconnection with backoff
