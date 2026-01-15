# OpenAlgo Desktop - Configuration Management

## Overview

This document defines the configuration management system for OpenAlgo Desktop, including environment variables, database settings, and runtime configuration.

---

## Configuration Sources

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Configuration Hierarchy                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Priority (highest to lowest):                                               │
│                                                                              │
│  1. Runtime Override (Tauri commands)                                        │
│     └── User changes via UI during runtime                                   │
│                                                                              │
│  2. Database Settings                                                        │
│     └── Persisted in settings table                                          │
│                                                                              │
│  3. Environment Variables                                                    │
│     └── .env file or system environment                                      │
│                                                                              │
│  4. Default Values                                                           │
│     └── Hardcoded in Config struct                                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Configuration Struct

```rust
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

/// Main application configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    /// Application settings
    pub app: ApplicationConfig,

    /// Server settings
    pub server: ServerConfig,

    /// Database settings
    pub database: DatabaseConfig,

    /// Security settings
    pub security: SecurityConfig,

    /// Rate limiting settings
    pub rate_limit: RateLimitConfig,

    /// Trading settings
    pub trading: TradingConfig,

    /// Sandbox settings
    pub sandbox: SandboxConfig,

    /// Logging settings
    pub logging: LoggingConfig,

    /// Telegram settings
    pub telegram: TelegramConfig,
}

/// Application settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ApplicationConfig {
    /// Application name
    pub name: String,
    /// Application version
    pub version: String,
    /// Data directory
    pub data_dir: PathBuf,
    /// Debug mode
    pub debug: bool,
    /// Auto-start on login
    pub auto_start: bool,
    /// Minimize to tray
    pub minimize_to_tray: bool,
}

/// Server settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerConfig {
    /// API server host
    pub host: String,
    /// API server port
    pub port: u16,
    /// WebSocket host
    pub ws_host: String,
    /// WebSocket port
    pub ws_port: u16,
    /// Enable CORS
    pub enable_cors: bool,
    /// Allowed origins
    pub allowed_origins: Vec<String>,
}

/// Database settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DatabaseConfig {
    /// Database path
    pub path: PathBuf,
    /// Enable encryption
    pub encryption: bool,
    /// Connection pool size
    pub pool_size: u32,
    /// Connection timeout (seconds)
    pub connection_timeout: u64,
}

/// Security settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SecurityConfig {
    /// Session timeout (minutes)
    pub session_timeout: u64,
    /// Max login attempts before lockout
    pub max_login_attempts: u32,
    /// Lockout duration (minutes)
    pub lockout_duration: u64,
    /// Minimum password length
    pub min_password_length: usize,
    /// Require special characters in password
    pub require_special_chars: bool,
}

/// Rate limiting settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RateLimitConfig {
    /// API requests per second
    pub api_rate_limit: u32,
    /// Order requests per second
    pub order_rate_limit: u32,
    /// Smart order requests per second
    pub smart_order_rate_limit: u32,
    /// Greeks requests per minute
    pub greeks_rate_limit: u32,
    /// Margin requests per second
    pub margin_rate_limit: u32,
}

/// Trading settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TradingConfig {
    /// Default product type
    pub default_product: String,
    /// Default price type
    pub default_price_type: String,
    /// Auto-download master contracts on startup
    pub auto_download_contracts: bool,
    /// Master contract download time (HH:MM)
    pub contract_download_time: String,
}

/// Sandbox settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SandboxConfig {
    /// Starting capital
    pub starting_capital: f64,
    /// Equity MIS leverage
    pub equity_mis_leverage: f64,
    /// Equity CNC leverage
    pub equity_cnc_leverage: f64,
    /// Futures leverage
    pub futures_leverage: f64,
    /// Option buy leverage
    pub option_buy_leverage: f64,
    /// Option sell leverage
    pub option_sell_leverage: f64,
    /// NSE/BSE auto square-off time
    pub nse_bse_squareoff_time: String,
    /// CDS/BCD auto square-off time
    pub cds_bcd_squareoff_time: String,
    /// MCX auto square-off time
    pub mcx_squareoff_time: String,
    /// Order check interval (seconds)
    pub order_check_interval: u64,
    /// MTM update interval (seconds)
    pub mtm_update_interval: u64,
}

/// Logging settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoggingConfig {
    /// Log level (trace, debug, info, warn, error)
    pub level: String,
    /// Log to file
    pub log_to_file: bool,
    /// Log file path
    pub log_file_path: PathBuf,
    /// Max log file size (MB)
    pub max_file_size: u64,
    /// Number of log files to retain
    pub max_files: u32,
    /// Log format (json, text)
    pub format: String,
}

/// Telegram settings
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TelegramConfig {
    /// Bot token
    pub bot_token: Option<String>,
    /// Chat ID
    pub chat_id: Option<String>,
    /// Enable bot
    pub enabled: bool,
    /// Alert on order
    pub alert_on_order: bool,
    /// Alert on trade
    pub alert_on_trade: bool,
    /// Alert on error
    pub alert_on_error: bool,
    /// Alert on P&L threshold
    pub alert_on_pnl: bool,
    /// P&L alert threshold
    pub pnl_threshold: f64,
}
```

---

## Default Configuration

```rust
impl Default for AppConfig {
    fn default() -> Self {
        let data_dir = dirs::data_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("OpenAlgo");

        Self {
            app: ApplicationConfig {
                name: "OpenAlgo Desktop".to_string(),
                version: env!("CARGO_PKG_VERSION").to_string(),
                data_dir: data_dir.clone(),
                debug: false,
                auto_start: false,
                minimize_to_tray: true,
            },
            server: ServerConfig {
                host: "127.0.0.1".to_string(),
                port: 5000,
                ws_host: "127.0.0.1".to_string(),
                ws_port: 8765,
                enable_cors: false,
                allowed_origins: vec!["http://localhost:3000".to_string()],
            },
            database: DatabaseConfig {
                path: data_dir.join("openalgo.db"),
                encryption: true,
                pool_size: 5,
                connection_timeout: 30,
            },
            security: SecurityConfig {
                session_timeout: 480,           // 8 hours
                max_login_attempts: 5,
                lockout_duration: 30,           // 30 minutes
                min_password_length: 8,
                require_special_chars: true,
            },
            rate_limit: RateLimitConfig {
                api_rate_limit: 10,
                order_rate_limit: 10,
                smart_order_rate_limit: 2,
                greeks_rate_limit: 30,
                margin_rate_limit: 50,
            },
            trading: TradingConfig {
                default_product: "MIS".to_string(),
                default_price_type: "MARKET".to_string(),
                auto_download_contracts: true,
                contract_download_time: "08:00".to_string(),
            },
            sandbox: SandboxConfig {
                starting_capital: 10_000_000.0,
                equity_mis_leverage: 5.0,
                equity_cnc_leverage: 1.0,
                futures_leverage: 10.0,
                option_buy_leverage: 1.0,
                option_sell_leverage: 10.0,
                nse_bse_squareoff_time: "15:15".to_string(),
                cds_bcd_squareoff_time: "16:45".to_string(),
                mcx_squareoff_time: "23:30".to_string(),
                order_check_interval: 5,
                mtm_update_interval: 5,
            },
            logging: LoggingConfig {
                level: "info".to_string(),
                log_to_file: true,
                log_file_path: data_dir.join("logs"),
                max_file_size: 10,
                max_files: 5,
                format: "text".to_string(),
            },
            telegram: TelegramConfig {
                bot_token: None,
                chat_id: None,
                enabled: false,
                alert_on_order: true,
                alert_on_trade: true,
                alert_on_error: true,
                alert_on_pnl: false,
                pnl_threshold: 10000.0,
            },
        }
    }
}
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENALGO_HOST` | API server host | 127.0.0.1 |
| `OPENALGO_PORT` | API server port | 5000 |
| `OPENALGO_WS_PORT` | WebSocket port | 8765 |
| `OPENALGO_DB_PATH` | Database file path | {data_dir}/openalgo.db |
| `OPENALGO_DB_ENCRYPTION` | Enable DB encryption | true |
| `OPENALGO_LOG_LEVEL` | Log level | info |
| `OPENALGO_LOG_FILE` | Log to file | true |
| `OPENALGO_DEBUG` | Debug mode | false |
| `API_RATE_LIMIT` | API rate limit/second | 10 |
| `ORDER_RATE_LIMIT` | Order rate limit/second | 10 |
| `SMART_ORDER_RATE_LIMIT` | Smart order rate limit/second | 2 |
| `GREEKS_RATE_LIMIT` | Greeks rate limit/minute | 30 |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | - |
| `TELEGRAM_CHAT_ID` | Telegram chat ID | - |
| `API_KEY_PEPPER` | Pepper for API key hashing | **REQUIRED** |

---

## Database Settings Table

```sql
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    description TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, key)
);
```

---

## Configuration Service

```rust
use std::sync::RwLock;

pub struct ConfigService {
    config: RwLock<AppConfig>,
    db: SqlitePool,
}

impl ConfigService {
    /// Load configuration from all sources
    pub async fn load() -> Result<Self, ConfigError> {
        // 1. Start with defaults
        let mut config = AppConfig::default();

        // 2. Load from environment
        config.merge_from_env()?;

        // 3. Connect to database
        let db = Self::connect_db(&config.database).await?;

        // 4. Load from database settings
        config.merge_from_db(&db).await?;

        Ok(Self {
            config: RwLock::new(config),
            db,
        })
    }

    /// Get current configuration
    pub fn get(&self) -> AppConfig {
        self.config.read().unwrap().clone()
    }

    /// Update a setting
    pub async fn set(
        &self,
        category: &str,
        key: &str,
        value: &str,
    ) -> Result<(), ConfigError> {
        // 1. Save to database
        sqlx::query!(
            r#"
            INSERT INTO settings (category, key, value, updated_at)
            VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
            ON CONFLICT(category, key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            "#,
            category,
            key,
            value
        )
        .execute(&self.db)
        .await?;

        // 2. Update in-memory config
        let mut config = self.config.write().unwrap();
        config.set_value(category, key, value)?;

        Ok(())
    }

    /// Get a single setting
    pub async fn get_setting(&self, category: &str, key: &str) -> Option<String> {
        sqlx::query_scalar!(
            r#"
            SELECT value FROM settings
            WHERE category = $1 AND key = $2
            "#,
            category,
            key
        )
        .fetch_optional(&self.db)
        .await
        .ok()
        .flatten()
    }

    /// Get all settings for a category
    pub async fn get_category(&self, category: &str) -> Result<Vec<Setting>, ConfigError> {
        let settings = sqlx::query_as!(
            Setting,
            r#"
            SELECT category, key, value, description
            FROM settings
            WHERE category = $1
            ORDER BY key
            "#,
            category
        )
        .fetch_all(&self.db)
        .await?;

        Ok(settings)
    }

    /// Reset to defaults
    pub async fn reset_to_defaults(&self, category: Option<&str>) -> Result<(), ConfigError> {
        match category {
            Some(cat) => {
                sqlx::query!("DELETE FROM settings WHERE category = $1", cat)
                    .execute(&self.db)
                    .await?;
            }
            None => {
                sqlx::query!("DELETE FROM settings")
                    .execute(&self.db)
                    .await?;
            }
        }

        // Reload config
        let mut config = self.config.write().unwrap();
        *config = AppConfig::default();
        config.merge_from_env()?;
        config.merge_from_db(&self.db).await?;

        Ok(())
    }
}

impl AppConfig {
    /// Merge environment variables
    fn merge_from_env(&mut self) -> Result<(), ConfigError> {
        if let Ok(host) = std::env::var("OPENALGO_HOST") {
            self.server.host = host;
        }
        if let Ok(port) = std::env::var("OPENALGO_PORT") {
            self.server.port = port.parse()?;
        }
        if let Ok(ws_port) = std::env::var("OPENALGO_WS_PORT") {
            self.server.ws_port = ws_port.parse()?;
        }
        if let Ok(path) = std::env::var("OPENALGO_DB_PATH") {
            self.database.path = PathBuf::from(path);
        }
        if let Ok(level) = std::env::var("OPENALGO_LOG_LEVEL") {
            self.logging.level = level;
        }
        if let Ok(debug) = std::env::var("OPENALGO_DEBUG") {
            self.app.debug = debug.parse().unwrap_or(false);
        }
        if let Ok(limit) = std::env::var("API_RATE_LIMIT") {
            self.rate_limit.api_rate_limit = limit.parse()?;
        }
        if let Ok(limit) = std::env::var("ORDER_RATE_LIMIT") {
            self.rate_limit.order_rate_limit = limit.parse()?;
        }
        if let Ok(token) = std::env::var("TELEGRAM_BOT_TOKEN") {
            self.telegram.bot_token = Some(token);
        }
        if let Ok(chat_id) = std::env::var("TELEGRAM_CHAT_ID") {
            self.telegram.chat_id = Some(chat_id);
        }

        Ok(())
    }

    /// Merge from database settings
    async fn merge_from_db(&mut self, db: &SqlitePool) -> Result<(), ConfigError> {
        let settings = sqlx::query_as!(
            Setting,
            "SELECT category, key, value, description FROM settings"
        )
        .fetch_all(db)
        .await?;

        for setting in settings {
            self.set_value(&setting.category, &setting.key, &setting.value)?;
        }

        Ok(())
    }

    /// Set a configuration value
    fn set_value(&mut self, category: &str, key: &str, value: &str) -> Result<(), ConfigError> {
        match (category, key) {
            ("server", "host") => self.server.host = value.to_string(),
            ("server", "port") => self.server.port = value.parse()?,
            ("server", "ws_port") => self.server.ws_port = value.parse()?,
            ("security", "session_timeout") => self.security.session_timeout = value.parse()?,
            ("rate_limit", "api_rate_limit") => self.rate_limit.api_rate_limit = value.parse()?,
            ("rate_limit", "order_rate_limit") => self.rate_limit.order_rate_limit = value.parse()?,
            ("sandbox", "starting_capital") => self.sandbox.starting_capital = value.parse()?,
            ("sandbox", "equity_mis_leverage") => self.sandbox.equity_mis_leverage = value.parse()?,
            ("logging", "level") => self.logging.level = value.to_string(),
            ("telegram", "enabled") => self.telegram.enabled = value.parse()?,
            ("telegram", "alert_on_order") => self.telegram.alert_on_order = value.parse()?,
            ("trading", "default_product") => self.trading.default_product = value.to_string(),
            _ => {
                tracing::warn!("Unknown setting: {}.{}", category, key);
            }
        }

        Ok(())
    }
}
```

---

## Tauri Commands

```rust
#[tauri::command]
pub async fn get_config(
    state: State<'_, AppState>,
) -> Result<AppConfig, String> {
    Ok(state.config.get())
}

#[tauri::command]
pub async fn set_config(
    state: State<'_, AppState>,
    category: String,
    key: String,
    value: String,
) -> Result<(), String> {
    state.config.set(&category, &key, &value).await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_settings(
    state: State<'_, AppState>,
    category: String,
) -> Result<Vec<Setting>, String> {
    state.config.get_category(&category).await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn reset_settings(
    state: State<'_, AppState>,
    category: Option<String>,
) -> Result<(), String> {
    state.config.reset_to_defaults(category.as_deref()).await
        .map_err(|e| e.to_string())
}
```

---

## Frontend Integration

```typescript
// src/lib/stores/config.ts
import { writable } from 'svelte/store';
import { invoke } from '@tauri-apps/api/tauri';

interface AppConfig {
    app: ApplicationConfig;
    server: ServerConfig;
    database: DatabaseConfig;
    security: SecurityConfig;
    rate_limit: RateLimitConfig;
    trading: TradingConfig;
    sandbox: SandboxConfig;
    logging: LoggingConfig;
    telegram: TelegramConfig;
}

export const config = writable<AppConfig | null>(null);

export async function loadConfig() {
    const cfg = await invoke<AppConfig>('get_config');
    config.set(cfg);
    return cfg;
}

export async function updateSetting(category: string, key: string, value: string) {
    await invoke('set_config', { category, key, value });
    await loadConfig();
}

export async function resetSettings(category?: string) {
    await invoke('reset_settings', { category });
    await loadConfig();
}
```

---

## Conclusion

The Configuration Management system provides:

1. **Hierarchical Configuration** - Defaults, env vars, database, runtime
2. **Persistent Settings** - Database-backed configuration
3. **Type Safety** - Strongly typed configuration structs
4. **Runtime Updates** - Change settings without restart
5. **Frontend Integration** - Tauri commands for UI access
