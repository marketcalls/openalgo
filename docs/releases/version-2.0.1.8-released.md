# Version 2.0.1.8 Released

**Date: 3rd August 2026**

**Security and Portfolio Release: fixes a high-severity account-takeover vector in the password reset flow (GHSA-pmxj-9wx6-hjmf); adds the Portfolio Backtester, Portfolio Analyzer and SIP Backtester to `/tools`; extends Flow with indicator, timeframe, calendar and order-update nodes plus per-strategy P&L; brings live order-update WebSockets to the four remaining Noren brokers; and corrects available-cash reporting across seven brokers**

This release spans 147 commits since 2.0.1.7. **Every deployment should upgrade** — it closes a high-severity password-reset vulnerability that allowed full account takeover from an unauthenticated request (details below). Beyond the security work, the `/tools` suite grew from 15 to 18 with a substantial **portfolio and investment analytics** effort: a full backtest engine with composable charge schedules, rebalancing-rule comparison, walk-forward and Monte Carlo validation, crisis-period analysis back to 1995, and a downloadable tearsheet; a **Portfolio Analyzer** that runs the same analytics against the holdings actually held at your broker; and a **SIP Backtester** for NSE and BSE with XIRR and statutory charges. **Flow** gained indicator, timeframe, calendar and order-update nodes, a per-strategy position book with real P&L, and a central validation pass over every execution entry point after a QA audit. On the broker side, **Shoonya, Flattrade, Zebu and Tradesmart** all gained live order-update WebSocket feeds over the Noren protocol, completing that family; **SL-M order handling** was corrected across the Noren brokers so a stop order is never silently downgraded; and a systematic pass over **funds and holdings** fixed available-cash reporting on Zerodha, Upstox, Dhan, Fyers and Angel, where several brokers were reporting net margin rather than actual withdrawable cash.

---

**Highlights**

* **Security: host header poisoning in password reset (`d22eef2d2`, GHSA-pmxj-9wx6-hjmf)** — the password reset link was built with `url_for(..., _external=True)`, which derives its host from the request's `Host` header. With no `SERVER_NAME`, no `ProxyFix` and no trusted-host validation anywhere in the codebase — and nginx forwarding `Host $host` unvalidated — an unauthenticated attacker could poison that header so the reset email pointed at an origin they controlled, capturing the token when the account owner clicked it. A second, more direct path was found while fixing it: the raw reset token was stored in the Flask session, which is a signed but **unencrypted** cookie, so whoever triggered the reset could base64-decode their own cookie and read the token with no Host trickery and no victim interaction at all, needing only the target's email address. Outbound links now build from the configured `HOST_SERVER` via a new `utils.config.build_external_url()` (also applied to the RMoney OAuth callback in `blueprints/brlogin.py`, which shared the pattern), and the session stores only a SHA-256 hash compared with `secrets.compare_digest()`. Reported by tonghuaroot.
* **Security: `react-router` 8.3.0 (`e4240ef0c`, GHSA-qwww-vcr4-c8h2)** — upgraded past a published advisory.
* **Portfolio Backtester (`76a4876ba`, `672c670e9`, `2f13f65c9`, `bf5366c7d` + ~30 follow-ups)** — a full backtest engine at `/portfolio-backtester`: charges modelled as a composable schedule rather than hardcoded Indian taxes, direct DuckDB reads with a price cache, crisis periods extended back to 1995, every rebalancing rule compared side by side, walk-forward and Monte Carlo validation wired into the report, portfolio structure derived from co-movement instead of invented sectors, itemised per-symbol P&L, correlation matrices, investor metrics, a transparent Portfolio Health score showing its working, SWOT findings each carrying the number behind it, and a downloadable openstatz tearsheet (`b17b358a7`). Unadjusted corporate actions are detected rather than assumed (`abca4d3f9`), and cost drag was made exact and validated against real data (`78bb07d24`).
* **Portfolio Analyzer (`9c8a82eba`, `8e7df5850`, `48a4adbfd`)** — runs the same analytics against the portfolio actually held at the broker, sourcing prices from either Historify or the broker API, with performance attribution separating selection from allocation (`61c0c6dd9`), per-asset trailing returns and a correlation matrix (`13f4044c3`), and a crisis timeline matching the backtester (`8b2816eef`).
* **SIP Backtester (`ee2cb7584`, `d989d2b82`, `be8e75113`, `7d54eebe8`)** — SIP backtesting for NSE and BSE with XIRR and statutory charges, close-to-close monthly returns, crisis-period analysis, and whole-share purchases carrying the remainder forward, since India has no fractional shares.
* **Flow: new nodes and per-strategy P&L (`c4d40f101`, `ba4dc214c`, `940476892`, `ff42cc954`)** — indicator, timeframe and order-update nodes; a calendar node detecting new day, week, month and quarter; a per-strategy position book reporting real P&L instead of an unknown strategy silently reading as zero (`49f41120e`); a bar-count ceiling with indicator lookback and history-as-series; logic gates now wait for all inputs and evaluate exactly once per run (`7bbc56f25`, `f26bee1cc`); and in-flight history fetches are shared with waiters rather than duplicated (`efdb65f75`).
* **Flow: execution validation and alert lifecycle (`0477e2cfb`, `edec9171d`, `ee1dee1bd`, `6abf6cdaa`)** — every execution entry point is now centrally validated, stale price-alert runs stopped, alert thresholds validated, and order sizing, prices and broken nodes corrected following a QA audit. Workflows can be replaced from JSON and honor special sessions (`ca5d1e8dc`).
* **Noren brokers: live order-update WebSockets (`ad404c83e`, `6ce8e89e0`, `5880f24ad`, `1284fa202`)** — Shoonya, Flattrade, Zebu and Tradesmart all gained live order/trade update feeds over the Noren order WebSocket, completing the family.
* **Noren brokers: SL-M order correctness (`d5d1d0b3f`, `cd020ecab`, `392075987`, `137a24e8f`, `fce8c3a0f`)** — an SL-M order no longer falls through as SL-MKT, the fallback limit is kept on the tick grid, un-acked order sockets are dropped, and Modify/Cancel now appear for resting SL orders on Shoonya, Zebu, Flattrade and Tradesmart.
* **Funds and holdings correctness across seven brokers** — several brokers were reporting net margin as available cash, which is not withdrawable: Zerodha now derives available cash from net, debits and collateral (`8a5e87007`, `7f9790ab4`); Upstox migrated to the V3 funds API with correct cash and collateral and fixed pledge field access (`5b26cfb77`, `3f487b061`, `3c12e02d1`); Dhan subtracts `collateralAmount` from `availabelBalance` (`508804635`); Fyers uses Clear Balance rather than Available Balance (`cc0f9d8fa`); Angel derives true free cash and takes realized/unrealized P&L from the position book instead of RMS (`199d298b2`, `8d639fbff`), and coerces numeric fields the broker returns as strings (`965351b0c`). Groww holdings statistics no longer silently return zero (`1686e07c6`, test at `6e7fdd6ae`), and Upstox holdings no longer drop `average_price` or risk a divide-by-zero (`62bebefbb`).
* **Charting and UI** — full text settings dialog for text-bearing drawings with double-click to edit (`88615dc9f`, `01b88b717`); a volume show/hide control in the context menu (`a69a04c3d`) with the overlay confined to the bottom 18% of the price pane (`f3bf560ae`); the last-price line coloured by candle direction (`1681be1fb`); drawing rail shortcuts, wedge caret and hover tooltips fixed (`4b7f42bc1`); `/trading` symbol search ranked by relevance with an Index chip (`517dc699c`); the home page now derives its tool count from the registry (`46d87a5ff`); and the strategy-builder payoff chart no longer shows fill wedges or beveled strike kinks (`3328311f2`).
* **Reliability** — `openalgo-backup` archived an empty volume and reported success (`fc15cca6a`); the Telegram startup write no longer fails with "database is locked" (`658d44830`); the latency tracker tolerates a non-JSON response body (`f2c338917`); routine startup and keepalive noise moved from info to debug (`3542a6e8f`); and 500 responses no longer echo exception text to the client (`3432e28a8`).

---

**Dependencies**

* `react-router`: upgraded to **8.3.0** (GHSA-qwww-vcr4-c8h2)

---

**Configuration changes**

`utils/version.py`: `VERSION = "2.0.1.8"`

`pyproject.toml`: `version = "2.0.1.8"` (`uv.lock` regenerated).

No database schema changes in this release.

No new environment variables. `HOST_SERVER` is now load-bearing for password reset links and the RMoney OAuth callback — it is already set by every official install script, but if you hand-edited `.env` and left it at the default `http://127.0.0.1:5000` while serving a real domain, reset emails will point at localhost. Set it to your actual public URL.

---

**Upgrade procedure**

**For existing installs (Native Ubuntu):**

```bash
cd /var/python/openalgo-flask/<deploy-name>/openalgo
sudo ./install/update.sh
```

**For existing installs (Docker):**

```bash
cd /opt/openalgo/<domain>
sudo docker compose pull
sudo docker compose up -d
```

**For local developers (uv):**

```bash
git pull origin main
uv sync
uv run upgrade/migrate_all.py
# Frontend: a plain pull already ships the CI-built dist. Only rebuild if
# you are editing React code:
cd frontend && npm install && npm run build
uv run app.py
```

Never run `cp .sample.env .env` on an existing installation — it destroys broker credentials and the `API_KEY_PEPPER`, permanently invalidating password hashes and encrypted tokens. Compare `.env.sample` against your `.env` for new variables instead.

---

**Links**

* **Repository**: <https://github.com/marketcalls/openalgo>
* **Documentation**: <https://docs.openalgo.in>
* **Python SDK on PyPI**: <https://pypi.org/project/openalgo/>
* **Discord**: <https://www.openalgo.in/discord>
* **YouTube**: <https://www.youtube.com/@openalgo>
* **Issue tracker**: <https://github.com/marketcalls/openalgo/issues>
