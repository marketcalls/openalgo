# feeds/

Live WebSocket scripts from `/live-feed`.

Named `<mode>_<symbol>.py` — e.g. `ltp_SBIN.py`, `depth_NIFTY.py`.

Aggregate ticks into bars before computing indicators; a 20-period EMA
recomputed per tick is meaningless and a CPU sink at 1000+ ticks/second.

These hold sockets open — run the `fd-audit` skill on anything long-lived.
