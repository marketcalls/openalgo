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

## Run a backtest

scripts/run-backtest.sh strategies/python/HelloLeanStrategy.py HelloLeanStrategy

The second argument is optional. If omitted, class name defaults to file name without .py.

After a successful backtest, the script now:
1. Archives the run under results/runs/<run-id>/
2. Updates results/index.json (all previous runs)
3. Starts the visualizer at http://localhost:3000 and auto-opens the browser

Use the run history list in the visualizer sidebar to open any previous run.

Environment flags:
- VISUALIZER_PORT=3000 (default)
- VISUALIZER_ENABLED=true (default). Set to false to skip visualizer startup.

Run history is retained indefinitely unless you manually delete entries from results/runs/ and results/index.json.

## Run live with IB Gateway

1. Start IB Gateway and enable API access.
2. Confirm host and port in .env (typically 127.0.0.1:4002 for paper).
3. Run with explicit safety confirmation:
   LIVE_CONFIRM=true scripts/run-live-ib.sh strategies/python/HelloLeanStrategy.py HelloLeanStrategy

## Security notes

- Keep .env private and never commit it.
- Generated runtime config lives in .tmp and is git-ignored.
- Prefer API session auth via gateway host/port and avoid storing IB password unless required.
