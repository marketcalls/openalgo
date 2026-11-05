# Live-hardening pass, verification, and cheat-sheet

## The live-hardening pass (where the real bugs are)

Scaffolding from docs gets you ~70%. The remaining 30% — the part that decides
whether the broker *works* — only falls to **live probing**. Arrow's
integration had SIX such bugs (auth field names, exchange codes, strike
scaling, websocket offsets, index quote vocabulary, multiquote cap), and not
one was visible in the code review. Budget a deliberate hardening pass.

1. **Probe with throwaway scripts, fix, then codify.** Keep a scratch dir
   OUTSIDE the repo. Pull the stored token once and hit the live endpoint
   directly with httpx, varying one thing at a time:

   ```python
   from database.auth_db import Auth, get_auth_token
   row = Auth.query.filter_by(broker="<name>", is_revoked=False).first()
   token = get_auth_token(row.name)   # then httpx.post(...) with candidates
   ```

   Probe matrices that pay off: symbol spelling variants x exchange-code
   variants for one instrument per segment; batch sizes (binary search) for
   multi-instrument endpoints; one quote per exchange you claim to support.

2. **Read `log/errors.jsonl` first** when a UI page breaks. Five "different"
   broken tools (option chain, IV chart, OI tracker, max pain, GEX) were ONE
   root cause: index quotes 400ing. Fix the deepest shared failure, not the
   page.

3. **Don't edit broker files while a background download is running** — the
   dev server auto-reloads on save and kills in-flight threads (worst case:
   between `delete_symtoken_table()` and the re-insert). Wait for the
   `master_contract_status` table to flip to `success`, then edit.

4. **Verify like-for-like after refactors**: when you rewrite a working path
   for speed (e.g. vectorizing the master contract), diff the new output
   against the validated output row-by-row before swapping it in.

5. **Resolve every `TODO(<name>)` with live evidence, then delete it** —
   replace each with a comment stating what was verified and how ("verified
   live: 100 -> 200 OK, 101 -> 500"). The next person must be able to tell
   guesses from facts.

## Static verification

```bash
# Compile + lint
uv run python -m py_compile broker/<name>/**/*.py
uv run ruff check broker/<name>/

# Import in NORMAL flow (websocket_proxy first to avoid the adapter
# circular-import that trips ALL brokers on direct-first import)
uv run python -c "from dotenv import load_dotenv; load_dotenv(); import websocket_proxy; \
from websocket_proxy.broker_factory import _get_adapter_class; \
print(_get_adapter_class('<name>').__name__)"

# FD/pooling audit — must be empty
grep -rnE 'httpx\.Client\(|requests\.|urllib|aiohttp' broker/<name>/
```

Then run the **`fd-audit`** skill on the whole change.

## Nuance cheat-sheet (the easy-to-miss list)

**Auth and wiring**
- [ ] `authenticate_broker` exact name; returns 2-tuple `(token, error)`
- [ ] signature arity matches the login model (1 arg OAuth vs 3 args TOTP/direct)
- [ ] error half may be a dict, not a string (fyers) — don't string-format it
- [ ] auth payload uses the broker's LITERAL JSON keys (verbatim curl/SDK, not prose)
- [ ] `BROKER_API_KEY` `:::` composite parsed in the right field order, with a clear error message
- [ ] callback param spelling (`auth_code` / `request-token` / camelCase) handled in `brlogin.py`
- [ ] feed_token/user_id brokers added to the explicit list in `brlogin.py`
- [ ] `REDIRECT_URL` exactly matches the broker portal and ends `/<broker>/callback`
- [ ] every success path in the branch returns `_complete_login(...)`, never `handle_auth_success` or `upsert_auth` directly (it uses up the pending login and runs the commit's checks)
- [ ] the broker sends and returns a `state` when it can, and is in `STATE_BROKERS`; a broker that posts from its own site is also in `BROKER_SITE_POST_BROKERS` with the state on its return address
- [ ] a form broker's POST carries the page's `csrf_token` and works only after a login started from Select Broker
- [ ] an account the broker reports is taken from its own answer for the token or exchange, never a posted label or an unverified JWT claim; a different account is refused (`account_mismatch`), and a configured one it does not confirm too (`account_unverified`); the verified account is passed as `user_id`
- [ ] a new refusal code has its fixed sentence in `LOGIN_ERRORS` (`frontend/src/pages/BrokerSelect.tsx`) and its test
- [ ] no thread started inside the login reads the keys (it would read the process's, another broker's during a switch); token read before key read in any code that calls the broker with both
- [ ] the callback's credential query parameter is masked by `utils/url_redaction._QUERY_CREDENTIAL` (checked with `.claude/skills/verify/redaction_check.py`)
- [ ] the `utils/broker_setup_guide.py` `sign_in` kind matches where the login goes (`test_the_setup_guide_matches_where_each_login_goes` passes)
- [ ] any identity endpoint the login relies on was proven against a real account, and the account is reported on every login or never
- [ ] sign-in address and setup-guide entry taken from OpenAlgo Desktop's `origin/master`, not a local checkout
- [ ] login tests assert the endpoint and header that reached the transport, with races landed at the write (`upsert_auth`), not before the checks

**Master contract**
- [ ] instrumenttype indices = **EQ** (there is no INDEX type)
- [ ] expiry `DD-MMM-YY` uppercase; empty string for EQ/index
- [ ] `name` = underlying for derivatives
- [ ] `contract_value` column declared (even if left NULL)
- [ ] real instrument file downloaded and segment codes counted BEFORE writing the parser
- [ ] strike scaling checked **per segment** (often differs for currency)
- [ ] vectorized, not `iterrows()`; output diffed against a known-good run
- [ ] `db_session.remove()` in a `finally` (runs in a background thread)

**Data**
- [ ] price de-scaling (paise x100) in quotes/depth/history
- [ ] history **daily/weekly/monthly +5:30**, intraday no shift
- [ ] NSE_INDEX/BSE_INDEX translated to the broker's index exchange on quote/depth/history
- [ ] index quote symbol vocabulary probed live (candidate-fallback + per-token cache if it differs from brsymbol)
- [ ] quote-unsupported exchanges fail fast AND are skipped in batch requests
- [ ] `get_multiquotes` implemented and chunked at the broker's PER-REQUEST cap (from the docs if published, else probed) + throttled under the rate limit; history throttled
- [ ] per-endpoint caps respected if LTP/OHLC/full differ (zerodha: 500 vs 1000)
- [ ] per-category rate limits respected (quote limits are often far tighter than order limits)
- [ ] `BrokerData.__init__` takes a second `feed_token` param only if the broker truly has one

**Orders and account**
- [ ] `place_order_api` sets `response.status`
- [ ] MARKET and SL-M emulated if the broker lacks them, using `utils/mpp_slab.py` slabs — see `order-type-emulation.md`
- [ ] SL-M limit on the correct side of the trigger, tick-snapped, >= one tick past
- [ ] emulation live-tested on a **cheap option** as well as equity (percentage slabs differ sharply)
- [ ] account-data output field names match `docs/api/account-services/*`
- [ ] `order_status` lowercased to open/complete/cancelled/rejected/trigger pending
- [ ] margin: single -> order calculator, multi-leg -> basket calculator (Dhan pattern); never sum legs when a basket endpoint exists
- [ ] `gtt_api.py` only if the broker supports GTT (the capability gate returns 501 otherwise)

**Streaming**
- [ ] sync `websocket-client`, never asyncio
- [ ] no `thread.join()` on daemon threads
- [ ] `cleanup_zmq()` in `disconnect()`
- [ ] fresh token re-read on reconnect (`bypass_cache=True`)
- [ ] keepalive + data-stall watchdog
- [ ] binary offsets taken from the SDK, validated with synthetic `struct.pack` packets
- [ ] order-update adapter registered in `services/order_update_service.py` `_BROKER_FACTORIES` (or broker added to `_POLLING_BROKERS`)
- [ ] postback + broker feed deduplicated on `orderid` + `order_status` + `filled_quantity`

**General**
- [ ] NO hardcoded market timings in the broker folder
- [ ] all REST via the shared pooled httpx client; explicit timeout on big downloads
- [ ] broker id added to `.sample.env` VALID_BROKERS + the `start.sh` fallback + READMEs + `utils/broker_login.py` + `utils/broker_keys.BROKER_NAMES` + a `utils/broker_setup_guide.py` entry + websocket_proxy registration (Select Broker lists brokers from `/api/broker/list`, so there is no frontend list; the installers carry none either and take VALID_BROKERS from `.sample.env`)
- [ ] `start.sh` (repo root, the Docker `CMD`) — the `${VALID_BROKERS:-...}` fallback. **Functional, not cosmetic**: missing here means the broker is unavailable on cloud/Railway deploys while every bare-metal install works
- [ ] `install/Docker-install-readme.md` table row added (markdown table, not a comma list)
- [ ] login start: the broker in `CALLBACK_START_BROKERS` or a `login_url()` branch in `utils/broker_login.py`; `STATE_BROKERS` / `BROKER_SITE_POST_BROKERS` where its answer needs them
- [ ] credentials read at call time, never at module import (keys change when the trader switches brokers; see `auth-and-login.md`)
- [ ] a real login completed end to end: the callback refuses an answer it cannot match to a started login
- [ ] frontend: if form-login, a `brokerFields` entry **and** a `brokerNames` entry in `BrokerTOTP.tsx` (unconfigured brokers silently fall back to a userid/password/totp `default` that may be the wrong fields)
- [ ] verified with one sweep: `grep -rn "<newbroker>" install/ start.sh .sample.env README.md frontend/src/pages/BrokerTOTP.tsx utils/broker_login.py utils/broker_keys.py utils/broker_setup_guide.py websocket_proxy/__init__.py`
- [ ] no emojis or icons anywhere (repo-wide rule)

## Live test plan (needs credentials + SEBI static-IP whitelisting)

- [ ] Login -> token stored -> master contract downloads -> symbols searchable
- [ ] Master contract validated offline BEFORE the in-app run: per-exchange row
      counts, sample symbols per segment vs `docs/prompt/symbol-format.md`,
      zero duplicate `(symbol, exchange)`, all common index symbols present
- [ ] Quotes / depth for EQ, FUT, option on **EVERY** exchange in `plugin.json`
      (not just NSE — Arrow's MCX needed a different code and CDS/NCO turned
      out unsupported) + NSE_INDEX/BSE_INDEX
- [ ] Multiquotes at realistic size (180+ option symbols — what the GEX tool
      sends) and mixed exchanges including an index
- [ ] History intraday + daily (epoch convention) for EQ, FUT, index
- [ ] `/websocket/test` page: LTP, Quote (real OHLC/volume — a wrong close
      like 0.02 means a binary-offset bug) and Depth including indices;
      reconnect after a forced drop
- [ ] `/websocket/test/20`, `/30`, `/50` for every depth level your
      `get_supported_depth_levels()` claims — an over-declared level surfaces
      as a client-side `UNSUPPORTED_DEPTH_LEVEL` error, not a server failure
- [ ] `/websocket/order` page: place an order and confirm a live `order_update`
      event with correct OpenAlgo symbol, lowercase status, and filled/pending
      quantities; check a rejection carries `rejection_reason`. If the broker
      has no order feed, confirm the polling fallback still emits events.
- [ ] Options tools end-to-end: `/optionchain`, `/ivchart`, `/oitracker`,
      `/maxpain`, `/gex` — these exercise quotes + multiquotes + expiry
      parsing together and fail loudly on any index-quote or batch-cap bug
- [ ] Margin: single order (vs the docs' example numbers), multi-leg straddle
      (basket number must be LESS than the per-leg sum), invalid symbol -> clean 400
- [ ] Place / modify / cancel / smart order; orderbook / positions / holdings / funds
- [ ] Every price type end to end: MARKET, LIMIT, SL, SL-M — BUY and SELL, on
      equity **and** a low-priced option. Confirm a MARKET order actually fills
      (not resting) and an SL-M actually **rests** (does not fire on placement)
- [ ] Analyze mode is NOT a test of your integration — it routes to the sandbox
      and never calls broker code
- [ ] Resolve all `TODO(<name>)` markers using observed live responses, then delete them
