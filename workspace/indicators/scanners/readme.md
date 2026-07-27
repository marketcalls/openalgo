# scanners/

Multi-symbol scanner scripts from `/indicator-scanner`.

Named `<condition>_<watchlist>.py` — e.g. `rsi_oversold_nifty50.py`. Result
CSVs go to `../output/` under the same stem.

Before trusting an empty result, seed the scan with a symbol you have already
confirmed meets the condition. An empty result set and a broken scanner look
identical.
