# charts/

Chart scripts from `/indicator-chart`.

Named `<indicator>_<symbol>_<interval>.py` — e.g. `ema_SBIN_D.py`,
`rsi_RELIANCE_1h.py`. The rendered HTML goes to `../output/` under the same
stem, so the script and its artifact stay associated without cluttering this
folder.

```bash
uv run --group analysis python workspace/indicators/charts/ema_SBIN_D.py
```
