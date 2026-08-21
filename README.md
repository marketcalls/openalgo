# lean-strategies

Private strategy repository that runs against a sibling Lean engine checkout.

## Expected folder layout

- /Users/arifkhan/github/Lean
- /Users/arifkhan/github/lean-strategies

If your layout is different, set LEAN_REPO or LEAN_LAUNCHER_DIR in environment.

## One-time setup

1. Build Lean engine once:
   dotnet build /Users/arifkhan/github/Lean/QuantConnect.Lean.sln /p:Configuration=Debug /p:DebugType=portable /p:WarningLevel=1
2. In this repo, create .env from .env.example and set your IB values.
3. Make scripts executable:
   chmod +x scripts/*.sh

Python runtime is auto-detected from /Users/arifkhan/github/Lean/.conda/lean-py311.
If your environment is different, set PYTHON_VENV and PYTHONNET_PYDLL in .env.

## Python strategy state

New Python strategies must persist recoverable state through
`strategies.python.common.StrategyStateStore`. The helper writes a versioned
Object Store envelope with a strategy ID, runtime scope, update timestamp, and
a strategy-owned payload. It does not define a universal trade schema.

```python
from strategies.python.common.strategy_state import StrategyStateStore

self.state_store = StrategyStateStore(
   self.object_store,
   "my-strategy",
   "paper",
   1,
   lambda: {"trades": {}},
)
result = self.state_store.load()
if result.is_valid:
   self.state = result.payload
elif result.status in {"corrupt", "incompatible"}:
   # Block new entries until strategy-specific reconciliation completes.
   self.state_reconciliation_required = True
else:
   self.state = result.payload
```

Use a stable strategy ID and a separate scope for paper/live deployments. Save
after every durable lifecycle change, reconcile restored state against Lean
portfolio and order data before allowing a new entry, and write migrations in
the owning strategy when its payload schema changes. Corrupt or incompatible
records must fail closed: retain them and block new entries until reconciliation
resolves the situation. Never store brokerage credentials, tokens, or account
secrets in strategy state.

## Run a backtest

scripts/run-backtest.sh strategies/python/HelloLeanStrategy.py HelloLeanStrategy

The second argument is optional. If omitted, class name defaults to file name without .py.

After a successful backtest, the script now:
1. Archives the run under results/runs/<run-id>/
2. Updates results/index.json (all previous runs)
3. Starts the Streamlit visualizer at http://localhost:3000 and auto-opens the browser

Use the run history list in the visualizer sidebar to open any previous run.

Environment flags:
- VISUALIZER_PORT=3000 (default)
- VISUALIZER_ENABLED=true (default). Set to false to skip visualizer startup.
- VISUALIZER_OPEN=true (default). Set to false to run headless.
- VISUALIZER_RUN_ID=<run-id> optional default run selection.
- VISUALIZER_RESULTS_DIR=<path> optional results directory override.

Run history is retained indefinitely unless you manually delete entries from results/runs/ and results/index.json.

## Start visualizer separately

If you already have archived runs and want to start only the visualizer:

- macOS/Linux:
   scripts/run-visualizer.sh

- Windows:
   scripts\run-visualizer.cmd

Optional arguments/env:
- pass port as first argument, e.g. scripts/run-visualizer.sh 3010
- VISUALIZER_PORT=3000 (default)
- VISUALIZER_OPEN=true to auto-open browser
- VISUALIZER_RUN_ID=<run-id> to open a specific run

### Streamlit dependency

Install Streamlit in your Python environment if needed:

python -m pip install streamlit

## Grafana live performance dashboard

The repo includes a local Grafana/Prometheus setup for monitoring a live Lean strategy run.

What it monitors:
- Strategy running status
- Equity
- Net profit
- Unrealized profit
- Fees
- Holdings value
- Order count and filled order events
- Lean status file freshness

The metrics source is Lean's local live result files in `/Users/arifkhan/github/Lean/Launcher/bin/Debug`, especially:

- `MesSimpleBuySellTestStrategy.json`
- `MesSimpleBuySellTestStrategy-order-events.json`

### One-time install

Install Grafana and Prometheus with Homebrew:

```bash
scripts/install-grafana-stack.sh
```

### Start the dashboard stack

Use three terminals:

```bash
scripts/run-metrics-exporter.sh MesSimpleBuySellTestStrategy
```

```bash
scripts/run-prometheus.sh
```

```bash
scripts/run-grafana.sh
```

Then open:

```text
http://127.0.0.1:3001/d/mes-live-performance/mes-live-strategy-performance
```

Grafana is provisioned from repo-local files:

- `config/prometheus/prometheus.yml`
- `config/grafana/provisioning/datasources/prometheus.yml`
- `config/grafana/provisioning/dashboards/dashboards.yml`
- `config/grafana/dashboards/mes-live-performance.json`

The exporter endpoint is:

```text
http://127.0.0.1:9108/metrics
```

Prometheus is available at:

```text
http://127.0.0.1:9090
```

Grafana data/log/plugin state is stored under `.tmp/grafana`, and Prometheus TSDB state is stored under `.tmp/prometheus`.

## Run live locally with IB Gateway

This repo is configured to run Lean live against an already-open local IB Gateway/TWS session.
It does not require a QuantConnect cloud job or Lean API connection for the local live run.

1. Start IB Gateway or TWS manually.
2. Enable API access in IB Gateway/TWS.
3. Confirm the socket host and port in `.env`.
   - Paper Gateway is usually `127.0.0.1:4002`.
   - Live Gateway is usually `127.0.0.1:4001`.
4. Confirm `IB_ACCOUNT` matches the account shown by IB Gateway/TWS.
5. Run in paper mode:

```bash
LIVE_CONFIRM=true IB_TRADING_MODE=paper scripts/run-live-ib.sh strategies/python/MesSimpleBuySellTestStrategy.py MesSimpleBuySellTestStrategy
```

For real live trading, two confirmations are required:

```bash
LIVE_CONFIRM=true LIVE_CONFIRM_REAL=true IB_TRADING_MODE=live scripts/run-live-ib.sh strategies/python/MesSimpleBuySellTestStrategy.py MesSimpleBuySellTestStrategy
```

Inline environment variables override `.env`, so `IB_TRADING_MODE=paper ...` is safe even if `.env` contains `IB_TRADING_MODE=live`.

### Local IB live configuration

The live template at `config/templates/live-interactive.template.json` pins the local live engine path:

- `job-user-id`, `api-access-token`, and `job-organization-id` are blanked.
- `lean-manager-type` is `LocalLeanManager`.
- `data-feed-handler` is `LiveTradingDataFeed`.
- `data-queue-handler` is `InteractiveBrokersBrokerage`.
- `data-provider` is `DefaultDataProvider`.
- `ib-skip-subscription-validation` is `true`.
- `ib-use-existing-gateway` is `true`.

The last two flags are supported by the local Interactive Brokers brokerage DLL. They skip QuantConnect product-subscription validation and connect to the existing Gateway socket instead of trying to launch Gateway from a default install path.

### Start IB Gateway with IBAutomater

By default, `.env` uses:

```bash
IB_USE_EXISTING_GATEWAY=true
```

That tells the local IB brokerage to connect to an already-open Gateway/TWS session and skip IBAutomater.

To have Lean start/manage IB Gateway through IBAutomater, set:

```bash
IB_USE_EXISTING_GATEWAY=false
IB_USER_NAME=your_ib_username
IB_PASSWORD=your_ib_password
IB_TWS_DIR=/Users/arifkhan/Jts
IB_VERSION=1046
IB_TRADING_MODE=paper
IB_HOST=127.0.0.1
IB_PORT=4002
```

You can update those values interactively without printing the password:

```bash
scripts/set-ib-credentials.sh
```

Then run:

```bash
LIVE_CONFIRM=true IB_USE_EXISTING_GATEWAY=false IB_TRADING_MODE=paper scripts/run-live-ib.sh strategies/python/MesSimpleBuySellTestStrategy.py MesSimpleBuySellTestStrategy
```

Notes:
- `IB_TWS_DIR` must be the local IB Gateway/TWS install folder. On macOS/Linux the usual default is `~/Jts`; on Windows it is usually `C:\Jts`.
- `IB_VERSION` must match the installed Gateway build folder/version expected by IBAutomater.
- This Mac has IB Gateway 10.46 installed at `/Users/arifkhan/Applications/IB Gateway 10.46`. IBAutomater expects a Unix-style launcher at `/Users/arifkhan/ibgateway/ibgateway`, so this setup includes a small wrapper there plus symlinks to the 10.46 `.install4j`, `jars`, `data`, and app resources.
- If another IB Gateway/TWS session is already open, IBAutomater may fail or detect the existing session. Close other IB sessions before using Automater.
- Two-factor authentication may still require your manual approval during login or weekly restart.
- Keep `ib-skip-subscription-validation=true` in the generated config for local Lean runs that should not call QuantConnect subscription validation.

If you rebuild or replace Lean, rebuild the local IB brokerage and copy the DLL into the Lean launcher output:

```bash
dotnet build /Users/arifkhan/github/Lean.Brokerages.InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage/QuantConnect.InteractiveBrokersBrokerage.csproj /p:Configuration=Debug
cp /Users/arifkhan/github/Lean.Brokerages.InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage/bin/Debug/QuantConnect.Brokerages.InteractiveBrokers.dll /Users/arifkhan/github/Lean/Launcher/bin/Debug/
cp /Users/arifkhan/github/Lean.Brokerages.InteractiveBrokers/QuantConnect.InteractiveBrokersBrokerage/bin/Debug/QuantConnect.Brokerages.InteractiveBrokers.pdb /Users/arifkhan/github/Lean/Launcher/bin/Debug/
```

### MES buy/sell test strategy (paper-live)

What it does:
- Trades 1 MES contract
- Enters every 30 minutes during 09:35-15:55 ET when flat
- Exits after 10 minutes
- Waits 20 minutes before next entry

During a successful local paper run, the logs should show:

- `ValidateSubscription(): Skipping Interactive Brokers subscription validation for local run.`
- `Using existing IB Gateway/TWS session.`
- `InteractiveBrokersBrokerage.Connect(): IB next valid id received.`
- `LiveTradingResultHandler.SendStatusUpdate(): status: 'Running'.  100`

After a live run starts writing artifacts, archive and open it in the visualizer:

scripts/ingest-visualizer.sh MesSimpleBuySellTestStrategy

You can run that command repeatedly while the live strategy is running to capture updated performance snapshots in `results/runs/`.

## Security notes

- Keep .env private and never commit it.
- Generated runtime config lives in .tmp and is git-ignored.
- Prefer connecting to an already-open Gateway via host/port.
- Do not keep IB credentials in `.env` unless you intentionally want Lean to automate Gateway login.
- `IB_TRADING_MODE=live` is blocked unless `LIVE_CONFIRM_REAL=true` is also set.

## Run live locally with FYERS

This repo can run Lean live against the local FYERS brokerage project at:

```text
/Users/arifkhan/github/Lean-Brokerages/Lean.Brokerages.Fyers/QuantConnect.FyersBrokerage
```

The runner builds that brokerage project, copies the FYERS plugin DLL and required FYERS dependencies into `/Users/arifkhan/github/Lean/Launcher/bin/Debug`, generates `.tmp/live-fyers.config.json`, and starts Lean with `FyersBrokerage` as both the live brokerage and data queue handler.

Required `.env` values:

```bash
FYERS_CLIENT_ID=
FYERS_SECRET_KEY=
```

Optional useful values:

```bash
FYERS_ACCESS_TOKEN=
FYERS_REFRESH_TOKEN=
FYERS_ACCOUNT_ID=
FYERS_TEST_SYMBOL=SBIN
FYERS_PLACE_TEST_ORDER=false
FYERS_TEST_QUANTITY=1
FYERS_TEST_HOLD_MINUTES=2
```

Connect and subscribe only:

```bash
LIVE_CONFIRM=true scripts/run-live-fyers.sh
```

Submit one guarded live test order:

```bash
LIVE_CONFIRM=true LIVE_CONFIRM_FYERS_ORDER=true FYERS_PLACE_TEST_ORDER=true scripts/run-live-fyers.sh
```

The default strategy is `strategies/python/FyersBrokerageSmokeTestStrategy.py`. It subscribes to one NSE equity symbol, logs live heartbeats, and only places an order when `FYERS_PLACE_TEST_ORDER=true`.

The FYERS brokerage factory was adjusted to read the `fyers-*` values from Lean config, so values generated from `.env` are passed into the live job instead of using placeholder defaults.


### Command to activate leans conda environment
````
conda activate /Users/arifkhan/github/Lean/.conda/lean-py311
````
