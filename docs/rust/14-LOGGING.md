# OpenAlgo Desktop - Logging System

## Overview

This document defines the structured logging system for OpenAlgo Desktop, using Rust's `tracing` ecosystem for high-performance, structured logging with multiple output targets.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Logging Architecture                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                     Application Code                                     ││
│  │                                                                          ││
│  │  tracing::info!("Order placed: {}", order_id);                          ││
│  │  tracing::error!(?error, "Failed to connect to broker");                ││
│  │  tracing::debug!(symbol = %sym, price = ltp, "Quote received");         ││
│  │                                                                          ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                     Tracing Subscriber                                   ││
│  │                                                                          ││
│  │  ┌────────────────┐  ┌────────────────┐  ┌────────────────────────────┐ ││
│  │  │ Console Layer  │  │  File Layer    │  │ Database Layer (API Log)   │ ││
│  │  │ (stdout/stderr)│  │ (rolling file) │  │ (orders, trades)           │ ││
│  │  └────────────────┘  └────────────────┘  └────────────────────────────┘ ││
│  │                                                                          ││
│  │  ┌────────────────┐  ┌────────────────┐  ┌────────────────────────────┐ ││
│  │  │ Frontend Layer │  │ Performance   │  │ Alert Layer               │ ││
│  │  │ (Tauri events) │  │ Layer (timing)│  │ (critical errors)         │ ││
│  │  └────────────────┘  └────────────────┘  └────────────────────────────┘ ││
│  │                                                                          ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Log Levels

| Level | Use Case | Example |
|-------|----------|---------|
| `trace` | Detailed debugging | Function entry/exit, variable values |
| `debug` | Development debugging | Request/response details |
| `info` | Normal operations | Order placed, user logged in |
| `warn` | Potential issues | Rate limit approaching, retry |
| `error` | Errors | API failure, database error |

---

## Dependencies

```toml
[dependencies]
tracing = "0.1"
tracing-subscriber = { version = "0.3", features = ["env-filter", "json"] }
tracing-appender = "0.2"
```

---

## Initialization

```rust
use tracing_subscriber::{
    layer::SubscriberExt,
    util::SubscriberInitExt,
    EnvFilter,
    fmt,
};
use tracing_appender::rolling::{RollingFileAppender, Rotation};
use std::path::Path;

pub struct LoggingService {
    _guard: Option<tracing_appender::non_blocking::WorkerGuard>,
}

impl LoggingService {
    /// Initialize logging system
    pub fn init(config: &LoggingConfig) -> Result<Self, LoggingError> {
        // Create log directory
        if config.log_to_file {
            std::fs::create_dir_all(&config.log_file_path)?;
        }

        // Build filter from config
        let filter = EnvFilter::try_from_default_env()
            .unwrap_or_else(|_| EnvFilter::new(&config.level));

        // Console layer
        let console_layer = fmt::layer()
            .with_target(true)
            .with_thread_ids(false)
            .with_thread_names(false)
            .with_file(true)
            .with_line_number(true);

        // File layer (if enabled)
        let (file_layer, guard) = if config.log_to_file {
            let file_appender = RollingFileAppender::new(
                Rotation::DAILY,
                &config.log_file_path,
                "openalgo.log",
            );
            let (non_blocking, guard) = tracing_appender::non_blocking(file_appender);

            let layer = fmt::layer()
                .with_writer(non_blocking)
                .with_ansi(false)
                .with_target(true)
                .with_file(true)
                .with_line_number(true);

            (Some(layer), Some(guard))
        } else {
            (None, None)
        };

        // Build subscriber
        let subscriber = tracing_subscriber::registry()
            .with(filter)
            .with(console_layer)
            .with(file_layer);

        // Set as global default
        subscriber.init();

        tracing::info!(
            version = env!("CARGO_PKG_VERSION"),
            "OpenAlgo Desktop started"
        );

        Ok(Self { _guard: guard })
    }
}
```

---

## Structured Logging Patterns

### Order Events

```rust
use tracing::{info, error, instrument, Span};

#[instrument(
    name = "place_order",
    skip(self, order_data),
    fields(
        symbol = %order_data.symbol,
        exchange = %order_data.exchange,
        action = %order_data.action,
        quantity = order_data.quantity,
    )
)]
pub async fn place_order(
    &self,
    order_data: PlaceOrderRequest,
    api_key: Option<&str>,
) -> ServiceResult<OrderResponse> {
    info!("Placing order");

    // ... order logic

    match result {
        Ok(response) => {
            info!(
                order_id = %response.orderid,
                "Order placed successfully"
            );
            Ok(response)
        }
        Err(e) => {
            error!(
                error = %e,
                "Order placement failed"
            );
            Err(e)
        }
    }
}
```

### Market Data Events

```rust
#[instrument(
    name = "get_quotes",
    skip(self),
    fields(
        symbol = %symbol,
        exchange = %exchange,
    )
)]
pub async fn get_quotes(
    &self,
    symbol: &str,
    exchange: &str,
    api_key: Option<&str>,
) -> ServiceResult<QuoteData> {
    let span = Span::current();

    let result = self.broker_adapter.get_quotes(symbol, exchange).await;

    match &result {
        Ok(quote) => {
            span.record("ltp", quote.ltp);
            tracing::debug!(
                ltp = quote.ltp,
                bid = quote.bid,
                ask = quote.ask,
                "Quote received"
            );
        }
        Err(e) => {
            tracing::warn!(
                error = %e,
                "Failed to fetch quote"
            );
        }
    }

    result
}
```

### Broker Connection Events

```rust
impl BrokerConnection {
    pub async fn connect(&mut self) -> Result<(), BrokerError> {
        tracing::info!(
            broker = %self.broker_name,
            "Connecting to broker"
        );

        match self.authenticate().await {
            Ok(_) => {
                tracing::info!(
                    broker = %self.broker_name,
                    "Connected successfully"
                );
                Ok(())
            }
            Err(e) => {
                tracing::error!(
                    broker = %self.broker_name,
                    error = %e,
                    "Connection failed"
                );
                Err(e)
            }
        }
    }
}
```

### WebSocket Events

```rust
impl WebSocketService {
    pub async fn on_message(&self, msg: &str) {
        tracing::trace!(
            message_len = msg.len(),
            "WebSocket message received"
        );

        match serde_json::from_str::<MarketData>(msg) {
            Ok(data) => {
                tracing::trace!(
                    symbol = %data.symbol,
                    exchange = %data.exchange,
                    ltp = data.ltp,
                    "Market data parsed"
                );
            }
            Err(e) => {
                tracing::warn!(
                    error = %e,
                    "Failed to parse WebSocket message"
                );
            }
        }
    }
}
```

---

## Database Logging (API Log)

```rust
/// API request/response log
#[derive(sqlx::FromRow)]
pub struct ApiLog {
    pub id: i64,
    pub api_type: String,           // placeorder, quotes, etc.
    pub request_data: String,       // JSON
    pub response_data: String,      // JSON
    pub status_code: i32,
    pub latency_ms: i64,
    pub user_id: Option<String>,
    pub ip_address: Option<String>,
    pub created_at: DateTime<Utc>,
}

pub struct ApiLogDb {
    db: SqlitePool,
}

impl ApiLogDb {
    /// Log API request/response asynchronously
    pub fn log_async(
        &self,
        api_type: &str,
        request: &serde_json::Value,
        response: &serde_json::Value,
        status_code: i32,
        latency_ms: i64,
    ) {
        let db = self.db.clone();
        let api_type = api_type.to_string();
        let request = request.to_string();
        let response = response.to_string();

        // Use background task to avoid blocking
        tokio::spawn(async move {
            if let Err(e) = sqlx::query!(
                r#"
                INSERT INTO api_logs (api_type, request_data, response_data, status_code, latency_ms, created_at)
                VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
                "#,
                api_type,
                request,
                response,
                status_code,
                latency_ms
            )
            .execute(&db)
            .await
            {
                tracing::error!(error = %e, "Failed to log API request");
            }
        });
    }

    /// Get logs with filtering
    pub async fn get_logs(
        &self,
        api_type: Option<&str>,
        start_date: Option<NaiveDate>,
        end_date: Option<NaiveDate>,
        limit: i64,
    ) -> Result<Vec<ApiLog>, DbError> {
        let logs = sqlx::query_as!(
            ApiLog,
            r#"
            SELECT * FROM api_logs
            WHERE ($1 IS NULL OR api_type = $1)
            AND ($2 IS NULL OR DATE(created_at) >= $2)
            AND ($3 IS NULL OR DATE(created_at) <= $3)
            ORDER BY created_at DESC
            LIMIT $4
            "#,
            api_type,
            start_date,
            end_date,
            limit
        )
        .fetch_all(&self.db)
        .await?;

        Ok(logs)
    }

    /// Clean old logs
    pub async fn cleanup_old_logs(&self, days_to_keep: i32) -> Result<u64, DbError> {
        let result = sqlx::query!(
            r#"
            DELETE FROM api_logs
            WHERE created_at < datetime('now', '-' || $1 || ' days')
            "#,
            days_to_keep
        )
        .execute(&self.db)
        .await?;

        tracing::info!(
            deleted_count = result.rows_affected(),
            "Cleaned up old API logs"
        );

        Ok(result.rows_affected())
    }
}
```

---

## Frontend Log Viewer

### Tauri Commands

```rust
#[tauri::command]
pub async fn get_logs(
    state: State<'_, AppState>,
    api_type: Option<String>,
    start_date: Option<String>,
    end_date: Option<String>,
    limit: Option<i64>,
) -> Result<Vec<ApiLogView>, String> {
    let start = start_date.map(|d| NaiveDate::parse_from_str(&d, "%Y-%m-%d").ok()).flatten();
    let end = end_date.map(|d| NaiveDate::parse_from_str(&d, "%Y-%m-%d").ok()).flatten();

    state.api_log.get_logs(
        api_type.as_deref(),
        start,
        end,
        limit.unwrap_or(100),
    ).await
        .map(|logs| logs.into_iter().map(ApiLogView::from).collect())
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_log_stats(
    state: State<'_, AppState>,
) -> Result<LogStats, String> {
    state.api_log.get_stats().await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn clear_logs(
    state: State<'_, AppState>,
    days_to_keep: i32,
) -> Result<u64, String> {
    state.api_log.cleanup_old_logs(days_to_keep).await
        .map_err(|e| e.to_string())
}
```

### Svelte Log Store

```typescript
// src/lib/stores/logs.ts
import { writable } from 'svelte/store';
import { invoke } from '@tauri-apps/api/tauri';

interface ApiLog {
    id: number;
    api_type: string;
    request_data: object;
    response_data: object;
    status_code: number;
    latency_ms: number;
    created_at: string;
}

interface LogFilter {
    api_type?: string;
    start_date?: string;
    end_date?: string;
    limit?: number;
}

export const logs = writable<ApiLog[]>([]);
export const logStats = writable<LogStats | null>(null);

export async function loadLogs(filter: LogFilter = {}) {
    const result = await invoke<ApiLog[]>('get_logs', {
        apiType: filter.api_type,
        startDate: filter.start_date,
        endDate: filter.end_date,
        limit: filter.limit || 100,
    });
    logs.set(result);
    return result;
}

export async function loadLogStats() {
    const stats = await invoke<LogStats>('get_log_stats');
    logStats.set(stats);
    return stats;
}

export async function clearLogs(daysToKeep: number = 30) {
    const deleted = await invoke<number>('clear_logs', { daysToKeep });
    await loadLogs();
    return deleted;
}
```

---

## Performance Logging

```rust
use std::time::Instant;

/// Log performance metrics
pub struct PerformanceSpan {
    name: String,
    start: Instant,
}

impl PerformanceSpan {
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            start: Instant::now(),
        }
    }
}

impl Drop for PerformanceSpan {
    fn drop(&mut self) {
        let elapsed = self.start.elapsed();
        tracing::debug!(
            operation = %self.name,
            duration_ms = elapsed.as_millis(),
            "Performance metric"
        );
    }
}

// Usage
pub async fn place_order(&self, order: PlaceOrderRequest) -> Result<OrderResponse, Error> {
    let _perf = PerformanceSpan::new("place_order");

    // Order placement logic...
}
```

---

## Log Rotation

```rust
use std::fs;
use chrono::{Duration, Utc};

pub struct LogRotator {
    log_dir: PathBuf,
    max_files: u32,
    max_size_mb: u64,
}

impl LogRotator {
    pub fn cleanup(&self) -> Result<(), std::io::Error> {
        let mut log_files: Vec<_> = fs::read_dir(&self.log_dir)?
            .filter_map(|e| e.ok())
            .filter(|e| {
                e.path()
                    .extension()
                    .map(|ext| ext == "log")
                    .unwrap_or(false)
            })
            .collect();

        // Sort by modification time (oldest first)
        log_files.sort_by_key(|e| {
            e.metadata()
                .and_then(|m| m.modified())
                .unwrap_or(std::time::SystemTime::UNIX_EPOCH)
        });

        // Remove files beyond limit
        while log_files.len() > self.max_files as usize {
            if let Some(file) = log_files.first() {
                fs::remove_file(file.path())?;
                log_files.remove(0);
            }
        }

        Ok(())
    }
}
```

---

## Error Alerting

```rust
pub struct AlertLayer {
    telegram_service: Arc<TelegramAlertService>,
}

impl<S> tracing_subscriber::Layer<S> for AlertLayer
where
    S: tracing::Subscriber,
{
    fn on_event(
        &self,
        event: &tracing::Event<'_>,
        _ctx: tracing_subscriber::layer::Context<'_, S>,
    ) {
        // Only process ERROR level
        if *event.metadata().level() != tracing::Level::ERROR {
            return;
        }

        // Extract message
        let mut visitor = MessageVisitor::default();
        event.record(&mut visitor);

        if let Some(message) = visitor.message {
            // Send to Telegram asynchronously
            let telegram = self.telegram_service.clone();
            tokio::spawn(async move {
                telegram.send_error_alert("System Error", &message).await.ok();
            });
        }
    }
}

#[derive(Default)]
struct MessageVisitor {
    message: Option<String>,
}

impl tracing::field::Visit for MessageVisitor {
    fn record_str(&mut self, field: &tracing::field::Field, value: &str) {
        if field.name() == "message" {
            self.message = Some(value.to_string());
        }
    }

    fn record_debug(&mut self, field: &tracing::field::Field, value: &dyn std::fmt::Debug) {
        if field.name() == "message" {
            self.message = Some(format!("{:?}", value));
        }
    }
}
```

---

## Log Configuration

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoggingConfig {
    /// Log level (trace, debug, info, warn, error)
    pub level: String,

    /// Log to file
    pub log_to_file: bool,

    /// Log file directory
    pub log_file_path: PathBuf,

    /// Max log file size (MB)
    pub max_file_size: u64,

    /// Number of log files to retain
    pub max_files: u32,

    /// Log format (json, text)
    pub format: String,

    /// Include source file info
    pub include_source: bool,

    /// Include timestamps
    pub include_timestamp: bool,
}
```

---

## Tauri Frontend Events

```rust
/// Emit log events to frontend for real-time display
pub struct FrontendLogLayer {
    app_handle: AppHandle,
}

impl<S> tracing_subscriber::Layer<S> for FrontendLogLayer
where
    S: tracing::Subscriber,
{
    fn on_event(
        &self,
        event: &tracing::Event<'_>,
        _ctx: tracing_subscriber::layer::Context<'_, S>,
    ) {
        // Only emit INFO and above
        if *event.metadata().level() > tracing::Level::INFO {
            return;
        }

        let mut visitor = LogEventVisitor::default();
        event.record(&mut visitor);

        let log_event = FrontendLogEvent {
            level: event.metadata().level().to_string(),
            target: event.metadata().target().to_string(),
            message: visitor.message.unwrap_or_default(),
            timestamp: chrono::Utc::now().to_rfc3339(),
        };

        self.app_handle.emit_all("log_event", &log_event).ok();
    }
}

#[derive(Serialize)]
struct FrontendLogEvent {
    level: String,
    target: String,
    message: String,
    timestamp: String,
}
```

---

## Conclusion

The Logging System provides:

1. **Structured Logging** - Using tracing for context-rich logs
2. **Multiple Outputs** - Console, file, database, frontend
3. **Performance Tracking** - Automatic latency measurement
4. **Log Rotation** - Automatic cleanup of old logs
5. **Error Alerting** - Critical errors sent to Telegram
6. **Frontend Integration** - Real-time log viewing in UI
