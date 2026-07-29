# Version 2.0.1.7 Released

**Date: 28th July 2026**

**Charting Terminal & Workspace Hardening Release: the `/trading` page gains history backfill, text drawings, drawing-tool settings and a redesigned brand mark; a new Kotak Securities live order-update WebSocket feed; and a repo-wide workspace/secret-hardening pass adding an indicator-analysis dependency group and skills reorganization**

This release spans 47 commits since v2.0.1.6. The bulk of the work continues building out the **`/trading` charting terminal**: history backfill on scroll-to-edge, text drawing annotations, a volume axis that no longer competes with the price scale, drawing-tool settings and view controls surfaced directly on the chart, a fix for a stale indicator list and white scrollbars, and four iterations on the on-chart brand mark (from a full app-icon crop down to a purpose-cut glyph with its own hover-reveal lockup linking to openalgo.in). Underneath, `openalgo-charts` moved from 1.0.7 to 1.0.25, picking up per-pane hairlines, a four-state MACD histogram, a William VIX FIX indicator, and an `sma` fix where a single non-finite value previously poisoned its running sum for the rest of the series. On the broker side, **Kotak Securities gained a live order-update WebSocket feed** (with unsubscribes batched and ordered ahead of subscribes, and orphanable WebSocket clients closed on re-init/double-connect) and **IIFL's XTS feed token now refreshes** on multiquotes and history calls instead of failing once it expires. A parallel **workspace and secrets-hardening** effort added a private, git-excluded `workspace/` folder, ignored every `.env` variant (not just the literal file), organized indicator-skill output into its own folder, and added an opt-in `analysis` dependency group so Streamlit/yfinance/seaborn/etc. never reach a production install. Dependency bumps include `react-router-dom` 7.18.0 (CVE-2026-53667) and a `postcss` override past a path-traversal advisory.

---

**Highlights**

* **`/trading` charting terminal — continued build-out (`f43a870c2`, `1e2a1d749`, `3b8952e15`, `0a7c733f9`, `d744246d7`)** — history backfill via `setHistoryLoader`/`historyLoadComplete` so scrolling to the left edge pages in older bars (duplicate-safe, movement-type aware for Renko/P&F); text drawing annotations; drawing-tool settings and view controls surfaced on the chart itself; volume now rides its own overlay scale instead of sharing the price axis; a stale indicator list, white scrollbars, and product-control width fixed; the brand mark redesigned across several iterations into a purpose-cut glyph (`openalgo-glyph.svg`) with a hover-reveal "OpenAlgo Charts" lockup linking to openalgo.in (UTM-tagged, `noopener`/`noreferrer`); and the right-click Grid submenu fixed to open on hover instead of tearing down its own parent menu on click.
* **`openalgo-charts` 1.0.7 → 1.0.25 (`febbf172e` + follow-ups)** — per-pane hairline separators, a four-state MACD histogram (sign and momentum direction instead of one flat colour), a new William VIX FIX synthetic-VIX indicator, a `padding` option used for the new brand glyph sizing, and an `sma` fix: a single non-finite value no longer poisons its running sum for the indicator's entire remaining length.
* **Kotak Securities: live order-update WebSocket feed (`07d4f31db`, `31ccdf05a`, `73e4ef7e2`)** — new dedicated order/trade-update WebSocket adapter; unsubscribes batched and ordered ahead of subscribes to avoid a race on resubscribe; orphanable WebSocket clients now closed on adapter re-init and double-connect instead of leaking a stale connection.
* **IIFL: XTS feed token refresh (`5abc35eda`)** — multiquotes and history requests now refresh the XTS feed token when it has expired, instead of failing outright.
* **Workspace and secrets hardening (`ac537c6b7` + follow-ups, PR #1681)** — a private `workspace/` folder (excluded from git, with a per-folder readme so the tree survives a clone) for local scratch work; every `.env` variant ignored by git, not just the literal `.env` filename; Codex review findings on the same PR addressed.
* **Indicator skills: organized output + opt-in analysis dependencies (`2781776da`, `fa918725c`, `60e221897`)** — indicator-skill output routed into its own organized folder; a new opt-in `analysis` PEP 735 dependency group (`dash`, `matplotlib`, `scipy`, `seaborn`, `streamlit`, `yfinance`, etc.) so a plain `uv sync` never pulls Streamlit/yfinance/seaborn into a production install — use `uv sync --group analysis`; new indicator-analysis skills added alongside a security-audit skill and an expanded fd-audit covering memory growth.
* **Docs and site fixes** — `CLAUDE.md` restructured with the broker-integration guide converted into a skill (`b40f60ba2`); broker and tool counts corrected on the FAQ and home page (`cd76cfe9a`); install scripts and docs re-synced for the current broker list (`0ff5e5419`); a dead `jmfinancial` entry dropped from the frontend broker list (`518d08503`); SDK docs corrected to state indicators ship in the base `openalgo` package, not a removed `[indicators]` extra (`b81a93616`, `339e64647`, `a0ff9f0b6`).
* **Reliability** — missing HTTP timeouts added and stray `print()` calls replaced with centralized logging repo-wide (`709d3e28f`).
* **Security dependency bumps** — `react-router-dom` 7.15.0 → **7.18.0** for CVE-2026-53667 (`3d98d60dc`); `postcss` override raised past a path-traversal advisory (`80b8a6223`).

---

**Dependencies**

* `openalgo-charts`: `1.0.7` → **1.0.25**
* `react-router-dom`: `7.15.0` → **7.18.0** (CVE-2026-53667)
* `postcss`: override raised to `>=8.5.18` (path-traversal advisory)
* New opt-in `analysis` dependency group (`pyproject.toml`): `dash`, `dash-bootstrap-components`, `ipywidgets`, `matplotlib`, `scipy`, `seaborn`, `streamlit`, `yfinance` — not installed by a plain `uv sync`

---

**Configuration changes**

`utils/version.py`: `VERSION = "2.0.1.7"`

`pyproject.toml`: `version = "2.0.1.7"` (`uv.lock` regenerated).

No database schema changes in this release.

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
