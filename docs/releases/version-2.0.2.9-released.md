# Version 2.0.2.9 Released

**Date: 17th October 2026**

**Custom chart intervals and independent indicator history: `/trading` and Historify adopt openalgo-charts 2.6.7, with saved interval favorites and a daily EMA 200 on an intraday chart. This release also includes strategy editor run controls, continuous crypto scheduling, broker data fixes and the MCP session security update.**

20 commits since v2.0.2.8, excluding automated frontend build commits and
including this release. The platform version moves from 2.0.2.8 to 2.0.2.9.
The pinned `openalgo` Python SDK remains 2.0.5. This release adds no database
migration.

**Highlights**

- **Custom intervals and saved favorites.** The chart interval menu groups
  choices by unit, supports adding and removing custom intervals, and shares
  favorites between charts while each pane retains its selection. Compatible
  native candles supply derived intervals, such as 7 minutes from 1 minute,
  aligned 2 hours from hourly data, and weeks, months and quarters from daily
  data. The SDK source planning and controls are covered by its commits
  `94d702e9`, `8b4b3149` and `dad20245`; the integration ships in this release.
  Historify keeps both chart panes inside the viewport; wide toolbars scroll
  within their own pane.
- **Independent higher-timeframe studies.** A daily EMA 200 on a five-minute
  chart requests daily warmup separately. Only observations whose availability
  is established enter the study. Historify uses stored daily history and
  does not confirm a partial final month just because its last stored candle
  exists. Missing history remains visible as unavailable data. SDK provider
  work: `68853d32` and `92578364`.
- **Stable chart controls and order edits (`bacc4be7c`).** Indicator legend
  controls retain their position as values change. Chart order modifications
  serialize edits and preserve acknowledged fields; uncertain outcomes require
  a refreshed order book before another edit.
- **Chart navigation (`b81323195`, `ff2856d23`, #2171).** Open a chart from
  orders, trades or positions. Derivative badges are read only from derivative
  symbols, avoiding accidental CE, PE or FUT labels on other names.
- **Strategy editor controls (`b9d155ff6`, `01d986cb7`, #2199).** Start and stop
  a strategy and open its logs from the editor. A newly created strategy moves
  to its broker exchange in one transaction (`fec180d4e`).
- **Continuous crypto operation (`f0919beaa`, `cced84316`).** Crypto strategies
  can run continuously, and sandbox P&L snapshots are retained on weekends.
- **Broker reliability (`50a559bb7`, #2235; `46fbd5553`, #2133).** Failed
  master-contract refreshes preserve existing symbols, a running download
  cannot be replaced by a stale stored contract, and currency derivatives and
  streamed prices use their instrument precision.
- **Broker coverage and price validation (`9aa6f2e30`, #2193;
  `bee4e181a`, #2052).** An additional broker plugin is available. Market-price
  protection rejects nonnumeric and non-finite prices.
- **Installer and CI (`febb0e8f5`, #2220; `8c1ce004c`).** The multi-instance
  installer adds the optional gthread worker, memory profiles, and port and
  snapshot fixes. Executor regression tests inspect their own worker pools.
- **Navigation and accessibility (`69970aaf9`, #2223; `4317e4b54`,
  `d7d64f41e`, #1869).** Navigation uses text tabs with overflow under More.
  Page loading is announced reliably. Routine startup logs move to debug
  (`c5ebfba20`).
- **Deployment guidance (`b53f85bc6`, #2240).** A new assistant setup skill
  covers isolated Linux installation, broker login, upgrades and Live-order
  network requirements.

**History and replay limits**

- Derived intervals require sufficient, compatible native source history and
  known session boundaries. Minute history cannot create second candles.
- Favorites persist across `/trading` and Historify; unsupported choices are
  disabled for the current source. Removing a saved choice preserves the
  chart currently displaying it.
- Requested studies use confirmed values. Independent replay needs historical
  snapshots from a suitable provider; a live-only provider cannot safely supply
  future daily observations during replay.
- Automated broker traffic is synthetic. No live broker orders were placed
  during release validation.

**Dependencies**

- `openalgo-charts`: 2.6.4 at the preceding platform release to 2.6.7, including
  the previously integrated 2.6.6 legend and settings fixes.
- MCP SDK: 1.30.0 across Python installation paths, fixing
  GHSA-84m7-p3x7-pcfv concerning retained stateful Streamable HTTP sessions
  (`bacc4be7c`).
- No new runtime dependency is required by the chart interval integration.

**Contributors**

- **@marketcalls** - chart integration and releases, navigation (#2223),
  strategy and crypto fixes, security update, CI reliability and deployment
  guidance (#2240).
- **@Kalaiviswa** - resilient contract refreshes and instrument precision
  (#2235).
- **@varshathT (Varshath Terli)** - additional broker integration (#2193).
- **@Ayush7614 (Felix-Ayush)** - finite market-price protection validation
  (#2052).
- **@samadarsh (Adarsh)** - prevent stale contract loading during downloads
  (#2133).
- **@dhvanilshah2007 (Dhvanil Shah)** - derivative symbol badges (#2171).
- **@rajatdangra (Rajat Maheshwari)** - strategy editor run controls and log
  links (#2199).
- **@aravindgandavadi (Aravind Gandavadi)** - multi-instance deployment options
  and fixes (#2220).
- **@anmoldwivedi89 (Anmol Dwivedi)** - accessible page loading status (#1869).

**Links**

- [Repository](https://github.com/marketcalls/openalgo)
- [Documentation](https://docs.openalgo.in/)
- [Python SDK](https://pypi.org/project/openalgo/)
- [Community](https://www.openalgo.in/discord)
- [Videos](https://www.youtube.com/@openalgo)
- [Issue tracker](https://github.com/marketcalls/openalgo/issues)
