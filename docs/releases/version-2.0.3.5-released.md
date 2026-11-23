# Version 2.0.3.5 Released

**Date: 20th November 2026**

**This release brings the pinned OpenAlgo Python SDK to 2.3.0, rebuilds the Pocketful plugin, adds order update streams for Tradejini, Groww and Sahi, and tightens the AI agent's web search and prompt handling.**

This is the first release after 2.0.3.4, with 25 commits since that bump, excluding automated frontend build commits and including this release. No migration is needed.

**Highlights**

- **OpenAlgo Python SDK 2.3.0** - the pin moves from 2.0.5 to 2.3.0 in `pyproject.toml`, `requirements.txt` and `requirements-nginx.txt`. Strategies run from `/python` import this version.
- **Pocketful rebuilt on its new API (`a1d539764`, #2467)** - the plugin follows Pocketful's new API.
- **Order update streams for Tradejini (`33158269c`, #2477), Groww and Sahi (`f0a50b038`, #2474)** - order status now arrives from each broker's own feed.
- **AI agent** - web fetch with Firecrawl and TinyFish and preferred sources for fundamentals (`46af9591f`), prompt caching for Claude models (`d941bb3b1`), search that falls through the other keyed providers (`5e19ce407`), and an operator's earlier messages redacted whole (`1ed72181e`).
- **Sandbox feed no longer stalls orders** - subscribe and unsubscribe run off the order path (`5cf708a8a`, #2192) and the feed queue is bounded while the proxy does not answer (`398f614cc`).
- **WebSocket clients reconnect after broker credential changes (`9512aa5fe`, #2277)**.
- **Broker fixes** - Flattrade trade book quantities (#2464, #2480), Nuvama empty order book (#2479), Tradesmart master contract, tick size and history (#2475), Aliceblue depth quotes (#2473), XTS order ids and positions (#2468), Wisdom reconnects (#2469), iBulls market price protection (#2466).
- **Other fixes** - Zerodha NSE series stocks stored under their base symbol (#2463), scalping keeps an earlier partial exit's P&L (#2437), and a clearer FERNET_SALT message (#2465).

**Dependencies**

- `openalgo` 2.0.5 to 2.3.0.
- `litellm` updated to 1.110.1 with `pydantic` 2.14.3.

**Contributors**

- **@marketcalls** - the AI agent work, the Pocketful, XTS, Wisdom, iBulls, Zerodha and FERNET_SALT fixes, the dependency updates and the release.
- **@Kalaiviswa** - Tradejini, Groww and Sahi order streams, and the Flattrade, Nuvama, Tradesmart and Aliceblue fixes (#2473 to #2480).
- **@jackiectl2 (Tianlang (Jackie) Chen)** - WebSocket reconnect after credential changes (#2277).
- **@samadarsh (Adarsh)** - sandbox feed subscribe off the order path (#2192).
- **@Mystery01092000 (Pranav Tomar)** - scalping partial exit P&L (#2437).
- **@Mr-Neutr0n** - contributing guide on first-run secrets (#2457).

**Links**

- [Repository](https://github.com/marketcalls/openalgo)
- [Documentation](https://docs.openalgo.in/)
- [Python SDK](https://pypi.org/project/openalgo/)
- [Community](https://www.openalgo.in/discord)
- [Videos](https://www.youtube.com/@openalgo)
- [Issue tracker](https://github.com/marketcalls/openalgo/issues)
