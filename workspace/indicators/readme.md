# workspace/indicators/

Output from the indicator skills. Each subfolder holds one artifact type; the
skills create what they need with `mkdir -p` and write here by default.

| Folder | Written by | Contents |
| --- | --- | --- |
| `charts/` | `/indicator-chart` | chart scripts |
| `scanners/` | `/indicator-scanner` | scanner scripts |
| `custom/` | `/custom-indicator` | reusable indicator modules |
| `dashboards/` | `/indicator-dashboard` | Dash and Streamlit apps |
| `feeds/` | `/live-feed` | live WebSocket scripts |
| `data/` | any | cached OHLCV |
| `output/` | any | rendered .html, .png, .csv |

Naming: `<indicator>_<symbol>_<interval>.py`, with rendered artifacts in
`output/` sharing the stem.

Run from the repo root:

```bash
uv run --group analysis python workspace/indicators/charts/ema_SBIN_D.py
```
