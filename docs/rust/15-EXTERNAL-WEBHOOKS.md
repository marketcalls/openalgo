# OpenAlgo Desktop - External Webhooks & Tunneling

## Overview

This document covers the external webhook integration for receiving trading signals from TradingView, GoCharting, ChartInk, and other platforms. Since the desktop app runs locally, a tunneling solution (ngrok or alternatives) is required for external access.

---

## Supported Platforms

| Platform | Webhook Type | Endpoint |
|----------|-------------|----------|
| TradingView | Alert Webhook | `/api/v1/placeorder`, `/api/v1/placesmartorder` |
| GoCharting | Alert Webhook | `/api/v1/placeorder`, `/api/v1/placesmartorder` |
| ChartInk | Scanner Webhook | `/chartink/webhook/{strategy_id}` |
| Custom Apps | REST API | All `/api/v1/*` endpoints |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      External Webhook Flow                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    External Services (Internet)                         │ │
│  │                                                                          │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │ │
│  │  │ TradingView  │  │ GoCharting   │  │  ChartInk    │  │ Custom App │  │ │
│  │  │   Alerts     │  │   Alerts     │  │  Scanner     │  │            │  │ │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘  │ │
│  │         │                 │                 │                │         │ │
│  └─────────┴─────────────────┴─────────────────┴────────────────┴─────────┘ │
│                              │                                               │
│                              ▼                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    Tunnel Service (ngrok/cloudflared)                   │ │
│  │                                                                          │ │
│  │    https://abc123.ngrok-free.app  →  http://127.0.0.1:5000             │ │
│  │                                                                          │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                              │                                               │
│                              ▼                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    OpenAlgo Desktop (Tauri)                             │ │
│  │                                                                          │ │
│  │  ┌────────────────────────────────────────────────────────────────┐    │ │
│  │  │              Embedded HTTP Server (axum)                        │    │ │
│  │  │                   127.0.0.1:5000                                │    │ │
│  │  │                                                                  │    │ │
│  │  │  /api/v1/placeorder     → Order Service                        │    │ │
│  │  │  /api/v1/placesmartorder → Smart Order Service                 │    │ │
│  │  │  /chartink/webhook/{id}  → ChartInk Handler                    │    │ │
│  │  │                                                                  │    │ │
│  │  └────────────────────────────────────────────────────────────────┘    │ │
│  │                              │                                          │ │
│  │                              ▼                                          │ │
│  │  ┌────────────────────────────────────────────────────────────────┐    │ │
│  │  │                    Broker API                                   │    │ │
│  │  └────────────────────────────────────────────────────────────────┘    │ │
│  │                                                                          │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Tunneling Options

### 1. ngrok (Recommended)

**Pros**:
- Easy setup, widely used
- Free tier available
- Stable tunnels with paid plan

**Cons**:
- Free tier URL changes on restart
- Rate limits on free tier

### 2. Cloudflare Tunnel (cloudflared)

**Pros**:
- Free with Cloudflare account
- Stable URLs
- No rate limits

**Cons**:
- Requires domain on Cloudflare

### 3. Tailscale Funnel

**Pros**:
- Free
- Secure
- Stable URLs

**Cons**:
- Beta feature
- Requires Tailscale setup

### 4. localhost.run

**Pros**:
- No signup required
- SSH-based

**Cons**:
- Limited features

---

## Database Schema

### Tunnel Configuration

```rust
#[derive(sqlx::FromRow, Serialize, Deserialize)]
pub struct TunnelConfig {
    pub id: i64,
    pub provider: String,           // "ngrok", "cloudflared", "tailscale"
    pub auth_token: Option<String>, // Encrypted
    pub domain: Option<String>,     // Custom domain (if available)
    pub auto_start: bool,
    pub enabled: bool,
    pub last_url: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(sqlx::FromRow, Serialize, Deserialize)]
pub struct TunnelSession {
    pub id: i64,
    pub public_url: String,
    pub local_port: u16,
    pub started_at: DateTime<Utc>,
    pub expires_at: Option<DateTime<Utc>>,
    pub status: String,             // "active", "expired", "disconnected"
}
```

---

## Rust Implementation

### Tunnel Manager Trait

```rust
use async_trait::async_trait;

#[async_trait]
pub trait TunnelProvider: Send + Sync {
    /// Start the tunnel
    async fn connect(&mut self, port: u16) -> Result<TunnelInfo, TunnelError>;

    /// Stop the tunnel
    async fn disconnect(&mut self) -> Result<(), TunnelError>;

    /// Get current tunnel URL
    fn get_url(&self) -> Option<&str>;

    /// Check if tunnel is connected
    fn is_connected(&self) -> bool;

    /// Provider name
    fn provider_name(&self) -> &'static str;
}

#[derive(Debug, Clone)]
pub struct TunnelInfo {
    pub public_url: String,
    pub local_port: u16,
    pub provider: String,
    pub expires_at: Option<DateTime<Utc>>,
}
```

### ngrok Provider

```rust
use std::process::{Child, Command, Stdio};
use std::io::{BufRead, BufReader};

pub struct NgrokProvider {
    auth_token: Option<String>,
    process: Option<Child>,
    public_url: Option<String>,
    local_port: u16,
}

impl NgrokProvider {
    pub fn new(auth_token: Option<String>) -> Self {
        Self {
            auth_token,
            process: None,
            public_url: None,
            local_port: 0,
        }
    }

    /// Configure ngrok auth token
    async fn configure_auth(&self) -> Result<(), TunnelError> {
        if let Some(token) = &self.auth_token {
            let status = Command::new("ngrok")
                .args(["config", "add-authtoken", token])
                .status()?;

            if !status.success() {
                return Err(TunnelError::ConfigurationFailed(
                    "Failed to configure ngrok auth token".to_string()
                ));
            }
        }
        Ok(())
    }

    /// Parse ngrok output for public URL
    fn parse_url_from_output(line: &str) -> Option<String> {
        if line.contains("url=") {
            // Parse JSON log format
            if let Ok(log) = serde_json::from_str::<serde_json::Value>(line) {
                if let Some(url) = log.get("url").and_then(|v| v.as_str()) {
                    if url.starts_with("https://") {
                        return Some(url.to_string());
                    }
                }
            }
        }
        None
    }
}

#[async_trait]
impl TunnelProvider for NgrokProvider {
    async fn connect(&mut self, port: u16) -> Result<TunnelInfo, TunnelError> {
        // Kill any existing ngrok process
        self.disconnect().await.ok();

        // Configure auth if available
        self.configure_auth().await?;

        // Start ngrok process
        let mut child = Command::new("ngrok")
            .args([
                "http",
                &port.to_string(),
                "--log", "stdout",
                "--log-format", "json",
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;

        self.local_port = port;

        // Wait for tunnel URL from output
        let stdout = child.stdout.take()
            .ok_or(TunnelError::ProcessError("No stdout".to_string()))?;

        let reader = BufReader::new(stdout);
        let mut public_url = None;

        // Read output lines until we get the URL (with timeout)
        let timeout = tokio::time::timeout(
            std::time::Duration::from_secs(30),
            async {
                for line in reader.lines() {
                    if let Ok(line) = line {
                        if let Some(url) = Self::parse_url_from_output(&line) {
                            return Ok(url);
                        }
                    }
                }
                Err(TunnelError::Timeout)
            }
        ).await??;

        self.public_url = Some(timeout.clone());
        self.process = Some(child);

        tracing::info!(url = %timeout, "ngrok tunnel established");

        Ok(TunnelInfo {
            public_url: timeout,
            local_port: port,
            provider: "ngrok".to_string(),
            expires_at: None,
        })
    }

    async fn disconnect(&mut self) -> Result<(), TunnelError> {
        if let Some(mut process) = self.process.take() {
            process.kill().ok();
            process.wait().ok();
            tracing::info!("ngrok tunnel disconnected");
        }
        self.public_url = None;
        Ok(())
    }

    fn get_url(&self) -> Option<&str> {
        self.public_url.as_deref()
    }

    fn is_connected(&self) -> bool {
        self.process.is_some() && self.public_url.is_some()
    }

    fn provider_name(&self) -> &'static str {
        "ngrok"
    }
}
```

### Cloudflare Tunnel Provider

```rust
pub struct CloudflaredProvider {
    credentials_path: PathBuf,
    tunnel_name: String,
    process: Option<Child>,
    public_url: Option<String>,
}

#[async_trait]
impl TunnelProvider for CloudflaredProvider {
    async fn connect(&mut self, port: u16) -> Result<TunnelInfo, TunnelError> {
        // cloudflared tunnel run --url http://localhost:PORT
        let mut child = Command::new("cloudflared")
            .args([
                "tunnel",
                "--url", &format!("http://localhost:{}", port),
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()?;

        // Parse URL from cloudflared output
        // Format: "Your quick Tunnel has been created! Visit it at: https://xxx.trycloudflare.com"
        let stderr = child.stderr.take().ok_or(TunnelError::ProcessError("No stderr".to_string()))?;
        let reader = BufReader::new(stderr);

        for line in reader.lines() {
            if let Ok(line) = line {
                if line.contains("trycloudflare.com") || line.contains("cloudflare") {
                    // Extract URL from line
                    if let Some(url) = Self::extract_url(&line) {
                        self.public_url = Some(url.clone());
                        self.process = Some(child);

                        tracing::info!(url = %url, "Cloudflare tunnel established");

                        return Ok(TunnelInfo {
                            public_url: url,
                            local_port: port,
                            provider: "cloudflared".to_string(),
                            expires_at: None,
                        });
                    }
                }
            }
        }

        Err(TunnelError::ConnectionFailed("Could not establish tunnel".to_string()))
    }

    async fn disconnect(&mut self) -> Result<(), TunnelError> {
        if let Some(mut process) = self.process.take() {
            process.kill().ok();
            process.wait().ok();
        }
        self.public_url = None;
        Ok(())
    }

    fn get_url(&self) -> Option<&str> {
        self.public_url.as_deref()
    }

    fn is_connected(&self) -> bool {
        self.process.is_some() && self.public_url.is_some()
    }

    fn provider_name(&self) -> &'static str {
        "cloudflared"
    }
}
```

### Tunnel Manager

```rust
pub struct TunnelManager {
    db: SqlitePool,
    provider: Option<Box<dyn TunnelProvider>>,
    config: TunnelConfig,
}

impl TunnelManager {
    /// Start tunnel with configured provider
    pub async fn start(&mut self) -> Result<TunnelInfo, TunnelError> {
        if !self.config.enabled {
            return Err(TunnelError::Disabled);
        }

        // Create provider based on config
        let mut provider: Box<dyn TunnelProvider> = match self.config.provider.as_str() {
            "ngrok" => Box::new(NgrokProvider::new(self.config.auth_token.clone())),
            "cloudflared" => Box::new(CloudflaredProvider::new()?),
            _ => return Err(TunnelError::UnsupportedProvider(self.config.provider.clone())),
        };

        // Get local port from server config
        let port = self.get_server_port().await?;

        // Connect
        let info = provider.connect(port).await?;

        // Save session to database
        self.save_session(&info).await?;

        // Update last URL in config
        self.update_last_url(&info.public_url).await?;

        self.provider = Some(provider);

        // Emit event to frontend
        self.emit_tunnel_status(&info).await;

        Ok(info)
    }

    /// Stop tunnel
    pub async fn stop(&mut self) -> Result<(), TunnelError> {
        if let Some(mut provider) = self.provider.take() {
            provider.disconnect().await?;
            self.update_session_status("disconnected").await?;
        }
        Ok(())
    }

    /// Get current tunnel URL
    pub fn get_url(&self) -> Option<String> {
        self.provider.as_ref()?.get_url().map(|s| s.to_string())
    }

    /// Check tunnel status
    pub fn is_connected(&self) -> bool {
        self.provider.as_ref().map(|p| p.is_connected()).unwrap_or(false)
    }

    /// Get webhook URL for a specific endpoint
    pub fn get_webhook_url(&self, endpoint: &str) -> Option<String> {
        self.get_url().map(|base| format!("{}{}", base, endpoint))
    }
}
```

---

## ChartInk Webhook Handler

ChartInk uses a specific webhook format with strategy-based routing:

```rust
#[derive(Deserialize)]
pub struct ChartInkWebhook {
    pub stocks: String,             // Comma-separated symbols
    pub trigger_prices: String,     // Comma-separated prices
    pub triggered_at: String,       // Time string
    pub scan_name: String,          // BUY, SELL, etc.
    pub scan_url: String,
    pub alert_name: String,
    pub webhook_url: String,
}

/// ChartInk webhook endpoint
pub async fn chartink_webhook(
    Path(strategy_id): Path<String>,
    Json(payload): Json<ChartInkWebhook>,
    state: State<AppState>,
) -> Result<Json<WebhookResponse>, ApiError> {
    tracing::info!(
        strategy_id = %strategy_id,
        scan_name = %payload.scan_name,
        stocks = %payload.stocks,
        "ChartInk webhook received"
    );

    // Get strategy configuration
    let strategy = state.strategy_service
        .get_strategy(&strategy_id)
        .await?
        .ok_or(ApiError::NotFound("Strategy not found".to_string()))?;

    // Parse symbols
    let symbols: Vec<&str> = payload.stocks.split(',').collect();

    // Determine action from scan_name
    let action = match payload.scan_name.to_uppercase().as_str() {
        "BUY" | "LONG" | "ENTRY" => Action::Buy,
        "SELL" | "SHORT" | "EXIT" => Action::Sell,
        _ => {
            tracing::warn!(scan_name = %payload.scan_name, "Unknown scan name, defaulting to BUY");
            Action::Buy
        }
    };

    // Place orders for each symbol
    let mut results = Vec::new();
    for symbol in symbols {
        let symbol = symbol.trim();
        if symbol.is_empty() {
            continue;
        }

        let order = PlaceOrderRequest {
            strategy: strategy.name.clone(),
            symbol: symbol.to_string(),
            exchange: strategy.exchange.clone(),
            action: action.clone(),
            quantity: strategy.quantity,
            pricetype: strategy.price_type.clone(),
            product: strategy.product.clone(),
            ..Default::default()
        };

        match state.order_service.place_order(order, Some(&strategy.api_key), None, None).await {
            Ok(response) => {
                results.push(OrderResult {
                    symbol: symbol.to_string(),
                    status: "success".to_string(),
                    order_id: Some(response.data.orderid),
                    error: None,
                });
            }
            Err(e) => {
                results.push(OrderResult {
                    symbol: symbol.to_string(),
                    status: "error".to_string(),
                    order_id: None,
                    error: Some(e.to_string()),
                });
            }
        }
    }

    Ok(Json(WebhookResponse {
        status: "success".to_string(),
        message: format!("Processed {} symbols", results.len()),
        results,
    }))
}
```

---

## TradingView/GoCharting Webhook Format

```json
{
    "apikey": "your-openalgo-api-key",
    "strategy": "NIFTY-STRATEGY",
    "symbol": "NIFTY24DEC19500CE",
    "exchange": "NFO",
    "action": "{{strategy.order.action}}",
    "quantity": {{strategy.order.contracts}},
    "pricetype": "MARKET",
    "product": "MIS"
}
```

### Webhook Validation

```rust
/// Validate webhook signature (for secure webhooks)
pub fn validate_webhook_signature(
    payload: &[u8],
    signature: &str,
    secret: &str,
) -> bool {
    use hmac::{Hmac, Mac};
    use sha2::Sha256;

    type HmacSha256 = Hmac<Sha256>;

    let mut mac = HmacSha256::new_from_slice(secret.as_bytes())
        .expect("HMAC can take key of any size");
    mac.update(payload);

    let expected = hex::encode(mac.finalize().into_bytes());
    signature == expected
}
```

---

## Tauri Commands

```rust
#[tauri::command]
pub async fn tunnel_start(
    state: State<'_, AppState>,
) -> Result<TunnelInfo, String> {
    let mut tunnel = state.tunnel.lock().await;
    tunnel.start().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn tunnel_stop(
    state: State<'_, AppState>,
) -> Result<(), String> {
    let mut tunnel = state.tunnel.lock().await;
    tunnel.stop().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn tunnel_status(
    state: State<'_, AppState>,
) -> Result<TunnelStatus, String> {
    let tunnel = state.tunnel.lock().await;

    Ok(TunnelStatus {
        connected: tunnel.is_connected(),
        url: tunnel.get_url(),
        provider: tunnel.config.provider.clone(),
    })
}

#[tauri::command]
pub async fn tunnel_configure(
    state: State<'_, AppState>,
    provider: String,
    auth_token: Option<String>,
    auto_start: bool,
) -> Result<(), String> {
    let mut tunnel = state.tunnel.lock().await;

    tunnel.configure(&provider, auth_token.as_deref(), auto_start).await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_webhook_url(
    state: State<'_, AppState>,
    endpoint: String,
) -> Result<Option<String>, String> {
    let tunnel = state.tunnel.lock().await;
    Ok(tunnel.get_webhook_url(&endpoint))
}
```

---

## Frontend Integration

### Tunnel Store

```typescript
// src/lib/stores/tunnel.ts
import { writable } from 'svelte/store';
import { invoke } from '@tauri-apps/api/tauri';

interface TunnelStatus {
    connected: boolean;
    url: string | null;
    provider: string;
}

export const tunnelStatus = writable<TunnelStatus>({
    connected: false,
    url: null,
    provider: 'ngrok'
});

export async function startTunnel() {
    const info = await invoke<TunnelInfo>('tunnel_start');
    tunnelStatus.set({
        connected: true,
        url: info.public_url,
        provider: info.provider
    });
    return info;
}

export async function stopTunnel() {
    await invoke('tunnel_stop');
    tunnelStatus.update(s => ({ ...s, connected: false, url: null }));
}

export async function getTunnelStatus() {
    const status = await invoke<TunnelStatus>('tunnel_status');
    tunnelStatus.set(status);
    return status;
}

export async function getWebhookUrl(endpoint: string): Promise<string | null> {
    return invoke('get_webhook_url', { endpoint });
}
```

### Webhook URL Display Component

```svelte
<script lang="ts">
import { onMount } from 'svelte';
import { tunnelStatus, startTunnel, stopTunnel } from '$lib/stores/tunnel';

let webhookUrls = {
    placeorder: null,
    smartorder: null,
    chartink: null
};

async function updateWebhookUrls() {
    if ($tunnelStatus.url) {
        webhookUrls = {
            placeorder: `${$tunnelStatus.url}/api/v1/placeorder`,
            smartorder: `${$tunnelStatus.url}/api/v1/placesmartorder`,
            chartink: `${$tunnelStatus.url}/chartink/webhook/{strategy_id}`
        };
    }
}

$: if ($tunnelStatus.connected) {
    updateWebhookUrls();
}

function copyToClipboard(text: string) {
    navigator.clipboard.writeText(text);
}
</script>

<div class="webhook-config">
    <h3>Webhook Configuration</h3>

    <div class="tunnel-status">
        <span class="status-dot" class:connected={$tunnelStatus.connected}></span>
        {#if $tunnelStatus.connected}
            <span>Tunnel Active: {$tunnelStatus.url}</span>
            <button on:click={stopTunnel}>Stop Tunnel</button>
        {:else}
            <span>Tunnel Inactive</span>
            <button on:click={startTunnel}>Start Tunnel</button>
        {/if}
    </div>

    {#if $tunnelStatus.connected}
        <div class="webhook-urls">
            <h4>TradingView / GoCharting</h4>
            <div class="url-row">
                <code>{webhookUrls.placeorder}</code>
                <button on:click={() => copyToClipboard(webhookUrls.placeorder)}>Copy</button>
            </div>

            <h4>ChartInk Scanner</h4>
            <div class="url-row">
                <code>{webhookUrls.chartink}</code>
                <button on:click={() => copyToClipboard(webhookUrls.chartink)}>Copy</button>
            </div>
        </div>
    {/if}
</div>
```

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TUNNEL_PROVIDER` | Tunnel provider (ngrok, cloudflared) | ngrok |
| `NGROK_AUTH_TOKEN` | ngrok authentication token | - |
| `TUNNEL_AUTO_START` | Start tunnel on app launch | false |
| `TUNNEL_ENABLED` | Enable tunneling feature | true |

### Database Settings

```sql
INSERT INTO settings (category, key, value, description) VALUES
('tunnel', 'provider', 'ngrok', 'Tunnel provider'),
('tunnel', 'auto_start', 'false', 'Auto-start tunnel on launch'),
('tunnel', 'enabled', 'true', 'Enable tunneling feature');
```

---

## Security Considerations

1. **API Key Validation** - All webhook endpoints validate the OpenAlgo API key
2. **Rate Limiting** - Webhook endpoints have rate limits to prevent abuse
3. **HTTPS Only** - Tunnel providers use HTTPS for secure communication
4. **No Credential Storage** - ngrok auth tokens stored encrypted in database
5. **Tunnel Expiry** - Free tier tunnels expire, requiring reconnection

---

## Conclusion

External webhook integration provides:

1. **TradingView Alerts** - Direct order execution from chart alerts
2. **GoCharting Integration** - Same webhook format as TradingView
3. **ChartInk Scanners** - Automated trading from scanner results
4. **Multiple Tunnel Providers** - ngrok, Cloudflare, Tailscale support
5. **One-Click Setup** - Easy tunnel management from UI
6. **Secure Webhooks** - API key validation on all endpoints
