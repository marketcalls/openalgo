$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $root "src"
python -c "from feedback.daily_retrain import run_daily_retrain; print(run_daily_retrain(r'$root\\examples\\sample_market_data.csv', r'$root\\examples\\sample_paper_trade_log.csv', r'$root\\examples\\feedback_store.csv'))"
