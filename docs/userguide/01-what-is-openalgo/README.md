# 01 - What is OpenAlgo?

## Introduction

**OpenAlgo** is a free, open-source algorithmic trading platform that bridges your trading ideas with execution. Built with Python Flask and a modern React frontend, it provides a unified API layer across 24+ Indian brokers, enabling seamless automation from TradingView, Amibroker, Python scripts, Excel, and AI agents.

**Website**: [https://openalgo.in](https://openalgo.in)
**GitHub**: [https://github.com/marketcalls/openalgo](https://github.com/marketcalls/openalgo)
**Documentation**: [https://docs.openalgo.in](https://docs.openalgo.in)

## The Problem OpenAlgo Solves

### Before OpenAlgo

```
You see a buy signal on TradingView
        ↓
You manually open your broker app
        ↓
You search for the stock
        ↓
You enter quantity and price
        ↓
You click buy
        ↓
Signal is 2 minutes old by now!
```

### With OpenAlgo

```
TradingView sends a signal
        ↓
OpenAlgo receives it instantly
        ↓
Order placed with your broker
        ↓
All in under 1 second!
```

## Who is OpenAlgo For?

### Retail Traders
- Tired of manually placing orders
- Want to trade multiple stocks simultaneously
- Need faster execution than manual trading

### Technical Traders
- Use TradingView for charting and alerts
- Use Amibroker for backtesting strategies
- Want to automate their proven strategies

### Algo Enthusiasts
- Want to learn algorithmic trading
- Need a platform to test strategies safely
- Looking for a free alternative to expensive platforms

### Investment Advisors
- Need order approval workflow (Action Center)
- Require audit trails for compliance
- Want semi-automated trading with client oversight

### Quant Developers
- Need historical data for backtesting (Historify)
- Want to build custom strategies in Python
- Require real-time WebSocket data feeds

## Key Features

### Trading Automation

| Feature | Description |
|---------|-------------|
| **Smart Order Placement** | Execute trades with position sizing, split orders, and bracket orders |
| **Multi-Broker Support** | Connect to 24+ Indian brokers through a unified API |
| **Multi-Exchange Trading** | NSE, NFO, BSE, BFO, MCX, CDS, BCD, NCDEX |
| **Real-Time Streaming** | WebSocket-based live quotes, depth, and order updates |
| **Auto Square-Off** | Time-based and one-click position square-off |

### Strategy Building

| Feature | Description |
|---------|-------------|
| **Flow Visual Builder** | No-code strategy builder with drag-and-drop nodes |
| **Python Strategy Hosting** | Host and schedule Python strategies directly in OpenAlgo |
| **TradingView Integration** | Pine Script alerts to automatic orders via webhooks |
| **Amibroker Integration** | AFL strategies with direct API communication |
| **ChartInk Integration** | Stock scanner alerts to automated trades |

### Analysis & Testing

| Feature | Description |
|---------|-------------|
| **Analyzer Mode** | Sandbox trading with ₹1 Crore sandbox capital |
| **Historify** | Download and store historical market data (DuckDB) |
| **P&L Tracker** | Real-time profit/loss tracking with charts |
| **Latency Monitor** | Track API and order execution latency |
| **Traffic Logs** | Comprehensive API request/response logging |

### Risk & Security

| Feature | Description |
|---------|-------------|
| **Action Center** | Order approval workflow for managed accounts |
| **Two-Factor Auth** | TOTP-based authentication for enhanced security |
| **Rate Limiting** | Configurable API rate limits per endpoint |
| **Order Validation** | Automatic validation of all order parameters |
| **Freeze Quantity** | Exchange-mandated quantity limits enforcement |

### Notifications & Monitoring

| Feature | Description |
|---------|-------------|
| **Telegram Bot** | Real-time trade notifications and commands |
| **WebSocket Updates** | Live order status, positions, and P&L |
| **Dashboard** | Real-time monitoring of all trading activity |
| **API Logs** | Detailed logging for debugging and audit |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Signal Sources                                   │
│                                                                          │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐           │
│  │ TradingView│ │ Amibroker  │ │  ChartInk  │ │   Python   │           │
│  │  Webhooks  │ │    AFL     │ │  Scanners  │ │  Scripts   │           │
│  └─────┬──────┘ └─────┬──────┘ └─────┬──────┘ └─────┬──────┘           │
│        │              │              │              │                    │
│        └──────────────┴──────────────┴──────────────┘                    │
│                              │                                           │
│                              ▼                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                         OpenAlgo Platform                          │  │
│  │                                                                    │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │  │
│  │  │  REST API   │  │  WebSocket  │  │    Flow     │               │  │
│  │  │  /api/v1/   │  │   Server    │  │   Builder   │               │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘               │  │
│  │                                                                    │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐               │  │
│  │  │  Analyzer   │  │  Historify  │  │   Python    │               │  │
│  │  │  (Sandbox)  │  │   (Data)    │  │  Strategies │               │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘               │  │
│  │                                                                    │  │
│  └───────────────────────────┬───────────────────────────────────────┘  │
│                              │                                           │
│                              ▼                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                    Unified Broker Layer                            │  │
│  │                                                                    │  │
│  │  Zerodha │ Angel │ Dhan │ Fyers │ 5paisa │ Upstox │ 20+ more...  │  │
│  │                                                                    │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Supported Brokers (24+)

| Category | Brokers |
|----------|---------|
| **Tier 1** | Zerodha, Angel One, Dhan, Fyers, Upstox |
| **Banks** | ICICI Direct, HDFC Securities, Kotak Neo |
| **Others** | 5paisa, Finvasia, Flattrade, Firstock, and more |

**Benefit**: Switch brokers without changing your strategy code - OpenAlgo's unified API handles the translation.

## Supported Exchanges

| Exchange | Description |
|----------|-------------|
| **NSE** | National Stock Exchange (Equity) |
| **NFO** | NSE Futures & Options |
| **BSE** | Bombay Stock Exchange (Equity) |
| **BFO** | BSE Futures & Options |
| **MCX** | Multi Commodity Exchange |
| **CDS** | Currency Derivatives Segment |
| **BCD** | BSE Currency Derivatives |
| **NCDEX** | National Commodity Exchange |

## Trading Modes

### Live Trading Mode
Execute real trades with your connected broker. Orders are sent directly to the exchange through your broker's API.

### Analyzer Mode (Sandbox Trading)
Test strategies with ₹1 Crore sandbox capital:
- Realistic margin calculations
- Position and holdings tracking
- Auto square-off at exchange timings
- Complete isolation from live trading
- Perfect for strategy testing and validation

## Platform Integration

### Signal Sources
- **TradingView**: Pine Script alerts via webhooks
- **Amibroker**: AFL strategies with HTTP calls
- **ChartInk**: Stock scanner webhooks
- **GoCharting**: Chart-based alerts
- **MetaTrader 5**: EA integration
- **Custom**: Any HTTP/Webhook capable platform

### Programming Languages
- **Python**: Official SDK available
- **Node.js**: REST API integration
- **Excel/VBA**: API calls from spreadsheets
- **Google Sheets**: Apps Script integration
- **Any Language**: Standard REST API

### AI Integration
- Works with AI assistants that can make API calls
- Natural language to trading orders
- Strategy automation via AI agents

## Data & Privacy

| Aspect | Detail |
|--------|--------|
| **Deployment** | Self-hosted on your computer/server |
| **Data Storage** | Local SQLite databases |
| **Historical Data** | DuckDB for efficient storage (Historify) |
| **External Calls** | Only to your broker's API |
| **Open Source** | Full code visibility and audit capability |

## API Capabilities

### Order Management
- Place, modify, cancel orders
- Smart orders with position sizing
- Basket orders for multiple symbols
- Split orders for large quantities
- Options orders with strike selection

### Market Data
- Real-time quotes and depth
- Historical OHLCV data
- Option chain with Greeks
- Multi-symbol batch quotes

### Account Information
- Funds and margins
- Order book and trade book
- Positions and holdings
- P&L calculations

### WebSocket Streaming
- Live LTP updates
- Full quote streaming
- Market depth (5/20 levels)
- Order status updates

## What OpenAlgo is NOT

Let's be clear about what OpenAlgo doesn't do:

| Misconception | Reality |
|---------------|---------|
| Get-rich-quick scheme | It's a tool - profitability depends on your strategy |
| Strategy provider | You need your own trading ideas |
| Financial advisor | You're responsible for trading decisions |
| Black box | 100% open source - verify every line of code |
| Cloud service | Self-hosted - you control everything |

## System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **OS** | Windows 10, macOS 10.15, Ubuntu 20.04 | Latest versions |
| **Python** | 3.12+ | 3.12+ |
| **RAM** | 4 GB | 8 GB+ |
| **Storage** | 2 GB | 10 GB+ (for historical data) |
| **Network** | Stable internet | Low latency connection |

## Getting Started

Ready to begin? Here's your path:

1. **Next**: Learn [Why Build with OpenAlgo](../02-why-build-with-openalgo/README.md)
2. Understand [Key Concepts](../03-key-concepts/README.md)
3. Check [System Requirements](../03-system-requirements/README.md)
4. Follow [Installation Guide](../04-installation/README.md)
5. Complete [First-Time Setup](../05-first-time-setup/README.md)
6. Place your [First Order](../10-placing-first-order/README.md)!

## Quick Links

| Resource | Link |
|----------|------|
| **GitHub** | [github.com/marketcalls/openalgo](https://github.com/marketcalls/openalgo) |
| **Documentation** | [docs.openalgo.in](https://docs.openalgo.in) |
| **API Reference** | [/api/docs](http://localhost:5000/api/docs) (after installation) |
| **Discord Community** | Join for support and discussions |

## Summary

| Aspect | OpenAlgo |
|--------|----------|
| **Cost** | Free (Open Source, MIT License) |
| **Brokers** | 24+ Indian brokers |
| **Exchanges** | NSE, NFO, BSE, BFO, MCX, CDS, BCD, NCDEX |
| **Signal Sources** | TradingView, Amibroker, ChartInk, Python, AI |
| **Strategy Building** | Flow (Visual), Python Hosting, External Webhooks |
| **Sandbox Trading** | Analyzer Mode with ₹1 Crore sandbox capital |
| **Historical Data** | Historify with DuckDB storage |
| **Real-Time Data** | WebSocket streaming for quotes and orders |
| **Notifications** | Telegram bot, WebSocket updates |
| **Data Privacy** | 100% - self-hosted on your infrastructure |
| **Skill Required** | Basic trading knowledge |

---

**Next**: [02 - Why Build with OpenAlgo](../02-why-build-with-openalgo/README.md) - Understand the value proposition.
