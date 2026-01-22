# 02 - Why Build with OpenAlgo?

*"Why should I use OpenAlgo when I can just build my strategy directly on top of the broker's SDK or API?"*

It's a common question. Many start with broker SDKs because it feels quick—just wire your signals and send orders. But soon, the pain points show up:

- How do you monitor trades in real-time?
- Where do you store and replay logs?
- How do you test webhooks or strategies before going live?
- How do you manage symbols, expiries, and contracts across brokers?
- What happens when you want to switch from Broker A to Broker B?

That's when you realize the SDK is not enough.

**OpenAlgo takes care of the heavy lifting.**

It's not just an API wrapper—it's a **full-stack, open-source trading automation framework** designed to host strategies, manage brokers, and scale securely.

---

## What Makes OpenAlgo Different?

### Strategy Management & Hosting

Host your **Python strategies directly inside OpenAlgo**, alongside strategies from TradingView, Amibroker, ChartInk, MetaTrader, Excel, or custom webhooks. Start, pause, schedule, monitor, and analyze—all from a central control plane.

| Capability | Description |
|------------|-------------|
| **Python Strategy Hosting** | Upload and run Python scripts with scheduling |
| **Flow Visual Builder** | Create strategies without code using drag-and-drop |
| **Multi-Platform Support** | TradingView, Amibroker, ChartInk, Excel, and more |
| **Centralized Control** | Manage all strategies from one dashboard |

### Sandbox Testing & API Analyzer

The **Analyzer Mode** works like a local sandbox—test your signals, APIs, and strategies with ₹1 Crore sandbox capital without hitting real broker servers. Validate everything before going live.

| Feature | Benefit |
|---------|---------|
| **Sandbox Capital** | ₹1 Crore to test freely |
| **Real Market Prices** | Realistic simulation with live data |
| **Margin Calculations** | Actual margin requirements enforced |
| **Position Tracking** | Full position and holdings management |
| **Zero Risk** | Complete isolation from live trading |

### Historical Data & Backtesting

**Historify** lets you download and store historical market data locally using DuckDB. Use this data for backtesting, analysis, or feeding into your strategy development workflow.

| Capability | Description |
|------------|-------------|
| **Bulk Downloads** | Download years of OHLCV data |
| **DuckDB Storage** | Efficient columnar storage |
| **Multiple Timeframes** | 1-minute to daily data |
| **Export Options** | CSV, JSON, or direct query |

### Multi-Broker, Multi-Platform

OpenAlgo supports **24+ Indian brokers** via a **unified API and WebSocket layer**. Write your strategy once, and run it across Zerodha, Angel One, Dhan, Upstox, Fyers, Flattrade, Firstock, and more—without rewriting code.

```
┌─────────────────────────────────────────────────────────────────┐
│                     Your Strategy Code                          │
│                    (Write Once)                                 │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   OpenAlgo Unified API                          │
│              (Common Interface for All Brokers)                 │
└───┬─────────┬─────────┬─────────┬─────────┬─────────┬──────────┘
    │         │         │         │         │         │
    ▼         ▼         ▼         ▼         ▼         ▼
┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐
│Zerodha│ │ Angel │ │  Dhan │ │ Fyers │ │Upstox │ │ More  │
└───────┘ └───────┘ └───────┘ └───────┘ └───────┘ └───────┘
```

### Unified Symbol & Contract Management

With OpenAlgo's **Common Symbol Format**, you don't have to worry about broker-specific quirks. Contracts, expiries, and lot sizes are maintained automatically.

| Broker | Their Format | OpenAlgo Format |
|--------|--------------|-----------------|
| Zerodha | `SBIN` | `SBIN` |
| Angel | `SBIN-EQ` | `SBIN` |
| Dhan | `SBIN` | `SBIN` |

**One symbol format. All brokers.**

---

## Speed, Stability, and Control

### Performance Optimizations

| Feature | Impact |
|---------|--------|
| **HTTPX Connection Pooling** | 50ms–120ms latency vs 150ms–250ms in plain scripts |
| **WebSocket Broadcast Layer** | One broker stream powers multiple strategies |
| **Symbol Caching** | Instant symbol lookups without repeated API calls |
| **Rate Limit Management** | Automatic throttling to stay within broker limits |

### Real-Time Monitoring

| Tool | Purpose |
|------|---------|
| **Latency Monitor** | Track order round-trip times |
| **Traffic Logs** | Complete API request/response history |
| **P&L Tracker** | Real-time profit/loss visualization |
| **WebSocket Dashboard** | Monitor live data connections |

### Notification & Alerts

| Channel | Capabilities |
|---------|--------------|
| **Telegram Bot** | Trade notifications, commands, alerts |
| **WebSocket Updates** | Real-time order and position changes |
| **Dashboard Alerts** | Visual notifications in UI |

---

## Security by Default

OpenAlgo is production-tested with enterprise-grade security:

| Security Feature | Description |
|------------------|-------------|
| **CORS & CSP Headers** | Cross-origin and content security policies |
| **CSRF Protection** | Token-based request validation |
| **Rate Limiting** | Per-endpoint request throttling |
| **Two-Factor Auth** | TOTP-based login security |
| **Session Management** | Secure session handling with timeouts |
| **Audit Trails** | Complete logging for compliance |
| **API Key Encryption** | Secure storage with pepper-based hashing |
| **Subprocess Isolation** | Sandboxed execution for hosted strategies |

Deploy locally, in **Docker**, or on cloud servers—secure out of the box.

---

## SDKs, Add-ins, and Ecosystem

### Official SDKs

| Language | Package |
|----------|---------|
| **Python** | `openalgo` on PyPI |
| **Node.js** | REST API integration |
| **Go** | REST API integration |

### Platform Integrations

| Platform | Integration Type |
|----------|------------------|
| **TradingView** | Webhooks |
| **Amibroker** | HTTP calls from AFL |
| **ChartInk** | Scanner webhooks |
| **Excel** | VBA with REST API |
| **Google Sheets** | Apps Script |
| **MetaTrader 5** | EA integration |

### Deployment Options

| Option | Best For |
|--------|----------|
| **Local** | Personal desktop trading |
| **Docker** | Clean, reproducible deployments |
| **Cloud Server** | 24/7 automated trading |
| **VPS** | Low-latency remote access |

---

## Why Not Just Use Broker APIs Directly?

With direct broker APIs, you'd have to build:

| Component | What You'd Build | OpenAlgo Provides |
|-----------|------------------|-------------------|
| **Strategy Hosting** | Process management, scheduling | Built-in with Python hosting |
| **Testing Environment** | Sandbox, mock broker | Analyzer Mode with ₹1 Cr capital |
| **Symbol Management** | Expiry handling, contract mapping | Unified symbol format |
| **Connection Pooling** | HTTP/WebSocket optimization | HTTPX with connection reuse |
| **Trade Dashboard** | React UI, real-time updates | Full React frontend included |
| **Log Storage** | Database, query interface | SQLite with traffic logs |
| **Latency Tracking** | Timing, metrics, alerts | Latency monitor built-in |
| **Multi-Broker Support** | N broker integrations | 24+ brokers pre-integrated |
| **Security Layer** | Auth, rate limiting, CSRF | Enterprise security included |
| **Notifications** | Telegram, alerts | Telegram bot integrated |

OpenAlgo ships with all this—**pre-wired, tested, and open source**.

---

## Open Source Freedom

Licensed under **AGPL**, OpenAlgo gives you:

| Freedom | Description |
|---------|-------------|
| **Full Source Code** | Inspect, modify, extend |
| **Self-Hosting** | Run on your infrastructure |
| **No Per-Order Fees** | Zero transaction costs |
| **No Vendor Lock-in** | Switch or fork anytime |
| **Commercial Use** | Build products on top (with compliance) |
| **Community Support** | Discord, GitHub, documentation |

---

## The Bottom Line

| Aspect | Broker APIs | OpenAlgo |
|--------|-------------|----------|
| **Setup Time** | Weeks of development | Hours to deploy |
| **Broker Switching** | Rewrite everything | Change one config |
| **Testing** | Build your own sandbox | Analyzer Mode ready |
| **Monitoring** | Build dashboards | Full UI included |
| **Security** | Implement yourself | Production-ready |
| **Maintenance** | You maintain everything | Community maintained |
| **Cost** | Your development time | Free and open source |

**Broker APIs give you *access*.**
**OpenAlgo gives you *infrastructure*.**

It doesn't replace your strategy logic—it **amplifies** it with the ecosystem you need to operate, monitor, test, and scale confidently.

And when you're ready to switch brokers or expand to multi-broker setups, you'll already be on **OpenAlgo's unified, broker-agnostic foundation**.

---

**Previous**: [01 - What is OpenAlgo](../01-what-is-openalgo/README.md)

**Next**: [03 - Key Concepts](../03-key-concepts/README.md)
