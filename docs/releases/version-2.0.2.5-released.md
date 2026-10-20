# Version 2.0.2.5 Released

**Date: 14th September 2026**

**Feature Release: adds a voice surface to the agent, so the platform can be asked a question out loud and answer on screen; ships order placement switched off by default; carries the charting terminal from openalgo-charts 2.1.7 to 2.2.0 with all 85 drawing tools; and makes the 5paisa XTS, Tradejini, 5paisa and Kotak feeds survive a full symbol book**

29 commits since v2.0.2.4, excluding the automated frontend build commits.
**This release requires a database migration** - run
`cd upgrade && uv run migrate_all.py` after pulling. No configuration changes
are needed. The platform version moves from 2.0.2.4 to 2.0.2.5; the pinned
`openalgo` SDK stays at 2.0.5.

The release is dominated by one thread. The agent at `/agent` gained a third
surface beside chat and chart: a spoken one. It is not a second agent. The
speech model hears and speaks and decides nothing, and every answer it reads out
comes from the model configured at `/agent/config`, through the same toolkits,
the same risk guard and the same audit rows a typed question goes through. Most
of the commits after it are the consequences of putting a microphone in front of
a trading platform, and several of them are corrections to decisions made in the
commit before: what happens to a session nobody is using, what an order actually
requires before it reaches a broker, what a spoken error is allowed to say, and
what must never be written down.

The second thread is the broker feeds. Three adapters were sending one HTTP
request per symbol at subscribe time, which is a thousand sequential round-trips
on a full book and the same again on every reconnect; one of them tore down the
entire feed when a single symbol was dropped.

---

**Highlights**

* **Voice surface on `/agent` and `/agent/config` (`d642b4cef`)** - `gpt-live-1` is minted in client delegation mode, so a spoken turn runs through the same `send()` the composer uses and renders as an ordinary message with its tool timeline and any chart it drew. No audio passes through the server: the browser holds the WebRTC connection directly with the provider, and the server's only involvement is one outbound call to mint the session. Design notes in `docs/design/56-voice-agent/README.md`.
* **Order placement is opt-in (`7faab9cd6`, #2036)** - the agent's trading switch shipped on, so a fresh install could reach an order tool by typing a sentence with nobody having chosen that. Place, modify and cancel are now not offered to the agent at all until an operator switches them on. An existing installation that never touched the setting picks the new value up on upgrade, in the safe direction. The voice surface keeps a second switch, also off, so enabling trading does not by itself put it on the spoken surface.
* **The spoken approval phrase is gone (`7faab9cd6`, `e17d644fa`, `2ef597bf7`)** - a configured secret word was the only way to approve an order out loud, and it cost more than it bought: every approval became a memory test, it was read aloud by the speech model until that was fixed, and it was written to the audit table in plaintext every time it was spoken - the one table this codebase deliberately makes shareable for triage. What protects an order now is the read-back: nothing is approved until the order has been spoken back in full, and the decision stays server-side.
* **A spoken order places, instead of being announced (`e85747e1b`)** - the agent resolved the contract and then said it would place the order without calling the tool. No tool call means no pause, no approval prompt and no order, while the trader has just been told one is on its way. Brevity now governs how a thing is said, never whether it is done.
* **The voice surface can draw (`5637c4bcb`, `89fa7f161`)** - "show me my order book" was answerable by typing and refused by voice in the same conversation. A spoken turn renders on screen exactly as a typed one does, and the premise of the surface is that the ear takes the conclusion while the screen keeps the detail. `render_ui` also draws figures the operator supplied in their own message, titled so they cannot be mistaken for an account.
* **Every spoken line is recorded, and every session gets a thread (`564f63583`, `707c33bb1`, `2049320b7`)** - a spoken turn previously reached the record only when it needed the agent, so a greeting or an acknowledgement left no trace, and the sidebar only ever asked for chat threads, which made fourteen existing voice conversations unreachable. Lines are now captured under a `transcript` phase, the first line of a session opens the thread, and the thread renders in the order it happened.
* **A quiet microphone hangs up (`cd3873f9e`)** - an open microphone is billed for as long as it is open, and silence is still audio being streamed. Three minutes of nobody speaking ends the session, the countdown restarts on any sign of life, and the interval is a setting because how long a desk tolerates a quiet microphone is the operator's call.
* **Voice errors are written for a trader (`9e424a9d0`, `85e85893d`, `66d8a178f`)** - an account with no credit produced "The voice provider refused the session (HTTP 500)", which sent operators through settings that were all correct. Messages now name the cause and the next step in plain words, on the browser half too: no more "secure origin", "WebRTC" or "SDP". The rule is recorded in `CLAUDE.md` under Conventions so it applies to the next feature rather than to this one.
* **The agent's voice is named Vega (`fe150ace9`)** - chosen to sit far from an order instruction phonetically, and an options Greek reads as deliberate on a trading platform. Only the shipped default moves; an operator's own name is left alone.
* **openalgo-charts 2.2.0 with all 85 drawing tools (`50f94b717`)** - advanced channels, pitchforks, Fibonacci and Gann geometry, wavefronts and manual patterns. Menu labels and glyphs follow the installed package through generated metadata, so an upgrade cannot leave the rail describing tools that are no longer there, and the drawing renderer stays lazy. Saved drawing IDs and version 2 documents remain compatible.
* **Notes, balloons, comments, signposts, price notes and tables use the content editor (`50f94b717`)** - font colours reach the rendered letters, content edits preserve table grids and theme defaults, and each editor shows only the controls its tool supports.
* **Shared branding with openalgo-charts 2.1.9 (`718d10bfa`)** and **2.1.8 (`80b24d7f8`)** - the terminal's watermark and chrome come from the engine, removing the local copy.
* **TPO and session volume profile restored to the chart-type menu (`804eb1e94`)** - both are selectable again with their existing settings, saved layouts, live updates and intraday interval handling. TPO now defaults to letters rather than letters and blocks (`704b2ca75`), and the Objects rail button is a glyph like every other panel on the rail instead of a word spelled down it (`40b6bb733`).
* **5paisa XTS subscriptions batched into one request per mode (`c1bc96c90`, #2042)** - the XTS API takes an instruments array, but the adapter sent one blocking HTTP POST per symbol, so a 1000-symbol startup was 1000 sequential round-trips and every reconnect replayed the book the same way. Two silent bookkeeping defects had to be fixed for batching to be safe: every LTP and depth unsubscribe was targeting the quote feed, and the tick filter compared an int against a string so it dropped every depth tick.
* **5paisa XTS unsubscribe no longer tears down the whole feed (`c1bc96c90`, #2042)** - it called `disconnect()` on every invocation, so dropping one symbol killed the feed for every other subscribed symbol and nothing could bring it back. Reachable from the normal path whenever a watchlist entry is removed or a chart switches symbol.
* **Kotak always emits `ltp` in quote and depth payloads (`c1bc96c90`, #2038)** - it was the only adapter that dropped the key when the price was zero, and mode 2 suppressed the publish entirely. The trading chart subscribes depth alone for tradeable symbols, so a payload without the key reads as "keep polling" and nothing could ever clear the REST fallback.
* **Tradejini feed syncs coalesced into one request per feed (`4f3a321cd`, #2044)** - a subscribe request replaces the server-side symbol list rather than appending to it, so every change has to re-send the complete list, which made subscription O(N^2) in tokens sent: 1000 symbols cost 1000 requests carrying roughly 500k token entries, and teardown cost the same again. Part of #1350.
* **5paisa `last_snapshot` cache bounded (`4f3a321cd`, #2044)** - nothing ever removed an entry, so the dict grew for the life of the Gunicorn worker, which never restarts. The leak was the slower half: a remembered value merged over a zero field resurfaced on a later re-subscribe as a price that never traded, and across the 3 AM token rollover as the previous day's.
* **Ctrl+C on the development server actually exits (`95583fdac`)** - it printed a scheduler traceback every five seconds and needed two or three presses. Three causes: six APScheduler instances were never stopped and kept firing into closed thread pools; the websocket proxy thread was non-daemon with its cleanup registered through `atexit`, which cannot work, since `atexit` runs only after that same thread is joined; and the health collector slept its whole sampling interval in one call so it could not see its stop flag. Measured on a real server with a live feed: never exited before, 1.5s after.
* **The LiteLLM usage warning no longer prints on every turn (`932887b87`)** - a pydantic serializer warning on every `chatgpt/` plan turn, several lines each, that nobody can act on. Noise on every turn is worse than it sounds: a warning everybody learns to scroll past includes the next one that matters.
* **Documentation** - SDK pin references synced to 2.0.5 (`81d71dbbf`, #2050); the retired YouTube subscriber badge replaced in the README (`3f06c5641`); the charting terminal user guide and the `chart-indicator` skill regenerated against 2.2.0.

---

**Migration**

This release adds two migration scripts, both idempotent and both supporting
`--status`:

* `upgrade/migrate_agent_voice.py` - seeds the voice settings rows on an
  installation that has none, leaving an operator's own values alone.
* `upgrade/migrate_agent_voice_phrase_removal.py` - removes the two retired
  approval-phrase settings rows.

Run them the usual way:

```sh
cd upgrade && uv run migrate_all.py
```

---

**Dependencies**

* `openalgo-charts`: **2.1.7** to **2.2.0** (`80b24d7f8`, `718d10bfa`, `50f94b717`)
* The pinned `openalgo` SDK: unchanged at **2.0.5**
* No other dependencies changed

---

**Contributors**

* **@marketcalls (Rajandran R)** - release management; the voice surface on `/agent` and `/agent/config` and everything that followed it, including order placement made opt-in (#2036), the removal of the spoken approval phrase and its audit-trail leak, the read-back that replaced it, spoken orders that place rather than being announced, drawing from the voice surface, spoken transcripts captured and threaded, the idle hangup, the plain-language rewrite of every voice error, and the two migrations; openalgo-charts 2.1.8, 2.1.9 and 2.2.0 with all 85 drawing tools and the generated drawing metadata; TPO and session volume profile restored to the chart-type menu, the TPO letters default and the Objects rail icon; the Ctrl+C shutdown fix on the development server; the LiteLLM usage warning filter; the charting terminal user guide and the `chart-indicator` skill regenerated for 2.2.0.
* **@Kalaiviswa** - 5paisa XTS websocket subscriptions batched into one request per mode, with the unsubscribe message-code and tick-filter defects fixed alongside; 5paisa XTS unsubscribe no longer disconnecting the whole feed; Kotak always emitting `ltp` in quote and depth payloads (#2038); Tradejini feed syncs coalesced into one request per feed (part of #1350); the 5paisa `last_snapshot` cache bounded on unsubscribe and cleared on disconnect (#2042, #2044).
* **@Ayush7614** - SDK pin references synced to 2.0.5 across the API and MCP architecture documentation (#2050).

Thank you to everyone who filed an issue, reproduced a defect or reviewed a pull
request this cycle. #2036 is the clearest example of why that matters: the agent
shipped able to place orders on a fresh install, nobody inside the project had
read it as a default worth questioning, and it took someone opening an issue to
say so.

---

**Links**

* **Repository**: <https://github.com/marketcalls/openalgo>
* **Documentation**: <https://docs.openalgo.in>
* **Python SDK on PyPI**: <https://pypi.org/project/openalgo/>
* **Discord**: <https://www.openalgo.in/discord>
* **YouTube**: <https://www.youtube.com/@openalgo>
* **Issue tracker**: <https://github.com/marketcalls/openalgo/issues>
