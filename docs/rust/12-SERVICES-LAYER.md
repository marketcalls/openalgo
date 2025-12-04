# OpenAlgo Desktop - Services Layer Architecture

## Overview

The Services Layer contains the core business logic of OpenAlgo, sitting between the API/UI layer and the broker adapters. This document defines the internal service patterns and their Rust implementations.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Services Layer                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                         API Layer (REST/Tauri)                          ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                         Order Services                                   ││
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐││
│  │  │ PlaceOrder  │ │ SmartOrder  │ │ BasketOrder │ │ OptionsOrder        │││
│  │  │ Service     │ │ Service     │ │ Service     │ │ Service             │││
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────────┘││
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐││
│  │  │ ModifyOrder │ │ CancelOrder │ │ ClosePos    │ │ SplitOrder          │││
│  │  │ Service     │ │ Service     │ │ Service     │ │ Service             │││
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────────┘││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                    │                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                         Data Services                                    ││
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐││
│  │  │ Quotes      │ │ Depth       │ │ History     │ │ OptionChain         │││
│  │  │ Service     │ │ Service     │ │ Service     │ │ Service             │││
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────────┘││
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐││
│  │  │ OptionGreeks│ │ Symbol      │ │ Instruments │ │ Search              │││
│  │  │ Service     │ │ Service     │ │ Service     │ │ Service             │││
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────────┘││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                    │                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                         Account Services                                 ││
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐││
│  │  │ OrderBook   │ │ TradeBook   │ │ PositionBook│ │ Holdings            │││
│  │  │ Service     │ │ Service     │ │ Service     │ │ Service             │││
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────────┘││
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                        ││
│  │  │ Funds       │ │ Margin      │ │ OpenPosition│                        ││
│  │  │ Service     │ │ Service     │ │ Service     │                        ││
│  │  └─────────────┘ └─────────────┘ └─────────────┘                        ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                    │                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                         Support Services                                 ││
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐││
│  │  │ OrderRouter │ │ Sandbox     │ │ Analyzer    │ │ TelegramAlert       │││
│  │  │ Service     │ │ Service     │ │ Service     │ │ Service             │││
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────────┘││
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                        ││
│  │  │ WebSocket   │ │ PendingOrder│ │ MasterContract                      ││
│  │  │ Service     │ │ Execution   │ │ Service     │                        ││
│  │  └─────────────┘ └─────────────┘ └─────────────┘                        ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                         Broker Adapters                                  ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Service Response Pattern

All services follow a consistent response pattern:

```rust
/// Standard service result type
pub type ServiceResult<T> = Result<ServiceResponse<T>, ServiceError>;

/// Service response wrapper
#[derive(Debug, Clone, Serialize)]
pub struct ServiceResponse<T> {
    pub success: bool,
    pub data: T,
    pub status_code: u16,
}

impl<T> ServiceResponse<T> {
    pub fn ok(data: T) -> ServiceResult<T> {
        Ok(Self {
            success: true,
            data,
            status_code: 200,
        })
    }

    pub fn created(data: T) -> ServiceResult<T> {
        Ok(Self {
            success: true,
            data,
            status_code: 201,
        })
    }
}

/// Service error types
#[derive(Debug, thiserror::Error)]
pub enum ServiceError {
    #[error("Validation error: {message}")]
    Validation { message: String, status_code: u16 },

    #[error("Authentication failed: {message}")]
    Authentication { message: String },

    #[error("Authorization failed: {message}")]
    Authorization { message: String },

    #[error("Resource not found: {message}")]
    NotFound { message: String },

    #[error("Broker error: {message}")]
    Broker { message: String, status_code: u16 },

    #[error("Database error: {0}")]
    Database(#[from] sqlx::Error),

    #[error("Internal error: {message}")]
    Internal { message: String },
}

impl ServiceError {
    pub fn status_code(&self) -> u16 {
        match self {
            Self::Validation { status_code, .. } => *status_code,
            Self::Authentication { .. } => 401,
            Self::Authorization { .. } => 403,
            Self::NotFound { .. } => 404,
            Self::Broker { status_code, .. } => *status_code,
            Self::Database(_) => 500,
            Self::Internal { .. } => 500,
        }
    }

    pub fn validation(message: impl Into<String>) -> Self {
        Self::Validation {
            message: message.into(),
            status_code: 400,
        }
    }
}
```

---

## Service Trait

```rust
use async_trait::async_trait;

/// Base trait for all services
#[async_trait]
pub trait Service: Send + Sync {
    /// Service name for logging
    fn name(&self) -> &'static str;

    /// Initialize service (called on startup)
    async fn init(&self) -> Result<(), ServiceError> {
        Ok(())
    }

    /// Shutdown service (called on app exit)
    async fn shutdown(&self) -> Result<(), ServiceError> {
        Ok(())
    }
}
```

---

## Order Services

### 1. PlaceOrderService

```rust
pub struct PlaceOrderService {
    db: SqlitePool,
    broker_manager: Arc<BrokerManager>,
    order_router: Arc<OrderRouterService>,
    sandbox_service: Arc<SandboxService>,
    telegram_alert: Arc<TelegramAlertService>,
    api_log: Arc<ApiLogDb>,
}

impl PlaceOrderService {
    /// Place an order with the broker
    ///
    /// Supports both API-based and internal calls:
    /// - API calls: Use `api_key` parameter
    /// - Internal calls: Use `auth_token` and `broker` parameters
    pub async fn place_order(
        &self,
        order_data: PlaceOrderRequest,
        api_key: Option<&str>,
        auth_token: Option<&str>,
        broker: Option<&str>,
    ) -> ServiceResult<OrderResponse> {
        // 1. Check for Action Center routing (semi-auto mode)
        if let Some(key) = api_key {
            if auth_token.is_none() && broker.is_none() {
                if self.order_router.should_route_to_pending(key, "placeorder").await? {
                    return self.order_router.queue_order(key, &order_data, "placeorder").await;
                }
            }
        }

        // 2. Validate order data
        self.validate_order(&order_data)?;

        // 3. Validate symbol exists in master contract
        self.validate_symbol(&order_data.symbol, &order_data.exchange).await?;

        // 4. Get authentication
        let (token, broker_name) = self.get_auth(api_key, auth_token, broker).await?;

        // 5. Check sandbox mode
        if self.is_analyze_mode().await? {
            return self.sandbox_service.place_order(order_data, api_key.unwrap()).await;
        }

        // 6. Get broker adapter
        let adapter = self.broker_manager.get_adapter(&broker_name)?;

        // 7. Execute order
        let result = adapter.place_order(&order_data, &token).await?;

        // 8. Log order
        self.api_log.log_order("placeorder", &order_data, &result).await;

        // 9. Send Telegram alert
        self.telegram_alert.send_order_alert("placeorder", &order_data, &result).await.ok();

        // 10. Emit WebSocket event
        self.emit_order_event(&order_data, &result).await;

        ServiceResponse::ok(result)
    }

    /// Validate order fields
    fn validate_order(&self, order: &PlaceOrderRequest) -> Result<(), ServiceError> {
        // Check required fields
        if order.symbol.is_empty() {
            return Err(ServiceError::validation("Symbol is required"));
        }

        // Validate quantity
        if order.quantity == 0 {
            return Err(ServiceError::validation("Quantity must be positive"));
        }

        // Validate price for LIMIT orders
        if order.pricetype == PriceType::Limit && order.price <= 0.0 {
            return Err(ServiceError::validation("Price is required for LIMIT orders"));
        }

        // Validate trigger price for SL orders
        if (order.pricetype == PriceType::Sl || order.pricetype == PriceType::SlM)
            && order.trigger_price <= 0.0
        {
            return Err(ServiceError::validation("Trigger price is required for SL orders"));
        }

        Ok(())
    }

    /// Validate symbol exists in master contract
    async fn validate_symbol(&self, symbol: &str, exchange: &Exchange) -> Result<(), ServiceError> {
        let token = self.master_contract.get_token(symbol, exchange).await?;

        if token.is_none() {
            return Err(ServiceError::validation(format!(
                "Symbol '{}' not found for exchange '{}'. Please verify the symbol name and ensure master contracts are downloaded.",
                symbol, exchange
            )));
        }

        Ok(())
    }

    /// Get authentication from API key or direct params
    async fn get_auth(
        &self,
        api_key: Option<&str>,
        auth_token: Option<&str>,
        broker: Option<&str>,
    ) -> Result<(String, String), ServiceError> {
        match (api_key, auth_token, broker) {
            // API-based authentication
            (Some(key), None, None) => {
                let (token, broker) = self.db.get_auth_token_broker(key).await?;
                match token {
                    Some(t) => Ok((t, broker.unwrap())),
                    None => Err(ServiceError::Authentication {
                        message: "Invalid openalgo apikey".to_string(),
                    }),
                }
            }
            // Direct internal call
            (_, Some(token), Some(broker)) => {
                Ok((token.to_string(), broker.to_string()))
            }
            _ => Err(ServiceError::validation(
                "Either api_key or both auth_token and broker must be provided"
            )),
        }
    }
}
```

### 2. SmartOrderService

```rust
pub struct SmartOrderService {
    db: SqlitePool,
    place_order_service: Arc<PlaceOrderService>,
    position_service: Arc<PositionBookService>,
}

impl SmartOrderService {
    /// Place a smart order (position-sized)
    ///
    /// Smart orders automatically adjust quantity based on:
    /// - Current position
    /// - Target position size
    /// - Requested action
    pub async fn place_smart_order(
        &self,
        order_data: SmartOrderRequest,
        api_key: Option<&str>,
        auth_token: Option<&str>,
        broker: Option<&str>,
    ) -> ServiceResult<SmartOrderResponse> {
        // 1. Get current position
        let current_position = self.get_current_position(
            &order_data.symbol,
            &order_data.exchange,
            &order_data.product,
            &order_data.strategy,
            api_key,
            auth_token,
            broker,
        ).await?;

        // 2. Calculate required action
        let (final_action, final_quantity) = self.calculate_smart_order(
            &order_data,
            current_position,
        )?;

        // 3. If no action needed, return early
        if final_quantity == 0 {
            return ServiceResponse::ok(SmartOrderResponse {
                status: "success".to_string(),
                message: "Position already at target size".to_string(),
                action_taken: None,
                orderid: None,
            });
        }

        // 4. Place the calculated order
        let place_order = PlaceOrderRequest {
            apikey: order_data.apikey.clone(),
            strategy: order_data.strategy.clone(),
            exchange: order_data.exchange.clone(),
            symbol: order_data.symbol.clone(),
            action: final_action.clone(),
            quantity: final_quantity,
            pricetype: order_data.pricetype.clone(),
            product: order_data.product.clone(),
            price: order_data.price,
            trigger_price: order_data.trigger_price,
            disclosed_quantity: order_data.disclosed_quantity,
        };

        let result = self.place_order_service.place_order(
            place_order,
            api_key,
            auth_token,
            broker,
        ).await?;

        ServiceResponse::ok(SmartOrderResponse {
            status: "success".to_string(),
            message: format!("Smart order executed: {} {}", final_action, final_quantity),
            action_taken: Some(final_action),
            orderid: Some(result.data.orderid),
        })
    }

    /// Calculate smart order action and quantity
    fn calculate_smart_order(
        &self,
        order: &SmartOrderRequest,
        current_position: i32,
    ) -> Result<(Action, u32), ServiceError> {
        let target_position = order.position_size;
        let action = &order.action;

        let diff = target_position - current_position;

        if diff == 0 {
            // Already at target
            return Ok((Action::Buy, 0));
        }

        if diff > 0 {
            // Need to BUY to reach target
            Ok((Action::Buy, diff as u32))
        } else {
            // Need to SELL to reach target
            Ok((Action::Sell, (-diff) as u32))
        }
    }

    /// Get current position for symbol
    async fn get_current_position(
        &self,
        symbol: &str,
        exchange: &Exchange,
        product: &Product,
        strategy: &str,
        api_key: Option<&str>,
        auth_token: Option<&str>,
        broker: Option<&str>,
    ) -> Result<i32, ServiceError> {
        let positions = self.position_service.get_positions(
            api_key, auth_token, broker
        ).await?;

        // Find matching position
        let position = positions.data.iter().find(|p| {
            p.symbol == symbol &&
            p.exchange == exchange.to_string() &&
            p.product == product.to_string()
        });

        Ok(position.map(|p| p.quantity).unwrap_or(0))
    }
}
```

### 3. BasketOrderService

```rust
pub struct BasketOrderService {
    db: SqlitePool,
    place_order_service: Arc<PlaceOrderService>,
}

impl BasketOrderService {
    /// Place multiple orders in a basket
    pub async fn place_basket_order(
        &self,
        basket_data: BasketOrderRequest,
        api_key: Option<&str>,
        auth_token: Option<&str>,
        broker: Option<&str>,
    ) -> ServiceResult<BasketOrderResponse> {
        let mut results = Vec::new();
        let mut success_count = 0;
        let mut failed_count = 0;

        for order_item in &basket_data.orders {
            let order = PlaceOrderRequest {
                strategy: basket_data.strategy.clone(),
                exchange: order_item.exchange.clone(),
                symbol: order_item.symbol.clone(),
                action: order_item.action.clone(),
                quantity: order_item.quantity,
                pricetype: order_item.pricetype.clone(),
                product: order_item.product.clone(),
                price: order_item.price,
                trigger_price: order_item.trigger_price,
                disclosed_quantity: order_item.disclosed_quantity,
                ..Default::default()
            };

            match self.place_order_service.place_order(
                order.clone(),
                api_key,
                auth_token,
                broker,
            ).await {
                Ok(response) => {
                    success_count += 1;
                    results.push(BasketOrderResult {
                        symbol: order_item.symbol.clone(),
                        exchange: order_item.exchange.to_string(),
                        status: "success".to_string(),
                        orderid: Some(response.data.orderid),
                        message: None,
                    });
                }
                Err(e) => {
                    failed_count += 1;
                    results.push(BasketOrderResult {
                        symbol: order_item.symbol.clone(),
                        exchange: order_item.exchange.to_string(),
                        status: "error".to_string(),
                        orderid: None,
                        message: Some(e.to_string()),
                    });
                }
            }
        }

        ServiceResponse::ok(BasketOrderResponse {
            status: if failed_count == 0 { "success" } else { "partial" }.to_string(),
            total_orders: basket_data.orders.len(),
            success_count,
            failed_count,
            results,
        })
    }
}
```

---

## Data Services

### 1. QuotesService

```rust
pub struct QuotesService {
    db: SqlitePool,
    broker_manager: Arc<BrokerManager>,
    master_contract: Arc<MasterContractService>,
}

impl QuotesService {
    /// Get real-time quote for a symbol
    pub async fn get_quotes(
        &self,
        symbol: &str,
        exchange: &str,
        api_key: Option<&str>,
        auth_token: Option<&str>,
        feed_token: Option<&str>,
        broker: Option<&str>,
    ) -> ServiceResult<QuoteData> {
        // 1. Validate symbol
        self.validate_symbol(symbol, exchange).await?;

        // 2. Get authentication
        let (token, feed, broker_name) = self.get_auth(api_key, auth_token, feed_token, broker).await?;

        // 3. Get broker data adapter
        let adapter = self.broker_manager.get_data_adapter(&broker_name)?;

        // 4. Fetch quotes
        let quotes = adapter.get_quotes(symbol, exchange, &token, feed.as_deref()).await?;

        ServiceResponse::ok(quotes)
    }

    /// Get quotes for multiple symbols
    pub async fn get_multiquotes(
        &self,
        symbols: Vec<SymbolExchange>,
        api_key: Option<&str>,
        auth_token: Option<&str>,
        feed_token: Option<&str>,
        broker: Option<&str>,
    ) -> ServiceResult<MultiQuoteResponse> {
        // 1. Validate all symbols
        let (valid, invalid) = self.validate_symbols_bulk(&symbols).await;

        if valid.is_empty() {
            return Err(ServiceError::validation("No valid symbols provided"));
        }

        // 2. Get authentication
        let (token, feed, broker_name) = self.get_auth(api_key, auth_token, feed_token, broker).await?;

        // 3. Get broker data adapter
        let adapter = self.broker_manager.get_data_adapter(&broker_name)?;

        // 4. Fetch quotes for valid symbols
        let mut results = Vec::new();

        // Add invalid symbol errors
        for item in invalid {
            results.push(QuoteResult {
                symbol: item.symbol,
                exchange: item.exchange,
                data: None,
                error: Some(item.error),
            });
        }

        // Fetch quotes (broker may support batch or we fallback to individual)
        if adapter.supports_multiquotes() {
            let quotes = adapter.get_multiquotes(&valid, &token, feed.as_deref()).await?;
            results.extend(quotes);
        } else {
            for item in valid {
                match adapter.get_quotes(&item.symbol, &item.exchange, &token, feed.as_deref()).await {
                    Ok(quote) => {
                        results.push(QuoteResult {
                            symbol: item.symbol,
                            exchange: item.exchange,
                            data: Some(quote),
                            error: None,
                        });
                    }
                    Err(e) => {
                        results.push(QuoteResult {
                            symbol: item.symbol,
                            exchange: item.exchange,
                            data: None,
                            error: Some(e.to_string()),
                        });
                    }
                }
            }
        }

        ServiceResponse::ok(MultiQuoteResponse { results })
    }

    /// Validate symbol exists in master contract
    async fn validate_symbol(&self, symbol: &str, exchange: &str) -> Result<(), ServiceError> {
        // Validate exchange
        let exchange = exchange.to_uppercase();
        if !VALID_EXCHANGES.contains(&exchange.as_str()) {
            return Err(ServiceError::validation(format!(
                "Invalid exchange '{}'. Must be one of: {}",
                exchange,
                VALID_EXCHANGES.join(", ")
            )));
        }

        // Validate symbol
        let token = self.master_contract.get_token(symbol, &exchange).await?;
        if token.is_none() {
            return Err(ServiceError::validation(format!(
                "Symbol '{}' not found for exchange '{}'. Please verify the symbol name and ensure master contracts are downloaded.",
                symbol, exchange
            )));
        }

        Ok(())
    }
}
```

### 2. HistoryService

```rust
pub struct HistoryService {
    db: SqlitePool,
    broker_manager: Arc<BrokerManager>,
    master_contract: Arc<MasterContractService>,
}

impl HistoryService {
    /// Get historical OHLCV data
    pub async fn get_history(
        &self,
        symbol: &str,
        exchange: &str,
        interval: &Interval,
        start_date: NaiveDate,
        end_date: NaiveDate,
        api_key: Option<&str>,
        auth_token: Option<&str>,
        broker: Option<&str>,
    ) -> ServiceResult<HistoryData> {
        // 1. Validate symbol
        self.validate_symbol(symbol, exchange).await?;

        // 2. Validate date range
        if end_date < start_date {
            return Err(ServiceError::validation("end_date must be >= start_date"));
        }

        // 3. Get authentication
        let (token, broker_name) = self.get_auth(api_key, auth_token, broker).await?;

        // 4. Get broker data adapter
        let adapter = self.broker_manager.get_data_adapter(&broker_name)?;

        // 5. Fetch historical data
        let history = adapter.get_history(
            symbol,
            exchange,
            interval,
            start_date,
            end_date,
            &token,
        ).await?;

        ServiceResponse::ok(history)
    }
}
```

### 3. OptionGreeksService

```rust
pub struct OptionGreeksService {
    db: SqlitePool,
    quotes_service: Arc<QuotesService>,
    master_contract: Arc<MasterContractService>,
}

impl OptionGreeksService {
    /// Calculate option Greeks using Black-76 model
    pub async fn calculate_greeks(
        &self,
        option_symbol: &str,
        exchange: &str,
        interest_rate: Option<f64>,
        forward_price: Option<f64>,
        underlying_symbol: Option<&str>,
        underlying_exchange: Option<&str>,
        expiry_time: Option<&str>,
        api_key: Option<&str>,
    ) -> ServiceResult<OptionGreeksResponse> {
        // 1. Parse option symbol
        let option_info = self.parse_option_symbol(option_symbol, exchange)?;

        // 2. Get option LTP
        let option_quote = self.quotes_service.get_quotes(
            option_symbol, exchange, api_key, None, None, None
        ).await?;
        let option_price = option_quote.data.ltp;

        // 3. Get forward price (or calculate from underlying)
        let forward = match forward_price {
            Some(f) => f,
            None => {
                // Get underlying price
                let (und_symbol, und_exchange) = match (underlying_symbol, underlying_exchange) {
                    (Some(s), Some(e)) => (s.to_string(), e.to_string()),
                    _ => self.resolve_underlying(&option_info)?,
                };

                let und_quote = self.quotes_service.get_quotes(
                    &und_symbol, &und_exchange, api_key, None, None, None
                ).await?;
                und_quote.data.ltp
            }
        };

        // 4. Calculate time to expiry
        let days_to_expiry = self.calculate_days_to_expiry(
            &option_info.expiry_date,
            expiry_time,
        )?;

        // 5. Calculate implied volatility
        let iv = self.calculate_iv(
            option_price,
            forward,
            option_info.strike as f64,
            days_to_expiry,
            interest_rate.unwrap_or(0.0),
            &option_info.option_type,
        )?;

        // 6. Calculate Greeks
        let greeks = self.calculate_black76_greeks(
            forward,
            option_info.strike as f64,
            days_to_expiry,
            iv,
            interest_rate.unwrap_or(0.0),
            &option_info.option_type,
        );

        ServiceResponse::ok(OptionGreeksResponse {
            symbol: option_symbol.to_string(),
            exchange: exchange.to_string(),
            underlying: option_info.underlying,
            strike: option_info.strike,
            option_type: option_info.option_type.to_string(),
            expiry_date: option_info.expiry_date.format("%d-%b-%Y").to_string(),
            days_to_expiry,
            forward_price: forward,
            option_price,
            interest_rate: interest_rate.unwrap_or(0.0),
            implied_volatility: iv * 100.0, // Convert to percentage
            greeks,
        })
    }

    /// Calculate Black-76 Greeks
    fn calculate_black76_greeks(
        &self,
        forward: f64,
        strike: f64,
        time: f64,
        volatility: f64,
        rate: f64,
        option_type: &OptionType,
    ) -> Greeks {
        let sqrt_t = (time / 365.0).sqrt();
        let d1 = ((forward / strike).ln() + (volatility.powi(2) / 2.0) * (time / 365.0))
            / (volatility * sqrt_t);
        let d2 = d1 - volatility * sqrt_t;

        let discount = (-rate * time / 365.0).exp();

        let (delta, gamma, theta, vega, rho) = match option_type {
            OptionType::Ce => {
                let delta = discount * Self::norm_cdf(d1);
                let gamma = discount * Self::norm_pdf(d1) / (forward * volatility * sqrt_t);
                let theta = -(forward * volatility * Self::norm_pdf(d1)) / (2.0 * sqrt_t)
                    + rate * strike * discount * Self::norm_cdf(d2);
                let vega = forward * discount * sqrt_t * Self::norm_pdf(d1) / 100.0;
                let rho = -time / 365.0 * discount *
                    (forward * Self::norm_cdf(d1) - strike * Self::norm_cdf(d2));

                (delta, gamma, theta / 365.0, vega, rho)
            }
            OptionType::Pe => {
                let delta = discount * (Self::norm_cdf(d1) - 1.0);
                let gamma = discount * Self::norm_pdf(d1) / (forward * volatility * sqrt_t);
                let theta = -(forward * volatility * Self::norm_pdf(d1)) / (2.0 * sqrt_t)
                    - rate * strike * discount * Self::norm_cdf(-d2);
                let vega = forward * discount * sqrt_t * Self::norm_pdf(d1) / 100.0;
                let rho = time / 365.0 * discount *
                    (strike * Self::norm_cdf(-d2) - forward * Self::norm_cdf(-d1));

                (delta, gamma, theta / 365.0, vega, rho)
            }
        };

        Greeks { delta, gamma, theta, vega, rho }
    }

    fn norm_cdf(x: f64) -> f64 {
        0.5 * (1.0 + libm::erf(x / std::f64::consts::SQRT_2))
    }

    fn norm_pdf(x: f64) -> f64 {
        (-x.powi(2) / 2.0).exp() / (2.0 * std::f64::consts::PI).sqrt()
    }
}
```

---

## Service Registry

```rust
/// Central service registry for dependency injection
pub struct ServiceRegistry {
    pub place_order: Arc<PlaceOrderService>,
    pub smart_order: Arc<SmartOrderService>,
    pub basket_order: Arc<BasketOrderService>,
    pub modify_order: Arc<ModifyOrderService>,
    pub cancel_order: Arc<CancelOrderService>,
    pub close_position: Arc<ClosePositionService>,
    pub split_order: Arc<SplitOrderService>,
    pub options_order: Arc<OptionsOrderService>,
    pub options_multi: Arc<OptionsMultiOrderService>,

    pub quotes: Arc<QuotesService>,
    pub depth: Arc<DepthService>,
    pub history: Arc<HistoryService>,
    pub option_chain: Arc<OptionChainService>,
    pub option_greeks: Arc<OptionGreeksService>,
    pub symbol: Arc<SymbolService>,
    pub search: Arc<SearchService>,
    pub instruments: Arc<InstrumentsService>,
    pub expiry: Arc<ExpiryService>,

    pub orderbook: Arc<OrderBookService>,
    pub tradebook: Arc<TradeBookService>,
    pub positionbook: Arc<PositionBookService>,
    pub holdings: Arc<HoldingsService>,
    pub funds: Arc<FundsService>,
    pub margin: Arc<MarginService>,
    pub open_position: Arc<OpenPositionService>,

    pub order_router: Arc<OrderRouterService>,
    pub sandbox: Arc<SandboxService>,
    pub analyzer: Arc<AnalyzerService>,
    pub telegram: Arc<TelegramAlertService>,
    pub websocket: Arc<WebSocketService>,
    pub master_contract: Arc<MasterContractService>,
}

impl ServiceRegistry {
    /// Initialize all services
    pub async fn new(db: SqlitePool, broker_manager: Arc<BrokerManager>) -> Result<Self, ServiceError> {
        // Initialize in dependency order
        let master_contract = Arc::new(MasterContractService::new(db.clone()));
        let telegram = Arc::new(TelegramAlertService::new(db.clone()));

        // ... initialize all services

        Ok(Self {
            // ... assign all services
        })
    }

    /// Shutdown all services gracefully
    pub async fn shutdown(&self) -> Result<(), ServiceError> {
        // Shutdown in reverse order
        self.websocket.shutdown().await?;
        self.telegram.shutdown().await?;
        // ... shutdown remaining services

        Ok(())
    }
}
```

---

## Conclusion

The Services Layer provides:

1. **Clean Separation** - Business logic isolated from API/UI layers
2. **Consistent Patterns** - Standard response types and error handling
3. **Dependency Injection** - Services receive dependencies through constructor
4. **Testability** - Services can be mocked for unit testing
5. **Reusability** - Services can be called from REST API, Tauri commands, or internal code
