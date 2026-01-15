# 16. Webhook Platforms Integration

## Overview

OpenAlgo Desktop supports multiple trading platforms through webhook integrations. Each platform has a dedicated module for generating webhook payloads and processing incoming signals. The Rust implementation must maintain 100% compatibility with existing integrations.

## Supported Platforms

### 1. TradingView (`/tradingview`)

**Purpose**: Generate webhook JSON for TradingView Pine Script strategies and line alerts.

**Blueprint**: `blueprints/tv_json.py`

#### Two Operating Modes

**Strategy Alert Mode** (default):
- Uses `placesmartorder` API endpoint
- Supports Pine Script strategy variables: `{{strategy.order.action}}`, `{{strategy.order.contracts}}`, `{{strategy.position_size}}`
- Automatic position management

**Line Alert Mode**:
- Uses `placeorder` API endpoint
- Fixed quantity and action
- Simple buy/sell signals

#### Rust Implementation

```rust
// src-tauri/src/platforms/tradingview.rs

use axum::{extract::State, Json};
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
pub struct TradingViewRequest {
    pub symbol: String,
    pub exchange: String,
    pub product: String,               // MIS, CNC, NRML
    pub mode: Option<String>,          // "strategy" or "line"
    pub action: Option<String>,        // Required for line mode
    pub quantity: Option<String>,      // Required for line mode
}

#[derive(Debug, Serialize)]
pub struct TradingViewWebhook {
    pub apikey: String,
    pub strategy: String,
    pub symbol: String,
    pub action: String,
    pub exchange: String,
    pub pricetype: String,
    pub product: String,
    pub quantity: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub position_size: Option<String>,
}

/// Generate TradingView webhook JSON
pub async fn generate_webhook(
    State(state): State<AppState>,
    session: Session,
    Json(req): Json<TradingViewRequest>,
) -> Result<Json<TradingViewWebhook>, ApiError> {
    let user_id = session.get_user_id()?;

    // Get API key from database
    let api_key = state.auth_service.get_api_key_for_tradingview(user_id).await?;

    // Validate and lookup symbol
    let symbol_data = state.symbol_service
        .enhanced_search(&req.symbol, Some(&req.exchange))
        .await?
        .first()
        .ok_or(ApiError::SymbolNotFound)?;

    let mode = req.mode.unwrap_or_else(|| "strategy".to_string());

    let webhook = if mode == "line" {
        // Line Alert Mode - simple fixed orders
        let action = req.action.ok_or(ApiError::MissingField("action"))?;
        let quantity = req.quantity.ok_or(ApiError::MissingField("quantity"))?;

        TradingViewWebhook {
            apikey: api_key,
            strategy: "TradingView Line Alert".to_string(),
            symbol: symbol_data.symbol.clone(),
            action: action.to_uppercase(),
            exchange: symbol_data.exchange.clone(),
            pricetype: "MARKET".to_string(),
            product: req.product,
            quantity,
            position_size: None,
        }
    } else {
        // Strategy Alert Mode - uses Pine Script variables
        TradingViewWebhook {
            apikey: api_key,
            strategy: "TradingView Strategy".to_string(),
            symbol: symbol_data.symbol.clone(),
            action: "{{strategy.order.action}}".to_string(),
            exchange: symbol_data.exchange.clone(),
            pricetype: "MARKET".to_string(),
            product: req.product,
            quantity: "{{strategy.order.contracts}}".to_string(),
            position_size: Some("{{strategy.position_size}}".to_string()),
        }
    };

    Ok(Json(webhook))
}
```

#### TradingView UI Page

The `/tradingview` page provides:
- Symbol search with autocomplete
- Exchange selection (NSE, BSE, NFO, MCX, etc.)
- Product type selection (MIS, CNC, NRML)
- Mode toggle (Strategy vs Line Alert)
- Generated JSON preview with copy button
- Webhook URL display (using HOST_SERVER configuration)

---

### 2. GoCharting (`/gocharting`)

**Purpose**: Generate webhook JSON for GoCharting platform alerts.

**Blueprint**: `blueprints/gc_json.py`

#### Key Differences from TradingView
- Always uses `placeorder` API (no smart orders)
- Fixed quantity (no Pine Script variables)
- Simpler payload structure

#### Rust Implementation

```rust
// src-tauri/src/platforms/gocharting.rs

#[derive(Debug, Deserialize)]
pub struct GoChartingRequest {
    pub symbol: String,
    pub exchange: String,
    pub product: String,
    pub action: String,      // BUY or SELL
    pub quantity: String,
}

#[derive(Debug, Serialize)]
pub struct GoChartingWebhook {
    pub apikey: String,
    pub strategy: String,
    pub symbol: String,
    pub action: String,
    pub exchange: String,
    pub pricetype: String,
    pub product: String,
    pub quantity: String,
}

pub async fn generate_webhook(
    State(state): State<AppState>,
    session: Session,
    Json(req): Json<GoChartingRequest>,
) -> Result<Json<GoChartingWebhook>, ApiError> {
    let user_id = session.get_user_id()?;
    let api_key = state.auth_service.get_api_key_for_tradingview(user_id).await?;

    // Validate symbol
    let symbol_data = state.symbol_service
        .enhanced_search(&req.symbol, Some(&req.exchange))
        .await?
        .first()
        .ok_or(ApiError::SymbolNotFound)?;

    Ok(Json(GoChartingWebhook {
        apikey: api_key,
        strategy: "GoCharting".to_string(),
        symbol: symbol_data.symbol.clone(),
        action: req.action.to_uppercase(),
        exchange: symbol_data.exchange.clone(),
        pricetype: "MARKET".to_string(),
        product: req.product,
        quantity: req.quantity,
    }))
}
```

---

### 3. ChartInk (`/chartink`)

**Purpose**: Full-featured strategy management for ChartInk stock screener alerts.

**Blueprint**: `blueprints/chartink.py`
**Database**: `database/chartink_db.py`

#### Key Features

1. **Strategy Management**
   - Create/edit/delete strategies
   - Per-strategy webhook URLs
   - User isolation (each user sees only their strategies)

2. **Symbol Mapping**
   - Map ChartInk symbols to broker symbols
   - Configure quantity per symbol
   - Set exchange (NSE/BSE only for ChartInk)
   - Set product type (MIS/CNC)

3. **Time Controls (Intraday)**
   - Start time: When to begin accepting signals
   - End time: When to stop accepting entry orders
   - Square-off time: Auto-close all positions
   - Scheduled square-off via APScheduler

4. **Order Processing**
   - Scan name parsing: BUY, SELL, SHORT, COVER
   - Rate-limited order queues (10/sec regular, 1/sec smart)
   - Background order processor thread

#### Database Schema

```rust
// src-tauri/src/database/models/chartink.rs

#[derive(Debug, Clone, Queryable, Insertable)]
#[diesel(table_name = chartink_strategies)]
pub struct ChartinkStrategy {
    pub id: i32,
    pub name: String,
    pub webhook_id: String,         // UUID for webhook URL
    pub user_id: String,
    pub is_active: bool,
    pub is_intraday: bool,
    pub start_time: Option<String>, // HH:MM format
    pub end_time: Option<String>,
    pub squareoff_time: Option<String>,
    pub created_at: NaiveDateTime,
    pub updated_at: Option<NaiveDateTime>,
}

#[derive(Debug, Clone, Queryable, Insertable)]
#[diesel(table_name = chartink_symbol_mappings)]
pub struct ChartinkSymbolMapping {
    pub id: i32,
    pub strategy_id: i32,
    pub chartink_symbol: String,
    pub exchange: String,
    pub quantity: i32,
    pub product_type: String,
    pub created_at: NaiveDateTime,
    pub updated_at: Option<NaiveDateTime>,
}
```

#### Webhook Handler

```rust
// src-tauri/src/platforms/chartink.rs

#[derive(Debug, Deserialize)]
pub struct ChartinkWebhook {
    pub scan_name: String,          // Contains BUY/SELL/SHORT/COVER
    pub stocks: String,             // Comma-separated symbols
    pub trigger_prices: Option<String>,
}

/// Handle incoming ChartInk webhook
pub async fn webhook_handler(
    State(state): State<AppState>,
    Path(webhook_id): Path<String>,
    Json(data): Json<ChartinkWebhook>,
) -> Result<Json<WebhookResponse>, ApiError> {
    // 1. Lookup strategy by webhook_id
    let strategy = state.chartink_service
        .get_strategy_by_webhook_id(&webhook_id)
        .await?
        .ok_or(ApiError::InvalidWebhookId)?;

    // 2. Check if strategy is active
    if !strategy.is_active {
        return Ok(Json(WebhookResponse::inactive()));
    }

    // 3. Parse action from scan_name
    let (action, use_smart_order, is_entry) = parse_scan_name(&data.scan_name)?;

    // 4. Time validation for intraday strategies
    if strategy.is_intraday {
        validate_trading_time(&strategy, is_entry)?;
    }

    // 5. Get symbol mappings and API key
    let mappings = state.chartink_service.get_symbol_mappings(strategy.id).await?;
    let api_key = state.auth_service.get_api_key_for_tradingview(&strategy.user_id).await?;

    // 6. Process each symbol
    let symbols: Vec<&str> = data.stocks.split(',').map(|s| s.trim()).collect();
    let mut processed = Vec::new();

    for symbol in symbols {
        if let Some(mapping) = mappings.iter().find(|m| m.chartink_symbol == symbol) {
            let order = build_order_payload(
                &api_key,
                &strategy,
                mapping,
                &action,
                use_smart_order,
            );

            // Queue order for rate-limited processing
            state.order_queue.enqueue(order, use_smart_order).await;
            processed.push(symbol.to_string());
        }
    }

    Ok(Json(WebhookResponse::success(processed)))
}

fn parse_scan_name(scan_name: &str) -> Result<(String, bool, bool), ApiError> {
    let upper = scan_name.to_uppercase();

    if upper.contains("BUY") {
        Ok(("BUY".to_string(), false, true))    // Regular order, entry
    } else if upper.contains("SELL") {
        Ok(("SELL".to_string(), true, false))   // Smart order, exit
    } else if upper.contains("SHORT") {
        Ok(("SELL".to_string(), false, true))   // Regular order, entry
    } else if upper.contains("COVER") {
        Ok(("BUY".to_string(), true, false))    // Smart order, exit
    } else {
        Err(ApiError::InvalidScanName)
    }
}
```

#### Order Queue System

```rust
// src-tauri/src/services/order_queue.rs

use std::collections::VecDeque;
use std::sync::Arc;
use tokio::sync::Mutex;

pub struct OrderQueue {
    regular_queue: Arc<Mutex<VecDeque<OrderPayload>>>,
    smart_queue: Arc<Mutex<VecDeque<OrderPayload>>>,
    last_regular_orders: Arc<Mutex<VecDeque<Instant>>>,
}

impl OrderQueue {
    pub async fn enqueue(&self, order: OrderPayload, is_smart: bool) {
        if is_smart {
            self.smart_queue.lock().await.push_back(order);
        } else {
            self.regular_queue.lock().await.push_back(order);
        }
    }

    /// Background processor with rate limiting
    /// - Smart orders: 1 per second
    /// - Regular orders: up to 10 per second
    pub async fn process_loop(&self, api_client: ApiClient) {
        loop {
            // Process smart orders first (1/sec)
            if let Some(order) = self.smart_queue.lock().await.pop_front() {
                if let Err(e) = api_client.place_smart_order(&order).await {
                    tracing::error!("Smart order failed: {}", e);
                }
                tokio::time::sleep(Duration::from_secs(1)).await;
                continue;
            }

            // Process regular orders (up to 10/sec)
            let now = Instant::now();
            {
                let mut last_orders = self.last_regular_orders.lock().await;
                // Remove timestamps older than 1 second
                while last_orders.front().map_or(false, |t| now.duration_since(*t) > Duration::from_secs(1)) {
                    last_orders.pop_front();
                }

                if last_orders.len() < 10 {
                    if let Some(order) = self.regular_queue.lock().await.pop_front() {
                        if let Err(e) = api_client.place_order(&order).await {
                            tracing::error!("Regular order failed: {}", e);
                        }
                        last_orders.push_back(now);
                    }
                }
            }

            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }
}
```

---

### 4. Universal Strategy Module (`/strategy`)

**Purpose**: Platform-agnostic strategy management supporting TradingView, ChartInk, and custom platforms.

**Blueprint**: `blueprints/strategy.py`
**Database**: `database/strategy_db.py`

#### Key Differences from ChartInk

1. **Multi-Platform Support**
   - Platform field: tradingview, chartink, gocharting, amibroker, custom
   - Different webhook payload handling per platform

2. **Trading Modes**
   - LONG: Only long positions (BUY to enter, SELL to exit)
   - SHORT: Only short positions (SELL to enter, BUY to exit)
   - BOTH: Bi-directional trading with position_size

3. **Extended Exchange Support**
   - NSE, BSE, NFO, CDS, BFO, BCD, MCX, NCDEX

4. **Caching Layer**
   - Webhook lookup cache (5-minute TTL)
   - User strategies cache (10-minute TTL)

#### Database Schema

```rust
// src-tauri/src/database/models/strategy.rs

#[derive(Debug, Clone, Queryable, Insertable)]
#[diesel(table_name = strategies)]
pub struct Strategy {
    pub id: i32,
    pub name: String,
    pub webhook_id: String,
    pub user_id: String,
    pub platform: String,              // tradingview, chartink, gocharting, etc.
    pub is_active: bool,
    pub is_intraday: bool,
    pub trading_mode: String,          // LONG, SHORT, BOTH
    pub start_time: Option<String>,
    pub end_time: Option<String>,
    pub squareoff_time: Option<String>,
    pub created_at: NaiveDateTime,
    pub updated_at: Option<NaiveDateTime>,
}
```

#### Webhook Handler with Trading Mode Logic

```rust
pub async fn strategy_webhook(
    State(state): State<AppState>,
    Path(webhook_id): Path<String>,
    Json(data): Json<StrategyWebhook>,
) -> Result<Json<WebhookResponse>, ApiError> {
    let strategy = state.strategy_service
        .get_by_webhook_id(&webhook_id)
        .await?
        .ok_or(ApiError::InvalidWebhookId)?;

    // Validate action based on trading mode
    let action = data.action.to_uppercase();
    let position_size: i32 = data.position_size.unwrap_or(0);

    let use_smart_order = match strategy.trading_mode.as_str() {
        "LONG" => {
            if action != "BUY" && action != "SELL" {
                return Err(ApiError::InvalidAction("LONG mode requires BUY or SELL"));
            }
            action == "SELL"  // Exit orders use smart order
        }
        "SHORT" => {
            if action != "BUY" && action != "SELL" {
                return Err(ApiError::InvalidAction("SHORT mode requires BUY or SELL"));
            }
            action == "BUY"   // Exit orders use smart order
        }
        "BOTH" => {
            // Validate position_size based on action
            if action == "BUY" && position_size < 0 {
                return Err(ApiError::InvalidPositionSize);
            }
            if action == "SELL" && position_size > 0 {
                return Err(ApiError::InvalidPositionSize);
            }
            position_size == 0  // Exit when position_size is 0
        }
        _ => false,
    };

    // Time validation for intraday
    if strategy.is_intraday {
        let is_exit = use_smart_order;
        validate_trading_time(&strategy, !is_exit)?;
    }

    // Get mapping and place order
    let mapping = state.strategy_service
        .get_symbol_mapping(strategy.id, &data.symbol)
        .await?
        .ok_or(ApiError::SymbolNotMapped)?;

    // Build and queue order...
    Ok(Json(WebhookResponse::success(vec![data.symbol])))
}
```

---

## Platform Comparison Matrix

| Feature | TradingView | GoCharting | ChartInk | Strategy |
|---------|-------------|------------|----------|----------|
| Strategy Variables | Yes | No | No | Optional |
| Smart Orders | Yes | No | Yes | Yes |
| Position Management | Yes | No | Yes | Yes |
| Symbol Mapping | No | No | Yes | Yes |
| Time Controls | No | No | Yes | Yes |
| Trading Modes | N/A | N/A | N/A | LONG/SHORT/BOTH |
| Exchanges | All | All | NSE/BSE | All |
| Order Queue | No | No | Yes | Yes |

---

## UI Components

### Platform Selection Page (`/platforms`)

Central hub for accessing all webhook platform configurations:

```svelte
<!-- src/routes/platforms/+page.svelte -->
<script lang="ts">
  const platforms = [
    {
      name: 'TradingView',
      route: '/tradingview',
      description: 'Pine Script strategies and line alerts',
      icon: 'tradingview',
    },
    {
      name: 'GoCharting',
      route: '/gocharting',
      description: 'Simple webhook alerts',
      icon: 'gocharting',
    },
    {
      name: 'ChartInk',
      route: '/chartink',
      description: 'Stock screener strategy automation',
      icon: 'chartink',
    },
    {
      name: 'Custom Strategy',
      route: '/strategy',
      description: 'Platform-agnostic strategy management',
      icon: 'strategy',
    },
  ];
</script>

<div class="grid grid-cols-2 gap-4">
  {#each platforms as platform}
    <a href={platform.route} class="platform-card">
      <h3>{platform.name}</h3>
      <p>{platform.description}</p>
    </a>
  {/each}
</div>
```

### ChartInk Strategy Manager

Full CRUD interface for ChartInk strategies:

1. **Strategy List** (`/chartink`)
   - Table of user's strategies
   - Status toggle (active/inactive)
   - Quick actions (view, configure, delete)

2. **New Strategy** (`/chartink/new`)
   - Strategy name input (auto-prefixed with `chartink_`)
   - Type selection (Intraday/Positional)
   - Time controls for intraday

3. **Symbol Configuration** (`/chartink/{id}/configure`)
   - Symbol search with autocomplete
   - Bulk import (CSV format: symbol,exchange,quantity,product)
   - Mapping table with delete actions

4. **Strategy View** (`/chartink/{id}`)
   - Webhook URL with copy button
   - Strategy settings
   - Symbol mappings table
   - ChartInk webhook format guide

---

## Rate Limiting Configuration

Environment variables for webhook rate limits:

```rust
// src-tauri/src/config/rate_limits.rs

pub struct WebhookRateLimits {
    /// General webhook rate limit (default: 100 per minute)
    pub webhook_rate_limit: String,

    /// Strategy management rate limit (default: 200 per minute)
    pub strategy_rate_limit: String,

    /// Order placement rate limits
    pub order_rate_limit: String,        // 10 per second
    pub smart_order_rate_limit: String,  // 2 per second
}

impl Default for WebhookRateLimits {
    fn default() -> Self {
        Self {
            webhook_rate_limit: "100 per minute".to_string(),
            strategy_rate_limit: "200 per minute".to_string(),
            order_rate_limit: "10 per second".to_string(),
            smart_order_rate_limit: "2 per second".to_string(),
        }
    }
}
```

---

## Axum Router Configuration

```rust
// src-tauri/src/api/router.rs

pub fn platform_routes() -> Router<AppState> {
    Router::new()
        // TradingView
        .route("/tradingview", get(tradingview::page))
        .route("/tradingview", post(tradingview::generate_webhook))

        // GoCharting
        .route("/gocharting", get(gocharting::page))
        .route("/gocharting", post(gocharting::generate_webhook))

        // ChartInk
        .route("/chartink", get(chartink::index))
        .route("/chartink/new", get(chartink::new_strategy_page).post(chartink::create_strategy))
        .route("/chartink/:id", get(chartink::view_strategy))
        .route("/chartink/:id/configure", get(chartink::configure_page).post(chartink::add_symbol))
        .route("/chartink/:id/delete", post(chartink::delete_strategy))
        .route("/chartink/:id/toggle", post(chartink::toggle_strategy))
        .route("/chartink/:id/symbol/:mapping_id/delete", post(chartink::delete_symbol))
        .route("/chartink/search", get(chartink::search_symbols))
        .route("/chartink/webhook/:webhook_id", post(chartink::webhook_handler))

        // Universal Strategy
        .route("/strategy", get(strategy::index))
        .route("/strategy/new", get(strategy::new_strategy_page).post(strategy::create_strategy))
        .route("/strategy/:id", get(strategy::view_strategy))
        .route("/strategy/:id/configure", get(strategy::configure_page).post(strategy::add_symbol))
        .route("/strategy/:id/delete", post(strategy::delete_strategy))
        .route("/strategy/toggle/:id", post(strategy::toggle_strategy))
        .route("/strategy/:id/symbol/:mapping_id/delete", post(strategy::delete_symbol))
        .route("/strategy/search", get(strategy::search_symbols))
        .route("/strategy/webhook/:webhook_id", post(strategy::webhook_handler))

        // Platforms hub
        .route("/platforms", get(platforms::index))
}
```

---

## Testing

### Unit Tests

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_scan_name() {
        assert_eq!(parse_scan_name("Buy Signal").unwrap(), ("BUY", false, true));
        assert_eq!(parse_scan_name("SELL NOW").unwrap(), ("SELL", true, false));
        assert_eq!(parse_scan_name("Short Entry").unwrap(), ("SELL", false, true));
        assert_eq!(parse_scan_name("Cover Exit").unwrap(), ("BUY", true, false));
        assert!(parse_scan_name("Invalid").is_err());
    }

    #[test]
    fn test_trading_mode_validation() {
        // LONG mode
        assert!(validate_action("BUY", "LONG", 0).is_ok());
        assert!(validate_action("SELL", "LONG", 0).is_ok());

        // SHORT mode
        assert!(validate_action("SELL", "SHORT", 0).is_ok());
        assert!(validate_action("BUY", "SHORT", 0).is_ok());

        // BOTH mode
        assert!(validate_action("BUY", "BOTH", 100).is_ok());
        assert!(validate_action("SELL", "BOTH", -100).is_ok());
        assert!(validate_action("BUY", "BOTH", -100).is_err()); // Invalid: BUY with negative
        assert!(validate_action("SELL", "BOTH", 100).is_err()); // Invalid: SELL with positive
    }
}
```

### Integration Tests

```rust
#[tokio::test]
async fn test_chartink_webhook_flow() {
    let app = create_test_app().await;

    // Create strategy
    let strategy = app.create_chartink_strategy("test_strategy", true).await;

    // Add symbol mapping
    app.add_symbol_mapping(strategy.id, "RELIANCE", "NSE", 10, "MIS").await;

    // Send webhook
    let response = app.post(&format!("/chartink/webhook/{}", strategy.webhook_id))
        .json(&json!({
            "scan_name": "Buy Signal",
            "stocks": "RELIANCE",
            "trigger_prices": "2500"
        }))
        .await;

    assert_eq!(response.status(), 200);

    // Verify order was queued
    assert!(app.order_queue_contains("RELIANCE").await);
}
```
