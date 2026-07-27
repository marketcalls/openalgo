# dashboards/

Dash and Streamlit apps from `/indicator-dashboard`.

```bash
uv run --group analysis python workspace/indicators/dashboards/app.py
uv run --group analysis streamlit run workspace/indicators/dashboards/app.py
```

Match the refresh interval to the broker's quote rate limit. A 5-second refresh
across 20 symbols is 240 requests/minute, above several brokers' caps — batch
into one multi-quote call rather than looping.
