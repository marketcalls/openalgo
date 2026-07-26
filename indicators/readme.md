# indicators/

Everything the indicator skills generate lives here. Each skill writes into its
own subfolder, so scripts, results and cached data never mix.

```
indicators/
  charts/       chart scripts written by /indicator-chart
  scanners/     scanner scripts written by /indicator-scanner
  custom/       reusable indicator modules written by /custom-indicator
  dashboards/   Dash and Streamlit apps written by /indicator-dashboard
  feeds/        live WebSocket scripts written by /live-feed
  data/         cached OHLCV pulled from the broker (gitignored)
  output/       rendered artifacts: .html charts, .png, scan result .csv (gitignored)
```

## Naming

One file per artifact, named `<indicator>_<symbol>_<interval>.py` so a folder
stays scannable as it grows:

```
indicators/charts/ema_SBIN_D.py
indicators/charts/rsi_RELIANCE_1h.py
indicators/scanners/rsi_oversold_nifty50.py
indicators/custom/squeeze_momentum.py
indicators/dashboards/multi_timeframe_RELIANCE.py
indicators/feeds/ltp_SBIN.py
```

Rendered output goes to `output/` under the same stem, so a script and its
artifact stay associated without cluttering the source folder:

```
indicators/charts/ema_SBIN_D.py              ->  indicators/output/ema_SBIN_D.html
indicators/scanners/rsi_oversold_nifty50.py  ->  indicators/output/rsi_oversold_nifty50.csv
```

## What is tracked

**Nothing in here except this readme.** `.gitignore` carries:

```
indicators/*
!indicators/readme.md
```

Everything the skills generate is scratch work — reproducible from the skill
that produced it — and cached market data does not belong in git. That keeps
the repo clean no matter how much you experiment.

Consequence: the subfolders do not exist on a fresh clone. The skills
`mkdir -p` their own folder before writing, so you never need to create them by
hand.

If a custom indicator in `custom/` graduates into something the platform should
ship, move it into the codebase proper rather than un-ignoring it here.

## Using a different folder

`indicators/` is the default, not a requirement. Tell any indicator skill where
to write and it will use that path instead — "put the chart in `research/q3/`"
or "write the scanner to `/tmp/scans`". The skill creates the folder and keeps
the same subfolder layout beneath it.

A path outside `indicators/` is **not** covered by the gitignore rule above, so
check whether you want those artifacts tracked before pointing a skill at a
directory inside the repo.

## Running

From the repo root, using OpenAlgo's own environment — there is no separate
venv to activate:

```bash
uv run --group analysis python indicators/charts/ema_SBIN_D.py
uv run --group analysis streamlit run indicators/dashboards/multi_timeframe_RELIANCE.py
```

Scripts that only need `openalgo`, `pandas`, `numpy` or `plotly` can drop the
`--group analysis` flag — those are already main dependencies.

See `.claude/skills/indicator-setup/` for environment setup.
