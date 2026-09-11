# Voice Agent (`Milo`)

Milo is the spoken surface of the `/agent` module. A trader holds a
conversation out loud; the answer is spoken back and, at the same time, lands
on screen as an ordinary agent message with its tool timeline and any chart it
drew.

Milo is **not a second agent**. It is a third surface on the existing one.

## Non-negotiables

These extend the five in [`../55-agent/README.md`](../55-agent/README.md) and
are subject to all of them.

1. **The voice model decides nothing.** `gpt-live-1` runs in client delegation:
   it hears and it speaks. Every decision, every tool call and every order is
   made by the agno agent on LiteLLM, exactly as the text surface makes them.
2. **No audio passes through OpenAlgo.** The browser holds the WebRTC
   connection directly with OpenAI. The server's only involvement is one
   outbound HTTPS POST to mint the session.
3. **Voice widens nothing.** A tool unreachable from text chat is unreachable
   from voice. The surface filter narrows; it never adds.
4. **Approval is decided by a pure function, never by a model.** The matcher in
   `services/agent/safety/voice_confirm.py` takes a transcript string and
   returns a boolean. It reads no prompt and imports nothing.

## Why `gpt-live-1` and not a three-part pipeline

The obvious build is speech-to-text, then the LLM, then text-to-speech. It
works and it keeps every part swappable, and it costs roughly a second per turn
because the words are handed between three services.

`gpt-live-1` offers a third shape. Its **client delegation** mode
(`"delegation": {"type": "client"}`) means the voice model performs no
reasoning of its own: when it hears something that needs an answer it emits
`session.delegation.created` and waits for the application to supply one. The
application is us.

That buys the latency and the interruption handling of a native speech model
while leaving the intelligence exactly where this module already put it: any
provider registered at `/agent/config`, resolved through LiteLLM. Swapping the
brain from Claude to a local Ollama model changes nothing about the voice.

The trade is a dependency on one vendor for hearing and speech. It is a
contained one. `services/agent/voice.py` is the only module that knows the
provider exists, and nothing above it does.

## One turn

```
trader speaks
  -> gpt-live-1 (browser <-> OpenAI, WebRTC)
  -> session.delegation.created on the data channel
  -> POST /agent/api/chat/stream  {surface: "voice"}
       -> the same agno agent, the same toolkits, the same risk guard,
          the same ag_audit rows as a typed turn
  -> full answer renders on screen as a normal message
  -> spoken line returns on session.commentary.append
  -> gpt-live-1 speaks it
```

While tools are running the browser sends `session.thinking.append` so the
trader hears that work is happening rather than silence. That content is never
spoken verbatim; the voice model paraphrases it.

## The eventlet crossing that isn't one

This module adds no crossing. The realtime connection lives in the browser, so
the server never holds a socket, a thread, or an event loop for it. The single
server-side network call is:

```python
client = get_httpx_client()
response = client.post(LIVE_SESSIONS_URL, json=payload, timeout=...)
```

through the shared `utils/httpx_client`, with an explicit timeout, on the
request greenlet. There is no `asyncio`, no new thread, no new file descriptor,
and nothing to reap.

This is the reason the design puts WebRTC in the browser rather than
terminating it server-side. A server-side realtime session would need a real OS
thread carrying audio, a queue crossing into the hub, and a per-session
lifecycle under a worker that never restarts. All of that is avoidable, so it
is avoided.

## Configuration

Everything lives in the database, nothing in `.env`.

| Key | Kind | Default | Meaning |
| --- | --- | --- | --- |
| `voice_enabled` | bool | `False` | Master switch. Off means the mic never renders. |
| `voice_model` | text | `gpt-live-1` | The speech model. |
| `voice_speaker` | text | `marin` | Which OpenAI voice speaks. |
| `voice_agent_name` | text | `Milo` | What the agent is called **and** the spoken approval word. |
| `voice_trading_enabled` | bool | `False` | Whether mutating tools reach the voice surface at all. |
| `voice_confirm_window_seconds` | int | `30` | How long a spoken approval stays open. |

### `voice_agent_name` carries two jobs

It is the persona the trader addresses and the word that approves a staged
order, so it is validated harder than a label needs to be: **one word, letters
only, two to twenty characters**, stored with its capitalisation and matched
case-insensitively.

A multi-word name would break the alone-word rule below, and punctuation would
not survive transcription. Rejecting those at the settings boundary is what
keeps the matcher a simple, total function rather than a parser.

Changing the name changes both jobs at once, which is the point: an operator who
wants a word nobody says by accident sets one, and the persona follows.

The OpenAI key is an `ag_secret` under `voice:openai`, written through
`agent_db.set_secret` like every other credential, never returned to the
browser, and never logged.

`voice_trading_enabled` is subject to `trading_enabled`. Turning it on while
the master switch is off does nothing, which is deliberate: there is one place
to stop all order flow and it keeps working.

## Tools on the voice surface

`SURFACE_VOICE` is added to `services/agent/tools/__init__.py` and to
`agent_db.SURFACES`. Toolkits reaching voice:

`market`, `symbols`, `indicators`, `account`, `options`, `instrument`, `live`,
`viz`, `option_viz`.

`chart` stays `CHART_ONLY`; it drives the `/trading` panel, which a voice turn
is not attached to.

`viz` and `option_viz` are the reason this feature is worth building. "Show me
the Bank Nifty option chain" draws it on screen while the answer is spoken,
which is a thing the text surface cannot do hands-free.

Mutating tools are excluded from the voice surface unless **both**
`trading_enabled` and `voice_trading_enabled` are set.

## Speaking

A `SURFACE_VOICE` fragment in `prompts.py` gives Milo its persona and its
brevity:

- One or two sentences. Detail goes to the screen, not the ear.
- Numbers rounded for speech. "Twenty-three thousand four hundred", not
  "23,412.55". The exact figure is on screen.
- No markdown, no tables, no bullet lists. They are unspeakable.
- Say what is being done before a slow tool, not after.

`session.commentary.append` caps content at 500 tokens. `voice.speakable()`
enforces a shorter budget than that and is the only path to the data channel.

## Symbols are the hard part

Reference: [`docs/prompt/symbol-format.md`](../../prompt/symbol-format.md),
[`docs/prompt/order-constants.md`](../../prompt/order-constants.md),
[`docs/prompt/websockets-format.md`](../../prompt/websockets-format.md).

An OpenAlgo symbol is an exact contract identity, not a display label, and it is
built for machines: `NIFTY28MAR2420800CE`, `BANKNIFTY24APR24FUT`,
`VEDL25APR24292.5CE`. Text chat can show that string and a trader reads it at a
glance. A speaker cannot. This is the difference between the two surfaces and
most of the work in making voice usable.

Both directions need rules, and they are not the same rule.

**Speaking a symbol.** Never character by character. `NIFTY28MAR2420800CE` is
"the twenty thousand eight hundred Nifty call expiring on the twenty-eighth of
March". A decimal strike is a number, not digits: `292.5` is "two ninety-two
point five". Exchange codes are spoken the way a trader says them, and the
underscore in `NSE_INDEX` is never pronounced. Products and order types go to
words: `CNC` is delivery, `NRML` is normal, `MIS` is intraday, `SL-M` is "stop
loss market". These live in `voice.build_instructions`, because they govern
delivery, and in the `SURFACE_VOICE` prompt section, because they govern what
the agent writes in the first place.

**Hearing a symbol.** A spoken instrument is ambiguous in a way a typed one is
not: "buy fifty Nifty twenty-four thousand calls" names no expiry, and "the
Bank Nifty future" names no month. The agent resolves that through the `symbols`
toolkit - search, contract lookup, expiry dates - and never by assembling a
symbol string from what it heard. A symbol built by concatenation is a symbol
that can be subtly wrong and still exist.

This is the same rule `/strategy` already enforces for signal legs, quoted from
`symbol-format.md`:

> A signal leg on a derivatives exchange must name an exact listed contract. A
> base symbol plus expiry rank is refused rather than guessed.

Voice inherits it. **An order is never placed against a guessed contract.** If
the trader has not said enough to identify one listed contract, the agent asks
rather than choosing the nearest expiry, and the read-back names the exact
resolved contract, so the word that approves is spoken against something the
trader has just heard in full.

**Live data.** `websockets-format.md` defines modes 1/2/3 as LTP, Quote and
Depth. Voice never says a mode number: it says last price, quote, or market
depth. Depth in particular is a table, so the spoken answer is the top of book
and the screen carries the rest.

## Order approval

**The decision is made server-side.** `POST /agent/api/voice/approve` takes the
utterance and the run it is aimed at; everything that decides is read from
stored settings and from a registry the page cannot write. The page reports
what it heard and acts on the answer. A defect in the browser, or a browser
whose code has been altered, cannot turn a sentence into an approval.

This is not what stands between a sentence and a broker - the risk guard inside
the tool body is, and it runs after any approval and reads no prompt. This
narrows a different hazard: a word said out loud in a room that contains other
people, and a page deciding for itself what counted as that word.

Four things must hold, and they fail with different reasons on purpose, because
an operator who says the phrase into a closed window should be told the window
closed rather than that they said the wrong word:

1. `trading_effective` - both the platform switch and `voice_trading_enabled`.
2. The run is registered as waiting. `stream.py:_on_run_paused` stamps it, which
   is the one place a pause becomes a `confirm` frame.
3. The window is still open, per `voice_confirm_window_seconds`.
4. The utterance is the phrase, per `voice_confirm.is_approval`.

Approving consumes the window, so one utterance cannot approve one run twice. A
run that never paused is refused even for the right phrase.

**Shipped off.** `voice_trading_enabled` defaults to `False`, so the first
release is read-only and nothing below is reachable.

When an operator turns it on, an order requested by voice follows the same
pause the text surface uses. agno pauses the run, the confirmation card renders
on screen exactly as it does today, and Milo additionally reads the order back
and opens a spoken window:

```
Milo: "Buy 50 NIFTY24000CE at market, about 62,000 rupees. Say milo to place."
```

The approval word is `voice_agent_name`, lower-cased. It ships as `milo`, at the
operator's direction, and is configurable.

### What makes the word safe enough to use

`milo` is also what the trader calls the agent, so the matcher cannot simply
look for the word inside an utterance. It does not:

- **The utterance must be the word alone.** `milo`, optionally wrapped in a
  bare affirmation (`yes milo`, `milo confirm`, `ok milo`). Anything carrying
  other content does not match, so "Milo, what is Bank Nifty doing?" is a
  question even with a window open. Filler and punctuation are stripped first;
  a single remaining token that is not the word is a rejection, not a retry.
- **The window is short and single-use.** `voice_confirm_window_seconds`,
  default 30, one attempt. It opens only after an order has been staged and
  read back, and it closes on the first utterance either way.
- **The matcher is a pure function.** String in, boolean out. It reads no
  prompt, holds no state, and imports nothing from agno, LiteLLM or the
  database, so no phrasing anywhere in a conversation can alter its verdict.
- **The risk guard is unchanged.** It still runs inside the tool body, after
  approval, before the service call. Spoken approval reaches the same gate a
  tapped approval reaches.
- **The card never goes away.** Tapping still works, and is the only path when
  the window has expired.

### What this does not defend against

Stated plainly, because the meta-rule in `55-agent` applies here: a bare "milo"
spoken by anyone within earshot during an open window will approve the staged
order. The window, the single attempt and the alone-word rule reduce the
surface; they do not eliminate it. An operator who wants that surface closed
leaves `voice_trading_enabled` off and taps the card.

`ag_audit` records the approval mode, the utterance that matched, and the
window it matched in.

## Every spoken line is kept

A speech model handles much of an exchange itself - acknowledgements, asking
which expiry was meant - and none of that becomes an agent turn. A record built
only from turns would therefore be the subset of a conversation that happened to
need a tool, which is the wrong subset to have afterwards.

So every finalised line is recorded, through
`POST /agent/api/voice/transcript`, into **`ag_audit`** under the phase
`transcript`. It goes there rather than into `ag_message` because it is evidence
rather than conversation: the speech model paraphrases what it is given, so what
was said out loud and what the agent wrote are two records of one turn, and
flattening them into one table loses that distinction.

The same lines render live in the thread, in a quieter style than a message,
beside the ordinary messages a delegated turn still produces. Recording never
fails a caller: a line that cannot be written is logged, because losing a line
is better than interrupting a conversation over it.

## HTTP surface

| Route | Method | Purpose |
| --- | --- | --- |
| `/agent/api/voice/session` | POST | Exchange the browser's SDP offer for OpenAI's answer. Body is `application/sdp`, response is `application/sdp`. |
| `/agent/api/voice` | GET | The voice configuration, with no key in it. |
| `/agent/api/voice` | PUT | Update the configuration. |
| `/agent/api/voice/key` | PUT / DELETE | Store or remove the OpenAI key. |
| `/agent/api/voice/test` | POST | Mint a throwaway session and discard it, to prove the key works. |
| `/agent/api/voice/approve` | POST | Decide whether one utterance approves one paused run. |
| `/agent/api/voice/transcript` | POST | Record one finalised spoken line to `ag_audit`. |

The mint route is an egress surface: it posts to a fixed OpenAI URL that is a
module constant and is never taken from a request. There is no base-URL
override, which is what keeps it off the SSRF surface described in
`55-agent`.

## Frontend

- `lib/agent/voice.ts` — the connection and the delegation loop. Owns the
  `RTCPeerConnection`, the `oai-events` data channel, and the mapping from a
  delegation request to a `/chat/stream` call and back to
  `session.commentary.append`.
- `components/agent/VoiceButton.tsx` — the mic in the composer. States: idle,
  connecting, listening, thinking, speaking.
- `components/agent/config/VoicePanel.tsx` — the configuration panel, beside
  `TradingPanel`.

Spoken turns render as ordinary chat messages, so the transcript, the tool
timeline and the audit trail are the same artefacts the text surface produces.

## Deployment

Nothing in `install/` changes for this feature, and that is worth stating
explicitly because the first instinct is that it must.

### The header that has to be relaxed, and why it is not an installer change

`csp.py` sends `Permissions-Policy: ... microphone=() ...`. That directive
disables the microphone for the whole origin and **outranks every browser and
operating-system permission**: `getUserMedia` fails with `NotAllowedError`, the
browser stores no site exception, and `navigator.permissions.query` reports
`denied`. The page looks as though it was refused by a setting the operator
cannot find, in a browser where the microphone demonstrably works elsewhere.
That was a real afternoon.

So `csp.py` relaxes the one directive to `microphone=(self)` while
`voice_enabled` is on, and leaves the header byte-for-byte unchanged when it is
off. It lives in the application rather than in nginx because it follows a
database setting, and nginx knows nothing about that.

No installer needs a matching change: none of `install.sh`,
`install-docker.sh`, `install-multi.sh`,
`install-docker-multi-custom-ssl.sh` or `change-domain.sh` sets
`Permissions-Policy` at all, so the application's header reaches the browser
untouched. Their `add_header` lines cover HSTS, frame options, content-type
options, XSS and referrer policy only.

### Browsers and operating systems

The browser half uses `getUserMedia`, `RTCPeerConnection`, a data channel and an
`Audio` element, and nothing else. There is no vendor prefix anywhere in
`lib/agent/voice.ts` and no Chromium-only API; the build targets ES2022. That
set is baseline in current Chrome, Edge, Firefox and Safari, which is the whole
of the compatibility story for code.

What differs between platforms is **not the code, it is where the microphone
permission lives**, and the failure text is written for that:

- **Windows** - Settings, Privacy and security, Microphone. Both the global
  switch and the per-app switch for the browser have to be on.
- **macOS** - System Settings, Privacy and Security, Microphone, then the
  browser. It must be relaunched after a change.
- **Ubuntu** - no OS permission layer; a failure here is a missing or busy input
  device under PipeWire or PulseAudio.

`microphoneRefusal` distinguishes refused, none found, and in use by another
application, because the fix is different in each case and "access was refused"
sends an operator to the wrong screen. The insecure-origin case is checked
before the request, since an insecure page is never asked and the operator would
otherwise toggle a permission that was never consulted.

Two behaviours are worth knowing rather than fixing:

- **Firefox** can take longer to finish gathering ICE candidates.
  `waitForIceGathering` carries its own timeout and proceeds with what it has,
  rather than waiting for a `complete` that may not arrive promptly.
- **Safari** enforces user activation on audio playback, and the activation can
  lapse across the awaits between the click and the first remote track. The
  `play()` rejection is caught and ends the session rather than leaving a
  connection that holds the microphone and cannot be heard.

### What a deployment does have to satisfy

- **HTTPS, or localhost.** A microphone is only available in a secure context.
  Every installer provisions Let's Encrypt, so a domain deployment is fine, and
  `http://127.0.0.1:5000` is fine for a local one. **A LAN address over plain
  http is not** - `http://192.168.1.50:5000` cannot use a microphone whatever
  the permissions say. `lib/agent/voice.ts` checks `window.isSecureContext`
  before asking and says so in those words, because "access was refused" sends
  an operator to the wrong settings screen.
- **`PERMISSIONS_POLICY` is an override, not a merge.** An operator who has set
  it in `.env` owns the entire string, and `csp.py` will not rewrite it. Such an
  instance must add `microphone=(self)` by hand or voice stays dead with no
  error anywhere in the logs. Nothing ships that variable - it is absent from
  `.sample.env` and no installer writes it - so this affects only an instance
  that has been hardened by hand.
- **Proxy limits are already sufficient.** An SDP offer is a few kilobytes
  against `client_max_body_size` of 50M and 100M in the Docker installers and
  nginx's 1M default elsewhere, and the mint is one request well inside the
  86400s proxy timeouts. No audio crosses the server, so none of this is on the
  media path.
- **Eventlet is unaffected.** The mint is a single `utils/httpx_client` call on
  the request greenlet, the same shape every other outbound call in the platform
  uses under `gunicorn --worker-class eventlet -w 1`. Nothing added here imports
  `asyncio`, starts a thread, or opens a socket of its own, and the 20s mint
  timeout sits well inside gunicorn's 300s.
- **Docker needs no change.** The image already builds the frontend with
  `npm ci && npm run build`, so the voice panel and the mic ship with it. The
  container does need outbound access to the speech provider's API; nothing in
  `docker-compose.yaml` restricts egress today. No new port, process or volume
  is involved, because no audio reaches the server.

## Migration

`upgrade/migrate_agent_voice.py`, registered in `MIGRATIONS`. Idempotent,
supports `--status`, seeds the five settings rows only when absent, and never
overwrites a value an operator has set.
