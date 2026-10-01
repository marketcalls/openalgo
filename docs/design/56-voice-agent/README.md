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
| `voice_agent_name` | text | `Vega` | What the agent is called. It carries no authority. |
| `voice_trading_enabled` | bool | `False` | Whether mutating tools reach the voice surface at all. |
| `voice_confirm_window_seconds` | int | `30` | How long a spoken approval stays open. |

### There is no secret word

One was tried and removed. The operator configured a private phrase and only
that phrase approved an order. It cost more than it bought:

- Every approval became a memory test, in the moment a trader least wants one.
- The speech model read it aloud - "say milo to place it" - until that was
  fixed, which made a secret of nothing.
- It was written to `ag_audit` in plaintext every time it was spoken, in the one
  table this codebase makes shareable for triage.
- It accreted machinery: a second validated setting, a rule that the word could
  not appear in the agent's name, a separate rule for the word opening an
  instruction, and a rule that only the opening instruction could carry it.

What it bought was narrow: a stranger within earshot cannot say a word they do
not know. What replaced it is the thing a trader does anyway - answering.

### What protects an order now

**The read-back.** Nothing can be approved until the order has been spoken back
in full, so the trader is answering a question they have just heard the whole
of. `voice_confirm.is_spoken_confirmation` accepts a plain yes and nothing else:
every word must be an affirmation and there may be at most four of them, so
"yes", "go ahead" and "yes place it" approve, while "yes but wait" and any
question do not.

The decision is made server-side by `POST /agent/api/voice/approve`. The page
reports what it heard and which run it heard it against; whether trading is
reachable, whether a run is really waiting, whether the window is still open and
whether the words are an answer are all read from stored settings and from a
registry the page cannot write.

### What this does not defend against

Stated plainly, because the meta-rule in `55-agent` applies here: **anyone
within earshot who says yes while the window is open approves the staged order,
and the agent cannot tell one voice from another.** The window is short and
single use, the order has just been read back, and the risk guard inside the
tool body applies every limit afterwards. An operator who does not control the
room they trade in leaves `voice_trading_enabled` off and taps the card.

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
