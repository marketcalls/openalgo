# 17. Zero-Config Architecture

## Overview

The Rust desktop application implements a **zero-configuration installation** experience. Users can download, install, and immediately start connecting to their broker without any manual configuration. All settings that traditionally require `.env` file editing are stored in an encrypted SQLite database and configured through the UI.

## Design Goals

1. **Install and Run**: No terminal commands, no `.env` file editing
2. **First-Run Wizard**: Guided setup for essential configuration
3. **Database-Stored Settings**: All configuration persisted in encrypted SQLite
4. **Sensible Defaults**: Pre-configured for local development/use
5. **UI-Driven Configuration**: All settings accessible through the app interface
6. **Migration Support**: Import settings from existing Python OpenAlgo installations

---

## Configuration Categories

### 1. Core Application Settings

These are automatically configured with sensible defaults:

| Setting | Default Value | Description |
|---------|--------------|-------------|
| `app_key` | Auto-generated | 64-char hex string for session encryption |
| `api_key_pepper` | Auto-generated | 64-char hex string for hashing/encryption |
| `database_path` | `{app_data}/openalgo.db` | Main database location |

```rust
// src-tauri/src/config/core.rs

#[derive(Debug, Clone)]
pub struct CoreConfig {
    pub app_key: String,
    pub api_key_pepper: String,
    pub database_url: String,
    pub logs_database_url: String,
    pub latency_database_url: String,
}

impl CoreConfig {
    /// Generate new secure configuration on first run
    pub fn generate_new() -> Self {
        use rand::Rng;

        let mut rng = rand::thread_rng();
        let app_key: String = (0..32).map(|_| format!("{:02x}", rng.gen::<u8>())).collect();
        let pepper: String = (0..32).map(|_| format!("{:02x}", rng.gen::<u8>())).collect();

        let app_data = tauri::api::path::app_data_dir(&tauri::Config::default())
            .expect("Failed to get app data directory");

        Self {
            app_key,
            api_key_pepper: pepper,
            database_url: format!("sqlite:///{}/openalgo.db", app_data.display()),
            logs_database_url: format!("sqlite:///{}/logs.db", app_data.display()),
            latency_database_url: format!("sqlite:///{}/latency.db", app_data.display()),
        }
    }
}
```

### 2. Network Configuration

Configurable through Settings UI:

| Setting | Default Value | Description |
|---------|--------------|-------------|
| `flask_host_ip` | `127.0.0.1` | HTTP server bind address |
| `flask_port` | `5000` | HTTP server port |
| `websocket_host` | `127.0.0.1` | WebSocket server bind address |
| `websocket_port` | `8765` | WebSocket server port |
| `zmq_host` | `127.0.0.1` | ZeroMQ bind address |
| `zmq_port` | `5555` | ZeroMQ port |
| `host_server` | `http://127.0.0.1:5000` | Public URL for webhooks |

```rust
// src-tauri/src/config/network.rs

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NetworkConfig {
    // HTTP Server
    pub http_host: String,
    pub http_port: u16,

    // WebSocket Server
    pub websocket_host: String,
    pub websocket_port: u16,

    // ZeroMQ (for inter-process communication)
    pub zmq_host: String,
    pub zmq_port: u16,

    // Public URL (for webhook generation)
    pub host_server: String,
}

impl Default for NetworkConfig {
    fn default() -> Self {
        Self {
            http_host: "127.0.0.1".to_string(),
            http_port: 5000,
            websocket_host: "127.0.0.1".to_string(),
            websocket_port: 8765,
            zmq_host: "127.0.0.1".to_string(),
            zmq_port: 5555,
            host_server: "http://127.0.0.1:5000".to_string(),
        }
    }
}

impl NetworkConfig {
    pub fn websocket_url(&self) -> String {
        format!("ws://{}:{}", self.websocket_host, self.websocket_port)
    }

    pub fn http_bind_addr(&self) -> String {
        format!("{}:{}", self.http_host, self.http_port)
    }
}
```

### 3. Broker Configuration

Set during first-run or via Settings:

| Setting | Default Value | Description |
|---------|--------------|-------------|
| `broker_api_key` | Empty | Broker-provided API key |
| `broker_api_secret` | Empty (encrypted) | Broker-provided API secret |
| `broker_api_key_market` | Empty | Market data API key (XTS brokers) |
| `broker_api_secret_market` | Empty (encrypted) | Market data API secret |
| `redirect_url` | Auto-generated | OAuth callback URL |

```rust
// src-tauri/src/config/broker.rs

#[derive(Debug, Clone)]
pub struct BrokerConfig {
    pub api_key: String,
    pub api_secret: SecureString,  // Encrypted in database
    pub api_key_market: Option<String>,
    pub api_secret_market: Option<SecureString>,
    pub redirect_url: String,
}

impl BrokerConfig {
    pub fn redirect_url_for_broker(broker: &str, network: &NetworkConfig) -> String {
        format!("{}/{}/callback", network.host_server, broker)
    }
}
```

### 4. Rate Limiting Configuration

| Setting | Default Value | Description |
|---------|--------------|-------------|
| `login_rate_limit_min` | `5 per minute` | Login attempts per minute |
| `login_rate_limit_hour` | `25 per hour` | Login attempts per hour |
| `api_rate_limit` | `50 per second` | API calls per second |
| `order_rate_limit` | `10 per second` | Order placement rate |
| `smart_order_rate_limit` | `2 per second` | Smart order rate |
| `webhook_rate_limit` | `100 per minute` | Webhook rate |
| `smart_order_delay` | `0.5` | Delay between multi-leg orders |

### 5. Security Configuration

| Setting | Default Value | Description |
|---------|--------------|-------------|
| `session_expiry_time` | `03:00` | Daily session expiry (IST) |
| `csrf_enabled` | `true` | CSRF protection |
| `cors_enabled` | `true` | CORS support |
| `cors_allowed_origins` | `http://127.0.0.1:5000` | Allowed origins |

### 6. Logging Configuration

| Setting | Default Value | Description |
|---------|--------------|-------------|
| `log_level` | `INFO` | Minimum log level |
| `log_to_file` | `false` | Write logs to file |
| `log_dir` | `{app_data}/logs` | Log file directory |
| `log_retention` | `14` | Days to keep logs |

### 7. Tunneling Configuration (External Access)

| Setting | Default Value | Description |
|---------|--------------|-------------|
| `tunnel_provider` | `none` | none, ngrok, cloudflared, tailscale |
| `ngrok_auth_token` | Empty | ngrok authentication token |
| `ngrok_domain` | Empty | Custom ngrok domain |
| `cloudflared_tunnel_id` | Empty | Cloudflare tunnel ID |

---

## Database Schema

All configuration is stored in a `settings` table with key-value structure:

```sql
-- Settings table for all configuration
CREATE TABLE IF NOT EXISTS app_settings (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,           -- 'core', 'network', 'broker', 'security', etc.
    key TEXT NOT NULL,
    value TEXT,                       -- JSON-encoded value
    encrypted BOOLEAN DEFAULT FALSE,  -- Whether value is encrypted
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category, key)
);

-- Index for fast lookups
CREATE INDEX idx_settings_category ON app_settings(category);
CREATE INDEX idx_settings_key ON app_settings(category, key);
```

### Rust Schema

```rust
// src-tauri/src/database/models/settings.rs

use diesel::prelude::*;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Queryable, Insertable, AsChangeset)]
#[diesel(table_name = app_settings)]
pub struct AppSetting {
    pub id: Option<i32>,
    pub category: String,
    pub key: String,
    pub value: Option<String>,
    pub encrypted: bool,
    pub created_at: NaiveDateTime,
    pub updated_at: NaiveDateTime,
}

/// Setting categories
pub enum SettingCategory {
    Core,
    Network,
    Broker,
    RateLimit,
    Security,
    Logging,
    Tunnel,
    Smtp,
    Telegram,
}

impl SettingCategory {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Core => "core",
            Self::Network => "network",
            Self::Broker => "broker",
            Self::RateLimit => "rate_limit",
            Self::Security => "security",
            Self::Logging => "logging",
            Self::Tunnel => "tunnel",
            Self::Smtp => "smtp",
            Self::Telegram => "telegram",
        }
    }
}
```

---

## Settings Service

```rust
// src-tauri/src/services/settings_service.rs

use crate::database::models::settings::{AppSetting, SettingCategory};
use crate::encryption::Encryptor;

pub struct SettingsService {
    db: DatabaseConnection,
    encryptor: Encryptor,
    cache: RwLock<HashMap<String, serde_json::Value>>,
}

impl SettingsService {
    /// Get a setting by category and key
    pub async fn get<T: DeserializeOwned>(
        &self,
        category: SettingCategory,
        key: &str,
    ) -> Result<Option<T>, SettingsError> {
        let cache_key = format!("{}:{}", category.as_str(), key);

        // Check cache first
        if let Some(cached) = self.cache.read().await.get(&cache_key) {
            return Ok(Some(serde_json::from_value(cached.clone())?));
        }

        // Query database
        let setting = app_settings::table
            .filter(app_settings::category.eq(category.as_str()))
            .filter(app_settings::key.eq(key))
            .first::<AppSetting>(&mut self.db.get()?)
            .optional()?;

        if let Some(setting) = setting {
            let value = if setting.encrypted {
                let decrypted = self.encryptor.decrypt(&setting.value.unwrap_or_default())?;
                serde_json::from_str(&decrypted)?
            } else {
                serde_json::from_str(&setting.value.unwrap_or_default())?
            };

            // Update cache
            self.cache.write().await.insert(cache_key, value.clone());

            Ok(Some(serde_json::from_value(value)?))
        } else {
            Ok(None)
        }
    }

    /// Set a setting
    pub async fn set<T: Serialize>(
        &self,
        category: SettingCategory,
        key: &str,
        value: &T,
        encrypt: bool,
    ) -> Result<(), SettingsError> {
        let json_value = serde_json::to_string(value)?;

        let stored_value = if encrypt {
            self.encryptor.encrypt(&json_value)?
        } else {
            json_value
        };

        diesel::insert_into(app_settings::table)
            .values(&AppSetting {
                id: None,
                category: category.as_str().to_string(),
                key: key.to_string(),
                value: Some(stored_value),
                encrypted: encrypt,
                created_at: chrono::Utc::now().naive_utc(),
                updated_at: chrono::Utc::now().naive_utc(),
            })
            .on_conflict((app_settings::category, app_settings::key))
            .do_update()
            .set((
                app_settings::value.eq(excluded(app_settings::value)),
                app_settings::encrypted.eq(encrypt),
                app_settings::updated_at.eq(chrono::Utc::now().naive_utc()),
            ))
            .execute(&mut self.db.get()?)?;

        // Invalidate cache
        let cache_key = format!("{}:{}", category.as_str(), key);
        self.cache.write().await.remove(&cache_key);

        Ok(())
    }

    /// Get all settings for a category
    pub async fn get_category(&self, category: SettingCategory) -> Result<HashMap<String, serde_json::Value>, SettingsError> {
        let settings = app_settings::table
            .filter(app_settings::category.eq(category.as_str()))
            .load::<AppSetting>(&mut self.db.get()?)?;

        let mut result = HashMap::new();
        for setting in settings {
            let value = if setting.encrypted {
                let decrypted = self.encryptor.decrypt(&setting.value.unwrap_or_default())?;
                serde_json::from_str(&decrypted)?
            } else {
                serde_json::from_str(&setting.value.unwrap_or_default())?
            };
            result.insert(setting.key, value);
        }

        Ok(result)
    }

    /// Load complete configuration
    pub async fn load_config(&self) -> Result<AppConfig, SettingsError> {
        Ok(AppConfig {
            core: self.get_or_default(SettingCategory::Core, "config").await?,
            network: self.get_or_default(SettingCategory::Network, "config").await?,
            broker: self.get_or_default(SettingCategory::Broker, "config").await?,
            rate_limits: self.get_or_default(SettingCategory::RateLimit, "config").await?,
            security: self.get_or_default(SettingCategory::Security, "config").await?,
            logging: self.get_or_default(SettingCategory::Logging, "config").await?,
            tunnel: self.get_or_default(SettingCategory::Tunnel, "config").await?,
        })
    }
}
```

---

## First-Run Setup Wizard

On first launch, the app detects no configuration and launches a setup wizard:

### Step 1: Welcome

```svelte
<!-- src/routes/setup/+page.svelte -->
<script lang="ts">
  import { goto } from '$app/navigation';
</script>

<div class="setup-wizard">
  <h1>Welcome to OpenAlgo</h1>
  <p>Let's get you set up in just a few steps.</p>

  <div class="features">
    <div class="feature">
      <h3>Multi-Broker Support</h3>
      <p>Connect to 24+ Indian brokers</p>
    </div>
    <div class="feature">
      <h3>Algo Trading</h3>
      <p>Automate your trading strategies</p>
    </div>
    <div class="feature">
      <h3>Secure & Private</h3>
      <p>All data stored locally on your device</p>
    </div>
  </div>

  <button on:click={() => goto('/setup/broker')}>Get Started</button>
</div>
```

### Step 2: Broker Selection

```svelte
<!-- src/routes/setup/broker/+page.svelte -->
<script lang="ts">
  import { invoke } from '@tauri-apps/api/tauri';

  const brokers = [
    { id: 'zerodha', name: 'Zerodha', logo: '/logos/zerodha.png' },
    { id: 'angel', name: 'Angel One', logo: '/logos/angel.png' },
    { id: 'fyers', name: 'Fyers', logo: '/logos/fyers.png' },
    // ... 24 brokers
  ];

  let selectedBroker = '';

  async function selectBroker(brokerId: string) {
    selectedBroker = brokerId;
    await invoke('set_selected_broker', { broker: brokerId });
  }
</script>

<div class="broker-selection">
  <h2>Select Your Broker</h2>

  <div class="broker-grid">
    {#each brokers as broker}
      <button
        class="broker-card"
        class:selected={selectedBroker === broker.id}
        on:click={() => selectBroker(broker.id)}
      >
        <img src={broker.logo} alt={broker.name} />
        <span>{broker.name}</span>
      </button>
    {/each}
  </div>

  <button disabled={!selectedBroker} on:click={() => goto('/setup/credentials')}>
    Continue
  </button>
</div>
```

### Step 3: API Credentials

```svelte
<!-- src/routes/setup/credentials/+page.svelte -->
<script lang="ts">
  import { invoke } from '@tauri-apps/api/tauri';

  let apiKey = '';
  let apiSecret = '';
  let loading = false;
  let error = '';

  async function saveCredentials() {
    loading = true;
    error = '';

    try {
      await invoke('save_broker_credentials', {
        apiKey,
        apiSecret,
      });
      goto('/setup/network');
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  }
</script>

<div class="credentials-form">
  <h2>Enter API Credentials</h2>
  <p>Get these from your broker's developer portal</p>

  <form on:submit|preventDefault={saveCredentials}>
    <label>
      API Key
      <input type="text" bind:value={apiKey} required />
    </label>

    <label>
      API Secret
      <input type="password" bind:value={apiSecret} required />
    </label>

    {#if error}
      <p class="error">{error}</p>
    {/if}

    <button type="submit" disabled={loading}>
      {loading ? 'Saving...' : 'Continue'}
    </button>
  </form>
</div>
```

### Step 4: Network Configuration (Optional)

```svelte
<!-- src/routes/setup/network/+page.svelte -->
<script lang="ts">
  import { invoke } from '@tauri-apps/api/tauri';

  let config = {
    httpPort: 5000,
    websocketPort: 8765,
    bindAddress: '127.0.0.1',
  };

  let useDefaults = true;

  async function saveNetwork() {
    if (!useDefaults) {
      await invoke('save_network_config', { config });
    }
    goto('/setup/complete');
  }
</script>

<div class="network-config">
  <h2>Network Configuration</h2>

  <label class="checkbox">
    <input type="checkbox" bind:checked={useDefaults} />
    Use default settings (recommended)
  </label>

  {#if !useDefaults}
    <div class="advanced-settings">
      <label>
        HTTP Port
        <input type="number" bind:value={config.httpPort} min="1024" max="65535" />
      </label>

      <label>
        WebSocket Port
        <input type="number" bind:value={config.websocketPort} min="1024" max="65535" />
      </label>

      <label>
        Bind Address
        <select bind:value={config.bindAddress}>
          <option value="127.0.0.1">Local only (127.0.0.1)</option>
          <option value="0.0.0.0">All interfaces (0.0.0.0)</option>
        </select>
      </label>
    </div>
  {/if}

  <button on:click={saveNetwork}>Continue</button>
</div>
```

### Step 5: Setup Complete

```svelte
<!-- src/routes/setup/complete/+page.svelte -->
<script lang="ts">
  import { invoke } from '@tauri-apps/api/tauri';

  async function finishSetup() {
    await invoke('complete_setup');
    goto('/login');
  }
</script>

<div class="setup-complete">
  <div class="success-icon">Check</div>
  <h2>Setup Complete!</h2>
  <p>OpenAlgo is ready to use.</p>

  <div class="next-steps">
    <h3>Next Steps:</h3>
    <ol>
      <li>Create your OpenAlgo account</li>
      <li>Connect to your broker</li>
      <li>Start trading!</li>
    </ol>
  </div>

  <button on:click={finishSetup}>Launch OpenAlgo</button>
</div>
```

---

## Settings UI

### Main Settings Page

```svelte
<!-- src/routes/settings/+page.svelte -->
<script lang="ts">
  const settingsCategories = [
    { id: 'network', name: 'Network', icon: 'network', route: '/settings/network' },
    { id: 'broker', name: 'Broker', icon: 'key', route: '/settings/broker' },
    { id: 'security', name: 'Security', icon: 'shield', route: '/settings/security' },
    { id: 'rate-limits', name: 'Rate Limits', icon: 'gauge', route: '/settings/rate-limits' },
    { id: 'logging', name: 'Logging', icon: 'file-text', route: '/settings/logging' },
    { id: 'tunnel', name: 'External Access', icon: 'globe', route: '/settings/tunnel' },
    { id: 'telegram', name: 'Telegram', icon: 'message', route: '/settings/telegram' },
    { id: 'smtp', name: 'Email (SMTP)', icon: 'mail', route: '/settings/smtp' },
    { id: 'backup', name: 'Backup & Restore', icon: 'database', route: '/settings/backup' },
  ];
</script>

<div class="settings-page">
  <h1>Settings</h1>

  <div class="settings-grid">
    {#each settingsCategories as category}
      <a href={category.route} class="settings-card">
        <span class="icon">{category.icon}</span>
        <span class="name">{category.name}</span>
      </a>
    {/each}
  </div>
</div>
```

### Network Settings

```svelte
<!-- src/routes/settings/network/+page.svelte -->
<script lang="ts">
  import { invoke } from '@tauri-apps/api/tauri';
  import { onMount } from 'svelte';

  let config = {
    httpHost: '127.0.0.1',
    httpPort: 5000,
    websocketHost: '127.0.0.1',
    websocketPort: 8765,
    zmqHost: '127.0.0.1',
    zmqPort: 5555,
    hostServer: 'http://127.0.0.1:5000',
  };

  let saving = false;
  let restartRequired = false;

  onMount(async () => {
    config = await invoke('get_network_config');
  });

  async function saveConfig() {
    saving = true;
    try {
      await invoke('save_network_config', { config });
      restartRequired = true;
    } finally {
      saving = false;
    }
  }

  async function restartServices() {
    await invoke('restart_services');
    restartRequired = false;
  }
</script>

<div class="network-settings">
  <h2>Network Configuration</h2>

  {#if restartRequired}
    <div class="warning-banner">
      <p>Settings saved. Restart required for changes to take effect.</p>
      <button on:click={restartServices}>Restart Now</button>
    </div>
  {/if}

  <form on:submit|preventDefault={saveConfig}>
    <fieldset>
      <legend>HTTP Server</legend>

      <label>
        Bind Address
        <select bind:value={config.httpHost}>
          <option value="127.0.0.1">Local only (127.0.0.1)</option>
          <option value="0.0.0.0">All interfaces (0.0.0.0)</option>
        </select>
      </label>

      <label>
        Port
        <input type="number" bind:value={config.httpPort} min="1024" max="65535" />
      </label>
    </fieldset>

    <fieldset>
      <legend>WebSocket Server</legend>

      <label>
        Bind Address
        <select bind:value={config.websocketHost}>
          <option value="127.0.0.1">Local only (127.0.0.1)</option>
          <option value="0.0.0.0">All interfaces (0.0.0.0)</option>
        </select>
      </label>

      <label>
        Port
        <input type="number" bind:value={config.websocketPort} min="1024" max="65535" />
      </label>
    </fieldset>

    <fieldset>
      <legend>Public URL</legend>

      <label>
        Host Server URL
        <input type="url" bind:value={config.hostServer} placeholder="http://127.0.0.1:5000" />
        <small>Used for generating webhook URLs</small>
      </label>
    </fieldset>

    <button type="submit" disabled={saving}>
      {saving ? 'Saving...' : 'Save Changes'}
    </button>
  </form>
</div>
```

---

## Migration from Python OpenAlgo

Users with existing Python installations can import their settings:

```rust
// src-tauri/src/migration/import.rs

use std::path::Path;

pub struct MigrationService;

impl MigrationService {
    /// Import settings from Python OpenAlgo .env file
    pub async fn import_from_env(
        env_path: &Path,
        settings_service: &SettingsService,
    ) -> Result<ImportResult, MigrationError> {
        let content = std::fs::read_to_string(env_path)?;
        let mut imported = Vec::new();
        let mut skipped = Vec::new();

        for line in content.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }

            if let Some((key, value)) = line.split_once('=') {
                let key = key.trim();
                let value = value.trim().trim_matches('\'').trim_matches('"');

                match key {
                    // Network settings
                    "FLASK_HOST_IP" => {
                        settings_service.set(SettingCategory::Network, "http_host", &value, false).await?;
                        imported.push(key.to_string());
                    }
                    "FLASK_PORT" => {
                        let port: u16 = value.parse()?;
                        settings_service.set(SettingCategory::Network, "http_port", &port, false).await?;
                        imported.push(key.to_string());
                    }
                    "WEBSOCKET_HOST" => {
                        settings_service.set(SettingCategory::Network, "websocket_host", &value, false).await?;
                        imported.push(key.to_string());
                    }
                    "WEBSOCKET_PORT" => {
                        let port: u16 = value.parse()?;
                        settings_service.set(SettingCategory::Network, "websocket_port", &port, false).await?;
                        imported.push(key.to_string());
                    }
                    "HOST_SERVER" => {
                        settings_service.set(SettingCategory::Network, "host_server", &value, false).await?;
                        imported.push(key.to_string());
                    }

                    // Broker settings (encrypted)
                    "BROKER_API_KEY" if value != "YOUR_BROKER_API_KEY" => {
                        settings_service.set(SettingCategory::Broker, "api_key", &value, true).await?;
                        imported.push(key.to_string());
                    }
                    "BROKER_API_SECRET" if value != "YOUR_BROKER_API_SECRET" => {
                        settings_service.set(SettingCategory::Broker, "api_secret", &value, true).await?;
                        imported.push(key.to_string());
                    }

                    // Rate limits
                    "API_RATE_LIMIT" => {
                        settings_service.set(SettingCategory::RateLimit, "api", &value, false).await?;
                        imported.push(key.to_string());
                    }
                    "ORDER_RATE_LIMIT" => {
                        settings_service.set(SettingCategory::RateLimit, "order", &value, false).await?;
                        imported.push(key.to_string());
                    }

                    // Skip internal/generated values
                    "APP_KEY" | "API_KEY_PEPPER" | "DATABASE_URL" => {
                        skipped.push(key.to_string());
                    }

                    _ => {
                        skipped.push(key.to_string());
                    }
                }
            }
        }

        Ok(ImportResult { imported, skipped })
    }

    /// Import database from Python OpenAlgo
    pub async fn import_database(
        db_path: &Path,
        dest_db: &DatabaseConnection,
    ) -> Result<DatabaseImportResult, MigrationError> {
        // Open source database
        let source_db = SqliteConnection::establish(db_path.to_str().unwrap())?;

        // Import users, strategies, API keys, etc.
        // (with proper encryption key migration)

        Ok(DatabaseImportResult { /* ... */ })
    }
}
```

### Migration UI

```svelte
<!-- src/routes/settings/backup/+page.svelte -->
<script lang="ts">
  import { invoke } from '@tauri-apps/api/tauri';
  import { open } from '@tauri-apps/api/dialog';

  let importing = false;
  let importResult = null;

  async function importFromPython() {
    const selected = await open({
      multiple: false,
      filters: [{ name: '.env', extensions: ['env'] }],
    });

    if (selected) {
      importing = true;
      try {
        importResult = await invoke('import_from_env', { path: selected });
      } finally {
        importing = false;
      }
    }
  }

  async function exportSettings() {
    const path = await invoke('export_settings');
    // Show success message with path
  }

  async function importSettings() {
    const selected = await open({
      filters: [{ name: 'OpenAlgo Backup', extensions: ['oabak'] }],
    });

    if (selected) {
      await invoke('import_settings', { path: selected });
    }
  }
</script>

<div class="backup-settings">
  <h2>Backup & Restore</h2>

  <section>
    <h3>Export Settings</h3>
    <p>Create a backup of all your settings and configuration.</p>
    <button on:click={exportSettings}>Export Backup</button>
  </section>

  <section>
    <h3>Import Settings</h3>
    <p>Restore settings from a backup file.</p>
    <button on:click={importSettings}>Import Backup</button>
  </section>

  <section>
    <h3>Migrate from Python OpenAlgo</h3>
    <p>Import settings from an existing Python OpenAlgo installation.</p>
    <button on:click={importFromPython} disabled={importing}>
      {importing ? 'Importing...' : 'Import from .env'}
    </button>

    {#if importResult}
      <div class="import-result">
        <p>Imported {importResult.imported.length} settings</p>
        <p>Skipped {importResult.skipped.length} settings</p>
      </div>
    {/if}
  </section>
</div>
```

---

## Tauri Commands

```rust
// src-tauri/src/commands/settings.rs

#[tauri::command]
pub async fn get_network_config(
    state: State<'_, AppState>,
) -> Result<NetworkConfig, String> {
    state.settings_service
        .get(SettingCategory::Network, "config")
        .await
        .map_err(|e| e.to_string())?
        .unwrap_or_default()
}

#[tauri::command]
pub async fn save_network_config(
    config: NetworkConfig,
    state: State<'_, AppState>,
) -> Result<(), String> {
    state.settings_service
        .set(SettingCategory::Network, "config", &config, false)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn save_broker_credentials(
    api_key: String,
    api_secret: String,
    state: State<'_, AppState>,
) -> Result<(), String> {
    state.settings_service
        .set(SettingCategory::Broker, "api_key", &api_key, true)
        .await
        .map_err(|e| e.to_string())?;

    state.settings_service
        .set(SettingCategory::Broker, "api_secret", &api_secret, true)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn is_first_run(state: State<'_, AppState>) -> Result<bool, String> {
    let has_config = state.settings_service
        .get::<CoreConfig>(SettingCategory::Core, "config")
        .await
        .map_err(|e| e.to_string())?
        .is_some();

    Ok(!has_config)
}

#[tauri::command]
pub async fn complete_setup(state: State<'_, AppState>) -> Result<(), String> {
    // Generate and save core config if not exists
    let core_config = CoreConfig::generate_new();
    state.settings_service
        .set(SettingCategory::Core, "config", &core_config, false)
        .await
        .map_err(|e| e.to_string())?;

    // Mark setup as complete
    state.settings_service
        .set(SettingCategory::Core, "setup_complete", &true, false)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn restart_services(state: State<'_, AppState>) -> Result<(), String> {
    // Reload configuration
    let config = state.settings_service.load_config().await.map_err(|e| e.to_string())?;

    // Restart HTTP server
    state.http_server.restart(&config.network).await.map_err(|e| e.to_string())?;

    // Restart WebSocket server
    state.ws_server.restart(&config.network).await.map_err(|e| e.to_string())?;

    Ok(())
}

#[tauri::command]
pub async fn import_from_env(
    path: String,
    state: State<'_, AppState>,
) -> Result<ImportResult, String> {
    MigrationService::import_from_env(
        Path::new(&path),
        &state.settings_service,
    )
    .await
    .map_err(|e| e.to_string())
}
```

---

## App Initialization Flow

```rust
// src-tauri/src/main.rs

#[tokio::main]
async fn main() {
    tauri::Builder::default()
        .setup(|app| {
            let app_handle = app.handle();

            tauri::async_runtime::spawn(async move {
                // 1. Initialize database
                let db = Database::init(&app_handle).await?;

                // 2. Initialize settings service
                let settings = SettingsService::new(db.clone());

                // 3. Check if first run
                let is_first_run = settings
                    .get::<bool>(SettingCategory::Core, "setup_complete")
                    .await?
                    .unwrap_or(false) == false;

                if is_first_run {
                    // Navigate to setup wizard
                    app_handle.emit_all("navigate", "/setup")?;
                    return Ok(());
                }

                // 4. Load configuration
                let config = settings.load_config().await?;

                // 5. Start services
                let http_server = HttpServer::start(&config.network).await?;
                let ws_server = WebSocketServer::start(&config.network).await?;

                // 6. Store in app state
                app_handle.manage(AppState {
                    settings_service: Arc::new(settings),
                    http_server: Arc::new(http_server),
                    ws_server: Arc::new(ws_server),
                    config: Arc::new(RwLock::new(config)),
                });

                // 7. Navigate to dashboard
                app_handle.emit_all("navigate", "/login")?;

                Ok::<_, anyhow::Error>(())
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_network_config,
            save_network_config,
            save_broker_credentials,
            is_first_run,
            complete_setup,
            restart_services,
            import_from_env,
            // ... other commands
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

---

## Configuration Validation

```rust
// src-tauri/src/config/validation.rs

pub fn validate_network_config(config: &NetworkConfig) -> Result<(), ValidationError> {
    // Validate ports
    if config.http_port < 1024 {
        return Err(ValidationError::PortTooLow("http_port"));
    }
    if config.websocket_port < 1024 {
        return Err(ValidationError::PortTooLow("websocket_port"));
    }
    if config.http_port == config.websocket_port {
        return Err(ValidationError::PortConflict);
    }

    // Validate URL format
    if !config.host_server.starts_with("http://") && !config.host_server.starts_with("https://") {
        return Err(ValidationError::InvalidUrl("host_server"));
    }

    Ok(())
}

pub fn validate_broker_config(config: &BrokerConfig) -> Result<(), ValidationError> {
    if config.api_key.is_empty() {
        return Err(ValidationError::MissingField("api_key"));
    }
    if config.api_secret.expose_secret().is_empty() {
        return Err(ValidationError::MissingField("api_secret"));
    }

    Ok(())
}
```

---

## Summary

The zero-config architecture ensures:

1. **No .env file required** - All settings stored in encrypted database
2. **First-run wizard** - Guided setup for essential configuration
3. **UI-driven configuration** - All settings accessible through the app
4. **Sensible defaults** - Works out-of-the-box for local development
5. **Migration support** - Import from existing Python installations
6. **Hot-reload** - Most settings can be changed without app restart
7. **Validation** - All configuration validated before saving
8. **Encryption** - Sensitive values (API secrets, passwords) encrypted at rest
