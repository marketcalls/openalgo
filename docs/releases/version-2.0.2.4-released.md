# Version 2.0.2.4 Released

**Date: 11th September 2026**

**Maintenance Release: carries the charting terminal from openalgo-charts 2.0.2 to 2.1.7, adding TPO and session volume profiles, a pane Objects panel and a data loading controller, while fixing replay isolation and stale history loads; completes the Upstox V3 migration and corrects tick size, daily-candle stamping and previous-close reporting across Upstox, Kotak, Samco, Groww and Flattrade; makes GTT history visible in the order book; and clears every open Dependabot advisory**

37 commits since v2.0.2.3, excluding the automated frontend build commits. No
database migration is required and no configuration changes are needed. The
platform version moves from 2.0.2.3 to 2.0.2.4; the pinned `openalgo` SDK moves
independently from 2.0.3 to 2.0.5.

This release is dominated by two threads. The charting terminal continued the
work started in 2.0.2.3, taking four upstream chart-engine releases and adding
the profile studies and object management that the terminal was missing. In
parallel, the broker plugins received a long run of correctness fixes, several
of them affecting numbers a trader reads directly: prices reported in paise
rather than rupees, a daily candle stamped in host local time rather than IST,
and a previous close that never populated.

---

**Highlights**

* **Charting terminal on openalgo-charts 2.1.7 (`5287faaa8`, `2e838fc38`, `f958009be`, `536eafe73`)** - four engine upgrades across 2.1.3, 2.1.4, 2.1.5 and 2.1.7. Two-axis mouse and pen panning is restored as the default with horizontal-only kept as an explicit preference; drawings that extend past the latest candle or before the first loaded bar now keep their preview and commit where they were drawn instead of disappearing mid-gesture; saved navigation preferences and a reset control are retained.
* **TPO and session volume profiles (`1e1bf79ec`)** - market profile and session volume studies on the chart, with the profile entries removed from the chart type menu where they did not belong (`2f9f057de`).
* **Pane Objects panel (`536eafe73`)** - per-pane listing and management of the objects on a chart.
* **Chart data loading controller (`b6d53a782`)** - history loading moved onto the engine's controller, and replay is now isolated from live history refreshes with obsolete symbol and pagination responses rejected (`e0ee99fd7`).
* **Upstox V3 migration completed (`c7fbf6c24`, #2028)** - CAS data, shared rate limiting and WebSocket leak fixes, together with a Flattrade fix where a WebSocket close stalled the reconnect (#1965).
* **Upstox tick size reported in rupees (`0db9038de`, #2026)** - the API returns paise; the plugin was passing that through unscaled, so every tick-derived value was off by a factor of a hundred.
* **Upstox synthetic daily candle stamped in IST (`8a9fcb8db`, #2030)** - it was stamped in host local time, so the candle landed on the wrong day for anyone not running in IST.
* **Upstox multiquotes populate previous close (`eeffb40a4`, #1725)** - `prev_close` was never set, which broke percentage-change everywhere it was displayed.
* **Kotak market data over SFeed (`0b9fc879e`, #2016)** - per-data-centre routing, unavailable HSM fields decoded rather than published as prices, and the measured quotes instrument cap recorded.
* **Kotak average price on holdings (`0e19dfed8`, #2001)** and **tradebook fills keyed correctly (`122390cc5`, #2007)** - `fill_timestamp` is used instead of `order_timestamp`, and per-fill `trade_id` is preserved.
* **Samco stops reconnecting after a rejected session token (`697ab24be`, #2035)** - a rejected token previously drove an unbounded reconnect loop.
* **Groww tradebook prices in rupees (`a8b84b202`, #1995)** - reported in the units Groww actually sends.
* **GTT history in the order book (`bb89272ee`)** - GTT rows are visible alongside orders, and sandbox GTT no longer reports 501. Sandbox GTT rows are stamped in IST like every other sandbox timestamp (`6c28e16f3`).
* **Holiday checks respect the requested date range (`0ca0d2792`, #1938)**.
* **Central CORS policy applied to blueprint decorators (`f2d703e4a`, #1927)** - decorated routes were bypassing the configured policy.
* **Ordered shutdown on Ctrl+C (`761fa6070`, #2031)** - the development server stops the health collector and releases its sessions before exiting, so an instance no longer keeps writing to `health.db` after it has been asked to stop.
* **Every open Dependabot advisory cleared (`8b09dbe42`)** - GitPython, maplibre-gl, svgo, vitest and colord. `npm audit` reports no known vulnerabilities.
* **`gpt-6-astra` added to the ChatGPT subscription models (`aaf7c496e`)**.
* **Smaller fixes** - negative Net GEX values abbreviated with K/L/Cr suffixes (`c84321853`, #1911); SIP inputs validated before prices load (`963024300`, #1884); backtester controls labelled for screen readers (`2475048f1`, #1877); the Docker installer no longer starts a container from a failed build (`a41aa280f`, #2005).
* **Test and documentation** - Footer fetch and conditional rendering covered (`2cef5b91e`, #1964); the strategy-builder Greeks tab awaited rather than queried synchronously (`9022f5152`, #1903); the README quick-contribution example aligned with Conventional Commits (`6e6dea88d`, #1935); the `chart-indicator` skill's export index regenerated against the pinned engine and enforced in CI (`2b7a91bf3`).

---

**Dependencies**

* `openalgo-charts`: **2.0.2** to **2.1.7**
* The pinned `openalgo` SDK: **2.0.3** to **2.0.5** (`4cb25db21`, `ddc8cb57a`)
* Security advisories cleared (`8b09dbe42`): GitPython to **3.1.62**, maplibre-gl to **6.9.0**, svgo to **4.1.0**, vitest and `@vitest/mocker` to **4.1.11**, colord to **2.10.0**
* `docker/login-action`: **3** to **4.5.2** (#1719)
* `requirements-nginx.txt` realigned with the other dependency lists, which had been left a version behind on the SDK pin

---

**Contributors**

* **@marketcalls (Rajandran R)** - release management; the charting terminal through four engine upgrades to openalgo-charts 2.1.7, TPO and session volume profiles, the pane Objects panel, the data loading controller and replay isolation; GTT history in the order book and sandbox GTT timestamps; ordered shutdown on Ctrl+C (#2031); clearing every open Dependabot advisory; the `chart-indicator` skill regeneration and its CI gate; SDK pin bumps to 2.0.4 and 2.0.5.
* **@Kalaiviswa** - the Upstox V3 migration with CAS data, shared rate limiting and WebSocket leak fixes, plus the Flattrade reconnect stall (#2028, #1965); Kotak market data over SFeed with per-data-centre routing and HSM field decoding (#2016); the Upstox synthetic daily candle stamped in IST (#2030); Samco reconnect loop after a rejected session token (#2035).
* **@arsalanansari17** - tradebook fills keyed on `fill_timestamp` with per-fill `trade_id` preserved (#2007); Kotak average price on holdings (#2001).
* **@anishkun (Anish kunda)** - Upstox tick size normalized from paise to rupees (#2026); and the root-cause analysis on #2029 that traced an apparent `crossover` defect to NaN propagation in the SDK's moving-average kernels.
* **@linuxsmiths** - Upstox multiquotes never populating `prev_close`, which broke percentage-change reporting (#1725).
* **@nightcityblade** - holiday checks applying the requested date range (#1938).
* **@WilliamK112 (Ching Wei Kang)** - central CORS policy applied to blueprint decorators (#1927).
* **@vibecoding-skills (Harsh Dattani)** - Groww tradebook prices reported in the rupees Groww sends (#1995).
* **@srajbr (Samiran Raj Boro)** - negative Net GEX values abbreviated with K/L/Cr suffixes (#1911).
* **@siddharthg2309 (Siddharth Gouthaman)** - SIP inputs validated before prices are loaded (#1884).
* **@hafzism (Hafeez)** - backtester controls labelled for assistive technology (#1877).
* **@aravindgandavadi (Aravind Gandavadi)** - the Docker installer no longer starting a container from a failed build (#2005).
* **@Mr-Neutr0n (hari)** - frontend test coverage for Footer fetch and conditional rendering (#1964).
* **@Pragitics (Pragit R V)** - the strategy-builder Greeks tab awaited instead of queried synchronously (#1903).
* **@santhiprakash (Santhi Prakash)** - the README quick-contribution example aligned with Conventional Commits (#1935).

Thank you to everyone who filed an issue, reproduced a defect or reviewed a pull
request this cycle. Several fixes in this release came directly from user
reports: the tick-size and previous-close defects were both found by people
checking numbers against their broker terminal, and #2029 was diagnosed in the
issue thread before any maintainer looked at it.

---

**Links**

* **Repository**: <https://github.com/marketcalls/openalgo>
* **Documentation**: <https://docs.openalgo.in>
* **Python SDK on PyPI**: <https://pypi.org/project/openalgo/>
* **Discord**: <https://www.openalgo.in/discord>
* **YouTube**: <https://www.youtube.com/@openalgo>
* **Issue tracker**: <https://github.com/marketcalls/openalgo/issues>
