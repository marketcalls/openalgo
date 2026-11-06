# 07 - Dashboard Overview

## Open the Dashboard

After connecting a broker, open `/dashboard` or choose **Dashboard** in the navigation bar. It shows funds from the current execution mode and the status of the symbol master download.

## Account Cards

| Card | What it shows |
|---|---|
| Available Balance | Available cash returned by the funds service |
| Collateral | Collateral value returned by the funds service |
| Unrealized P&L | Mark-to-market P&L on open positions |
| Realized P&L | Booked P&L |
| Utilised Margin | Margin currently used |

Values and availability depend on the broker's normalized funds response. In **Analyze** mode these cards use sandbox funds. They are not a statement of your entire portfolio's value.

Funds load when the page opens and refresh after relevant order events and mode changes. The Dashboard does not promise a fixed 30-second funds refresh or a streaming position P&L view. Use [Positions](../14-positions-holdings/README.md) and the [PnL Tracker](../24-pnl-tracker/README.md) for those workflows.

## Master Contract Status

The master-contract indicator shows **Checking**, **Downloading**, **Ready** (with a symbol count when available), or **Error**. OpenAlgo checks its status every five seconds until it is ready. Wait for readiness before searching for contracts or starting strategies that need symbol mappings.

Use **Master Contract** from the profile menu to inspect the download. If it fails, check your broker connection and application logs.

## Quick Access

Dashboard cards link to OpenAlgo Symbols, Live Logs, Documentation, P&L Tracker, API Playground and Getting Started. The header provides the broker badge where space permits, the **Live/Analyze** badge and mode control, theme toggle and profile menu.

The mode applies across this single-user instance. Turning Analyze off sends supported subsequent order requests to the live broker. Check running strategies and open positions before changing it; see [Analyzer Mode](../15-analyzer-mode/README.md).

## When Data Does Not Load

- If the broker session expired, reconnect from **Select Broker** (`/broker`). OpenAlgo can retain your application sign-in while asking for a fresh broker login.
- If the application sign-in expired, sign in again.
- If funds return an error, read its message and the logs before placing an order. A zero value is not proof of a valid broker connection.
- If symbols are missing, wait for the master contract to finish or inspect its error.

See [Understanding the Interface](../08-understanding-interface/README.md) for navigation and [Broker Connection](../06-broker-connection/README.md) for switching and multi-device session behavior.

---

**Previous**: [06 - Broker Connection](../06-broker-connection/README.md)

**Next**: [08 - Understanding the Interface](../08-understanding-interface/README.md)
