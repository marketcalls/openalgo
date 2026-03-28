$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $root "src"
python -c "from pathlib import Path; from data.prepare_market_data import prepare_file; root=Path(r'D:\TV_proj\output\reliance_timeframes'); path=root/'RELIANCE_15m_5029bars.csv'; out=Path(r'$root')/'examples'/'prepared_output'; print(prepare_file(path, out, 'RELIANCE', '15m'))"
