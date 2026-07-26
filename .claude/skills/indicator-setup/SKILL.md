---
name: indicator-setup
description: Set up the Python environment for OpenAlgo indicator analysis. Installs openalgo, plotly, dash, streamlit, yfinance, matplotlib, seaborn, and creates the project folder structure.
allowed-tools: Bash, Read, Write, Glob, AskUserQuestion
---

Set up the complete Python environment for OpenAlgo indicator analysis, charting, and dashboard development.

## Arguments

**None.** This skill takes no Python-version argument.

It used to, back when it built a standalone venv. Now that it uses OpenAlgo's
own project environment, the interpreter is the repo's to decide — pinned by
`requires-python = ">=3.12"` in `pyproject.toml` and by the existing `.venv`.
Re-pinning the shared environment from an analysis skill would rebuild the
application's venv on a different interpreter, which is a good way to break the
running platform.

If the project environment genuinely needs a different interpreter, that is a
deliberate repo-level change: `uv sync -p 3.13` from the repo root, made
knowingly and not as a side effect of setting up charting.

Confirm what you have:

```bash
uv run python -V     # must be 3.12+; openalgo 2.x supports 3.12 / 3.13 / 3.14
```

## Steps

### Step 1: Detect Operating System

```bash
uname -s 2>/dev/null || echo "Windows"
```

Map: `Darwin` = macOS, `Linux` = Linux, `MINGW*`/`CYGWIN*`/`Windows` = Windows.

### Step 2: Use OpenAlgo's existing environment

**Do not create a separate venv.** Work inside the OpenAlgo repo and use its
own uv-managed environment — the platform already ships more than half of what
indicator analysis needs, and `CLAUDE.md` mandates `uv run` with no
hand-managed virtualenvs.

Already present as main dependencies, nothing to install:

`openalgo` (which bundles the Rust-backed `ta` library), `plotly`, `pandas`,
`numpy`, `python-dotenv`, `websocket-client`, `httpx`, `nbformat`

The remainder live in an opt-in `analysis` dependency group in
`pyproject.toml`, so charting and dashboard packages never reach a production
install:

```bash
uv sync --group analysis
```

That installs `dash`, `dash-bootstrap-components`, `ipywidgets`, `matplotlib`,
`scipy`, `seaborn`, `streamlit` and `yfinance`.

**To pull the newest releases**, re-resolve rather than reinstalling:

```bash
uv sync --group analysis --upgrade
```

The group uses `>=` constraints, so a plain sync already gives you the latest
compatible release; `--upgrade` additionally re-resolves transitive pins in
`uv.lock`. Run it whenever you want to move forward deliberately.

If a package is genuinely one-off and not worth adding to the group, use
`uv run --with <pkg>` for an ephemeral install instead of editing
`pyproject.toml`.

### Step 3: Running anything

Every command in these skills runs through uv, from the repo root. There is no
environment to activate:

```bash
uv run --group analysis python your_script.py
uv run --group analysis streamlit run app.py
```

Only scripts that touch the analysis packages need `--group analysis`; anything
using just `openalgo`, `pandas`, `numpy` or `plotly` runs under a plain
`uv run python`.

Verify the environment before going further:

```bash
uv run --group analysis python -c "
from openalgo import ta
import dash, streamlit, yfinance, scipy, matplotlib, seaborn
print(f'ta indicators: {len([f for f in dir(ta) if not f.startswith(chr(95))])}')
print('analysis stack ready')"
```

Expect 127 indicators from `openalgo.ta` — it ships in the base package, so
there is no extra to request.

### Step 4: Output folders

Everything the indicator skills generate goes under **`workspace/indicators/`** in the
repo root, one subfolder per artifact type:

```
workspace/indicators/
  charts/       chart scripts        (/indicator-chart)
  scanners/     scanner scripts      (/indicator-scanner)
  custom/       indicator modules    (/custom-indicator)
  dashboards/   Dash / Streamlit     (/indicator-dashboard)
  feeds/        live WebSocket        (/live-feed)
  data/         cached OHLCV
  output/       rendered .html / .png / .csv
```

Every folder ships a tracked `readme.md`, so the tree exists after a clone —
git does not track empty directories, and the readme is what keeps each one
present. Everything else under `workspace/` is gitignored, so nothing you
generate is ever committed by accident.

Skills still `mkdir -p` the folder they need before writing, so a deleted
folder is recreated on demand.

**The location is overridable.** If the user names a different folder, use it
and keep the same subfolder layout beneath it. Only `workspace/` carries the
gitignore rule, so if the user points at another path inside the repo, say so
before writing there.

See `workspace/readme.md` for the naming convention.

### Step 5: Configure .env File

**5a. Ask the user for their OpenAlgo API key** using AskUserQuestion:
- "Enter your OpenAlgo API key (from the OpenAlgo dashboard at /apikey):"

**5b. Ask for the OpenAlgo host URL:**
- Default: `http://127.0.0.1:5000`
- If user has a custom domain or ngrok URL, use that

**5c. Optionally ask about WebSocket URL:**
- Default: derived from host automatically
- Only needed if user has a custom WebSocket setup

**5d. Write the `.env` file** in the project root:

```
# OpenAlgo API Configuration
OPENALGO_API_KEY={user_provided_key or "your_openalgo_api_key_here"}
OPENALGO_HOST={user_provided_host or "http://127.0.0.1:5000"}

# WebSocket (optional - auto-derived from host if not set)
# OPENALGO_WS_URL=ws://127.0.0.1:8765
```

**5e. Add `.env` to `.gitignore`:**

```bash
grep -qxF '.env' .gitignore 2>/dev/null || echo '.env' >> .gitignore
```

### Step 6: Verify Installation

```bash
uv run --group analysis python -c "
import openalgo
from openalgo import ta
import plotly
import dash
import streamlit
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
import seaborn
import nbformat
from dotenv import load_dotenv
print('All packages installed successfully')
print(f'  openalgo: {openalgo.__version__}')
print(f'  plotly: {plotly.__version__}')
print(f'  dash: {dash.__version__}')
print(f'  streamlit: {streamlit.__version__}')
print(f'  numpy: {np.__version__}')
print(f'  pandas: {pd.__version__}')
print(f'  matplotlib: {matplotlib.__version__}')
print(f'  seaborn: {seaborn.__version__}')

# Quick indicator test
close = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 104.0, 103.0, 102.0, 101.0])
ema = ta.ema(close, 3)
rsi = ta.rsi(close, 5)
print(f'  ta.ema test: {ema[-1]:.2f}')
print(f'  ta.rsi test: {rsi[-1]:.2f}')
print('Indicator library ready')
"
```

### Step 7: Print Summary

Print a summary showing:
- Detected OS
- Python version reported by `uv run python -V`
- Environment: OpenAlgo's own uv-managed .venv (no separate venv)
- Installed packages and versions
- Output location: workspace/indicators/ (created on demand)
- `.env` file status
- Available skills: `/indicator-chart`, `/custom-indicator`, `/indicator-dashboard`, `/indicator-scanner`, `/live-feed`

## Important Notes

- Never install packages globally and never create a separate venv — use OpenAlgo's uv environment with `uv run`
- Analysis-only packages belong in the `analysis` dependency group, never the main list, so they never ship to production
- NEVER commit `.env` files — they contain API keys
- `python-dotenv` is used by all scripts to load `.env` via `find_dotenv()`
- openalgo 2.x indicators run on a compiled Rust core inside the wheel — no JIT compilation or warmup; requires Python 3.12+
