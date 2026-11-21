# SDK gotchas, operations and content rules

## SDK gotchas

- Load the API key in the shell with `set -a; . ./.env; set +a` in the research
  project; `python-dotenv` may not be installed there. Then
  `api(api_key=os.environ["OPENALGO_API_KEY"], host=os.environ["OPENALGO_HOST"])`.
- `history(symbol, exchange, interval, start_date, end_date)`; dates as
  `YYYY-MM-DD`. Intraday intervals like `1m`, `5m`, `1h`; daily is `D`.
- NFO symbol formats:
  - Futures: `NIFTY27OCT26FUT` (underlying + DDMMMYY + FUT).
  - Options: `NIFTY19OCT26<strike>CE` / `PE`, for example `NIFTY19OCT2624000CE`.
  - Weekly and monthly expiries use the same DDMMMYY form; take the real
    expiry dates from `expiry()` or the master contract, never compute them.
- `optionchain(underlying, exchange, expiry_date, strike_count)`: `exchange` is
  the underlying's exchange (`NSE_INDEX` for NIFTY), `expiry_date` is `DDMMMYY`.
- Tickers get renamed (for example after a company rename); search with
  `search` or the master contract when a symbol returns nothing.

## Operations

- Restart only the app, never the machine:
  `cd <repo> && nohup setsid script -qfec "uv run app.py" app.log >/dev/null 2>&1 &`.
- Weekly upgrade on Sunday 6:00 AM IST ([weekly-upgrade.md](weekly-upgrade.md)).
- Daily 8:00 AM IST broker login only for Indian brokers (sessions expire
  around 3:00 AM IST). Crypto brokers need no daily login.
- Do the broker login only in that routine unless the user asks; other routines
  (Historify verify, reports) should report a disconnected broker, not log in.
- Never push, merge or open PRs on the user's repos without their go-ahead.

## Content rules for public posts

- Never name a broker in public content (articles, posts, screenshots) and
  never show funds, margins or account balances. Crop broker badges out of
  screenshots.
- Market posts: analysis, statistics and factual summary only; no
  recommendations or levels framing.
- Never post or send anything externally without the user's explicit ask.
