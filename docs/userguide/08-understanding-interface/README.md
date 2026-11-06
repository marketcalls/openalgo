# 08 - Understanding the Interface

## Navigation

The desktop interface uses a top navigation bar. **Dashboard**, **Orderbook** and **Positions** remain on the bar; **Tradebook** and **Trading** move into **More** on smaller desktops. **Platforms**, **Strategies**, **Logs** and **Tools** also move into **More** when space is limited.

On mobile, the bottom bar opens Dashboard, Orderbook, Tradebook and Positions. **Toggle menu** opens the remaining navigation and quick-access links.

The charting terminal at `/trading` fills the viewport and has its own toolbar with **Dashboard**, mode control, theme toggle and profile menu. See [Charting Terminal](../32-charting-terminal/README.md).

## Main Destinations

| Destination | Route | Purpose |
|---|---|---|
| Dashboard | `/dashboard` | Funds and master-contract status |
| Orderbook | `/orderbook` | Orders and GTT triggers/history |
| Tradebook | `/tradebook` | Executed trades |
| Positions | `/positions` | Current positions and exits |
| Trading | `/trading` | Charting terminal, chart orders, scripts, backtests and deployments |
| Platforms | `/platforms` | TradingView, GoCharting and other integration entry points |
| Strategies | `/strategy` | Batch and signal strategies with RMS; see the [strategy guide](../../prompt/strategy_rms_documentation.md) |
| Logs | `/logs` | Live/sandbox logs, security, traffic and latency views |
| Tools | `/tools` | [Options and portfolio analytics](../31-tools/README.md) |

## Profile Menu and Quick Access

The profile menu opens **Profile**, **API Key**, **Action Center**, **Agent**, **Master Contract**, **Telegram Bot**, **WhatsApp Bot**, **Holdings**, **Flow Editor**, **Scalping**, **Python Strategies**, **PnL Tracker**, **Historify**, **Search**, **Sandbox**, **Leverage** and **Admin**.

Entries follow broker capabilities: Holdings is hidden for a crypto broker, and Leverage appears only when the broker supports leverage configuration.

| Workflow | Route | Guide |
|---|---|---|
| Save or edit broker keys | `/broker/config` | [Broker Connection](../06-broker-connection/README.md); also available from Profile's Broker tab |
| API key and Auto/Semi-Auto order mode | `/apikey` | [API Key Management](../09-api-key-management/README.md) |
| Approve queued orders | `/action-center` | [Action Center](../22-action-center/README.md) |
| Host Python scripts | `/python` | [Python Strategies](../20-python-strategies/README.md) |
| Build no-code workflows | `/flow` | [Flow Visual Builder](../21-flow-visual-builder/README.md) |
| Security events and IP bans | `/logs/security` | [Security Settings](../27-security-settings/README.md) |
| API request metadata | `/logs/traffic` | [Traffic Logs](../26-traffic-logs/README.md) |
| Order latency | `/logs/latency` | [Latency Monitor](../25-latency-monitor/README.md) |
| Agent settings and Remote MCP administration | `/admin` | Agent Configuration card and [Remote MCP](../remote-mcp.md) |

Historify (`/historify`) downloads local market history and opens its chart view at `/historify/charts`. Scalping (`/scalping`) is a separate terminal for index options using NRML or MIS; see the [Scalping guide](../../scalping/PRD.md). WhatsApp setup is described in [WhatsApp alerts](../../whatsapp.md).

## Mode and Theme Controls

**Live** sends supported orders to your broker; **Analyze** uses the sandbox. This setting applies across the instance, including external API clients. The theme toggle switches light/dark appearance in Live and is disabled in Analyze, which uses the analyzer theme.

Auto/Semi-Auto order mode is a separate control on **API Key**. Semi-Auto queues supported placements for approval; it does not turn live orders into sandbox orders. Read [Action Center](../22-action-center/README.md) before using it for automated entries or exits.

## Orders and Charts

Orderbook, Tradebook and Positions offer a chart action for an instrument. It opens `/trading` with that symbol and exchange. Placement success means acceptance, not a completed fill: check the order's status and trades before treating it as a position.

Use the shortcuts documented for each surface. The charting terminal and Flow editor have their own shortcut sets; there is no application-wide command palette documented by the current interface.

---

**Previous**: [07 - Dashboard Overview](../07-dashboard-overview/README.md)

**Next**: [09 - API Key Management](../09-api-key-management/README.md)
