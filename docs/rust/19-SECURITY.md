# 19. Security Architecture

## Overview

OpenAlgo Desktop implements defense-in-depth security with multiple layers of protection. This document covers all security mechanisms that must be implemented in the Rust version, matching or exceeding the Python implementation's security posture.

---

## 1. Authentication & Authorization

### 1.1 User Authentication

**Password Hashing**: Argon2id (winner of Password Hashing Competition)

```rust
// src-tauri/src/security/password.rs

use argon2::{
    password_hash::{PasswordHash, PasswordHasher, PasswordVerifier, SaltString},
    Argon2, Params,
};
use rand::rngs::OsRng;

pub struct PasswordService {
    pepper: String,
    argon2: Argon2<'static>,
}

impl PasswordService {
    pub fn new(pepper: String) -> Self {
        // Argon2id parameters (memory-hard to prevent GPU attacks)
        let params = Params::new(
            65536,   // 64 MB memory
            3,       // 3 iterations
            4,       // 4 parallel threads
            None,    // Default output length
        ).expect("Invalid Argon2 params");

        Self {
            pepper,
            argon2: Argon2::new(
                argon2::Algorithm::Argon2id,
                argon2::Version::V0x13,
                params,
            ),
        }
    }

    pub fn hash_password(&self, password: &str) -> Result<String, SecurityError> {
        // Add pepper to password
        let peppered = format!("{}{}", password, self.pepper);

        // Generate random salt
        let salt = SaltString::generate(&mut OsRng);

        // Hash with Argon2id
        let hash = self.argon2
            .hash_password(peppered.as_bytes(), &salt)
            .map_err(|e| SecurityError::HashingFailed(e.to_string()))?;

        Ok(hash.to_string())
    }

    pub fn verify_password(&self, password: &str, hash: &str) -> Result<bool, SecurityError> {
        let peppered = format!("{}{}", password, self.pepper);
        let parsed_hash = PasswordHash::new(hash)
            .map_err(|e| SecurityError::InvalidHash(e.to_string()))?;

        Ok(self.argon2
            .verify_password(peppered.as_bytes(), &parsed_hash)
            .is_ok())
    }
}
```

### 1.2 API Key Authentication

**API Key Format**: 32-character hex string (128 bits of entropy)

```rust
// src-tauri/src/security/api_key.rs

use rand::Rng;
use sha2::{Sha256, Digest};

pub struct ApiKeyService {
    password_service: PasswordService,
    fernet: Fernet,
    verified_cache: TTLCache<String, String>,
    invalid_cache: TTLCache<String, bool>,
}

impl ApiKeyService {
    /// Generate a new API key
    pub fn generate_api_key() -> String {
        let mut rng = rand::thread_rng();
        (0..32).map(|_| format!("{:02x}", rng.gen::<u8>())).collect()
    }

    /// Store API key (hashed for verification, encrypted for retrieval)
    pub async fn store_api_key(&self, user_id: &str, api_key: &str) -> Result<(), SecurityError> {
        // Hash with Argon2 + pepper for verification
        let hash = self.password_service.hash_password(api_key)?;

        // Encrypt for retrieval (webhook payload generation)
        let encrypted = self.fernet.encrypt(api_key.as_bytes());

        // Store both in database
        sqlx::query!(
            r#"
            INSERT INTO api_keys (user_id, api_key_hash, api_key_encrypted, created_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET api_key_hash = $2, api_key_encrypted = $3, created_at = NOW()
            "#,
            user_id,
            hash,
            encrypted
        )
        .execute(&self.db)
        .await?;

        // Invalidate caches on key change
        self.invalidate_caches(user_id);

        Ok(())
    }

    /// Verify API key with caching
    pub async fn verify_api_key(&self, api_key: &str) -> Result<Option<String>, SecurityError> {
        // Generate cache key (SHA256 of API key - never store plaintext)
        let cache_key = hex::encode(Sha256::digest(api_key.as_bytes()));

        // Check invalid cache first (fast rejection)
        if self.invalid_cache.contains_key(&cache_key) {
            return Ok(None);
        }

        // Check valid cache
        if let Some(user_id) = self.verified_cache.get(&cache_key) {
            return Ok(Some(user_id.clone()));
        }

        // Cache miss - expensive Argon2 verification
        let api_keys = sqlx::query!("SELECT user_id, api_key_hash FROM api_keys")
            .fetch_all(&self.db)
            .await?;

        for record in api_keys {
            if self.password_service.verify_password(api_key, &record.api_key_hash)? {
                // Cache valid result
                self.verified_cache.insert(cache_key, record.user_id.clone());
                return Ok(Some(record.user_id));
            }
        }

        // Cache invalid result (shorter TTL to prevent cache poisoning)
        self.invalid_cache.insert(cache_key, true);

        Ok(None)
    }
}
```

### 1.3 Session Management

```rust
// src-tauri/src/security/session.rs

use chrono::{DateTime, NaiveTime, Utc, TimeZone};
use chrono_tz::Asia::Kolkata;

pub struct SessionService {
    expiry_time: NaiveTime,  // Default: 03:00 IST
    secret_key: String,
}

impl SessionService {
    /// Check if session is expired
    pub fn is_session_expired(&self, session_created_at: DateTime<Utc>) -> bool {
        let now_ist = Utc::now().with_timezone(&Kolkata);
        let session_ist = session_created_at.with_timezone(&Kolkata);

        // Check if we've passed today's expiry time since session creation
        let today_expiry = now_ist.date_naive().and_time(self.expiry_time);

        if session_ist.naive_local() < today_expiry && now_ist.naive_local() >= today_expiry {
            return true;
        }

        false
    }

    /// Create session token
    pub fn create_session(&self, user_id: &str, broker: &str) -> Result<String, SecurityError> {
        let claims = SessionClaims {
            user_id: user_id.to_string(),
            broker: broker.to_string(),
            created_at: Utc::now(),
            exp: self.calculate_expiry(),
        };

        // Sign with HMAC-SHA256
        let token = jsonwebtoken::encode(
            &jsonwebtoken::Header::default(),
            &claims,
            &jsonwebtoken::EncodingKey::from_secret(self.secret_key.as_bytes()),
        )?;

        Ok(token)
    }
}
```

---

## 2. Encryption

### 2.1 Data at Rest

**Auth Tokens**: Encrypted with Fernet (AES-128-CBC + HMAC-SHA256)

```rust
// src-tauri/src/security/encryption.rs

use fernet::Fernet;
use pbkdf2::pbkdf2_hmac;
use sha2::Sha256;
use base64::{Engine as _, engine::general_purpose::URL_SAFE};

pub struct EncryptionService {
    fernet: Fernet,
}

impl EncryptionService {
    pub fn new(pepper: &str) -> Result<Self, SecurityError> {
        // Derive Fernet key from pepper using PBKDF2
        let salt = b"openalgo_static_salt";
        let mut key = [0u8; 32];

        pbkdf2_hmac::<Sha256>(
            pepper.as_bytes(),
            salt,
            100_000,  // 100k iterations
            &mut key,
        );

        let fernet_key = URL_SAFE.encode(key);
        let fernet = Fernet::new(&fernet_key)
            .ok_or(SecurityError::InvalidKey)?;

        Ok(Self { fernet })
    }

    pub fn encrypt(&self, plaintext: &str) -> String {
        self.fernet.encrypt(plaintext.as_bytes())
    }

    pub fn decrypt(&self, ciphertext: &str) -> Result<String, SecurityError> {
        let decrypted = self.fernet.decrypt(ciphertext)
            .map_err(|_| SecurityError::DecryptionFailed)?;

        String::from_utf8(decrypted)
            .map_err(|_| SecurityError::InvalidUtf8)
    }
}
```

### 2.2 Database Encryption (SQLCipher)

```rust
// src-tauri/src/database/connection.rs

use sqlx::sqlite::{SqliteConnectOptions, SqlitePoolOptions};

pub async fn create_encrypted_pool(
    db_path: &str,
    encryption_key: &str,
) -> Result<SqlitePool, DatabaseError> {
    let options = SqliteConnectOptions::new()
        .filename(db_path)
        .pragma("key", encryption_key)       // SQLCipher encryption key
        .pragma("cipher_page_size", "4096")
        .pragma("kdf_iter", "256000")        // PBKDF2 iterations
        .pragma("cipher_memory_security", "ON")
        .create_if_missing(true);

    SqlitePoolOptions::new()
        .max_connections(5)
        .connect_with(options)
        .await
        .map_err(|e| DatabaseError::ConnectionFailed(e.to_string()))
}
```

---

## 3. Rate Limiting

### 3.1 Rate Limiter Implementation

```rust
// src-tauri/src/security/rate_limiter.rs

use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;
use std::time::{Duration, Instant};

/// Moving window rate limiter
pub struct RateLimiter {
    limits: HashMap<String, RateLimit>,
    windows: Arc<RwLock<HashMap<String, SlidingWindow>>>,
}

#[derive(Clone)]
pub struct RateLimit {
    pub requests: u32,
    pub window: Duration,
}

struct SlidingWindow {
    timestamps: Vec<Instant>,
}

impl RateLimiter {
    pub fn new() -> Self {
        let mut limits = HashMap::new();

        // Configure rate limits per endpoint category
        limits.insert("login".to_string(), RateLimit {
            requests: 5,
            window: Duration::from_secs(60),  // 5 per minute
        });
        limits.insert("api".to_string(), RateLimit {
            requests: 50,
            window: Duration::from_secs(1),   // 50 per second
        });
        limits.insert("order".to_string(), RateLimit {
            requests: 10,
            window: Duration::from_secs(1),   // 10 per second
        });
        limits.insert("smart_order".to_string(), RateLimit {
            requests: 2,
            window: Duration::from_secs(1),   // 2 per second
        });
        limits.insert("webhook".to_string(), RateLimit {
            requests: 100,
            window: Duration::from_secs(60),  // 100 per minute
        });

        Self {
            limits,
            windows: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Check if request is allowed
    pub async fn check(&self, key: &str, limit_type: &str) -> Result<bool, RateLimitError> {
        let limit = self.limits.get(limit_type)
            .ok_or(RateLimitError::UnknownLimitType)?;

        let composite_key = format!("{}:{}", limit_type, key);
        let now = Instant::now();

        let mut windows = self.windows.write().await;
        let window = windows.entry(composite_key).or_insert(SlidingWindow {
            timestamps: Vec::new(),
        });

        // Remove expired timestamps
        window.timestamps.retain(|t| now.duration_since(*t) < limit.window);

        // Check if under limit
        if window.timestamps.len() < limit.requests as usize {
            window.timestamps.push(now);
            Ok(true)
        } else {
            Ok(false)
        }
    }
}
```

### 3.2 Rate Limit Configuration

| Endpoint Category | Limit | Window |
|-------------------|-------|--------|
| Login | 5 requests | 1 minute |
| Login | 25 requests | 1 hour |
| Password Reset | 15 requests | 1 hour |
| API (general) | 50 requests | 1 second |
| Order Placement | 10 requests | 1 second |
| Smart Order | 2 requests | 1 second |
| Webhook | 100 requests | 1 minute |
| Strategy Mgmt | 200 requests | 1 minute |

---

## 4. IP Security

### 4.1 IP Ban System

```rust
// src-tauri/src/security/ip_security.rs

use chrono::{DateTime, Duration, Utc};
use std::net::IpAddr;

pub struct IpSecurityService {
    db: DatabaseConnection,
    settings: SecuritySettings,
}

#[derive(Debug, Clone)]
pub struct IpBan {
    pub ip_address: IpAddr,
    pub reason: String,
    pub ban_count: i32,
    pub banned_at: DateTime<Utc>,
    pub expires_at: Option<DateTime<Utc>>,
    pub is_permanent: bool,
    pub created_by: String,
}

impl IpSecurityService {
    /// Check if IP is banned
    pub async fn is_banned(&self, ip: IpAddr) -> Result<bool, SecurityError> {
        // Never ban localhost
        if ip.is_loopback() {
            return Ok(false);
        }

        let ban = sqlx::query_as!(
            IpBan,
            "SELECT * FROM ip_bans WHERE ip_address = $1",
            ip.to_string()
        )
        .fetch_optional(&self.db)
        .await?;

        match ban {
            Some(b) if b.is_permanent => Ok(true),
            Some(b) => {
                if let Some(expires) = b.expires_at {
                    if Utc::now() < expires {
                        Ok(true)
                    } else {
                        // Ban expired, remove it
                        self.unban(ip).await?;
                        Ok(false)
                    }
                } else {
                    Ok(false)
                }
            }
            None => Ok(false),
        }
    }

    /// Ban an IP address
    pub async fn ban(
        &self,
        ip: IpAddr,
        reason: &str,
        duration_hours: Option<i64>,
        created_by: &str,
    ) -> Result<(), SecurityError> {
        // Never ban localhost
        if ip.is_loopback() {
            tracing::warn!("Attempted to ban localhost IP: {}", ip);
            return Ok(());
        }

        let expires_at = duration_hours.map(|h| Utc::now() + Duration::hours(h));
        let is_permanent = duration_hours.is_none();

        // Check for repeat offender
        let existing = sqlx::query!(
            "SELECT ban_count FROM ip_bans WHERE ip_address = $1",
            ip.to_string()
        )
        .fetch_optional(&self.db)
        .await?;

        let ban_count = existing.map(|r| r.ban_count + 1).unwrap_or(1);

        // Auto-permanent ban after configured number of offenses
        let (is_permanent, expires_at) = if ban_count >= self.settings.repeat_offender_limit {
            tracing::warn!(
                "IP {} permanently banned after {} offenses",
                ip, ban_count
            );
            (true, None)
        } else {
            (is_permanent, expires_at)
        };

        sqlx::query!(
            r#"
            INSERT INTO ip_bans (ip_address, ban_reason, ban_count, banned_at, expires_at, is_permanent, created_by)
            VALUES ($1, $2, $3, NOW(), $4, $5, $6)
            ON CONFLICT (ip_address) DO UPDATE
            SET ban_reason = $2, ban_count = $3, banned_at = NOW(), expires_at = $4, is_permanent = $5
            "#,
            ip.to_string(),
            reason,
            ban_count,
            expires_at,
            is_permanent,
            created_by
        )
        .execute(&self.db)
        .await?;

        tracing::info!("IP {} banned: {}", ip, reason);
        Ok(())
    }
}
```

### 4.2 Threat Detection

**404 Error Tracking** (Bot Detection):

```rust
// src-tauri/src/security/threat_detection.rs

pub struct ThreatDetector {
    db: DatabaseConnection,
    settings: SecuritySettings,
}

impl ThreatDetector {
    /// Track 404 errors for bot detection
    pub async fn track_404(&self, ip: IpAddr, path: &str) -> Result<(), SecurityError> {
        if self.ip_security.is_banned(ip).await? {
            return Ok(());
        }

        let now = Utc::now();

        // Get or create tracker
        let tracker = sqlx::query!(
            "SELECT id, error_count, first_error_at, paths_attempted FROM error_404_tracker WHERE ip_address = $1",
            ip.to_string()
        )
        .fetch_optional(&self.db)
        .await?;

        match tracker {
            Some(t) => {
                // Check if tracking period expired (24 hours)
                if now.signed_duration_since(t.first_error_at).num_days() >= 1 {
                    // Reset counter
                    sqlx::query!(
                        "UPDATE error_404_tracker SET error_count = 1, first_error_at = $1, paths_attempted = $2 WHERE id = $3",
                        now,
                        serde_json::to_string(&vec![path])?,
                        t.id
                    )
                    .execute(&self.db)
                    .await?;
                } else {
                    // Increment counter
                    let mut paths: Vec<String> = serde_json::from_str(&t.paths_attempted)?;
                    if !paths.contains(&path.to_string()) {
                        paths.push(path.to_string());
                        // Keep last 50 paths
                        if paths.len() > 50 {
                            paths = paths[paths.len()-50..].to_vec();
                        }
                    }

                    let new_count = t.error_count + 1;

                    sqlx::query!(
                        "UPDATE error_404_tracker SET error_count = $1, last_error_at = $2, paths_attempted = $3 WHERE id = $4",
                        new_count,
                        now,
                        serde_json::to_string(&paths)?,
                        t.id
                    )
                    .execute(&self.db)
                    .await?;

                    // Alert if threshold reached (manual ban via dashboard)
                    if new_count >= self.settings.threshold_404 {
                        tracing::warn!(
                            "IP {} exceeded 404 threshold: {} errors",
                            ip, new_count
                        );
                    }
                }
            }
            None => {
                // Create new tracker
                sqlx::query!(
                    "INSERT INTO error_404_tracker (ip_address, error_count, first_error_at, last_error_at, paths_attempted) VALUES ($1, 1, $2, $2, $3)",
                    ip.to_string(),
                    now,
                    serde_json::to_string(&vec![path])?
                )
                .execute(&self.db)
                .await?;
            }
        }

        Ok(())
    }

    /// Track invalid API key attempts
    pub async fn track_invalid_api_key(&self, ip: IpAddr, api_key_hash: &str) -> Result<(), SecurityError> {
        // Similar implementation to track_404
        // Tracks attempts per IP with 24-hour rolling window
        // Alerts when threshold reached
        // ...
    }
}
```

---

## 5. CSRF Protection

```rust
// src-tauri/src/security/csrf.rs

use rand::Rng;
use sha2::{Sha256, Digest};

pub struct CsrfService {
    secret: String,
    time_limit: Option<i64>,  // Seconds, None = session lifetime
}

impl CsrfService {
    pub fn generate_token(&self, session_id: &str) -> String {
        let timestamp = chrono::Utc::now().timestamp();
        let random: [u8; 16] = rand::thread_rng().gen();

        let data = format!(
            "{}:{}:{}:{}",
            session_id,
            timestamp,
            hex::encode(random),
            self.secret
        );

        let hash = Sha256::digest(data.as_bytes());
        format!("{}:{}", timestamp, hex::encode(hash))
    }

    pub fn verify_token(&self, token: &str, session_id: &str) -> bool {
        let parts: Vec<&str> = token.split(':').collect();
        if parts.len() != 2 {
            return false;
        }

        let timestamp: i64 = match parts[0].parse() {
            Ok(t) => t,
            Err(_) => return false,
        };

        // Check time limit if configured
        if let Some(limit) = self.time_limit {
            let now = chrono::Utc::now().timestamp();
            if now - timestamp > limit {
                return false;
            }
        }

        // Regenerate token and compare
        let expected = self.generate_token_with_timestamp(session_id, timestamp);
        constant_time_compare(token, &expected)
    }
}
```

---

## 6. CORS Configuration

```rust
// src-tauri/src/security/cors.rs

use tower_http::cors::{CorsLayer, Any};

pub fn configure_cors(settings: &CorsSettings) -> CorsLayer {
    let mut cors = CorsLayer::new();

    // Allowed origins
    if settings.allowed_origins.contains(&"*".to_string()) {
        cors = cors.allow_origin(Any);
    } else {
        cors = cors.allow_origin(
            settings.allowed_origins
                .iter()
                .filter_map(|o| o.parse().ok())
                .collect::<Vec<_>>()
        );
    }

    // Allowed methods
    cors = cors.allow_methods(
        settings.allowed_methods
            .iter()
            .filter_map(|m| m.parse().ok())
            .collect::<Vec<_>>()
    );

    // Allowed headers
    cors = cors.allow_headers(
        settings.allowed_headers
            .iter()
            .filter_map(|h| h.parse().ok())
            .collect::<Vec<_>>()
    );

    // Credentials
    if settings.allow_credentials {
        cors = cors.allow_credentials(true);
    }

    // Max age
    cors = cors.max_age(Duration::from_secs(settings.max_age));

    cors
}
```

---

## 7. Content Security Policy

```rust
// src-tauri/src/security/csp.rs

pub fn build_csp_header(settings: &CspSettings) -> String {
    let mut directives = vec![];

    if !settings.default_src.is_empty() {
        directives.push(format!("default-src {}", settings.default_src));
    }
    if !settings.script_src.is_empty() {
        directives.push(format!("script-src {}", settings.script_src));
    }
    if !settings.style_src.is_empty() {
        directives.push(format!("style-src {}", settings.style_src));
    }
    if !settings.img_src.is_empty() {
        directives.push(format!("img-src {}", settings.img_src));
    }
    if !settings.connect_src.is_empty() {
        directives.push(format!("connect-src {}", settings.connect_src));
    }
    if !settings.font_src.is_empty() {
        directives.push(format!("font-src {}", settings.font_src));
    }
    if !settings.object_src.is_empty() {
        directives.push(format!("object-src {}", settings.object_src));
    }
    if !settings.frame_ancestors.is_empty() {
        directives.push(format!("frame-ancestors {}", settings.frame_ancestors));
    }
    if settings.upgrade_insecure_requests {
        directives.push("upgrade-insecure-requests".to_string());
    }

    directives.join("; ")
}
```

---

## 8. Broker Auth Token Security

```rust
// src-tauri/src/security/broker_auth.rs

pub struct BrokerAuthService {
    encryption: EncryptionService,
    db: DatabaseConnection,
}

impl BrokerAuthService {
    /// Store broker auth token (encrypted)
    pub async fn store_auth_token(
        &self,
        user_id: &str,
        auth_token: &str,
        feed_token: Option<&str>,
        broker: &str,
    ) -> Result<(), SecurityError> {
        let encrypted_auth = self.encryption.encrypt(auth_token);
        let encrypted_feed = feed_token.map(|t| self.encryption.encrypt(t));

        sqlx::query!(
            r#"
            INSERT INTO auth (name, auth, feed_token, broker, is_revoked)
            VALUES ($1, $2, $3, $4, false)
            ON CONFLICT (name) DO UPDATE
            SET auth = $2, feed_token = $3, broker = $4, is_revoked = false
            "#,
            user_id,
            encrypted_auth,
            encrypted_feed,
            broker
        )
        .execute(&self.db)
        .await?;

        Ok(())
    }

    /// Revoke broker auth (logout)
    pub async fn revoke_auth(&self, user_id: &str) -> Result<(), SecurityError> {
        sqlx::query!(
            "UPDATE auth SET is_revoked = true WHERE name = $1",
            user_id
        )
        .execute(&self.db)
        .await?;

        // Clear from cache
        self.clear_auth_cache(user_id);

        Ok(())
    }

    /// Get decrypted auth token (with revocation check)
    pub async fn get_auth_token(&self, user_id: &str) -> Result<Option<String>, SecurityError> {
        let auth = sqlx::query!(
            "SELECT auth, is_revoked FROM auth WHERE name = $1",
            user_id
        )
        .fetch_optional(&self.db)
        .await?;

        match auth {
            Some(a) if !a.is_revoked => {
                Ok(Some(self.encryption.decrypt(&a.auth)?))
            }
            _ => Ok(None),
        }
    }
}
```

---

## 9. Security Settings Schema

```rust
// src-tauri/src/config/security.rs

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SecuritySettings {
    // IP Ban thresholds
    pub threshold_404: i32,           // Default: 20 per day
    pub ban_duration_404: i32,        // Default: 24 hours
    pub threshold_api: i32,           // Default: 10 per day
    pub ban_duration_api: i32,        // Default: 48 hours
    pub repeat_offender_limit: i32,   // Default: 3 (then permanent)

    // Session
    pub session_expiry_time: String,  // Default: "03:00" IST

    // CSRF
    pub csrf_enabled: bool,           // Default: true
    pub csrf_time_limit: Option<i64>, // None = session lifetime

    // CORS
    pub cors_enabled: bool,
    pub cors_allowed_origins: Vec<String>,
    pub cors_allowed_methods: Vec<String>,
    pub cors_allowed_headers: Vec<String>,
    pub cors_allow_credentials: bool,
    pub cors_max_age: u64,

    // CSP
    pub csp_enabled: bool,
    pub csp_report_only: bool,
    pub csp_directives: CspDirectives,
}

impl Default for SecuritySettings {
    fn default() -> Self {
        Self {
            threshold_404: 20,
            ban_duration_404: 24,
            threshold_api: 10,
            ban_duration_api: 48,
            repeat_offender_limit: 3,
            session_expiry_time: "03:00".to_string(),
            csrf_enabled: true,
            csrf_time_limit: None,
            cors_enabled: true,
            cors_allowed_origins: vec!["http://127.0.0.1:5000".to_string()],
            cors_allowed_methods: vec!["GET".to_string(), "POST".to_string()],
            cors_allowed_headers: vec!["Content-Type".to_string(), "Authorization".to_string()],
            cors_allow_credentials: false,
            cors_max_age: 86400,
            csp_enabled: true,
            csp_report_only: false,
            csp_directives: CspDirectives::default(),
        }
    }
}
```

---

## 10. Security Dashboard

The Rust app includes a security dashboard for monitoring and management:

### Features

1. **Banned IPs List**
   - View all current bans (permanent/temporary)
   - Manual ban/unban functionality
   - Ban count tracking

2. **Suspicious Activity**
   - 404 error tracking per IP
   - Invalid API key attempts
   - Paths attempted

3. **Security Settings**
   - Configurable thresholds
   - Ban duration settings
   - Repeat offender limits

### UI Implementation

```svelte
<!-- src/routes/security/+page.svelte -->
<script lang="ts">
  import { invoke } from '@tauri-apps/api/tauri';
  import { onMount } from 'svelte';

  let bannedIps = [];
  let suspiciousIps = [];
  let apiAbuseIps = [];
  let settings = {};

  onMount(async () => {
    [bannedIps, suspiciousIps, apiAbuseIps, settings] = await Promise.all([
      invoke('get_banned_ips'),
      invoke('get_suspicious_ips'),
      invoke('get_api_abuse_ips'),
      invoke('get_security_settings'),
    ]);
  });

  async function banIp(ip: string, reason: string, permanent: boolean) {
    await invoke('ban_ip', { ip, reason, permanent });
    bannedIps = await invoke('get_banned_ips');
  }

  async function unbanIp(ip: string) {
    await invoke('unban_ip', { ip });
    bannedIps = await invoke('get_banned_ips');
  }

  async function updateSettings() {
    await invoke('update_security_settings', { settings });
  }
</script>

<div class="security-dashboard">
  <h1>Security Dashboard</h1>

  <!-- Banned IPs Section -->
  <section>
    <h2>Banned IPs ({bannedIps.length})</h2>
    <table>
      <thead>
        <tr>
          <th>IP Address</th>
          <th>Reason</th>
          <th>Ban Count</th>
          <th>Expires</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {#each bannedIps as ban}
          <tr>
            <td>{ban.ip_address}</td>
            <td>{ban.ban_reason}</td>
            <td>{ban.ban_count}</td>
            <td>{ban.is_permanent ? 'Permanent' : ban.expires_at}</td>
            <td>
              <button on:click={() => unbanIp(ban.ip_address)}>Unban</button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </section>

  <!-- Suspicious Activity Section -->
  <section>
    <h2>Suspicious 404 Activity</h2>
    <!-- Similar table for 404 tracking -->
  </section>

  <!-- Settings Section -->
  <section>
    <h2>Security Settings</h2>
    <form on:submit|preventDefault={updateSettings}>
      <label>
        404 Threshold (per day)
        <input type="number" bind:value={settings.threshold_404} />
      </label>
      <label>
        404 Ban Duration (hours)
        <input type="number" bind:value={settings.ban_duration_404} />
      </label>
      <!-- More settings -->
      <button type="submit">Save Settings</button>
    </form>
  </section>
</div>
```

---

## 11. Security Middleware Stack

```rust
// src-tauri/src/api/middleware.rs

use axum::{
    middleware::{self, Next},
    http::{Request, Response},
    body::Body,
};

pub fn security_middleware_stack() -> tower::ServiceBuilder<...> {
    tower::ServiceBuilder::new()
        // 1. IP Ban Check (first - reject banned IPs immediately)
        .layer(middleware::from_fn(ip_ban_middleware))

        // 2. Rate Limiting
        .layer(middleware::from_fn(rate_limit_middleware))

        // 3. CORS
        .layer(configure_cors(&settings.cors))

        // 4. CSRF Verification (for state-changing requests)
        .layer(middleware::from_fn(csrf_middleware))

        // 5. API Key Authentication
        .layer(middleware::from_fn(api_key_auth_middleware))

        // 6. Request Logging
        .layer(middleware::from_fn(request_logging_middleware))

        // 7. CSP Headers
        .layer(middleware::from_fn(csp_header_middleware))
}

async fn ip_ban_middleware<B>(
    State(state): State<AppState>,
    ConnectInfo(addr): ConnectInfo<SocketAddr>,
    request: Request<B>,
    next: Next<B>,
) -> Response<Body> {
    if state.ip_security.is_banned(addr.ip()).await.unwrap_or(false) {
        return Response::builder()
            .status(403)
            .body(Body::from("Forbidden: IP banned"))
            .unwrap();
    }

    next.run(request).await
}
```

---

## 12. Security Audit Checklist

### Authentication
- [ ] Passwords hashed with Argon2id + pepper
- [ ] API keys hashed with Argon2id + pepper
- [ ] Session tokens signed with HMAC-SHA256
- [ ] Session expiry enforced daily at configured time

### Encryption
- [ ] Auth tokens encrypted with Fernet (AES-128-CBC)
- [ ] Database encrypted with SQLCipher
- [ ] API secrets never logged
- [ ] Pepper stored securely (not in code)

### Rate Limiting
- [ ] All endpoints rate-limited
- [ ] Moving window algorithm
- [ ] Per-IP tracking
- [ ] Different limits per endpoint type

### IP Security
- [ ] IP ban system functional
- [ ] 404 tracking for bot detection
- [ ] Invalid API key tracking
- [ ] Repeat offender escalation
- [ ] Localhost never banned

### Input Validation
- [ ] All API inputs validated
- [ ] SQL injection prevented (parameterized queries)
- [ ] XSS prevented (output encoding)
- [ ] Path traversal prevented

### Headers
- [ ] CORS properly configured
- [ ] CSP headers set
- [ ] X-Frame-Options set
- [ ] X-Content-Type-Options set
- [ ] Strict-Transport-Security (if HTTPS)
