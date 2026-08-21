# SPX 1:45 PM Sandwich — Native LEAN + IB Gateway/IBAutomater Deployment Plan

## Objective

Prepare and run the Option Alpha `1:45pm Sandwich` strategy as a QuantConnect LEAN Python algorithm on a MacBook, using Interactive Brokers Gateway through `IBAutomater`, with a path to reproducible deployment on another macOS or Linux server.

The strategy repository is:

```text
/Users/arifkhan/github/lean-strategies
```

The LEAN source and launcher repository is:

```text
/Users/arifkhan/github/Lean
```

The Interactive Brokers brokerage source is:

```text
/Users/arifkhan/github/Lean-Brokerages/Lean.Brokerages.InteractiveBrokers
```

## Strategy being reproduced

The source behavior shown in the Option Alpha bot must be treated as a specification to verify, not as a complete implementation specification. The currently visible strategy summary is:

- Name: `1:45pm Sandwich`.
- Instrument: SPX 0DTE iron condor, expected to use same-day-expiring `SPXW` contracts in LEAN.
- Entry window: 1:45 PM–2:00 PM New York time.
- Trading days: Monday, Tuesday, Thursday, and Friday; Wednesday is excluded.
- Structure: $10-wide iron condor; short put and short call are $5 below and above the reference SPX price; each long wing is $5 beyond its short leg.
- Filter: VIX below 24 at entry.
- Entry quality: minimum reward/risk of 100%.
- Holding period: the bot notes indicate holding to expiration.
- Safeguards: $2,500 allocation, one position per day, and one position at a time.

Before coding, record the exact Option Alpha behavior for these unresolved items:

1. Whether the reference price is the SPX index price, midpoint, last trade, or another value.
2. Strike rounding and the exact option symbols/expiration selected.
3. Whether “100% reward/risk” means credit divided by defined risk, and whether fees/slippage are included.
4. Order type, limit-price logic, fill timeout, partial-fill handling, and cancellation behavior.
5. Whether the position is held through settlement or closed before the final trading cutoff.
6. The exact exit-options rules, which are enabled in the bot but not fully visible in the summary.
7. Position quantity and how the $2,500 allocation is translated into contracts and margin.
8. The VIX symbol/data source and the timestamp used for the filter.

The closed positions strongly suggest that item 3 is `credit / (500 - credit)` for a one-lot $10-wide condor, subject to confirmation from the scanner and backtest configuration.

The Entry Scanner was subsequently inspected. Its market-condition decision is explicitly:

- `Market closes at 4:00PM today`.
- `VIX is between 0 - 24`.

The scanner then proceeds to `Open Position` when the bot-level daily/open-position safeguard allows it. The bot is configured to scan every minute, and Exit Options are enabled at a one-minute scan speed; the detailed exit workflow still needs to be opened and verified before enabling any early-exit logic in LEAN.

Do not enable live orders until these rules are documented and reproduced in paper trading.

## QuantConnect implementation design

Create a dedicated strategy folder rather than extending the existing order-flow strategy:

```text
strategies/python/spx_1_45pm_sandwich/
├── Spx1_45PmSandwichStrategy.py
├── .env.example
├── README.md
└── run-live.sh
```

The algorithm should:

1. Subscribe to `SPX` and `SPXW` at minute resolution, with a 0DTE option filter.
2. Use New York exchange time for the schedule and explicitly skip Wednesday.
3. Evaluate the VIX threshold and reference-price rule during the entry window.
4. Select the four strikes deterministically and log the selected symbols, expiry, reference price, credit, maximum risk, and reward/risk calculation.
5. Enforce one entry per day, one open position, and the configured allocation limit inside the algorithm as well as through broker safeguards.
6. Submit the four-leg order atomically where supported, otherwise use a guarded legging workflow that cancels and neutralizes incomplete structures.
7. Persist an order/position state machine so reconnects and process restarts cannot duplicate an entry.
8. Implement the verified exit policy and an emergency flattening policy before expiration/settlement.
9. Expose parameters for paper testing, with order placement enabled by default in paper mode; decision-only mode remains available through an explicit override.

The existing `spx_0dte_orderflow_profile` strategy is not this strategy: it uses SPY order-flow proxies and directional spreads. Reuse its SPXW subscription, Grafana, and runner patterns only after checking each behavior.

## Closed-position evidence reviewed

The bot’s Positions view was reviewed through the visible closed-position history. Forty loaded trades from June 8 through August 18 were all shown as:

- `SPX Iron Condor`, quantity 1, DTE `0`.
- Four legs with $5 strike spacing: long call, short call, short put, long put. For example, `7,710 C / 7,705 C / 7,695 P / 7,690 P`. Relative to the displayed `7,701.34` opening price, this indicates strikes are selected on the $5 grid around the price rather than being exactly five index points away.
- Expiry status on every reviewed trade; there was no evidence of a discretionary early close in this sample.
- Premium credited at entry and defined risk equal to approximately `$500 - premium × 100` for one $5-wing condor. A `$2.55` credit produced `$255` premium and `$245` risk.
- The displayed ROR is consistent with `premium / defined risk`: `$2.65` credit with `$235` risk displayed approximately `112.8%` ROR.
- Trades with `--` close price appear to have expired fully out of the money and retain the entry premium. Trades with a `$5.00` close price incurred the full remaining defined risk for that credit.
- The reviewed sample contained 18 profitable and 22 losing trades, with displayed aggregate P/L of approximately `$1,515` and average P/L of approximately `$37.88` per position. This is an observation of the loaded paper-trading history, not a performance claim or a complete backtest.

These observations tighten the implementation requirements: use a five-point wing on each side, calculate defined risk per spread, require the configured 100% premium-to-risk threshold, and model expiration settlement explicitly. The remaining history should be loaded and exported before using performance statistics for validation.

## Strategy acceptance tests

Paper-mode tests must cover:

| Test | Expected result |
|---|---|
| Wednesday session | No order is submitted |
| Before 1:45 PM ET | No entry evaluation/order |
| 1:45–2:00 PM ET with VIX ≥ 24 | No order |
| Valid VIX and valid strikes | Correct $10-wide SPXW 0DTE condor is constructed |
| Reward/risk below 100% | No order |
| One position already open | No second order |
| Daily position already used | No second order |
| Credit/margin exceeds allocation | No order |
| Missing or stale option quotes | No order and clear warning |
| Partial/rejected multi-leg order | No unhedged position remains |
| LEAN restart with an open position | State is reconciled; no duplicate entry |
| Expiration/exit event | Verified exit policy runs exactly once |

The first milestone is a paper account run that logs every decision and submits a controlled paper order. A decision-only diagnostic mode remains available with `SPX_SANDWICH_PLACE_ORDERS=false`. Real-money trading requires a separate approval and remains disabled by default.

## Target architecture

```text
macOS launchd / Linux systemd
              |
              v
Strategy runner in lean-strategies
              |
              v
LEAN Launcher
              |
              v
InteractiveBrokersBrokerage
              |
              v
IBAutomater
              |
              v
IB Gateway
              |
              v
Interactive Brokers
```

### MacBook operating model

The primary deployment target is a logged-in macOS user session because IB Gateway/IBAutomater may require access to the user’s GUI/session for login and weekly 2FA. Use one `launchd` user agent for the strategy, not a root daemon. Keep the Mac awake during the trading window and configure the service to start only after the user session and network are available.

On macOS, install the repository-managed `deploy/macos/IBAutomater.sh` wrapper with `scripts/install-macos-ibautomater.sh`. The wrapper launches the native Gateway in the existing user session and must not use Linux `ps` flags, Xvfb, or broad Java-process termination.

The live runner now selects the Gateway path automatically: if the configured IB host/port is already listening, LEAN connects to that Gateway and disables IBAutomater for the run; otherwise it enables IBAutomater so it can launch and authenticate Gateway. The Interactive Brokers brokerage plugin honors `ib-use-existing-gateway` and skips its scheduled Gateway restart tasks when using an externally running Gateway.

The service must have a single owner for the full process tree:

```text
launchd user agent
  └── run-live.sh
      └── LEAN
          └── IBAutomater
              └── IB Gateway
```

Do not combine a manually started Gateway with managed mode. Do not run multiple strategies with the same IB login and client ID unless the account and Gateway configuration explicitly support it.

The operating-system service keeps LEAN alive after terminal closure, crashes, and reboots. `IBAutomater` owns the IB Gateway process, login, gateway restart events, and gateway output. LEAN owns the API socket, heartbeat, data subscriptions, orders, and state restoration.

## Important operating assumptions

1. Docker is not used.
2. IB Gateway is not started manually in managed mode.
3. Managed mode means the brokerage itself starts IB Gateway through IBAutomater.
4. Existing-Gateway mode is supported only after the brokerage source explicitly implements it. The current checked-out brokerage always constructs and starts IBAutomater, so this mode is currently a blocker and must not be represented as working configuration.
5. IB Gateway performs daily automatic restarts Monday through Saturday when auto-restart is enabled.
6. IB requires re-authentication after the Saturday server reset, normally requiring IBKR Mobile/IB Key confirmation on Sunday.
7. LEAN and Gateway must run under the same user/session when the IB Gateway installation requires a GUI session.
8. Only one active IB API session should use the same IB login unless the account setup explicitly supports multiple sessions.

## Existing components to reuse

- `scripts/run-live-ib.sh`
- `scripts/common.sh`
- `config/templates/live-interactive.template.json`
- `scripts/set-ib-credentials.sh`
- `/Users/arifkhan/github/Lean/Launcher/bin/Debug/QuantConnect.Lean.Launcher.dll`
- The compiled `QuantConnect.Brokerages.InteractiveBrokers.dll`

Do not create a second independent IB login daemon. The brokerage contains the intended managed IBAutomater lifecycle, including startup, heartbeat recovery, Gateway exit handling, and weekly restart scheduling. Verify the compiled DLL matches the source before deployment.

## Current gaps to resolve first

### 1. Align brokerage and runner versions

The checked-out brokerage source always instantiates and starts `IBAutomater` during initialization. It does not currently consume `ib-use-existing-gateway`. Either implement and test existing-Gateway mode in the brokerage, or remove that mode from the supported deployment contract. The source, compiled DLL, `QuantConnect.IBAutomater` package, CSharp API assembly, and LEAN runtime must be built and tested as one versioned set.

### 2. Correct the brokerage source path

The actual brokerage checkout is:

```text
/Users/arifkhan/github/Lean-Brokerages/Lean.Brokerages.InteractiveBrokers
```

Any scripts or README commands referencing `/Users/arifkhan/github/Lean.Brokerages.InteractiveBrokers` must be corrected or replaced with a configurable `IB_BROKERAGE_REPO` value.

### 3. Remove credentials from generated config files

The current runner generates a temporary JSON configuration containing the IB password. Improve it so that:

- `.env` is permission-protected;
- credentials are never committed;
- generated config files are created in `.tmp` with restrictive permissions;
- generated configs are removed on exit;
- passwords are never printed in logs;
- migration packages exclude `.env`, password-bearing configs, and IB session tokens.

The runner must use `umask 077`, create the generated config atomically, install a cleanup trap for normal exit and signals, and avoid printing account numbers or credentials. A crash or power loss can still leave a file behind, so the startup path must also remove stale generated configs owned by the current user.

### 4. Pin dependencies

Replace floating package versions such as `2.5.*` with a tested version set, or record the exact resolved package versions. The Lean engine, brokerage DLL, CSharp API assembly, and `IBAutomater` version must be upgraded together.

## Configuration contract

Use repository-level defaults and strategy-level overrides.

Example `.env.example`:

```bash
# Runtime paths
LEAN_REPO=/Users/arifkhan/github/Lean
IB_BROKERAGE_REPO=/Users/arifkhan/github/Lean-Brokerages/Lean.Brokerages.InteractiveBrokers
LEAN_CONFIGURATION=Debug

# IB connection
IB_USE_EXISTING_GATEWAY=false
IB_HOST=127.0.0.1
IB_PORT=4002
IB_VERSION=1046
IB_TWS_DIR=/Users/arifkhan/Jts
IB_TRADING_MODE=paper
IB_CLIENT_ID=8
IB_WEEKLY_RESTART_UTC_TIME=21:00:00
IB_ACCOUNT=replace_me
IB_USER_NAME=replace_me
IB_PASSWORD=replace_me

# Safety gates
LIVE_CONFIRM=false
LIVE_CONFIRM_REAL=false
```

For a migrated server, only the machine-specific paths, Gateway version, Python runtime, and secrets should need changing.

## Implementation phases

### Phase 0: Reproduce and paper-test the strategy

- Capture the complete Option Alpha entry and exit scanner settings, including all conditions hidden behind the Entry Scanner and Exit Options controls.
- Implement `Spx1_45PmSandwichStrategy` in its dedicated folder.
- Run the strategy in IB paper mode as the incubation phase using the same session window, weekdays, VIX filter, strike construction, reward/risk rule, and expiration behavior.
- Add decision logs and metrics before enabling order placement.
- Confirm the algorithm’s allocation and position limits independently of the broker UI.

Acceptance criteria:

- The strategy produces an auditable decision for every eligible session.
- No orders are submitted on Wednesday, outside the entry window, or when VIX/reward-risk conditions fail.
- Paper incubation results are reconciled against the Option Alpha behavior for a known sample of dates.

Backtests may still be used for debugging, but are not part of the operational performance history.

## Incubation-to-live performance history

The performance dashboard must exclude backtest data. It tracks two operational phases only:

1. **Incubation:** actual IB paper-account equity, P/L, fills, drawdown, and position history.
2. **Live:** actual IB live-account equity, P/L, fills, drawdown, and position history after production cutover.

Prometheus storage and strategy event snapshots must persist across MacBook restarts. Record a `LIVE_CUTOVER_UTC` timestamp when switching to live mode and display it as a dashboard annotation. Keep incubation and live series separate with an `account_mode` label; do not add paper equity to live equity. A chronological view may show both phases with a visible transition marker, but each phase’s values remain authoritative.

### Phase 1: Establish a reproducible native build

- Build `/Users/arifkhan/github/Lean` from source.
- Build the Interactive Brokers brokerage against that LEAN version.
- Copy or publish the brokerage DLL and required dependencies into the launcher output.
- Record SDK, .NET, Python, brokerage, and `IBAutomater` versions.
- Add a script that validates all required binaries before starting live trading.
- Record exact Git commit SHAs and resolved NuGet versions; do not rely on `2.5.*` package ranges.

Acceptance criteria:

- `dotnet build` succeeds for LEAN.
- The brokerage DLL is present in the launcher output.
- A paper-mode smoke test loads the Interactive Brokers brokerage.

### Phase 2: Make managed IB Gateway startup reliable

- Configure `IBAutomater` with username, password, paper/live mode, Gateway directory, and Gateway version.
- Verify the Gateway installation layout expected by `IBAutomater`.
- Ensure no second Gateway/TWS session is already using the same login.
- Capture Gateway stdout/stderr into the strategy log directory.
- Test startup with both paper and live configuration, keeping live mode disabled by default.
- Use a strategy-specific client ID and verify the brokerage actually honors it; the current brokerage hardcodes client ID `0`.

Acceptance criteria:

- Starting the runner with no Gateway process starts Gateway automatically.
- LEAN receives the IB next-valid-order ID.
- Account and holdings download completes.
- The strategy reaches `Running` state.

### Phase 3: Handle daily and weekly IB resets

- Enable Gateway auto-restart.
- Retain the brokerage heartbeat and reconnect behavior.
- Retain the brokerage gateway-exit handler.
- Configure a Sunday weekly restart time that is convenient for manual IBKR Mobile confirmation.
- Log reset codes `1100`, `1101`, and `1102` distinctly.
- Treat 2FA timeout as an operator action, not an infinite blind retry.

Acceptance criteria:

- A Gateway restart causes LEAN to reconnect.
- Market-data subscriptions are restored after connectivity loss.
- Existing holdings and open orders are reloaded safely.
- Missing Sunday authentication produces a clear alert and does not silently submit orders.

### Phase 4: Add native process supervision

Create:

```text
deploy/macos/com.quantconnect.lean.<strategy>.plist
deploy/linux/lean-live-<strategy>.service
scripts/install-native-service.sh
scripts/uninstall-native-service.sh
scripts/status-live-ib.sh
```

macOS `launchd` requirements:

- `RunAtLoad=true`
- `KeepAlive=true`
- absolute working directory
- absolute executable paths
- persistent stdout/stderr logs
- environment file or generated environment dictionary

Linux `systemd` requirements:

- `Restart=always`
- `RestartSec=30`
- `After=network-online.target`
- `Wants=network-online.target`
- dedicated service user
- persistent log directory

The service must restart LEAN if LEAN exits. It must not launch a second LEAN instance while an existing one is running.

For macOS, install a per-user LaunchAgent with a strategy-specific label, `RunAtLoad`, `KeepAlive`, absolute paths, and persistent logs. Add a lock/PID check in the runner. Use bounded restart behavior for authentication failures so a bad password or missing 2FA does not create an endless restart loop.

### Phase 5: Add health checks

Implement a health script that checks:

- LEAN process existence;
- IB Gateway process existence;
- API port availability;
- recent LEAN log modification time;
- latest heartbeat/reconnect message;
- latest market-data timestamp;
- repeated gateway exits;
- 2FA or authentication failure indicators.

Exit codes should distinguish healthy, degraded, and stopped states so a future monitor can alert reliably.

### Phase 6: Validate migration

Create a migration bundle containing:

```text
strategy source
runner scripts
config templates
service templates
dependency/version manifest
brokerage build instructions
health-check instructions
```

Do not include:

```text
.env
IB passwords
IB session tokens
live result secrets
private API keys
```

Test migration on a clean server by changing only environment-specific paths and credentials.

## Required runner behavior

The strategy runner must:

1. Resolve paths from its own location.
2. Load repository `.env` first and strategy `.env` second; preserve variables exported before startup.
3. Preserve explicitly exported shell variables.
4. Default to paper trading.
5. Require `LIVE_CONFIRM=true` for any live run.
6. Require `LIVE_CONFIRM_REAL=true` for real-money mode.
7. Validate LEAN, the brokerage DLL, IBAutomater, CSharpAPI, Python runtime, and dependency manifest before launching.
8. Generate a strategy-specific config file.
9. Remove generated configs after exit and clean stale configs at startup.
10. Write logs, Gateway output, and live results to persistent strategy-specific directories.
11. Print the LEAN PID, managed-process status, API host/port, mode, and log locations without exposing secrets.
12. Return LEAN's exit code to `launchd` or `systemd`.

## Validation test matrix

| Test | Expected result |
|---|---|
| Managed paper mode with no Gateway process | LEAN starts exactly one Gateway through IBAutomater |
| Gateway already running, existing-gateway mode | Blocked until brokerage support is implemented; never silently start a second Gateway |
| Gateway absent, managed mode | LEAN starts Gateway through `IBAutomater` |
| Wrong password | Startup fails clearly; no endless restart loop |
| Gateway API port unavailable | Retry and report connection failure |
| Gateway daily restart | LEAN reconnects and restores subscriptions |
| IB error 1100 | Connection marked unavailable and recovery begins |
| IB error 1101 | Reconnect and restore subscriptions |
| IB error 1102 | Reconnect without unnecessary subscription loss |
| Gateway process crash | `IBAutomater`/service restarts it and LEAN reconnects |
| LEAN process crash | `launchd`/`systemd` restarts LEAN |
| Sunday 2FA approved | Session resumes normally |
| Sunday 2FA missed | Clear degraded/stopped state and operator alert |
| Host reboot | Service starts LEAN and managed Gateway |
| Migration to another server | Only paths/secrets require changes |

The strategy-specific matrix in Phase 0 is required in addition to these infrastructure tests. Infrastructure recovery is not sufficient if a reconnect or process restart can duplicate an expiring SPX position.

## Definition of done

- `Spx1_45PmSandwichStrategy` runs natively from its dedicated `lean-strategies` folder.
- The strategy’s entry and exit behavior is documented from the Option Alpha scanner settings and reconciled with paper-incubation evidence.
- SPXW 0DTE strike selection, VIX filtering, reward/risk gating, weekday schedule, allocation, and one-position limits are covered by tests.
- IB Gateway starts automatically through `IBAutomater`.
- Credentials are supplied securely and are not committed or logged.
- Daily Gateway restart and LEAN reconnect are tested.
- Weekly IBKR Mobile authentication is documented and observable.
- LEAN restarts automatically after process failure or host reboot.
- macOS and Linux service templates exist.
- A clean-server migration test succeeds.
- Paper-incubation tests pass before any live-money test is enabled.
- The performance dashboard contains incubation and live data only, with a visible live cutover marker and durable history across restarts.
- The MacBook LaunchAgent starts one supervised LEAN/IBAutomater process tree after login and stops safely on authentication/2FA failure.
