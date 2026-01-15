# OpenAlgo Desktop - Sandbox Mode (Paper Trading)

## Overview

Sandbox Mode (also called API Analyzer) provides a complete simulated trading environment for testing strategies without risking real capital. It uses real-time market data from broker feeds but executes orders in a virtual environment.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Sandbox Mode Architecture                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                         API Request                                     │ │
│  └────────────────────────────────┬───────────────────────────────────────┘ │
│                                   │                                          │
│                                   ▼                                          │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    Mode Router (check analyze_mode)                     │ │
│  └────────────────────────────────┬───────────────────────────────────────┘ │
│                                   │                                          │
│                   ┌───────────────┴───────────────┐                         │
│                   │                               │                          │
│                   ▼                               ▼                          │
│  ┌──────────────────────────┐     ┌──────────────────────────────────────┐ │
│  │      LIVE MODE           │     │         SANDBOX MODE                  │ │
│  │   (analyze_mode=false)   │     │      (analyze_mode=true)              │ │
│  │                          │     │                                       │ │
│  │  - Real broker API       │     │  - Virtual order book                 │ │
│  │  - Real funds deducted   │     │  - Rs 1 Crore virtual capital         │ │
│  │  - Real positions        │     │  - Simulated execution at LTP         │ │
│  │                          │     │  - Sandbox database                   │ │
│  └──────────────────────────┘     └──────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Database Schema

### Sandbox Tables

```rust
// sandbox_orders table
#[derive(sqlx::FromRow, Serialize, Deserialize)]
pub struct SandboxOrder {
    pub id: i64,
    pub orderid: String,            // "SB-{timestamp}"
    pub user_id: String,
    pub strategy: Option<String>,
    pub symbol: String,
    pub exchange: String,
    pub action: String,             // BUY, SELL
    pub quantity: i32,
    pub price: Option<f64>,
    pub trigger_price: Option<f64>,
    pub price_type: String,         // MARKET, LIMIT, SL, SL-M
    pub product: String,            // MIS, NRML, CNC
    pub order_status: String,       // open, complete, cancelled, rejected
    pub average_price: Option<f64>,
    pub filled_quantity: i32,
    pub pending_quantity: i32,
    pub rejection_reason: Option<String>,
    pub margin_blocked: f64,
    pub order_timestamp: DateTime<Utc>,
    pub update_timestamp: DateTime<Utc>,
}

// sandbox_trades table
#[derive(sqlx::FromRow, Serialize, Deserialize)]
pub struct SandboxTrade {
    pub id: i64,
    pub tradeid: String,            // "ST-{timestamp}"
    pub orderid: String,
    pub user_id: String,
    pub symbol: String,
    pub exchange: String,
    pub action: String,
    pub quantity: i32,
    pub price: f64,
    pub product: String,
    pub strategy: Option<String>,
    pub trade_timestamp: DateTime<Utc>,
}

// sandbox_positions table
#[derive(sqlx::FromRow, Serialize, Deserialize)]
pub struct SandboxPosition {
    pub id: i64,
    pub user_id: String,
    pub symbol: String,
    pub exchange: String,
    pub product: String,
    pub quantity: i32,              // Can be negative (short)
    pub average_price: f64,
    pub ltp: Option<f64>,
    pub pnl: f64,
    pub pnl_percent: f64,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

// sandbox_holdings table
#[derive(sqlx::FromRow, Serialize, Deserialize)]
pub struct SandboxHolding {
    pub id: i64,
    pub user_id: String,
    pub symbol: String,
    pub exchange: String,
    pub quantity: i32,
    pub average_price: f64,
    pub ltp: Option<f64>,
    pub pnl: f64,
    pub pnl_percent: f64,
    pub settlement_date: NaiveDate,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

// sandbox_funds table
#[derive(sqlx::FromRow, Serialize, Deserialize)]
pub struct SandboxFunds {
    pub id: i64,
    pub user_id: String,
    pub total_capital: f64,         // Default: 10,000,000 (1 Crore)
    pub available_balance: f64,
    pub used_margin: f64,
    pub realized_pnl: f64,
    pub unrealized_pnl: f64,
    pub total_pnl: f64,
    pub last_reset_date: DateTime<Utc>,
    pub reset_count: i32,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

// sandbox_config table
#[derive(sqlx::FromRow, Serialize, Deserialize)]
pub struct SandboxConfig {
    pub id: i64,
    pub config_key: String,
    pub config_value: String,
    pub description: Option<String>,
    pub updated_at: DateTime<Utc>,
}
```

### Configuration Entries

| Key | Default | Description |
|-----|---------|-------------|
| `starting_capital` | 10000000.00 | Rs 1 Crore starting balance |
| `reset_day` | Sunday | Weekly reset day |
| `reset_time` | 00:00 | Reset time (IST) |
| `order_check_interval` | 5 | Seconds between order checks |
| `mtm_update_interval` | 5 | Seconds between MTM updates |
| `nse_bse_square_off_time` | 15:15 | NSE/BSE auto square-off (IST) |
| `cds_bcd_square_off_time` | 16:45 | CDS/BCD auto square-off |
| `mcx_square_off_time` | 23:30 | MCX auto square-off |
| `ncdex_square_off_time` | 17:00 | NCDEX auto square-off |
| `equity_mis_leverage` | 5 | Equity MIS leverage |
| `equity_cnc_leverage` | 1 | Equity CNC leverage (no leverage) |
| `futures_leverage` | 10 | Futures leverage |
| `option_buy_leverage` | 1 | Option buy (full premium) |
| `option_sell_leverage` | 10 | Option sell (futures margin) |
| `order_rate_limit` | 10 | Orders per second |
| `api_rate_limit` | 50 | API calls per second |

---

## Core Components

### 1. Sandbox Service

```rust
pub struct SandboxService {
    db: SqlitePool,
    config: SandboxConfig,
    execution_handle: Option<JoinHandle<()>>,
    squareoff_scheduler: Option<SquareoffScheduler>,
}

impl SandboxService {
    /// Toggle sandbox mode on/off
    pub async fn toggle_mode(&mut self, enable: bool) -> Result<SandboxStatus, SandboxError> {
        if enable {
            self.start_execution_thread().await?;
            self.start_squareoff_scheduler().await?;
            self.set_analyze_mode(true).await?;
        } else {
            self.stop_execution_thread().await?;
            self.stop_squareoff_scheduler().await?;
            self.set_analyze_mode(false).await?;
        }

        Ok(SandboxStatus {
            mode: if enable { "analyze" } else { "live" },
            execution_running: self.execution_handle.is_some(),
            squareoff_running: self.squareoff_scheduler.is_some(),
        })
    }

    /// Get sandbox status
    pub async fn get_status(&self) -> Result<SandboxStatus, SandboxError> {
        let analyze_mode = self.get_analyze_mode().await?;
        let stats = self.get_statistics().await?;

        Ok(SandboxStatus {
            mode: if analyze_mode { "analyze" } else { "live" },
            statistics: stats,
            execution_running: self.execution_handle.is_some(),
            squareoff_running: self.squareoff_scheduler.is_some(),
        })
    }
}
```

### 2. Order Manager

```rust
pub struct SandboxOrderManager {
    db: SqlitePool,
    fund_manager: Arc<SandboxFundManager>,
}

impl SandboxOrderManager {
    /// Place a sandbox order
    pub async fn place_order(
        &self,
        order_data: PlaceOrderRequest,
        user_id: &str,
    ) -> Result<SandboxOrderResponse, SandboxError> {
        // 1. Validate order data
        self.validate_order(&order_data)?;

        // 2. Get current LTP
        let ltp = self.get_ltp(&order_data.symbol, &order_data.exchange).await?;

        // 3. Calculate margin required
        let margin = self.calculate_margin(&order_data, ltp).await?;

        // 4. Check available funds
        let funds = self.fund_manager.get_funds(user_id).await?;
        if funds.available_balance < margin {
            return Err(SandboxError::InsufficientFunds {
                required: margin,
                available: funds.available_balance,
            });
        }

        // 5. Block margin
        self.fund_manager.block_margin(user_id, margin).await?;

        // 6. Generate order ID
        let orderid = format!("SB-{}", chrono::Utc::now().timestamp_millis());

        // 7. Create order record
        let order = SandboxOrder {
            orderid: orderid.clone(),
            user_id: user_id.to_string(),
            symbol: order_data.symbol.clone(),
            exchange: order_data.exchange.to_string(),
            action: order_data.action.to_string(),
            quantity: order_data.quantity as i32,
            price: Some(order_data.price),
            trigger_price: Some(order_data.trigger_price),
            price_type: order_data.pricetype.to_string(),
            product: order_data.product.to_string(),
            order_status: if order_data.pricetype == PriceType::Market {
                "complete".to_string()
            } else {
                "open".to_string()
            },
            margin_blocked: margin,
            filled_quantity: 0,
            pending_quantity: order_data.quantity as i32,
            order_timestamp: Utc::now(),
            update_timestamp: Utc::now(),
            ..Default::default()
        };

        self.insert_order(&order).await?;

        // 8. Execute if MARKET order
        if order_data.pricetype == PriceType::Market {
            self.execute_order(&orderid, ltp, user_id).await?;
        }

        Ok(SandboxOrderResponse {
            status: "success".to_string(),
            orderid,
            mode: "analyze".to_string(),
        })
    }

    /// Calculate margin for order
    async fn calculate_margin(
        &self,
        order: &PlaceOrderRequest,
        ltp: f64,
    ) -> Result<f64, SandboxError> {
        let config = self.get_config().await?;

        // Determine price for margin calculation
        let margin_price = match order.pricetype {
            PriceType::Market => ltp,
            PriceType::Limit => order.price,
            PriceType::Sl | PriceType::SlM => order.trigger_price,
        };

        // Determine leverage based on exchange and product
        let leverage = self.get_leverage(&order.exchange, &order.product, &order.symbol)?;

        // Calculate trade value
        let lot_size = self.get_lot_size(&order.symbol, &order.exchange).await?;
        let trade_value = margin_price * (order.quantity as f64) * (lot_size as f64);

        // Calculate margin
        let margin = trade_value / leverage;

        Ok(margin)
    }

    /// Get leverage based on instrument type
    fn get_leverage(
        &self,
        exchange: &Exchange,
        product: &Product,
        symbol: &str,
    ) -> Result<f64, SandboxError> {
        match exchange {
            Exchange::Nse | Exchange::Bse => {
                match product {
                    Product::Mis => Ok(5.0),    // equity_mis_leverage
                    Product::Cnc => Ok(1.0),    // equity_cnc_leverage
                    Product::Nrml => Ok(1.0),
                }
            }
            Exchange::Nfo | Exchange::Bfo | Exchange::Cds | Exchange::Bcd | Exchange::Mcx | Exchange::Ncdex => {
                // Check if option
                if symbol.ends_with("CE") || symbol.ends_with("PE") {
                    // Option - determine if BUY or SELL
                    // BUY: full premium (leverage = 1)
                    // SELL: futures margin (leverage = 10)
                    Ok(1.0) // Default to buy, actual check done in calling function
                } else {
                    // Futures
                    Ok(10.0) // futures_leverage
                }
            }
            _ => Ok(1.0),
        }
    }
}
```

### 3. Execution Engine

```rust
pub struct ExecutionEngine {
    db: SqlitePool,
    order_manager: Arc<SandboxOrderManager>,
    fund_manager: Arc<SandboxFundManager>,
    position_manager: Arc<SandboxPositionManager>,
    running: AtomicBool,
}

impl ExecutionEngine {
    /// Start execution thread
    pub fn start(&self) -> JoinHandle<()> {
        let engine = self.clone();
        tokio::spawn(async move {
            engine.running.store(true, Ordering::SeqCst);

            while engine.running.load(Ordering::SeqCst) {
                if let Err(e) = engine.check_pending_orders().await {
                    tracing::error!("Execution engine error: {}", e);
                }

                tokio::time::sleep(Duration::from_secs(5)).await;
            }
        })
    }

    /// Check and execute pending orders
    async fn check_pending_orders(&self) -> Result<(), SandboxError> {
        // Get all pending orders
        let pending_orders = self.get_pending_orders().await?;

        // Group by symbol for batch quote fetching
        let mut symbol_map: HashMap<(String, String), Vec<SandboxOrder>> = HashMap::new();
        for order in pending_orders {
            let key = (order.symbol.clone(), order.exchange.clone());
            symbol_map.entry(key).or_default().push(order);
        }

        // Fetch quotes and check execution conditions
        for ((symbol, exchange), orders) in symbol_map {
            let ltp = match self.get_ltp(&symbol, &exchange).await {
                Ok(ltp) => ltp,
                Err(_) => continue,
            };

            for order in orders {
                if self.should_execute(&order, ltp) {
                    self.execute_order(&order.orderid, ltp, &order.user_id).await?;
                }
            }
        }

        Ok(())
    }

    /// Check if order should execute at current LTP
    fn should_execute(&self, order: &SandboxOrder, ltp: f64) -> bool {
        let price = order.price.unwrap_or(0.0);
        let trigger = order.trigger_price.unwrap_or(0.0);

        match (order.price_type.as_str(), order.action.as_str()) {
            // LIMIT orders
            ("LIMIT", "BUY") => ltp <= price,
            ("LIMIT", "SELL") => ltp >= price,

            // SL orders
            ("SL", "BUY") => ltp >= trigger,
            ("SL", "SELL") => ltp <= trigger,

            // SL-M orders
            ("SL-M", "BUY") => ltp >= trigger,
            ("SL-M", "SELL") => ltp <= trigger,

            // MARKET orders should already be executed
            ("MARKET", _) => true,

            _ => false,
        }
    }

    /// Execute order at given price
    async fn execute_order(
        &self,
        orderid: &str,
        execution_price: f64,
        user_id: &str,
    ) -> Result<(), SandboxError> {
        // 1. Get order
        let order = self.get_order(orderid).await?;

        // 2. Create trade record
        let tradeid = format!("ST-{}", chrono::Utc::now().timestamp_millis());
        let trade = SandboxTrade {
            tradeid: tradeid.clone(),
            orderid: orderid.to_string(),
            user_id: user_id.to_string(),
            symbol: order.symbol.clone(),
            exchange: order.exchange.clone(),
            action: order.action.clone(),
            quantity: order.quantity,
            price: execution_price,
            product: order.product.clone(),
            strategy: order.strategy.clone(),
            trade_timestamp: Utc::now(),
            ..Default::default()
        };
        self.insert_trade(&trade).await?;

        // 3. Update order status
        self.update_order_status(orderid, "complete", execution_price, order.quantity).await?;

        // 4. Update position
        self.position_manager.update_position(&trade).await?;

        // 5. Adjust margin
        self.fund_manager.release_margin(user_id, order.margin_blocked).await?;

        // 6. Emit event
        self.emit_order_event(&order, execution_price).await;

        Ok(())
    }
}
```

### 4. Square-off Scheduler

```rust
pub struct SquareoffScheduler {
    scheduler: JobScheduler,
    db: SqlitePool,
    order_manager: Arc<SandboxOrderManager>,
    position_manager: Arc<SandboxPositionManager>,
}

impl SquareoffScheduler {
    /// Start scheduler with exchange-specific times
    pub async fn start(&mut self) -> Result<(), SandboxError> {
        // NSE/BSE at 15:15 IST
        self.add_job("nse_bse", "15 15 * * 1-5", vec!["NSE", "BSE", "NFO", "BFO"]).await?;

        // CDS/BCD at 16:45 IST
        self.add_job("cds_bcd", "45 16 * * 1-5", vec!["CDS", "BCD"]).await?;

        // MCX at 23:30 IST
        self.add_job("mcx", "30 23 * * 1-5", vec!["MCX"]).await?;

        // NCDEX at 17:00 IST
        self.add_job("ncdex", "0 17 * * 1-5", vec!["NCDEX"]).await?;

        self.scheduler.start().await?;
        Ok(())
    }

    /// Execute square-off for exchange group
    async fn squareoff_exchanges(&self, exchanges: &[&str]) -> Result<(), SandboxError> {
        // 1. Cancel all pending MIS orders
        let pending_orders = self.get_pending_mis_orders(exchanges).await?;
        for order in pending_orders {
            self.order_manager.cancel_order(&order.orderid, &order.user_id).await?;
        }

        // 2. Close all MIS positions
        let positions = self.get_mis_positions(exchanges).await?;
        for position in positions {
            if position.quantity != 0 {
                self.close_position(&position).await?;
            }
        }

        Ok(())
    }

    /// Close a single position
    async fn close_position(&self, position: &SandboxPosition) -> Result<(), SandboxError> {
        let ltp = self.get_ltp(&position.symbol, &position.exchange).await?;

        // Create reverse order
        let action = if position.quantity > 0 { "SELL" } else { "BUY" };
        let quantity = position.quantity.abs();

        let order = PlaceOrderRequest {
            symbol: position.symbol.clone(),
            exchange: position.exchange.parse()?,
            action: action.parse()?,
            quantity: quantity as u32,
            pricetype: PriceType::Market,
            product: position.product.parse()?,
            ..Default::default()
        };

        self.order_manager.place_order(order, &position.user_id).await?;

        Ok(())
    }

    /// Reload schedule from config
    pub async fn reload(&mut self) -> Result<(), SandboxError> {
        self.scheduler.shutdown().await?;
        self.start().await
    }
}
```

### 5. Fund Manager

```rust
pub struct SandboxFundManager {
    db: SqlitePool,
}

impl SandboxFundManager {
    /// Get or create funds for user
    pub async fn get_funds(&self, user_id: &str) -> Result<SandboxFunds, SandboxError> {
        match self.fetch_funds(user_id).await? {
            Some(funds) => Ok(funds),
            None => self.create_funds(user_id).await,
        }
    }

    /// Create initial funds for user
    async fn create_funds(&self, user_id: &str) -> Result<SandboxFunds, SandboxError> {
        let starting_capital = self.get_config_value("starting_capital")
            .await?
            .parse::<f64>()
            .unwrap_or(10_000_000.0);

        let funds = SandboxFunds {
            user_id: user_id.to_string(),
            total_capital: starting_capital,
            available_balance: starting_capital,
            used_margin: 0.0,
            realized_pnl: 0.0,
            unrealized_pnl: 0.0,
            total_pnl: 0.0,
            last_reset_date: Utc::now(),
            reset_count: 0,
            created_at: Utc::now(),
            updated_at: Utc::now(),
            ..Default::default()
        };

        self.insert_funds(&funds).await?;
        Ok(funds)
    }

    /// Block margin for order
    pub async fn block_margin(&self, user_id: &str, amount: f64) -> Result<(), SandboxError> {
        sqlx::query!(
            r#"
            UPDATE sandbox_funds
            SET used_margin = used_margin + $1,
                available_balance = available_balance - $1,
                updated_at = $2
            WHERE user_id = $3
            "#,
            amount,
            Utc::now(),
            user_id
        )
        .execute(&self.db)
        .await?;

        Ok(())
    }

    /// Release margin after order execution
    pub async fn release_margin(&self, user_id: &str, amount: f64) -> Result<(), SandboxError> {
        sqlx::query!(
            r#"
            UPDATE sandbox_funds
            SET used_margin = used_margin - $1,
                available_balance = available_balance + $1,
                updated_at = $2
            WHERE user_id = $3
            "#,
            amount,
            Utc::now(),
            user_id
        )
        .execute(&self.db)
        .await?;

        Ok(())
    }

    /// Update realized P&L after closing position
    pub async fn update_realized_pnl(
        &self,
        user_id: &str,
        pnl: f64,
    ) -> Result<(), SandboxError> {
        sqlx::query!(
            r#"
            UPDATE sandbox_funds
            SET realized_pnl = realized_pnl + $1,
                available_balance = available_balance + $1,
                total_pnl = realized_pnl + unrealized_pnl,
                updated_at = $2
            WHERE user_id = $3
            "#,
            pnl,
            Utc::now(),
            user_id
        )
        .execute(&self.db)
        .await?;

        Ok(())
    }

    /// Reset funds to initial state
    pub async fn reset_funds(&self, user_id: &str) -> Result<(), SandboxError> {
        let starting_capital = self.get_config_value("starting_capital")
            .await?
            .parse::<f64>()
            .unwrap_or(10_000_000.0);

        sqlx::query!(
            r#"
            UPDATE sandbox_funds
            SET total_capital = $1,
                available_balance = $1,
                used_margin = 0.0,
                realized_pnl = 0.0,
                unrealized_pnl = 0.0,
                total_pnl = 0.0,
                reset_count = reset_count + 1,
                last_reset_date = $2,
                updated_at = $2
            WHERE user_id = $3
            "#,
            starting_capital,
            Utc::now(),
            user_id
        )
        .execute(&self.db)
        .await?;

        Ok(())
    }
}
```

### 6. Position Manager

```rust
pub struct SandboxPositionManager {
    db: SqlitePool,
    fund_manager: Arc<SandboxFundManager>,
}

impl SandboxPositionManager {
    /// Update position after trade execution
    pub async fn update_position(&self, trade: &SandboxTrade) -> Result<(), SandboxError> {
        // Find existing position
        let existing = self.find_position(
            &trade.user_id,
            &trade.symbol,
            &trade.exchange,
            &trade.product,
        ).await?;

        match existing {
            Some(pos) => self.update_existing_position(&pos, trade).await,
            None => self.create_new_position(trade).await,
        }
    }

    /// Update existing position
    async fn update_existing_position(
        &self,
        position: &SandboxPosition,
        trade: &SandboxTrade,
    ) -> Result<(), SandboxError> {
        let old_qty = position.quantity;
        let old_avg = position.average_price;

        // Calculate new quantity
        let trade_qty = if trade.action == "BUY" {
            trade.quantity
        } else {
            -trade.quantity
        };
        let new_qty = old_qty + trade_qty;

        // Calculate new average price
        let new_avg = if new_qty == 0 {
            0.0
        } else if (old_qty > 0 && trade_qty > 0) || (old_qty < 0 && trade_qty < 0) {
            // Adding to position - weighted average
            let old_value = (old_qty as f64).abs() * old_avg;
            let trade_value = (trade_qty as f64).abs() * trade.price;
            (old_value + trade_value) / (new_qty as f64).abs()
        } else {
            // Reducing position - keep old average
            old_avg
        };

        // Calculate realized P&L if position reduced/closed
        let realized_pnl = if (old_qty > 0 && trade_qty < 0) || (old_qty < 0 && trade_qty > 0) {
            let closed_qty = trade_qty.abs().min(old_qty.abs());
            if old_qty > 0 {
                // Long position being closed
                (trade.price - old_avg) * (closed_qty as f64)
            } else {
                // Short position being closed
                (old_avg - trade.price) * (closed_qty as f64)
            }
        } else {
            0.0
        };

        // Update position in database
        sqlx::query!(
            r#"
            UPDATE sandbox_positions
            SET quantity = $1, average_price = $2, updated_at = $3
            WHERE id = $4
            "#,
            new_qty,
            new_avg,
            Utc::now(),
            position.id
        )
        .execute(&self.db)
        .await?;

        // Update realized P&L
        if realized_pnl != 0.0 {
            self.fund_manager.update_realized_pnl(&trade.user_id, realized_pnl).await?;
        }

        Ok(())
    }

    /// Create new position
    async fn create_new_position(&self, trade: &SandboxTrade) -> Result<(), SandboxError> {
        let quantity = if trade.action == "BUY" {
            trade.quantity
        } else {
            -trade.quantity
        };

        let position = SandboxPosition {
            user_id: trade.user_id.clone(),
            symbol: trade.symbol.clone(),
            exchange: trade.exchange.clone(),
            product: trade.product.clone(),
            quantity,
            average_price: trade.price,
            ltp: Some(trade.price),
            pnl: 0.0,
            pnl_percent: 0.0,
            created_at: Utc::now(),
            updated_at: Utc::now(),
            ..Default::default()
        };

        self.insert_position(&position).await
    }

    /// Update MTM (Mark-to-Market) for all positions
    pub async fn update_mtm(&self, user_id: &str) -> Result<(), SandboxError> {
        let positions = self.get_all_positions(user_id).await?;

        let mut total_unrealized = 0.0;

        for position in positions {
            if position.quantity == 0 {
                continue;
            }

            let ltp = self.get_ltp(&position.symbol, &position.exchange).await?;

            let pnl = if position.quantity > 0 {
                (ltp - position.average_price) * (position.quantity as f64)
            } else {
                (position.average_price - ltp) * (position.quantity.abs() as f64)
            };

            let investment = position.average_price * (position.quantity.abs() as f64);
            let pnl_percent = if investment > 0.0 { pnl / investment * 100.0 } else { 0.0 };

            sqlx::query!(
                r#"
                UPDATE sandbox_positions
                SET ltp = $1, pnl = $2, pnl_percent = $3, updated_at = $4
                WHERE id = $5
                "#,
                ltp,
                pnl,
                pnl_percent,
                Utc::now(),
                position.id
            )
            .execute(&self.db)
            .await?;

            total_unrealized += pnl;
        }

        // Update unrealized P&L in funds
        sqlx::query!(
            r#"
            UPDATE sandbox_funds
            SET unrealized_pnl = $1,
                total_pnl = realized_pnl + $1,
                updated_at = $2
            WHERE user_id = $3
            "#,
            total_unrealized,
            Utc::now(),
            user_id
        )
        .execute(&self.db)
        .await?;

        Ok(())
    }
}
```

---

## API Response Format (Sandbox Mode)

When in sandbox mode, API responses include `mode: "analyze"`:

```json
{
    "status": "success",
    "orderid": "SB-1701676800123",
    "mode": "analyze"
}
```

Error responses:
```json
{
    "status": "error",
    "message": "Insufficient funds. Required: 50000.00, Available: 25000.00",
    "mode": "analyze"
}
```

---

## Tauri Commands

```rust
#[tauri::command]
pub async fn sandbox_toggle(
    state: State<'_, AppState>,
    mode: bool,
) -> Result<SandboxStatus, String> {
    let mut sandbox = state.sandbox.lock().await;
    sandbox.toggle_mode(mode).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn sandbox_status(
    state: State<'_, AppState>,
) -> Result<SandboxStatus, String> {
    let sandbox = state.sandbox.lock().await;
    sandbox.get_status().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn sandbox_reset_funds(
    state: State<'_, AppState>,
    user_id: String,
) -> Result<SandboxFunds, String> {
    let sandbox = state.sandbox.lock().await;
    sandbox.fund_manager.reset_funds(&user_id).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn sandbox_update_config(
    state: State<'_, AppState>,
    key: String,
    value: String,
) -> Result<(), String> {
    let sandbox = state.sandbox.lock().await;
    sandbox.update_config(&key, &value).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn sandbox_reload_squareoff(
    state: State<'_, AppState>,
) -> Result<(), String> {
    let mut sandbox = state.sandbox.lock().await;
    sandbox.squareoff_scheduler.as_mut()
        .ok_or("Scheduler not running")?
        .reload().await
        .map_err(|e| e.to_string())
}
```

---

## Conclusion

The Sandbox Mode provides:

1. **Risk-Free Testing** - Test strategies with virtual Rs 1 Crore capital
2. **Real Market Data** - Uses live LTP from broker feeds
3. **Realistic Execution** - Orders execute at actual market prices
4. **Complete Isolation** - Separate database from live trading
5. **Auto Square-Off** - Exchange-specific MIS position closure
6. **Configurable Parameters** - Leverage, timing, capital settings
