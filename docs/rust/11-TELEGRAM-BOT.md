# OpenAlgo Desktop - Telegram Bot Integration

## Overview

The Telegram Bot provides mobile trading capabilities and real-time alerts. Users can manage positions, view account information, and receive order notifications directly through Telegram.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Telegram Bot Architecture                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐                            ┌────────────────────────┐ │
│  │   Telegram API   │◄──────────────────────────►│     User's Phone       │ │
│  │  (api.telegram)  │                            │   (Telegram App)       │ │
│  └────────┬─────────┘                            └────────────────────────┘ │
│           │                                                                  │
│           │ Long Polling                                                     │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                     OpenAlgo Desktop (Tauri)                            ││
│  │                                                                          ││
│  │  ┌────────────────┐  ┌────────────────┐  ┌───────────────────────────┐ ││
│  │  │ Telegram Bot   │  │ Alert Service  │  │ Command Handler           │ ││
│  │  │ Client         │  │                │  │                           │ ││
│  │  │ (teloxide)     │  │ - Order alerts │  │ - /start, /help           │ ││
│  │  │                │  │ - P&L updates  │  │ - /positions, /orders     │ ││
│  │  │                │  │ - Error notifs │  │ - /funds, /holdings       │ ││
│  │  └────────┬───────┘  └────────┬───────┘  │ - /close, /cancel         │ ││
│  │           │                   │          └───────────────────────────┘ ││
│  │           └───────────────────┼───────────────────────────────────────┘ ││
│  │                               │                                          ││
│  │                               ▼                                          ││
│  │  ┌─────────────────────────────────────────────────────────────────────┐││
│  │  │                     Broker Services                                  │││
│  │  │  (Positions, Orders, Holdings, Funds)                               │││
│  │  └─────────────────────────────────────────────────────────────────────┘││
│  │                                                                          ││
│  └──────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Configuration

### Database Schema

```rust
#[derive(sqlx::FromRow, Serialize, Deserialize)]
pub struct TelegramConfig {
    pub id: i64,
    pub user_id: String,
    pub bot_token: String,
    pub chat_id: String,
    pub enabled: bool,
    pub alert_on_order: bool,
    pub alert_on_trade: bool,
    pub alert_on_error: bool,
    pub alert_on_pnl: bool,
    pub pnl_threshold: f64,         // Alert if P&L exceeds this
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}
```

### Environment Variables

```rust
pub struct TelegramEnv {
    pub bot_token: Option<String>,  // TELEGRAM_BOT_TOKEN
    pub chat_id: Option<String>,    // TELEGRAM_CHAT_ID
}
```

---

## Bot Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/start` | Initialize bot and show menu | `/start` |
| `/help` | Show available commands | `/help` |
| `/positions` | View open positions | `/positions` |
| `/orders` | View pending orders | `/orders` |
| `/holdings` | View holdings (CNC) | `/holdings` |
| `/funds` | View available funds | `/funds` |
| `/pnl` | View today's P&L | `/pnl` |
| `/close <symbol>` | Close specific position | `/close RELIANCE` |
| `/closeall` | Close all positions | `/closeall` |
| `/cancel <orderid>` | Cancel specific order | `/cancel 123456` |
| `/cancelall` | Cancel all orders | `/cancelall` |
| `/mode` | Check trading mode | `/mode` |
| `/status` | System status | `/status` |

---

## Implementation

### 1. Bot Client (teloxide)

```rust
use teloxide::{prelude::*, utils::command::BotCommands};

#[derive(BotCommands, Clone)]
#[command(rename_rule = "lowercase", description = "OpenAlgo Trading Bot")]
pub enum Command {
    #[command(description = "Start the bot")]
    Start,

    #[command(description = "Show help")]
    Help,

    #[command(description = "View open positions")]
    Positions,

    #[command(description = "View pending orders")]
    Orders,

    #[command(description = "View holdings")]
    Holdings,

    #[command(description = "View available funds")]
    Funds,

    #[command(description = "View today's P&L")]
    Pnl,

    #[command(description = "Close a position")]
    Close(String),

    #[command(description = "Close all positions")]
    CloseAll,

    #[command(description = "Cancel an order")]
    Cancel(String),

    #[command(description = "Cancel all orders")]
    CancelAll,

    #[command(description = "Check trading mode")]
    Mode,

    #[command(description = "System status")]
    Status,
}

pub struct TelegramBot {
    bot: Bot,
    db: SqlitePool,
    broker_services: Arc<BrokerServices>,
}

impl TelegramBot {
    pub fn new(token: &str, db: SqlitePool, broker_services: Arc<BrokerServices>) -> Self {
        Self {
            bot: Bot::new(token),
            db,
            broker_services,
        }
    }

    pub async fn start(&self) -> Result<(), TelegramError> {
        let handler = Update::filter_message()
            .branch(
                dptree::entry()
                    .filter_command::<Command>()
                    .endpoint(self.handle_command()),
            );

        Dispatcher::builder(self.bot.clone(), handler)
            .enable_ctrlc_handler()
            .build()
            .dispatch()
            .await;

        Ok(())
    }

    async fn handle_command(
        &self,
        bot: Bot,
        msg: Message,
        cmd: Command,
    ) -> ResponseResult<()> {
        // Verify chat ID
        if !self.is_authorized_chat(&msg.chat.id).await {
            bot.send_message(msg.chat.id, "Unauthorized chat. Please configure your chat ID.")
                .await?;
            return Ok(());
        }

        let response = match cmd {
            Command::Start => self.handle_start().await,
            Command::Help => self.handle_help().await,
            Command::Positions => self.handle_positions().await,
            Command::Orders => self.handle_orders().await,
            Command::Holdings => self.handle_holdings().await,
            Command::Funds => self.handle_funds().await,
            Command::Pnl => self.handle_pnl().await,
            Command::Close(symbol) => self.handle_close(&symbol).await,
            Command::CloseAll => self.handle_close_all().await,
            Command::Cancel(order_id) => self.handle_cancel(&order_id).await,
            Command::CancelAll => self.handle_cancel_all().await,
            Command::Mode => self.handle_mode().await,
            Command::Status => self.handle_status().await,
        };

        match response {
            Ok(text) => {
                bot.send_message(msg.chat.id, text)
                    .parse_mode(ParseMode::Html)
                    .await?;
            }
            Err(e) => {
                bot.send_message(msg.chat.id, format!("Error: {}", e))
                    .await?;
            }
        }

        Ok(())
    }
}
```

### 2. Command Handlers

```rust
impl TelegramBot {
    async fn handle_start(&self) -> Result<String, TelegramError> {
        Ok(format!(
            r#"<b>Welcome to OpenAlgo Trading Bot!</b>

Your trading companion for real-time alerts and position management.

<b>Quick Commands:</b>
/positions - View open positions
/orders - View pending orders
/funds - Check available funds
/pnl - Today's P&L

<b>Trading Commands:</b>
/close SYMBOL - Close position
/closeall - Close all positions
/cancel ORDERID - Cancel order
/cancelall - Cancel all orders

Type /help for full command list."#
        ))
    }

    async fn handle_positions(&self) -> Result<String, TelegramError> {
        let positions = self.broker_services.get_positions().await?;

        if positions.is_empty() {
            return Ok("No open positions.".to_string());
        }

        let mut response = String::from("<b>Open Positions</b>\n\n");

        for pos in positions {
            let pnl_emoji = if pos.pnl >= 0.0 { "+" } else { "" };
            response.push_str(&format!(
                "<b>{}</b> ({})\n{} {} @ {:.2}\nP&L: {}{:.2} ({:.2}%)\n\n",
                pos.symbol,
                pos.exchange,
                pos.quantity,
                if pos.quantity > 0 { "LONG" } else { "SHORT" },
                pos.average_price,
                pnl_emoji,
                pos.pnl,
                pos.pnl_percent
            ));
        }

        Ok(response)
    }

    async fn handle_orders(&self) -> Result<String, TelegramError> {
        let orders = self.broker_services.get_orderbook().await?;

        let pending: Vec<_> = orders.iter()
            .filter(|o| o.status == "open" || o.status == "pending")
            .collect();

        if pending.is_empty() {
            return Ok("No pending orders.".to_string());
        }

        let mut response = String::from("<b>Pending Orders</b>\n\n");

        for order in pending {
            response.push_str(&format!(
                "<b>{}</b> ({})\n{} {} @ {} ({})\nID: {}\n\n",
                order.symbol,
                order.exchange,
                order.action,
                order.quantity,
                order.price,
                order.pricetype,
                order.orderid
            ));
        }

        Ok(response)
    }

    async fn handle_funds(&self) -> Result<String, TelegramError> {
        let funds = self.broker_services.get_funds().await?;

        Ok(format!(
            r#"<b>Account Funds</b>

Available: Rs. {:.2}
Used Margin: Rs. {:.2}
Total: Rs. {:.2}

<b>P&L</b>
Realized: Rs. {:.2}
Unrealized: Rs. {:.2}"#,
            funds.available_balance,
            funds.used_margin,
            funds.total_balance,
            funds.realized_pnl,
            funds.unrealized_pnl
        ))
    }

    async fn handle_pnl(&self) -> Result<String, TelegramError> {
        let positions = self.broker_services.get_positions().await?;

        let total_pnl: f64 = positions.iter().map(|p| p.pnl).sum();
        let pnl_emoji = if total_pnl >= 0.0 { "" } else { "" };

        let mut response = format!(
            "<b>Today's P&L</b> {}\n\n<b>Total: Rs. {:.2}</b>\n\n",
            pnl_emoji,
            total_pnl
        );

        // Top gainers/losers
        let mut sorted = positions.clone();
        sorted.sort_by(|a, b| b.pnl.partial_cmp(&a.pnl).unwrap());

        if !sorted.is_empty() {
            response.push_str("<b>Top Performers:</b>\n");
            for pos in sorted.iter().take(3) {
                let emoji = if pos.pnl >= 0.0 { "" } else { "" };
                response.push_str(&format!(
                    "{} {}: Rs. {:.2}\n",
                    emoji,
                    pos.symbol,
                    pos.pnl
                ));
            }
        }

        Ok(response)
    }

    async fn handle_close(&self, symbol: &str) -> Result<String, TelegramError> {
        // Find position
        let positions = self.broker_services.get_positions().await?;
        let position = positions.iter()
            .find(|p| p.symbol.to_uppercase() == symbol.to_uppercase())
            .ok_or(TelegramError::PositionNotFound(symbol.to_string()))?;

        // Close position
        let result = self.broker_services.close_position(&position.symbol, &position.exchange, &position.product).await?;

        Ok(format!(
            "Position closed!\n\nSymbol: {}\nOrder ID: {}",
            symbol,
            result.order_id
        ))
    }

    async fn handle_close_all(&self) -> Result<String, TelegramError> {
        let result = self.broker_services.close_all_positions().await?;

        Ok(format!(
            "All positions closed!\n\nClosed: {}\nFailed: {}",
            result.success_count,
            result.failed_count
        ))
    }

    async fn handle_cancel(&self, order_id: &str) -> Result<String, TelegramError> {
        let result = self.broker_services.cancel_order(order_id).await?;

        Ok(format!(
            "Order cancelled!\n\nOrder ID: {}",
            order_id
        ))
    }

    async fn handle_cancel_all(&self) -> Result<String, TelegramError> {
        let result = self.broker_services.cancel_all_orders().await?;

        Ok(format!(
            "All orders cancelled!\n\nCancelled: {}\nFailed: {}",
            result.success_count,
            result.failed_count
        ))
    }

    async fn handle_mode(&self) -> Result<String, TelegramError> {
        let analyze_mode = get_analyze_mode().await?;
        let order_mode = get_order_mode_for_user().await?;

        let trading_mode = if analyze_mode { "SANDBOX" } else { "LIVE" };
        let order_mode_str = if order_mode == OrderMode::SemiAuto { "SEMI-AUTO" } else { "AUTO" };

        Ok(format!(
            r#"<b>Trading Mode</b>

Trading: <b>{}</b>
Order Mode: <b>{}</b>

{}"#,
            trading_mode,
            order_mode_str,
            if analyze_mode {
                "Orders execute in sandbox environment (paper trading)."
            } else {
                "Orders execute with real broker."
            }
        ))
    }

    async fn handle_status(&self) -> Result<String, TelegramError> {
        let broker = get_current_broker().await?;
        let connected = self.broker_services.is_connected().await;

        Ok(format!(
            r#"<b>System Status</b>

Broker: <b>{}</b>
Connection: <b>{}</b>
WebSocket: <b>{}</b>

Version: {}"#,
            broker,
            if connected { "Connected" } else { "Disconnected" },
            if self.ws_connected() { "Active" } else { "Inactive" },
            env!("CARGO_PKG_VERSION")
        ))
    }
}
```

### 3. Alert Service

```rust
pub struct TelegramAlertService {
    bot: Bot,
    config: TelegramConfig,
}

impl TelegramAlertService {
    /// Send order execution alert
    pub async fn send_order_alert(
        &self,
        api_type: &str,
        order_data: &OrderData,
        response: &OrderResponse,
    ) -> Result<(), AlertError> {
        if !self.config.enabled || !self.config.alert_on_order {
            return Ok(());
        }

        let emoji = match order_data.action.as_str() {
            "BUY" => "",
            "SELL" => "",
            _ => "",
        };

        let message = format!(
            r#"{} <b>Order Executed</b>

<b>{}</b> ({})
{} {} @ {}
Type: {}
Order ID: {}"#,
            emoji,
            order_data.symbol,
            order_data.exchange,
            order_data.action,
            order_data.quantity,
            order_data.price.unwrap_or(0.0),
            order_data.pricetype,
            response.order_id
        );

        self.send_message(&message).await
    }

    /// Send trade execution alert
    pub async fn send_trade_alert(&self, trade: &TradeData) -> Result<(), AlertError> {
        if !self.config.enabled || !self.config.alert_on_trade {
            return Ok(());
        }

        let message = format!(
            r#"<b>Trade Executed</b>

<b>{}</b> ({})
{} {} @ {:.2}
Trade ID: {}"#,
            trade.symbol,
            trade.exchange,
            trade.action,
            trade.quantity,
            trade.price,
            trade.trade_id
        );

        self.send_message(&message).await
    }

    /// Send error alert
    pub async fn send_error_alert(
        &self,
        operation: &str,
        error: &str,
    ) -> Result<(), AlertError> {
        if !self.config.enabled || !self.config.alert_on_error {
            return Ok(());
        }

        let message = format!(
            r#"<b>Error Alert</b>

Operation: {}
Error: {}

Please check your OpenAlgo dashboard."#,
            operation,
            error
        );

        self.send_message(&message).await
    }

    /// Send P&L threshold alert
    pub async fn send_pnl_alert(&self, pnl: f64, threshold: f64) -> Result<(), AlertError> {
        if !self.config.enabled || !self.config.alert_on_pnl {
            return Ok(());
        }

        let emoji = if pnl >= 0.0 { "" } else { "" };
        let direction = if pnl >= 0.0 { "profit" } else { "loss" };

        let message = format!(
            r#"{} <b>P&L Alert</b>

Your {} has exceeded the threshold!

Current P&L: Rs. {:.2}
Threshold: Rs. {:.2}

Consider reviewing your positions."#,
            emoji,
            direction,
            pnl,
            threshold
        );

        self.send_message(&message).await
    }

    /// Send message to configured chat
    async fn send_message(&self, message: &str) -> Result<(), AlertError> {
        self.bot.send_message(ChatId(self.config.chat_id.parse()?), message)
            .parse_mode(ParseMode::Html)
            .await?;

        Ok(())
    }
}
```

### 4. Bot Manager

```rust
pub struct TelegramBotManager {
    db: SqlitePool,
    bot: Option<TelegramBot>,
    alert_service: Option<Arc<TelegramAlertService>>,
    running: AtomicBool,
}

impl TelegramBotManager {
    /// Start the bot with configuration from database
    pub async fn start(&mut self) -> Result<(), TelegramError> {
        let config = self.get_config().await?;

        if !config.enabled {
            tracing::info!("Telegram bot is disabled");
            return Ok(());
        }

        // Create bot
        let bot = TelegramBot::new(
            &config.bot_token,
            self.db.clone(),
            self.broker_services.clone(),
        );

        // Create alert service
        let alert_service = TelegramAlertService {
            bot: bot.bot.clone(),
            config: config.clone(),
        };

        self.bot = Some(bot);
        self.alert_service = Some(Arc::new(alert_service));
        self.running.store(true, Ordering::SeqCst);

        // Start polling in background
        let bot = self.bot.as_ref().unwrap().clone();
        tokio::spawn(async move {
            if let Err(e) = bot.start().await {
                tracing::error!("Telegram bot error: {}", e);
            }
        });

        tracing::info!("Telegram bot started");
        Ok(())
    }

    /// Stop the bot
    pub async fn stop(&mut self) -> Result<(), TelegramError> {
        self.running.store(false, Ordering::SeqCst);
        self.bot = None;
        self.alert_service = None;

        tracing::info!("Telegram bot stopped");
        Ok(())
    }

    /// Get alert service for sending notifications
    pub fn get_alert_service(&self) -> Option<Arc<TelegramAlertService>> {
        self.alert_service.clone()
    }

    /// Reload configuration
    pub async fn reload(&mut self) -> Result<(), TelegramError> {
        self.stop().await?;
        self.start().await
    }
}
```

---

## Tauri Commands

```rust
#[tauri::command]
pub async fn telegram_configure(
    state: State<'_, AppState>,
    bot_token: String,
    chat_id: String,
) -> Result<(), String> {
    let mut telegram = state.telegram.lock().await;

    telegram.save_config(&bot_token, &chat_id).await
        .map_err(|e| e.to_string())?;

    telegram.reload().await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn telegram_enable(
    state: State<'_, AppState>,
    enabled: bool,
) -> Result<(), String> {
    let mut telegram = state.telegram.lock().await;

    if enabled {
        telegram.start().await.map_err(|e| e.to_string())
    } else {
        telegram.stop().await.map_err(|e| e.to_string())
    }
}

#[tauri::command]
pub async fn telegram_test(
    state: State<'_, AppState>,
) -> Result<(), String> {
    let telegram = state.telegram.lock().await;

    if let Some(alert_service) = telegram.get_alert_service() {
        alert_service.send_message("Test message from OpenAlgo Desktop!")
            .await
            .map_err(|e| e.to_string())
    } else {
        Err("Telegram bot not configured".to_string())
    }
}

#[tauri::command]
pub async fn telegram_get_config(
    state: State<'_, AppState>,
) -> Result<TelegramConfigView, String> {
    let telegram = state.telegram.lock().await;
    telegram.get_config().await
        .map(TelegramConfigView::from)
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn telegram_update_alerts(
    state: State<'_, AppState>,
    alert_on_order: bool,
    alert_on_trade: bool,
    alert_on_error: bool,
    alert_on_pnl: bool,
    pnl_threshold: f64,
) -> Result<(), String> {
    let mut telegram = state.telegram.lock().await;

    telegram.update_alert_config(
        alert_on_order,
        alert_on_trade,
        alert_on_error,
        alert_on_pnl,
        pnl_threshold,
    ).await.map_err(|e| e.to_string())?;

    telegram.reload().await.map_err(|e| e.to_string())
}
```

---

## Dependencies

```toml
[dependencies]
teloxide = { version = "0.12", features = ["macros"] }
```

---

## Conclusion

The Telegram Bot integration provides:

1. **Mobile Trading** - Execute trades from anywhere via Telegram
2. **Real-time Alerts** - Order, trade, and P&L notifications
3. **Position Management** - View and close positions
4. **Order Control** - View and cancel orders
5. **Account Overview** - Quick access to funds and P&L
6. **Mode Awareness** - Check if trading in live or sandbox mode
