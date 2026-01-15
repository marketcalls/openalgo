# OpenAlgo - Open Source Algorithmic Trading Platform

<div align="center">

[![PyPI Downloads](https://static.pepy.tech/badge/openalgo)](https://pepy.tech/projects/openalgo)
[![PyPI Downloads](https://static.pepy.tech/badge/openalgo/month)](https://pepy.tech/projects/openalgo)
[![X (formerly Twitter) Follow](https://img.shields.io/twitter/follow/openalgoHQ)](https://twitter.com/openalgoHQ)
[![YouTube Channel Subscribers](https://img.shields.io/youtube/channel/subscribers/UCw7eVneIEyiTApy4RtxrJsQ)](https://www.youtube.com/@openalgo)
[![Discord](https://img.shields.io/discord/1219847221055455263)](https://discord.com/invite/UPh7QPsNhP)

</div>

![OpenAlgo - Your Personal Algo Trading Platform](static/images/image.png)

**OpenAlgo** is a production-ready, open-source algorithmic trading platform built with Flask and Python. It provides a unified API layer across 24+ Indian brokers, enabling seamless integration with popular platforms like TradingView, Amibroker, Excel, Python, and AI agents. Designed for traders and developers, OpenAlgo makes algo trading accessible, secure, and powerful.

## Quick Links

- **Documentation**: [docs.openalgo.in](https://docs.openalgo.in)
- **Installation Guide**: [Getting Started](https://docs.openalgo.in/installation-guidelines/getting-started)
- **Upgrade Guide**: [Upgrade Instructions](https://docs.openalgo.in/installation-guidelines/getting-started/upgrade)
- **Why OpenAlgo**: [Why Build with OpenAlgo](https://docs.openalgo.in/why-to-build-with-openalgo)
- **Video Tutorial**: 

[![What is OpenAlgo](https://img.youtube.com/vi/kAS3jTb3OkI/0.jpg)](https://www.youtube.com/watch?v=kAS3jTb3OkI)

## Python Compatibility

**Supports Python 3.11, 3.12, 3.13, and 3.14**

## Supported Brokers (24+)

<details>
<summary>View All Supported Brokers</summary>

- 5paisa (Standard + XTS)
- AliceBlue
- AngelOne
- Compositedge
- Definedge
- Dhan (Live + Sandbox)
- Firstock
- Flattrade
- Fyers
- Groww
- IBulls
- IIFL
- Indmoney
- JainamXTS
- Kotak Neo
- Motilal Oswal
- Mstock
- Paytm Money
- Pocketful
- Samco
- Shoonya (Finvasia)
- Tradejini
- Upstox
- Wisdom Capital
- Zebu
- Zerodha

</details>

All brokers share a unified API interface, making it easy to switch between brokers without changing your code.

## Core Features

### Unified REST API Layer (`/api/v1/`)
A single, standardized API across all brokers with 30+ endpoints:
- **Order Management**: Place, modify, cancel orders, basket orders, smart orders with position sizing
- **Portfolio**: Get positions, holdings, order book, trade book, funds
- **Market Data**: Real-time quotes, historical data, market depth (Level 5), symbol search
- **Advanced**: Option Greeks calculator, margin calculator, synthetic futures, auto-split orders

### Real-Time WebSocket Streaming
- Unified WebSocket proxy server for all brokers (port 8765)
- Common WebSocket implementation using ZMQ for normalized data across brokers
- Subscribe to LTP, Quote, or Market Depth for any symbol
- ZeroMQ-based message bus for high-performance data distribution
- Automatic reconnection and failover handling

### API Analyzer Mode
Complete testing environment with ₹1 Crore virtual capital:
- Test strategies with real market data without risking money
- Pre-deployment testing for strategy validation
- Supports all order types (Market, Limit, SL, SL-M)
- Realistic margin system with leverage
- Auto square-off at exchange timings
- Separate database for complete isolation

[API Analyzer Documentation](https://docs.openalgo.in/new-features/api-analyzer)

### Action Center
Order approval workflow for manual control:
- **Auto Mode**: Immediate order execution (for personal trading)
- **Semi-Auto Mode**: Manual approval required before broker execution
- Complete audit trail with IST timestamps
- Approve individual orders or bulk approve all

[Action Center Documentation](https://docs.openalgo.in/new-features/action-center)

### Python Strategy Manager
Host and run Python strategies directly on OpenAlgo:
- Built-in code editor with syntax highlighting
- Run multiple strategies in parallel with process isolation
- Automated scheduling with IST-based start/stop times
- Secure environment variable management with encryption
- Real-time logs and state persistence
- No need for external servers or hosting

### ChartInk Integration
Direct webhook integration for scanner alerts:
- Supports BUY, SELL, SHORT, COVER actions
- Intraday with auto square-off and positional strategies
- Bulk symbol configuration via CSV
- Real-time strategy monitoring

### AI-Powered Trading (MCP Server)
Connect AI assistants for natural language trading:
- Compatible with Claude Desktop, Cursor, Windsurf, ChatGPT
- Execute trades using natural language commands
- Full trading capabilities: orders, positions, market data
- Local and secure integration with your OpenAlgo instance

### Telegram Bot Integration
Real-time notifications and command execution:
- Automatic order and trade alerts delivered to Telegram
- Get orderbook, positions, holdings, funds on demand
- Generate intraday and daily charts
- Interactive button-based menu
- Receive strategy alerts directly to Telegram
- Secure API key encryption

### Advanced Monitoring Tools
**Latency Monitor**: Track order execution performance and round-trip times across brokers

**Traffic Monitor**: API usage analytics, error tracking, and endpoint statistics

**PnL Tracker**: Real-time profit/loss with interactive charts powered by TradingView Lightweight Charts

[PnL Tracker Documentation](https://docs.openalgo.in/new-features/pnl-tracker)

[Traffic & Latency Monitor Documentation](https://docs.openalgo.in/new-features/traffic-latency-monitor)

### Enterprise-Grade Security
**Password Security**: Argon2 hashing (Password Hashing Competition winner)

**Token Encryption**: Fernet symmetric encryption with PBKDF2 key derivation

**Rate Limiting**: Configurable limits for login, API, orders, webhooks

**Manual IP Ban System**: Monitor and ban suspicious IPs via `/security` dashboard

**Browser Protection**: CSP headers, CORS rules, CSRF protection, secure headers, secure sessions

**SQL Injection Prevention**: SQLAlchemy ORM with parameterized queries

**Privacy First**: Zero data collection policy - your data stays on your server

### Modern UI with DaisyUI
- 30+ beautiful themes to choose from (Light, Dark, and more)
- Real-time updates via WebSocket (orders, trades, positions, logs)
- Mobile-friendly responsive design
- Theme-aware syntax highlighting
- Zero-config installation

## Supported Platforms

Connect your algo strategies and run from any platform:

- **Amibroker** - Direct integration with AFL scripts
- **TradingView** - Webhook alerts for Pine Script strategies
- **GoCharting** - Webhook integration
- **N8N** - Workflow automation
- **Python** - Official SDK with 100+ technical indicators
- **GO** - REST API integration
- **Node.js** - JavaScript/TypeScript library
- **ChartInk** - Scanner webhook integration
- **MetaTrader** - Compatible with MT4/MT5
- **Excel** - REST API + upcoming Add-in
- **Google Sheets** - REST API integration

Receive your strategy alerts directly to **Telegram** for all platforms.

## Architecture Highlights

- **Backend**: Flask 3.0 + SQLAlchemy 2.0
- **Frontend**: Tailwind CSS 4.1 + DaisyUI 5.1
- **Real-time**: Flask-SocketIO, WebSockets, ZeroMQ
- **Security**: Argon2-CFFI, Cryptography (Fernet), Flask-WTF
- **Databases**: SQLite (4 separate DBs: main, logs, latency, sandbox)
- **Broker Pattern**: Standardized structure (auth, order, data, funds, streaming, mapping)
- **Connection Pooling**: Optimized latency with efficient connection management

## OpenAlgo FOSS Ecosystem

OpenAlgo is part of a larger open-source trading ecosystem:

- **OpenAlgo Core**: This repository (Python Flask)
- **Historify**: Stock market data management platform
- **Python Library**: Native Python SDK
- **Node.js Library**: JavaScript/TypeScript SDK
- **Excel Add-in**: Direct Excel integration
- **MCP Server**: AI agents integration
- **Chrome Plugin**: Browser-based tools
- **Fast Scalper**: High-performance trading (Rust + Tauri)
- **Web Portal**: Modern UI (NextJS + ShadcnUI)
- **Documentation**: Comprehensive guides on [Gitbook](https://docs.openalgo.in/mini-foss-universe)

## Installation

### Minimum Requirements
- **RAM**: 2GB (or 0.5GB + 2GB swap)
- **Disk**: 1GB
- **CPU**: 1 vCPU
- **Python**: 3.11, 3.12, 3.13, or 3.14

### Quick Start with UV

OpenAlgo uses the modern `uv` package manager for faster, more reliable installations:

```bash
# Clone the repository
git clone https://github.com/marketcalls/openalgo.git
cd openalgo

# Install UV package manager
pip install uv

# Configure environment
cp .sample.env .env
# Edit .env with your broker API credentials as per documentation

# Run the application using UV
uv run app.py
```

The application will be available at `http://127.0.0.1:5000`

For detailed installation instructions, deployment options (Docker, AWS, etc.), and configuration guides, visit [docs.openalgo.in/installation-guidelines/getting-started](https://docs.openalgo.in/installation-guidelines/getting-started)

## API Documentation

Complete API reference and examples:
- **API Documentation**: [docs.openalgo.in/api-documentation/v1](https://docs.openalgo.in/api-documentation/v1)
- **Symbol Format**: [docs.openalgo.in/symbol-format](https://docs.openalgo.in/symbol-format)

## Key Benefits

- **Zero-Config Installation**: One-command setup with UV
- **Single API, Multiple Brokers**: Switch brokers without code changes
- **No Data Collection**: Complete privacy - your data stays on your server
- **Host Python Strategies**: Run strategies directly without external servers
- **Smart Order Execution**: Intelligent routing for complex strategies
- **Order Splitting**: Automatically split large orders into smaller chunks
- **Real-Time Analytics**: PnL tracking, latency monitoring, traffic analysis
- **Strategy Templates**: Rapid prototyping with pre-built templates
- **Plugin Architecture**: Extensible design for custom integrations
- **Active Community**: Discord support, virtual meetups, open roadmap

## Documentation

Comprehensive documentation is available at [docs.openalgo.in](https://docs.openalgo.in):
- API Reference with examples
- Broker-specific guides
- Security best practices
- Deployment tutorials
- Strategy development guides
- Troubleshooting and FAQs

## Contributing

We welcome contributions! To contribute:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Community & Support

- **Discord**: [Join our community](https://www.openalgo.in/discord)
- **Twitter/X**: [@openalgoHQ](https://twitter.com/openalgoHQ)
- **YouTube**: [@openalgo](https://www.youtube.com/@openalgo)
- **GitHub Issues**: [Report bugs or request features](https://github.com/marketcalls/openalgo/issues)

## License

OpenAlgo is released under the **AGPL V3.0 License**. See [LICENSE](LICENSE) for details.

## Credits

### Third-Party Libraries

- **[DaisyUI](https://github.com/saadeghi/daisyui)** - MIT License - Modern UI component library for Tailwind CSS with 30+ themes
- **[TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts)** - Apache 2.0 - Financial charting library for PnL visualization

## Repo Activity

![Alt](https://repobeats.axiom.co/api/embed/0b6b18194a3089cb47ab8ae588caabb14aa9972b.svg "Repobeats analytics image")

## Disclaimer

**This software is for educational purposes only. Do not risk money which you are afraid to lose. USE THE SOFTWARE AT YOUR OWN RISK. THE AUTHORS AND ALL AFFILIATES ASSUME NO RESPONSIBILITY FOR YOUR TRADING RESULTS.**

Always test your strategies in Analyzer Mode before deploying with real money. Past performance does not guarantee future results. Trading involves substantial risk of loss.

---

Built with ❤️ by traders, for traders. Making algorithmic trading accessible to everyone.
