# OpenAlgo - Open Source Algorithmic Trading Platform

<div align="center">

[![PyPI Downloads](https://static.pepy.tech/badge/openalgo)](https://pepy.tech/projects/openalgo)
[![PyPI Downloads](https://static.pepy.tech/badge/openalgo/month)](https://pepy.tech/projects/openalgo)
[![X (formerly Twitter) Follow](https://img.shields.io/twitter/follow/openalgoHQ)](https://twitter.com/openalgoHQ)
[![YouTube Channel Subscribers](https://img.shields.io/youtube/channel/subscribers/UCw7eVneIEyiTApy4RtxrJsQ)](https://www.youtube.com/@openalgo)
[![Discord](https://img.shields.io/discord/1219847221055455263)](https://discord.com/invite/UPh7QPsNhP)

</div>

**OpenAlgo** is a production-ready, open-source algorithmic trading platform built with Flask and React. It provides a unified API layer across 24+ Indian brokers, enabling seamless integration with popular platforms like TradingView, Amibroker, Excel, Python, and AI agents. Designed for traders and developers, OpenAlgo makes algo trading accessible, secure, and powerful.

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

### Flow Visual Strategy Builder
Build trading strategies visually without writing code:
- **Node-based editor** powered by xyflow/React Flow
- **Pre-built nodes**: Market data, conditions, order execution, notifications
- **Real-time execution** with live market data
- **Webhook triggers** for TradingView and external signals
- **Visual debugging** with execution flow highlighting

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
- Built-in code editor powered by **CodeMirror** with Python syntax highlighting
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

**Two-Factor Authentication**: TOTP support with authenticator apps

**Rate Limiting**: Configurable limits for login, API, orders, webhooks

**Manual IP Ban System**: Monitor and ban suspicious IPs via `/security` dashboard

**Browser Protection**: CSP headers, CORS rules, CSRF protection, secure headers, secure sessions

**SQL Injection Prevention**: SQLAlchemy ORM with parameterized queries

**Privacy First**: Zero data collection policy - your data stays on your server

### Modern React Frontend
- **React 19** with TypeScript for type-safe, maintainable code
- **shadcn/ui** components with Tailwind CSS 4.0 for beautiful, accessible UI
- **TanStack Query** for efficient server state management and caching
- **Zustand** for lightweight client state management
- **Real-time updates** via Socket.IO (orders, trades, positions, logs)
- **CodeMirror** for Python and JSON editing with syntax highlighting and themes
- **xyflow/React Flow** for visual Flow strategy builder
- **TradingView Lightweight Charts** for P&L and market data visualization
- Light and Dark themes with 8 accent colors
- Mobile-friendly responsive design

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

## Technology Stack

### Backend
- **Flask 3.0** - Python web framework
- **SQLAlchemy 2.0** - Database ORM
- **Flask-SocketIO** - Real-time WebSocket communication
- **ZeroMQ** - High-performance message bus
- **Argon2-CFFI** - Password hashing
- **Cryptography** - Fernet encryption for tokens

### Frontend
- **React 19** - UI library
- **TypeScript** - Type-safe JavaScript
- **Vite 7** - Fast build tool
- **Tailwind CSS 4** - Utility-first CSS framework
- **shadcn/ui** - Component library built on Radix UI
- **TanStack Query** - Server state management
- **Zustand** - Client state management

### Data Visualization & Editors
- **TradingView Lightweight Charts** - Financial charts
- **CodeMirror** - Code editor for strategies
- **xyflow/React Flow** - Visual Flow builder
- **Lucide React** - Icon library

### Testing & Quality
- **Vitest** - Unit testing
- **Playwright** - E2E testing
- **Biome** - Linting and formatting
- **axe-core** - Accessibility testing

### Databases
- **SQLite** - 4 separate databases (main, logs, latency, sandbox)
- **DuckDB** - Historical market data (Historify)

## Official SDKs

OpenAlgo provides officially supported client libraries for application development and system-level integrations:

| Language / Platform | Repository |
|---------------------|------------|
| Python | [openalgo-python-library](https://github.com/marketcalls/openalgo-python-library) |
| Node.js | [openalgo-node](https://github.com/marketcalls/openalgo-node) |
| Java | [openalgo-java](https://github.com/marketcalls/openalgo-java) |
| Rust | [openalgo-rust](https://github.com/marketcalls/openalgo-rust) |
| .NET / C# | [openalgo.NET](https://github.com/marketcalls/openalgo.NET) |
| Go | [openalgo-go](https://github.com/marketcalls/openalgo-go) |

## OpenAlgo FOSS Ecosystem

OpenAlgo is part of a larger open-source trading ecosystem:

- **OpenAlgo Core**: This repository (Python Flask + React)
- **Historify**: Stock market data management platform
- **Official SDKs**: Python, Node.js, Java, Rust, .NET, Go (see above)
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
- **Node.js**: 20+ (for frontend development)

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
- **Visual Strategy Builder**: Create strategies with drag-and-drop Flow editor
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

## Credits & Acknowledgments

OpenAlgo is built upon the shoulders of giants. We extend our gratitude to all the open-source projects that make this platform possible.

### Core Framework
- **[Flask](https://flask.palletsprojects.com)** - BSD License - Python web microframework
- **[React](https://react.dev)** - MIT License - UI library for building user interfaces
- **[SQLAlchemy](https://www.sqlalchemy.org)** - MIT License - Python SQL toolkit and ORM

### UI Components & Styling
- **[shadcn/ui](https://ui.shadcn.com)** - MIT License - Beautifully designed components built with Radix UI and Tailwind CSS
- **[Radix UI](https://www.radix-ui.com)** - MIT License - Unstyled, accessible UI components
- **[Tailwind CSS](https://tailwindcss.com)** - MIT License - Utility-first CSS framework
- **[Lucide](https://lucide.dev)** - ISC License - Beautiful & consistent icon library

### Data Visualization
- **[TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts)** - Apache 2.0 - Financial charting library for market data and P&L visualization
- **[Plotly](https://plotly.com/javascript/)** - MIT License - Interactive charting library for options analytics and visualization
- **[xyflow/React Flow](https://reactflow.dev)** - MIT License - Highly customizable library for building node-based visual strategy editors

### Code Editors
- **[CodeMirror](https://codemirror.net)** - MIT License - Versatile code editor for Python and JSON with syntax highlighting
- **[@uiw/react-codemirror](https://uiwjs.github.io/react-codemirror)** - MIT License - CodeMirror React wrapper with themes

### State Management & Data Fetching
- **[TanStack Query](https://tanstack.com/query)** - MIT License - Powerful asynchronous state management
- **[Zustand](https://zustand-demo.pmnd.rs)** - MIT License - Lightweight state management
- **[Axios](https://axios-http.com)** - MIT License - Promise-based HTTP client

### Real-Time Communication
- **[Socket.IO](https://socket.io)** - MIT License - Real-time bidirectional event-based communication
- **[ZeroMQ](https://zeromq.org)** - LGPL License - High-performance asynchronous messaging

### Security
- **[Argon2-CFFI](https://argon2-cffi.readthedocs.io)** - MIT License - Argon2 password hashing (PHC winner)
- **[Cryptography](https://cryptography.io)** - BSD/Apache License - Cryptographic recipes and primitives

### Build & Development Tools
- **[Vite](https://vitejs.dev)** - MIT License - Fast frontend build tool
- **[TypeScript](https://www.typescriptlang.org)** - Apache 2.0 - JavaScript with syntax for types
- **[Biome](https://biomejs.dev)** - MIT License - Fast formatter and linter
- **[Vitest](https://vitest.dev)** - MIT License - Blazing fast unit testing
- **[Playwright](https://playwright.dev)** - Apache 2.0 - End-to-end testing framework

### Additional Libraries
- **[React Router](https://reactrouter.com)** - MIT License - Declarative routing for React
- **[Sonner](https://sonner.emilkowal.ski)** - MIT License - Toast notifications
- **[cmdk](https://cmdk.paco.me)** - MIT License - Command palette component
- **[next-themes](https://github.com/pacocoursey/next-themes)** - MIT License - Theme switching
- **[react-resizable-panels](https://github.com/bvaughn/react-resizable-panels)** - MIT License - Resizable panel layouts
- **[html2canvas-pro](https://html2canvas.hertzen.com)** - MIT License - Screenshot generation

## Repo Activity

![Alt](https://repobeats.axiom.co/api/embed/0b6b18194a3089cb47ab8ae588caabb14aa9972b.svg "Repobeats analytics image")

## Disclaimer

**This software is for educational purposes only. Do not risk money which you are afraid to lose. USE THE SOFTWARE AT YOUR OWN RISK. THE AUTHORS AND ALL AFFILIATES ASSUME NO RESPONSIBILITY FOR YOUR TRADING RESULTS.**

Always test your strategies in Analyzer Mode before deploying with real money. Past performance does not guarantee future results. Trading involves substantial risk of loss.

---

Built with ❤️ by traders, for traders. Making algorithmic trading accessible to everyone.
