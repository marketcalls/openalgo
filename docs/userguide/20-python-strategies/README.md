# 20 - Python Strategies

## Choose How to Run Python

OpenAlgo supports external Python clients and the built-in **Python Strategies** host at `/python`. Both use the same OpenAlgo API; the host additionally stores scripts, starts subprocesses, schedules them and shows their logs.

For SDK methods, request fields and complete examples, use the [Python SDK reference](<../../prompt/openalgo python sdk.md>). Methods include `placeorder`, `placesmartorder` and `basketorder`; they do not use underscores. Python `openalgo.ta` indicators are separate from JavaScript [chart indicators](../../custom-indicators.md) and [OpenScript](../../openscript.md).

## Upload a Hosted Strategy

1. Connect the intended broker and generate an [OpenAlgo API key](../09-api-key-management/README.md).
2. Open **Python Strategies** from the profile menu, or visit `/python`.
3. Choose **Add Strategy**, supply a name and upload a `.py` file (up to 1 MB). The page also offers an Example Strategy Template you can copy and edit.
4. Choose the **Exchange**. The selector follows the broker's supported exchanges and initially uses its default. This choice controls the host's holiday calendar and trading window; your script must still send the correct symbol and exchange in each API request.
5. Set the mandatory schedule and upload. Review the saved schedule on the strategy card before starting.

Scripts are stored under `strategies/scripts/`; configuration is under `strategies/strategy_configs.json`. On Docker, the `strategies` volume preserves them across container rebuilds.

## Schedule and Start

All schedule times are **IST**. For securities exchanges, the host follows the calendar database, including holidays, partial sessions and special sessions. A run stops at the earlier of its configured stop time or that exchange's session close. Do not assume every exchange follows NSE hours.

**Start** can start a strategy immediately within its eligible window or mark it **Scheduled** to start later. Read the returned message and card status: Scheduled is not proof that a process is already running. **Cancel** cancels a scheduled auto-start; **Stop** ends a running process. The schedule is mandatory and can be edited rather than disabled.

The master contract must be ready before a strategy starts. If strategies are waiting for it, the list offers a check/start action. Logs show what happened after startup; a successful start response alone does not prove that the script remained running or placed a trade.

### Crypto and Run 24/7

For the `CRYPTO` exchange, **Run 24/7** runs across all seven days without a stop time or Indian-exchange holiday checks. It is available on both New Strategy and Edit Schedule; the card displays **24/7**. Turn it off to choose particular days and hours. A timed crypto window may cross midnight; identical start and stop times are refused, so use Run 24/7 when no daily stop is intended.

The host's 24/7 schedule does not renew expired broker credentials or make your script's own market-hours checks disappear. Broker connectivity and the script's trading logic must also support continuous operation.

## Edit and Control a Strategy

Open a card's editor at `/python/<strategyId>/edit`.

| Control | Behavior |
|---|---|
| Save / `Ctrl+S` or `Cmd+S` | Save edits to the file the next process will run |
| Reset | Discard edits back to the last saved content |
| Start | Start the saved file; save or discard unsaved changes first |
| Stop | End a running strategy process |
| Cancel | Cancel a scheduled auto-start |
| View Logs | Open the log viewer; save or discard unsaved edits before leaving |
| Fullscreen / `F11` | Expand the editor; `Esc` leaves fullscreen |
| Export | Download the saved version or the server's current-content version |

Start/Stop/Cancel and View Logs remain available in fullscreen. A running strategy opens read-only; stop it before editing or saving. Edit Schedule also refuses changes while a strategy is running.

**Stopping the Python process is not a position-close instruction.** Implement and verify your own exit behavior and check positions/orders at the broker after stopping. Logging out does not stop hosted strategies. Broker switching is refused while live automation that binds the current broker is still running; see [Broker Connection](../06-broker-connection/README.md).

## Connect From the Script

The host supplies `STRATEGY_ID`, `STRATEGY_NAME`, `OPENALGO_STRATEGY_EXCHANGE`, `OPENALGO_HOST` and, when available, `OPENALGO_API_KEY` to the subprocess. Keep credentials out of source files:

```python
import os
from openalgo import api

client = api(
    api_key=os.environ['OPENALGO_API_KEY'],
    host=os.environ['OPENALGO_HOST'],
)
print(client.ping())
```

Install dependencies in the environment used by OpenAlgo; the host does not create a separate virtual environment per strategy. Strategy-specific environment settings are available from the strategy list. Python files execute as programs on your server; review code before uploading it.

## Logs and Recovery

**View Logs** opens `/python/<strategyId>/logs`. Standard output and errors are written to per-run files under `log/strategies/`, with timestamps in IST. Use the viewer to inspect startup errors, missing packages, authentication failures and your own diagnostic messages. Stop a strategy before clearing its logs.

On a server restart, the host restores schedules and reconciles saved running strategies. That is process recovery, not proof that your script can reconstruct its position safely. Reconcile broker orders and positions before letting a restarted script send new entries.

## Rehearse Before Live Trading

1. Enable **Analyze** and verify the header badge before starting the script.
2. Check sandbox order book, trades, positions and funds, plus the strategy's log.
3. Exercise entry, exit, schedule boundaries and a restart with your script's position-recovery logic.
4. Stop the rehearsal and reconcile positions before changing execution mode.
5. For Live, verify broker/account, instrument, product and quantity again and watch the broker terminal.

A timeout, dropped connection or missing order ID can leave an order's outcome unknown. Do not automatically resend an order after an unclear response: check the order book, trade book and positions first. Basket requests may have partial outcomes. Semi-Auto queue success is also not a fill; check [Action Center](../22-action-center/README.md).

For host internals and endpoint contracts, see [Python Strategies](../../prd/python-strategies.md), [scheduling](../../prd/python-strategies-scheduling.md) and [API reference](../../prd/python-strategies-api-reference.md).

---

**Previous**: [19 - GoCharting Integration](../19-gocharting-integration/README.md)

**Next**: [21 - Flow Visual Builder](../21-flow-visual-builder/README.md)
