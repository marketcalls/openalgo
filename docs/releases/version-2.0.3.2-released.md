# Version 2.0.3.2 Released

**Date: 31st October 2026**

**NSE's lower index freeze limits from Monday 2 November, the published Diwali Muhurat session on Sunday 8 November, upgrades that keep the holidays you set, a WhatsApp bot that stays connected, and LiteLLM 1.106.6 for the agent. Upgrade before Monday's open.**

6 commits since v2.0.3.1, excluding automated frontend build commits and
including this release. The platform version moves from 2.0.3.1 to 2.0.3.2.
The pinned `openalgo` Python SDK remains 2.0.5. This release adds two data
migrations, `migrate_qty_freeze_nov_2026.py` and `migrate_muhurat_2026.py`,
which `migrate_all.py` runs, and no schema change.

**Highlights**

- **NSE index freeze limits from 2 November (`8e4241127`).** NSE circular
  NSE/FAOP/77189 (30 October 2026) lowers every index freeze limit from
  Monday 2 November: NIFTY 3,510 to 1,800, BANKNIFTY 1,440 to 900, FINNIFTY
  3,240 to 1,800, MIDCPNIFTY 5,760 to 2,800, NIFTYNXT50 1,125 to 600 and
  NIFTYFPI 53,900 to 8,500. The exchange rejects any order above the limit, so
  on the October limits the `/trading` terminal would have let a 28 to 54-lot
  NIFTY order go in one piece, and the scalping terminal would have closed
  positions in pieces of up to 54 lots. OpenAlgo stores NSE's figure, 1,800 for
  NIFTY, and rounds down to whole lots when it splits an order, so the largest
  single NIFTY order is 27 lots (1,755).
- **Diwali Muhurat on Sunday 8 November (`8e4241127`).** The 2026 calendar
  carried a guess of 18:00 to 19:15, with MCX running to 00:15. It now carries
  the session NSE, BSE and MCX published: trading from 14:20 to 15:30, equity
  derivatives to 15:40, after a pre-open from 14:05. NSE commodities (NCO) is
  open for it too. A `/python` strategy scheduled for that Sunday now runs
  during the real session, not the guessed one.
- **An upgrade no longer erases the holidays you set (`8e4241127`).** Every
  upgrade deleted the whole holiday calendar and reloaded the one OpenAlgo
  ships, so a holiday you added or edited on the Holidays page was undone, and
  one you deleted came back. Upgrades and startup now change only rows
  OpenAlgo shipped and nobody edited.
- **WhatsApp alerts stay connected (`b196469e7`, #2332).** The WhatsApp bot
  could miss an alert and then disconnect within an hour of starting, most
  often on Docker. Its periodic session save removed files the live
  connection was still using. The save now runs in a separate process, so the
  connection keeps its files.
- **Newer models for the agent (`8a2fbf1d0`).** LiteLLM 1.106.6 brings Claude
  Sonnet 5.5 and Haiku 5.5, GPT-6.1 Sol, Gemini 4 Argon, Mistral Large 4 and
  four more ChatGPT Plus and Pro models to `/agent/config`. OpenRouter now
  lists no models, because LiteLLM removed them; add an OpenRouter model by
  name.

**What to check after upgrading**

- **Upgrade and restart before Monday's open.** The update scripts run
  `migrate_all.py`; if you upgrade by hand, run `cd upgrade && uv run
  migrate_all.py`, then restart OpenAlgo. The Muhurat timings also apply on a
  restart alone.
- **A freeze limit you set yourself** on the Freeze Quantities page is left as
  it is, and the migration lists it next to NSE's new figure.
- **A holiday an earlier upgrade erased is not restored.** Add it again on the
  Holidays page, and it now stays.
- **A server whose uv waits a number of days before installing a new package
  (`exclude-newer`)** refuses LiteLLM 1.106.6, published on 28 October, until
  it is old enough. `uv run --frozen app.py` installs from the lockfile and is
  not affected.

**Dependencies**

- `litellm` 1.104.0 to 1.106.6, and with it `boto3` and `botocore` 1.43.87 to
  1.43.122 (`8a2fbf1d0`). LiteLLM still caps `filelock` below 4.0, so the
  `filelock>=4.2.1` override stays.
- The pinned `openalgo` Python SDK remains 2.0.5.

**Contributors**

- **@marketcalls** - the November freeze limits, the Muhurat session, the
  holiday calendar fix, LiteLLM 1.106.6 and the release.
- **@Kalaiviswa** - WhatsApp alerts that stay connected (#2332).

**Links**

- [Repository](https://github.com/marketcalls/openalgo)
- [Documentation](https://docs.openalgo.in/)
- [Python SDK](https://pypi.org/project/openalgo/)
- [Community](https://www.openalgo.in/discord)
- [Videos](https://www.youtube.com/@openalgo)
- [Issue tracker](https://github.com/marketcalls/openalgo/issues)
