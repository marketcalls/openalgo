# 21. Monitoring Dashboards

## Overview

OpenAlgo Desktop provides three monitoring dashboards for real-time visibility into system operations:

1. **Analyzer Dashboard** (`/analyzer`) - Strategy request analysis and debugging
2. **Live Logs** (`/logs`) - Real-time API request/response logs
3. **Latency Dashboard** (`/latency`) - Order execution performance metrics

---

## 1. Analyzer Dashboard

### Purpose
The Analyzer Dashboard provides deep analysis of incoming trading requests, helping users debug strategy issues, identify configuration problems, and track order flow.

### Features
- Request/response analysis for all API types
- Error categorization (rate limit, invalid symbol, missing quantity, invalid exchange)
- Source (strategy) tracking
- Date filtering and search
- CSV export
- Real-time stats

### Blueprint: `blueprints/analyzer.py`

### Database Schema

```rust
// src-tauri/src/database/models/analyzer.rs

#[derive(Debug, Clone, Queryable, Insertable)]
#[diesel(table_name = analyzer_logs)]
pub struct AnalyzerLog {
    pub id: i32,
    pub api_type: String,           // placeorder, placesmartorder, cancelorder, etc.
    pub request_data: String,       // JSON request body
    pub response_data: String,      // JSON response body
    pub created_at: NaiveDateTime,
}
```

### Rust Service Implementation

```rust
// src-tauri/src/services/analyzer_service.rs

use chrono::{DateTime, NaiveDateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize)]
pub struct AnalyzerStats {
    pub total_requests: i64,
    pub sources: HashMap<String, i64>,
    pub symbols: Vec<SymbolCount>,
    pub issues: IssueStats,
}

#[derive(Debug, Serialize)]
pub struct IssueStats {
    pub total: i64,
    pub by_type: IssuesByType,
}

#[derive(Debug, Serialize)]
pub struct IssuesByType {
    pub rate_limit: i64,
    pub invalid_symbol: i64,
    pub missing_quantity: i64,
    pub invalid_exchange: i64,
    pub other: i64,
}

#[derive(Debug, Serialize)]
pub struct FormattedRequest {
    pub timestamp: String,
    pub api_type: String,
    pub source: String,
    pub symbol: Option<String>,
    pub exchange: Option<String>,
    pub action: Option<String>,
    pub quantity: Option<String>,
    pub price_type: Option<String>,
    pub product_type: Option<String>,
    pub position_size: Option<String>,
    pub request_data: serde_json::Value,
    pub response_data: serde_json::Value,
    pub analysis: RequestAnalysis,
}

#[derive(Debug, Serialize)]
pub struct RequestAnalysis {
    pub issues: bool,
    pub error: Option<String>,
    pub error_type: String,
    pub warnings: Vec<String>,
}

pub struct AnalyzerService {
    db: DatabaseConnection,
}

impl AnalyzerService {
    /// Log a request for analysis
    pub async fn log_request(
        &self,
        api_type: &str,
        request_data: &serde_json::Value,
        response_data: &serde_json::Value,
    ) -> Result<(), AnalyzerError> {
        sqlx::query!(
            r#"
            INSERT INTO analyzer_logs (api_type, request_data, response_data, created_at)
            VALUES ($1, $2, $3, $4)
            "#,
            api_type,
            serde_json::to_string(request_data)?,
            serde_json::to_string(response_data)?,
            Utc::now().naive_utc()
        )
        .execute(&self.db)
        .await?;

        Ok(())
    }

    /// Get analyzer statistics
    pub async fn get_stats(&self) -> Result<AnalyzerStats, AnalyzerError> {
        let logs = sqlx::query_as!(
            AnalyzerLog,
            "SELECT * FROM analyzer_logs ORDER BY created_at DESC LIMIT 1000"
        )
        .fetch_all(&self.db)
        .await?;

        let mut total_requests = 0i64;
        let mut sources: HashMap<String, i64> = HashMap::new();
        let mut symbols: HashMap<String, i64> = HashMap::new();
        let mut issues = IssueStats {
            total: 0,
            by_type: IssuesByType {
                rate_limit: 0,
                invalid_symbol: 0,
                missing_quantity: 0,
                invalid_exchange: 0,
                other: 0,
            },
        };

        for log in &logs {
            total_requests += 1;

            let request: serde_json::Value = serde_json::from_str(&log.request_data)?;
            let response: serde_json::Value = serde_json::from_str(&log.response_data)?;

            // Track sources (strategies)
            if let Some(strategy) = request.get("strategy").and_then(|s| s.as_str()) {
                *sources.entry(strategy.to_string()).or_insert(0) += 1;
            }

            // Track symbols
            if let Some(symbol) = request.get("symbol").and_then(|s| s.as_str()) {
                *symbols.entry(symbol.to_string()).or_insert(0) += 1;
            }

            // Track errors
            if response.get("status").and_then(|s| s.as_str()) == Some("error") {
                issues.total += 1;

                if let Some(message) = response.get("message").and_then(|m| m.as_str()) {
                    let msg_lower = message.to_lowercase();
                    if msg_lower.contains("rate limit") {
                        issues.by_type.rate_limit += 1;
                    } else if msg_lower.contains("symbol") || msg_lower.contains("not found") {
                        issues.by_type.invalid_symbol += 1;
                    } else if msg_lower.contains("quantity") {
                        issues.by_type.missing_quantity += 1;
                    } else if msg_lower.contains("exchange") {
                        issues.by_type.invalid_exchange += 1;
                    } else {
                        issues.by_type.other += 1;
                    }
                }
            }
        }

        // Convert symbols to sorted vec
        let mut symbol_counts: Vec<SymbolCount> = symbols
            .into_iter()
            .map(|(symbol, count)| SymbolCount { symbol, count })
            .collect();
        symbol_counts.sort_by(|a, b| b.count.cmp(&a.count));

        Ok(AnalyzerStats {
            total_requests,
            sources,
            symbols: symbol_counts.into_iter().take(10).collect(),
            issues,
        })
    }

    /// Get filtered requests
    pub async fn get_filtered_requests(
        &self,
        start_date: Option<NaiveDate>,
        end_date: Option<NaiveDate>,
    ) -> Result<Vec<FormattedRequest>, AnalyzerError> {
        let ist = chrono_tz::Asia::Kolkata;
        let today = Utc::now().with_timezone(&ist).date_naive();

        let start = start_date.unwrap_or(today);
        let end = end_date.unwrap_or(today);

        let logs = sqlx::query_as!(
            AnalyzerLog,
            r#"
            SELECT * FROM analyzer_logs
            WHERE DATE(created_at) >= $1 AND DATE(created_at) <= $2
            ORDER BY created_at DESC
            "#,
            start,
            end
        )
        .fetch_all(&self.db)
        .await?;

        let mut requests = Vec::new();
        for log in logs {
            if let Some(formatted) = self.format_request(&log, &ist)? {
                requests.push(formatted);
            }
        }

        Ok(requests)
    }

    /// Clear old analyzer logs (older than 24 hours)
    pub async fn clear_old_logs(&self) -> Result<i64, AnalyzerError> {
        let cutoff = Utc::now().naive_utc() - chrono::Duration::hours(24);

        let result = sqlx::query!(
            "DELETE FROM analyzer_logs WHERE created_at < $1",
            cutoff
        )
        .execute(&self.db)
        .await?;

        Ok(result.rows_affected() as i64)
    }

    /// Export logs to CSV
    pub fn export_to_csv(&self, requests: &[FormattedRequest]) -> Result<String, AnalyzerError> {
        let mut wtr = csv::Writer::from_writer(vec![]);

        // Write headers
        wtr.write_record(&[
            "Timestamp", "API Type", "Source", "Symbol", "Exchange", "Action",
            "Quantity", "Price Type", "Product Type", "Status", "Error Message"
        ])?;

        // Write data
        for req in requests {
            wtr.write_record(&[
                &req.timestamp,
                &req.api_type,
                &req.source,
                req.symbol.as_deref().unwrap_or(""),
                req.exchange.as_deref().unwrap_or(""),
                req.action.as_deref().unwrap_or(""),
                req.quantity.as_deref().unwrap_or(""),
                req.price_type.as_deref().unwrap_or(""),
                req.product_type.as_deref().unwrap_or(""),
                if req.analysis.issues { "Error" } else { "Success" },
                req.analysis.error.as_deref().unwrap_or(""),
            ])?;
        }

        Ok(String::from_utf8(wtr.into_inner()?)?)
    }
}
```

### Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/analyzer` | GET | Render analyzer dashboard |
| `/analyzer/stats` | GET | Get analyzer statistics (JSON) |
| `/analyzer/requests` | GET | Get recent requests (JSON) |
| `/analyzer/clear` | GET | Clear logs older than 24 hours |
| `/analyzer/export` | GET | Export to CSV |

---

## 2. Live Logs (API Logs)

### Purpose
Live Logs provide real-time visibility into all API requests and responses, enabling users to track order flow, debug issues, and audit trading activity.

### Features
- Real-time API request/response logging
- Date filtering
- Full-text search across request/response data
- Pagination (20 per page)
- CSV export
- API key sanitization (never shown in logs)

### Blueprint: `blueprints/log.py`

### Database Schema

```rust
// src-tauri/src/database/models/api_log.rs

#[derive(Debug, Clone, Queryable, Insertable)]
#[diesel(table_name = order_logs)]
pub struct OrderLog {
    pub id: i32,
    pub api_type: String,           // placeorder, placesmartorder, quotes, etc.
    pub request_data: String,       // JSON request (apikey sanitized)
    pub response_data: String,      // JSON response
    pub created_at: NaiveDateTime,
}
```

### Rust Service Implementation

```rust
// src-tauri/src/services/log_service.rs

pub struct LogService {
    db: DatabaseConnection,
}

#[derive(Debug, Serialize)]
pub struct FormattedLog {
    pub id: i32,
    pub api_type: String,
    pub request_data: serde_json::Value,
    pub response_data: serde_json::Value,
    pub strategy: String,
    pub created_at: String,
}

impl LogService {
    /// Log an API request (with API key sanitization)
    pub async fn log_request(
        &self,
        api_type: &str,
        request_data: &serde_json::Value,
        response_data: &serde_json::Value,
    ) -> Result<(), LogError> {
        // Sanitize request - remove apikey
        let mut sanitized = request_data.clone();
        if let Some(obj) = sanitized.as_object_mut() {
            obj.remove("apikey");
        }

        sqlx::query!(
            r#"
            INSERT INTO order_logs (api_type, request_data, response_data, created_at)
            VALUES ($1, $2, $3, $4)
            "#,
            api_type,
            serde_json::to_string(&sanitized)?,
            serde_json::to_string(response_data)?,
            Utc::now().naive_utc()
        )
        .execute(&self.db)
        .await?;

        Ok(())
    }

    /// Get filtered logs with pagination
    pub async fn get_filtered_logs(
        &self,
        start_date: Option<NaiveDate>,
        end_date: Option<NaiveDate>,
        search_query: Option<&str>,
        page: Option<i32>,
        per_page: Option<i32>,
    ) -> Result<(Vec<FormattedLog>, i32, i64), LogError> {
        let ist = chrono_tz::Asia::Kolkata;
        let today = Utc::now().with_timezone(&ist).date_naive();

        let start = start_date.unwrap_or(today);
        let end = end_date.unwrap_or(today);

        // Build query
        let mut query = "SELECT * FROM order_logs WHERE DATE(created_at) >= $1 AND DATE(created_at) <= $2".to_string();
        let mut params: Vec<Box<dyn sqlx::Encode<'_, _>>> = vec![Box::new(start), Box::new(end)];

        if let Some(search) = search_query {
            if !search.is_empty() {
                query += " AND (api_type LIKE $3 OR request_data LIKE $3 OR response_data LIKE $3)";
                params.push(Box::new(format!("%{}%", search)));
            }
        }

        // Get total count
        let count_query = format!("SELECT COUNT(*) as count FROM ({}) as subq", query);
        let total: i64 = sqlx::query_scalar(&count_query)
            .fetch_one(&self.db)
            .await?;

        // Apply pagination
        query += " ORDER BY created_at DESC";
        if let (Some(p), Some(pp)) = (page, per_page) {
            let offset = (p - 1) * pp;
            query += &format!(" LIMIT {} OFFSET {}", pp, offset);
        }

        let total_pages = if let Some(pp) = per_page {
            ((total as i32) + pp - 1) / pp
        } else {
            1
        };

        // Execute query
        let logs = sqlx::query_as::<_, OrderLog>(&query)
            .fetch_all(&self.db)
            .await?;

        let formatted: Vec<FormattedLog> = logs
            .into_iter()
            .filter_map(|log| self.format_log(&log, &ist).ok())
            .collect();

        Ok((formatted, total_pages, total))
    }

    /// Export logs to CSV
    pub fn export_to_csv(&self, logs: &[FormattedLog]) -> Result<String, LogError> {
        let mut wtr = csv::Writer::from_writer(vec![]);

        wtr.write_record(&[
            "ID", "Timestamp", "API Type", "Strategy", "Exchange", "Symbol",
            "Action", "Product", "Price Type", "Quantity", "Position Size",
            "Price", "Trigger Price", "Disclosed Quantity", "Order ID", "Response"
        ])?;

        for log in logs {
            let req = &log.request_data;
            wtr.write_record(&[
                &log.id.to_string(),
                &log.created_at,
                &log.api_type,
                &log.strategy,
                req.get("exchange").and_then(|v| v.as_str()).unwrap_or(""),
                req.get("symbol").and_then(|v| v.as_str()).unwrap_or(""),
                req.get("action").and_then(|v| v.as_str()).unwrap_or(""),
                req.get("product").and_then(|v| v.as_str()).unwrap_or(""),
                req.get("pricetype").and_then(|v| v.as_str()).unwrap_or(""),
                req.get("quantity").and_then(|v| v.as_str()).unwrap_or(""),
                req.get("position_size").and_then(|v| v.as_str()).unwrap_or(""),
                req.get("price").and_then(|v| v.as_str()).unwrap_or(""),
                req.get("trigger_price").and_then(|v| v.as_str()).unwrap_or(""),
                req.get("disclosed_quantity").and_then(|v| v.as_str()).unwrap_or(""),
                req.get("orderid").and_then(|v| v.as_str()).unwrap_or(""),
                &serde_json::to_string(&log.response_data).unwrap_or_default(),
            ])?;
        }

        Ok(String::from_utf8(wtr.into_inner()?)?)
    }
}
```

### Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/logs` | GET | Render logs page (supports AJAX pagination) |
| `/logs/export` | GET | Export filtered logs to CSV |

---

## 3. Latency Dashboard

### Purpose
The Latency Dashboard provides detailed performance metrics for order execution, helping users understand and optimize their trading latency.

### Features
- Real-time latency tracking
- Per-broker statistics
- RTT histogram visualization
- Percentile calculations (p50, p90, p95, p99)
- SLA tracking (% under 100ms, 150ms, 200ms)
- Order success/failure rates
- CSV export

### Blueprint: `blueprints/latency.py`

### Database Schema

```rust
// src-tauri/src/database/models/latency.rs

#[derive(Debug, Clone, Queryable, Insertable)]
#[diesel(table_name = order_latency)]
pub struct OrderLatency {
    pub id: i32,
    pub timestamp: NaiveDateTime,
    pub order_id: String,
    pub user_id: Option<i32>,
    pub broker: Option<String>,
    pub symbol: Option<String>,
    pub order_type: Option<String>,      // MARKET, LIMIT, etc.

    // Round-trip time (comparable to Postman/Bruno)
    pub rtt_ms: Option<f64>,

    // Processing overhead breakdown
    pub validation_latency_ms: Option<f64>,  // Pre-request processing
    pub response_latency_ms: Option<f64>,    // Post-response processing
    pub overhead_ms: Option<f64>,            // Total overhead

    // Total time including overhead
    pub total_latency_ms: f64,

    // Request details
    pub request_body: Option<String>,    // JSON
    pub response_body: Option<String>,   // JSON
    pub status: Option<String>,          // SUCCESS, FAILED, PARTIAL
    pub error: Option<String>,
}
```

### Rust Service Implementation

```rust
// src-tauri/src/services/latency_service.rs

use std::collections::HashMap;

#[derive(Debug, Serialize)]
pub struct LatencyStats {
    pub total_orders: i64,
    pub failed_orders: i64,
    pub success_rate: f64,
    pub avg_rtt: f64,
    pub avg_overhead: f64,
    pub avg_total: f64,
    pub p50_total: f64,
    pub p90_total: f64,
    pub p95_total: f64,
    pub p99_total: f64,
    pub sla_100ms: f64,
    pub sla_150ms: f64,
    pub sla_200ms: f64,
    pub broker_stats: HashMap<String, BrokerLatencyStats>,
    pub broker_histograms: HashMap<String, HistogramData>,
}

#[derive(Debug, Serialize)]
pub struct BrokerLatencyStats {
    pub total_orders: i64,
    pub failed_orders: i64,
    pub avg_rtt: f64,
    pub avg_overhead: f64,
    pub avg_total: f64,
    pub p50_total: f64,
    pub p99_total: f64,
    pub sla_150ms: f64,
}

#[derive(Debug, Serialize)]
pub struct HistogramData {
    pub bins: Vec<String>,
    pub counts: Vec<i64>,
    pub avg_rtt: f64,
    pub min_rtt: f64,
    pub max_rtt: f64,
}

pub struct LatencyService {
    db: DatabaseConnection,
}

impl LatencyService {
    /// Log order execution latency
    pub async fn log_latency(
        &self,
        order_id: &str,
        user_id: Option<i32>,
        broker: Option<&str>,
        symbol: Option<&str>,
        order_type: Option<&str>,
        latencies: &LatencyMeasurements,
        request_body: Option<&serde_json::Value>,
        response_body: Option<&serde_json::Value>,
        status: &str,
        error: Option<&str>,
    ) -> Result<(), LatencyError> {
        sqlx::query!(
            r#"
            INSERT INTO order_latency (
                order_id, user_id, broker, symbol, order_type,
                rtt_ms, validation_latency_ms, response_latency_ms,
                overhead_ms, total_latency_ms,
                request_body, response_body, status, error, timestamp
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            "#,
            order_id,
            user_id,
            broker,
            symbol,
            order_type,
            latencies.rtt,
            latencies.validation,
            latencies.broker_response,
            latencies.overhead,
            latencies.total,
            request_body.map(|v| serde_json::to_string(v).ok()).flatten(),
            response_body.map(|v| serde_json::to_string(v).ok()).flatten(),
            status,
            error,
            Utc::now().naive_utc()
        )
        .execute(&self.db)
        .await?;

        Ok(())
    }

    /// Get latency statistics (optimized with single queries)
    pub async fn get_stats(&self) -> Result<LatencyStats, LatencyError> {
        // Single query for overall stats using CASE statements
        let overall = sqlx::query!(
            r#"
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed,
                AVG(rtt_ms) as avg_rtt,
                AVG(overhead_ms) as avg_overhead,
                AVG(total_latency_ms) as avg_total,
                SUM(CASE WHEN total_latency_ms < 100 THEN 1 ELSE 0 END) as under_100,
                SUM(CASE WHEN total_latency_ms < 150 THEN 1 ELSE 0 END) as under_150,
                SUM(CASE WHEN total_latency_ms < 200 THEN 1 ELSE 0 END) as under_200
            FROM order_latency
            "#
        )
        .fetch_one(&self.db)
        .await?;

        let total = overall.total.unwrap_or(0);
        let failed = overall.failed.unwrap_or(0);

        // Calculate percentiles
        let latencies: Vec<f64> = sqlx::query_scalar!(
            "SELECT total_latency_ms FROM order_latency WHERE total_latency_ms IS NOT NULL"
        )
        .fetch_all(&self.db)
        .await?
        .into_iter()
        .flatten()
        .collect();

        let (p50, p90, p95, p99) = if !latencies.is_empty() {
            let mut sorted = latencies.clone();
            sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
            (
                percentile(&sorted, 50.0),
                percentile(&sorted, 90.0),
                percentile(&sorted, 95.0),
                percentile(&sorted, 99.0),
            )
        } else {
            (0.0, 0.0, 0.0, 0.0)
        };

        // Get broker stats with GROUP BY
        let broker_rows = sqlx::query!(
            r#"
            SELECT
                broker,
                COUNT(*) as total,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) as failed,
                AVG(rtt_ms) as avg_rtt,
                AVG(overhead_ms) as avg_overhead,
                AVG(total_latency_ms) as avg_total,
                SUM(CASE WHEN total_latency_ms < 150 THEN 1 ELSE 0 END) as under_150
            FROM order_latency
            WHERE broker IS NOT NULL
            GROUP BY broker
            "#
        )
        .fetch_all(&self.db)
        .await?;

        let mut broker_stats = HashMap::new();
        let mut broker_histograms = HashMap::new();

        for row in broker_rows {
            if let Some(broker) = &row.broker {
                let broker_total = row.total.unwrap_or(0);

                // Get percentiles for this broker
                let broker_latencies: Vec<f64> = sqlx::query_scalar!(
                    "SELECT total_latency_ms FROM order_latency WHERE broker = $1 AND total_latency_ms IS NOT NULL",
                    broker
                )
                .fetch_all(&self.db)
                .await?
                .into_iter()
                .flatten()
                .collect();

                let (broker_p50, broker_p99) = if !broker_latencies.is_empty() {
                    let mut sorted = broker_latencies.clone();
                    sorted.sort_by(|a, b| a.partial_cmp(b).unwrap());
                    (percentile(&sorted, 50.0), percentile(&sorted, 99.0))
                } else {
                    (0.0, 0.0)
                };

                broker_stats.insert(broker.clone(), BrokerLatencyStats {
                    total_orders: broker_total,
                    failed_orders: row.failed.unwrap_or(0),
                    avg_rtt: row.avg_rtt.unwrap_or(0.0),
                    avg_overhead: row.avg_overhead.unwrap_or(0.0),
                    avg_total: row.avg_total.unwrap_or(0.0),
                    p50_total: broker_p50,
                    p99_total: broker_p99,
                    sla_150ms: if broker_total > 0 {
                        (row.under_150.unwrap_or(0) as f64 / broker_total as f64) * 100.0
                    } else {
                        0.0
                    },
                });

                // Generate histogram for this broker
                broker_histograms.insert(
                    broker.clone(),
                    self.get_histogram_data(Some(broker)).await?,
                );
            }
        }

        Ok(LatencyStats {
            total_orders: total,
            failed_orders: failed,
            success_rate: if total > 0 {
                ((total - failed) as f64 / total as f64) * 100.0
            } else {
                0.0
            },
            avg_rtt: overall.avg_rtt.unwrap_or(0.0),
            avg_overhead: overall.avg_overhead.unwrap_or(0.0),
            avg_total: overall.avg_total.unwrap_or(0.0),
            p50_total: p50,
            p90_total: p90,
            p95_total: p95,
            p99_total: p99,
            sla_100ms: if total > 0 {
                (overall.under_100.unwrap_or(0) as f64 / total as f64) * 100.0
            } else {
                0.0
            },
            sla_150ms: if total > 0 {
                (overall.under_150.unwrap_or(0) as f64 / total as f64) * 100.0
            } else {
                0.0
            },
            sla_200ms: if total > 0 {
                (overall.under_200.unwrap_or(0) as f64 / total as f64) * 100.0
            } else {
                0.0
            },
            broker_stats,
            broker_histograms,
        })
    }

    /// Get histogram data for RTT distribution
    pub async fn get_histogram_data(
        &self,
        broker: Option<&str>,
    ) -> Result<HistogramData, LatencyError> {
        let rtts: Vec<f64> = if let Some(b) = broker {
            sqlx::query_scalar!(
                "SELECT rtt_ms FROM order_latency WHERE broker = $1 AND rtt_ms IS NOT NULL",
                b
            )
            .fetch_all(&self.db)
            .await?
        } else {
            sqlx::query_scalar!(
                "SELECT rtt_ms FROM order_latency WHERE rtt_ms IS NOT NULL"
            )
            .fetch_all(&self.db)
            .await?
        }
        .into_iter()
        .flatten()
        .collect();

        if rtts.is_empty() {
            return Ok(HistogramData {
                bins: vec![],
                counts: vec![],
                avg_rtt: 0.0,
                min_rtt: 0.0,
                max_rtt: 0.0,
            });
        }

        let min_rtt = rtts.iter().cloned().fold(f64::INFINITY, f64::min);
        let max_rtt = rtts.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let avg_rtt = rtts.iter().sum::<f64>() / rtts.len() as f64;

        // Create histogram with 30 bins
        let bin_count = 30;
        let bin_width = (max_rtt - min_rtt) / bin_count as f64;

        let mut counts = vec![0i64; bin_count];
        let mut bins = Vec::with_capacity(bin_count);

        for i in 0..bin_count {
            let bin_start = min_rtt + (i as f64 * bin_width);
            bins.push(format!("{:.1}", bin_start));
        }

        for rtt in &rtts {
            let bin_idx = ((rtt - min_rtt) / bin_width).floor() as usize;
            let bin_idx = bin_idx.min(bin_count - 1);
            counts[bin_idx] += 1;
        }

        Ok(HistogramData {
            bins,
            counts,
            avg_rtt,
            min_rtt,
            max_rtt,
        })
    }

    /// Purge old non-order logs
    pub async fn purge_old_logs(&self, days: i64) -> Result<i64, LatencyError> {
        let cutoff = Utc::now().naive_utc() - chrono::Duration::days(days);
        let order_types = vec!["PLACE", "SMART", "MODIFY", "CANCEL", "CLOSE", "CANCEL_ALL", "BASKET", "SPLIT", "OPTIONS", "OPTIONS_MULTI"];

        let result = sqlx::query!(
            "DELETE FROM order_latency WHERE timestamp < $1 AND order_type NOT IN ($2)",
            cutoff,
            order_types.join(",")
        )
        .execute(&self.db)
        .await?;

        Ok(result.rows_affected() as i64)
    }
}

fn percentile(sorted_data: &[f64], p: f64) -> f64 {
    if sorted_data.is_empty() {
        return 0.0;
    }
    let idx = (p / 100.0 * (sorted_data.len() - 1) as f64).round() as usize;
    sorted_data[idx.min(sorted_data.len() - 1)]
}
```

### Routes

| Route | Method | Description |
|-------|--------|-------------|
| `/latency` | GET | Render latency dashboard |
| `/latency/api/logs` | GET | Get recent logs (JSON) |
| `/latency/api/stats` | GET | Get latency statistics (JSON) |
| `/latency/api/broker/{broker}/stats` | GET | Get broker-specific stats |
| `/latency/export` | GET | Export to CSV |

---

## 4. UI Components

### Analyzer Dashboard UI

```svelte
<!-- src/routes/analyzer/+page.svelte -->
<script lang="ts">
  import { invoke } from '@tauri-apps/api/tauri';
  import { onMount } from 'svelte';

  let stats = null;
  let requests = [];
  let startDate = '';
  let endDate = '';
  let loading = true;

  onMount(async () => {
    await loadData();
  });

  async function loadData() {
    loading = true;
    [stats, requests] = await Promise.all([
      invoke('get_analyzer_stats'),
      invoke('get_analyzer_requests', { startDate, endDate }),
    ]);
    loading = false;
  }

  async function exportCsv() {
    const csv = await invoke('export_analyzer_csv', { startDate, endDate });
    downloadCsv(csv, 'analyzer_logs.csv');
  }

  async function clearLogs() {
    await invoke('clear_analyzer_logs');
    await loadData();
  }
</script>

<div class="analyzer-dashboard">
  <h1>Analyzer Dashboard</h1>

  <!-- Stats Cards -->
  <div class="stats-grid">
    <div class="stat-card">
      <h3>Total Requests</h3>
      <p class="stat-value">{stats?.total_requests ?? 0}</p>
    </div>
    <div class="stat-card">
      <h3>Issues Found</h3>
      <p class="stat-value error">{stats?.issues?.total ?? 0}</p>
    </div>
    <div class="stat-card">
      <h3>Active Strategies</h3>
      <p class="stat-value">{Object.keys(stats?.sources ?? {}).length}</p>
    </div>
  </div>

  <!-- Issue Breakdown -->
  {#if stats?.issues?.total > 0}
    <div class="issues-breakdown">
      <h3>Issue Types</h3>
      <div class="issue-bars">
        {#each Object.entries(stats.issues.by_type) as [type, count]}
          {#if count > 0}
            <div class="issue-bar">
              <span class="label">{type.replace('_', ' ')}</span>
              <div class="bar" style="width: {(count / stats.issues.total) * 100}%"></div>
              <span class="count">{count}</span>
            </div>
          {/if}
        {/each}
      </div>
    </div>
  {/if}

  <!-- Filters -->
  <div class="filters">
    <input type="date" bind:value={startDate} on:change={loadData} />
    <input type="date" bind:value={endDate} on:change={loadData} />
    <button on:click={exportCsv}>Export CSV</button>
    <button on:click={clearLogs} class="danger">Clear Old Logs</button>
  </div>

  <!-- Request Log Table -->
  <table class="log-table">
    <thead>
      <tr>
        <th>Time</th>
        <th>API Type</th>
        <th>Strategy</th>
        <th>Symbol</th>
        <th>Action</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody>
      {#each requests as req}
        <tr class:error={req.analysis.issues}>
          <td>{req.timestamp}</td>
          <td>{req.api_type}</td>
          <td>{req.source}</td>
          <td>{req.symbol ?? '-'}</td>
          <td>{req.action ?? '-'}</td>
          <td>
            {#if req.analysis.issues}
              <span class="badge error">{req.analysis.error}</span>
            {:else}
              <span class="badge success">Success</span>
            {/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
```

### Latency Dashboard UI

```svelte
<!-- src/routes/latency/+page.svelte -->
<script lang="ts">
  import { invoke } from '@tauri-apps/api/tauri';
  import { onMount } from 'svelte';
  import { Chart } from 'chart.js/auto';

  let stats = null;
  let logs = [];
  let selectedBroker = null;
  let histogramChart = null;

  onMount(async () => {
    stats = await invoke('get_latency_stats');
    logs = await invoke('get_latency_logs', { limit: 100 });
    renderHistogram();
  });

  function renderHistogram() {
    const broker = selectedBroker || Object.keys(stats.broker_histograms)[0];
    const data = stats.broker_histograms[broker];

    if (!data) return;

    const ctx = document.getElementById('histogram-chart');
    if (histogramChart) histogramChart.destroy();

    histogramChart = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: data.bins,
        datasets: [{
          label: 'RTT Distribution (ms)',
          data: data.counts,
          backgroundColor: 'rgba(59, 130, 246, 0.8)',
        }]
      },
      options: {
        responsive: true,
        scales: {
          y: { beginAtZero: true }
        }
      }
    });
  }
</script>

<div class="latency-dashboard">
  <h1>Latency Dashboard</h1>

  <!-- Overall Stats -->
  <div class="stats-grid">
    <div class="stat-card">
      <h3>Total Orders</h3>
      <p class="stat-value">{stats?.total_orders ?? 0}</p>
    </div>
    <div class="stat-card">
      <h3>Success Rate</h3>
      <p class="stat-value">{stats?.success_rate?.toFixed(1) ?? 0}%</p>
    </div>
    <div class="stat-card">
      <h3>Avg RTT</h3>
      <p class="stat-value">{stats?.avg_rtt?.toFixed(1) ?? 0} ms</p>
    </div>
    <div class="stat-card">
      <h3>P99 Latency</h3>
      <p class="stat-value">{stats?.p99_total?.toFixed(1) ?? 0} ms</p>
    </div>
  </div>

  <!-- SLA Metrics -->
  <div class="sla-metrics">
    <h3>SLA Compliance</h3>
    <div class="sla-bars">
      <div class="sla-bar">
        <span>&lt;100ms</span>
        <div class="progress" style="width: {stats?.sla_100ms ?? 0}%"></div>
        <span>{stats?.sla_100ms?.toFixed(1) ?? 0}%</span>
      </div>
      <div class="sla-bar">
        <span>&lt;150ms</span>
        <div class="progress" style="width: {stats?.sla_150ms ?? 0}%"></div>
        <span>{stats?.sla_150ms?.toFixed(1) ?? 0}%</span>
      </div>
      <div class="sla-bar">
        <span>&lt;200ms</span>
        <div class="progress" style="width: {stats?.sla_200ms ?? 0}%"></div>
        <span>{stats?.sla_200ms?.toFixed(1) ?? 0}%</span>
      </div>
    </div>
  </div>

  <!-- Broker Selection -->
  <div class="broker-select">
    <label>Select Broker:</label>
    <select bind:value={selectedBroker} on:change={renderHistogram}>
      {#each Object.keys(stats?.broker_stats ?? {}) as broker}
        <option value={broker}>{broker}</option>
      {/each}
    </select>
  </div>

  <!-- Histogram Chart -->
  <div class="chart-container">
    <canvas id="histogram-chart"></canvas>
  </div>

  <!-- Recent Logs Table -->
  <table class="log-table">
    <thead>
      <tr>
        <th>Time (IST)</th>
        <th>Broker</th>
        <th>Order ID</th>
        <th>Symbol</th>
        <th>RTT (ms)</th>
        <th>Total (ms)</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody>
      {#each logs as log}
        <tr class:error={log.status === 'FAILED'}>
          <td>{log.timestamp}</td>
          <td>{log.broker}</td>
          <td>{log.order_id}</td>
          <td>{log.symbol}</td>
          <td>{log.rtt_ms?.toFixed(2)}</td>
          <td>{log.total_latency_ms?.toFixed(2)}</td>
          <td>
            <span class="badge" class:success={log.status === 'SUCCESS'} class:error={log.status === 'FAILED'}>
              {log.status}
            </span>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
```

---

## 5. Tauri Commands

```rust
// src-tauri/src/commands/monitoring.rs

// Analyzer Commands
#[tauri::command]
pub async fn get_analyzer_stats(state: State<'_, AppState>) -> Result<AnalyzerStats, String> {
    state.analyzer_service.get_stats().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_analyzer_requests(
    start_date: Option<String>,
    end_date: Option<String>,
    state: State<'_, AppState>,
) -> Result<Vec<FormattedRequest>, String> {
    let start = start_date.map(|s| NaiveDate::parse_from_str(&s, "%Y-%m-%d").ok()).flatten();
    let end = end_date.map(|s| NaiveDate::parse_from_str(&s, "%Y-%m-%d").ok()).flatten();
    state.analyzer_service.get_filtered_requests(start, end).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn clear_analyzer_logs(state: State<'_, AppState>) -> Result<i64, String> {
    state.analyzer_service.clear_old_logs().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn export_analyzer_csv(
    start_date: Option<String>,
    end_date: Option<String>,
    state: State<'_, AppState>,
) -> Result<String, String> {
    let start = start_date.map(|s| NaiveDate::parse_from_str(&s, "%Y-%m-%d").ok()).flatten();
    let end = end_date.map(|s| NaiveDate::parse_from_str(&s, "%Y-%m-%d").ok()).flatten();
    let requests = state.analyzer_service.get_filtered_requests(start, end).await.map_err(|e| e.to_string())?;
    state.analyzer_service.export_to_csv(&requests).map_err(|e| e.to_string())
}

// Latency Commands
#[tauri::command]
pub async fn get_latency_stats(state: State<'_, AppState>) -> Result<LatencyStats, String> {
    state.latency_service.get_stats().await.map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn get_latency_logs(
    limit: Option<i32>,
    state: State<'_, AppState>,
) -> Result<Vec<OrderLatency>, String> {
    state.latency_service.get_recent_logs(limit.unwrap_or(100)).await.map_err(|e| e.to_string())
}

// Log Commands
#[tauri::command]
pub async fn get_api_logs(
    start_date: Option<String>,
    end_date: Option<String>,
    search: Option<String>,
    page: Option<i32>,
    state: State<'_, AppState>,
) -> Result<(Vec<FormattedLog>, i32, i64), String> {
    let start = start_date.map(|s| NaiveDate::parse_from_str(&s, "%Y-%m-%d").ok()).flatten();
    let end = end_date.map(|s| NaiveDate::parse_from_str(&s, "%Y-%m-%d").ok()).flatten();
    state.log_service.get_filtered_logs(start, end, search.as_deref(), page, Some(20))
        .await
        .map_err(|e| e.to_string())
}
```

---

## 6. Summary

The monitoring dashboards provide:

1. **Analyzer Dashboard**: Strategy debugging, error analysis, request tracking
2. **Live Logs**: Real-time API logging with search and export
3. **Latency Dashboard**: Performance metrics, SLA tracking, per-broker stats

All three use separate SQLite databases for isolation:
- `db/openalgo.db` - Main database
- `db/logs.db` - Traffic/security logs
- `db/latency.db` - Order latency logs
