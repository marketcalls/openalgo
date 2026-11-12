# OpenAlgo Documentation Map

The entry point for humans and AI agents. This file is a **map, not a copy** —
it points at the canonical docs that already live under `docs/`. Edit a source
doc once; everything that reads through this map sees the change immediately.

**How to use (progressive disclosure):** read this map → open the one area you
need → drill into the specific file. Don't load everything at once.

---

## Using OpenAlgo (product, API, SDK)

| Read this when you need… | Entry point |
|---|---|
| The REST API (`/api/v1/`) — orders, market data, options, account, streaming | [api/README.md](api/README.md) |
| The Python SDK — install, client, data/order/account calls | [<prompt/openalgo python sdk.md>](<prompt/openalgo python sdk.md>) |
| Symbol format across exchanges (equity/futures/options) | [prompt/symbol-format.md](prompt/symbol-format.md) |
| Order constants (exchange / product / price-type / action codes) | [prompt/order-constants.md](prompt/order-constants.md) |
| Historical lot-size snapshot; read current `lotsize` / `freeze_qty` from symbol metadata | [prompt/LotSize.md](prompt/LotSize.md) |
| WebSocket subscription & message format | [prompt/websockets-format.md](prompt/websockets-format.md) · [prompt/websockets-verbose-control.md](prompt/websockets-verbose-control.md) |
| Service-layer functions & Flow JSON import | [prompt/services_documentation.md](prompt/services_documentation.md) · [prompt/flow-import-format.md](prompt/flow-import-format.md) |
| Strategy module & risk engine (multi-leg options, signal mode, RMS) | [prompt/strategy_rms_documentation.md](prompt/strategy_rms_documentation.md) · [api/strategy-services/](api/strategy-services/) · [prd/strategy-module-rms.md](prd/strategy-module-rms.md) · [bdd/strategy_module_rms.feature](bdd/strategy_module_rms.feature) |
| Technical indicators (`ta` library) | [<prompt/indicators/openalgo indicators - introduction.md>](<prompt/indicators/openalgo indicators - introduction.md>) |
| The charting terminal at `/trading`, its order dock and its shortcuts | [userguide/32-charting-terminal](userguide/32-charting-terminal/README.md) |
| Writing your own chart indicators for `/trading` | [custom-indicators.md](custom-indicators.md) |
| Writing studies in OpenScript for `/trading` | [openscript.md](openscript.md) |
| Step-by-step user guide (setup → first order → integrations) | [userguide/README.md](userguide/README.md) |
| MCP tool reference (Claude Desktop / Cursor / Windsurf) | [mcp-tool-reference.md](mcp-tool-reference.md) |
| Connecting hosted AI clients through Remote MCP | [userguide/remote-mcp.md](userguide/remote-mcp.md) |
| Saving broker keys and connecting a broker | [userguide/06-broker-connection/README.md](userguide/06-broker-connection/README.md) |

## Install, deploy & operate

| Topic | Entry point |
|---|---|
| Ubuntu server install | [installation-guidelines/getting-started/ubuntu-server-installation.md](installation-guidelines/getting-started/ubuntu-server-installation.md) |
| Docker | [docker/README.md](docker/README.md) |
| Optional gthread web server: fresh installs, switching on Ubuntu and Docker, verification and rollback | [gthread/README.md](gthread/README.md) |
| Upgrade / SMTP / TOTP / forgot-password | [Upgrade](design/30-upgrade-procedure/README.md) · [SMTP](design/47-smtp-config/README.md) · [TOTP](design/50-totp-configuration/README.md) · [Password reset](design/48-password-reset/README.md) |
| Desktop and companion apps on the public `/download` page | [Installation guide](userguide/04-installation/README.md) |
| Broker integration (38 plugins, including Dhan Sandbox) | [broker-integration-guide.md](broker-integration-guide.md) |
| Release notes & changelog | [releases/](releases/) · [CHANGELOG.md](CHANGELOG.md) |

## Feature surfaces

| Feature | Entry point |
|---|---|
| Agent (`/agent`) and voice | [design/55-agent/README.md](design/55-agent/README.md) · [design/56-voice-agent/README.md](design/56-voice-agent/README.md) |
| The 20 options and portfolio tools, including Strike Profile and Sector Rotation | [userguide/31-tools/README.md](userguide/31-tools/README.md) |
| Portfolio, SIP and sector-rotation REST APIs | [api/README.md](api/README.md#portfolio-sip-and-sector-analysis) |
| Python strategy hosting and Flow workflows | [Python](userguide/20-python-strategies/README.md) · [Flow](userguide/21-flow-visual-builder/README.md) |
| Scalping Terminal (`/scalping`) | [scalping/PRD.md](scalping/PRD.md) |
| Scanner design proposal (external service, not shipped) | [scanner-architecture.md](scanner-architecture.md) |
| Alerts: Telegram, WhatsApp, Slack and Discord on one page | [alerts.md](alerts.md) |
| WhatsApp alerts | [whatsapp.md](whatsapp.md) |
| Telegram chart rendering | [telegram-chart-rendering.md](telegram-chart-rendering.md) |
| Health monitoring | [HEALTH_MONITORING_IMPLEMENTATION.md](HEALTH_MONITORING_IMPLEMENTATION.md) · [HEALTH_MONITOR_REACT_FRONTEND.md](HEALTH_MONITOR_REACT_FRONTEND.md) |

## Architecture, design & specs (contributors)

| Topic | Entry point |
|---|---|
| First-time contributor setup (devsprint prep) | [devsprint/README.md](devsprint/README.md) |
| System design (frontend, backend, DB, UI) | [design/README.md](design/README.md) |
| Product requirements — Flow, Python strategies, Strategy module & RMS, Sandbox, Historify, MCP, event bus, websocket proxy | [prd/README.md](prd/README.md) · [prd/PRD.md](prd/PRD.md) |
| BDD feature specs (Gherkin `.feature`) | [bdd/README.md](bdd/README.md) |
| WebSocket architecture & quote feed | [websocket-architecture.md](websocket-architecture.md) · [websocket-quote-feed.md](websocket-quote-feed.md) |
| Documentation gap audit and verification limits (2026-11-06) | [audit/2026-11-06-documentation-gap-audit.md](audit/2026-11-06-documentation-gap-audit.md) |
| Security audits (historical findings) | [audit/README.md](audit/README.md) |
| CI/CD | [prd/ci-cd.md](prd/ci-cd.md) |
| Benchmarks | [benchmarks/](benchmarks/) |
| Migration plans | [migration/](migration/) |
| Implementation plans | [plans/](plans/) |
| Testing guides | [test/](test/) |
| XTS API | [xtsapi.md](xtsapi.md) |

---

## Current guidance and historical records

User guides, API references and current architecture documents describe the
installed code. Dated release notes, audits, benchmarks, plans, validation
reports and trackers record a particular revision or proposed work; they are
not fresh verification of today's implementation. Generated indicator and
OpenUI references should be refreshed with their source generators, not edited
by hand.

## Governance

- User responsibilities & risk ownership: https://docs.openalgo.in/responsibilities
- Repository: https://github.com/marketcalls/openalgo · Docs: https://docs.openalgo.in
