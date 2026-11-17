# 24 - PnL Tracker

## Open the Tracker

Choose **PnL Tracker** from the profile menu or visit `/pnl-tracker`. This page shows an **intraday MTM curve**, drawdown and summary metrics. It is separate from the historical Portfolio/SIP backtest tools and the Sandbox's own P&L page.

## Read the Page

| Card | Meaning |
|---|---|
| Current MTM | Latest MTM value in the returned series |
| Max MTM | Highest returned MTM and its time |
| Min MTM | Lowest returned MTM and its time |
| Max Drawdown | Largest decline from a running peak in that intraday series |

The **Intraday PnL Curve** draws MTM and drawdown together. Hover and navigate the chart to inspect values. The current-MTM percentage shown by this UI uses a fixed INR 100,000 reference; it is not a return calculated from your broker balance or invested capital.

Use **Refresh** to fetch the current series and **Screenshot** to download an image of the summary and curve. The current page has no date-range picker, per-strategy/per-symbol breakdown, CSV/Excel export, win-rate or Sharpe-ratio report. Use the order/trade books and [Tools](../31-tools/README.md) for their respective records and analyses.

## Interpret Results Carefully

The series depends on the active mode, broker data and the underlying P&L service. Compare it with account positions and the broker terminal when investigating a discrepancy. An unavailable or delayed series is not proof that the account is flat, and MTM is not an instruction to close positions.

If loading fails, read the error, confirm the broker/session and current Live/Analyze mode, then use Refresh. See [Positions & Holdings](../14-positions-holdings/README.md) and [Analyzer Mode](../15-analyzer-mode/README.md).

---

**Previous**: [23 - Telegram Bot](../23-telegram-bot/README.md)

**Next**: [25 - Latency Monitor](../25-latency-monitor/README.md)
