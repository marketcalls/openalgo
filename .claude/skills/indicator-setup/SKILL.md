---
name: indicator-setup
description: Set up the Python environment for OpenAlgo indicator analysis. Installs openalgo, plotly, dash, streamlit, yfinance, matplotlib, seaborn, and creates the project folder structure.
argument-hint: "[python-version]"
allowed-tools: Bash, Read, Write, Glob, AskUserQuestion
---

Set up the complete Python environment for OpenAlgo indicator analysis, charting, and dashboard development.

## Arguments

- `$0` = Python version (optional, default: `python3`). Examples: `python3.12`, `python3.13`

**Note**: openalgo 2.x requires **Python 3.12 or newer** (3.12 / 3.13 / 3.14). Check the version before creating the venv and abort with a clear message if it is older:

```bash
python3 --version   # must be 3.12+
```

## Steps

### Step 1: Detect Operating System

```bash
uname -s 2>/dev/null || echo "Windows"
```

Map: `Darwin` = macOS, `Linux` = Linux, `MINGW*`/`CYGWIN*`/`Windows` = Windows.

### Step 2: Create Virtual Environment

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
```

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
pip install --upgrade pip
```

If user specified a Python version argument, use that instead of `python3`.

### Step 3: Install Python Packages

Install all required packages:

```bash
pip install openalgo yfinance plotly dash dash-bootstrap-components streamlit numpy pandas python-dotenv websocket-client httpx scipy nbformat matplotlib seaborn ipywidgets
```

### Step 4: Create Project Folders

Create only the top-level directories. Subdirectories are created on-demand by other skills.

```bash
mkdir -p charts dashboards custom_indicators scanners
```

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
python -c "
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
- Python version used
- Virtual environment path
- Installed packages and versions
- Project folders created
- `.env` file status
- Available skills: `/indicator-chart`, `/custom-indicator`, `/indicator-dashboard`, `/indicator-scanner`, `/live-feed`

## Important Notes

- Never install packages globally — always use the virtual environment
- If the user already has a virtual environment, ask before creating a new one
- NEVER commit `.env` files — they contain API keys
- `python-dotenv` is used by all scripts to load `.env` via `find_dotenv()`
- openalgo 2.x indicators run on a compiled Rust core inside the wheel — no JIT compilation or warmup; requires Python 3.12+
