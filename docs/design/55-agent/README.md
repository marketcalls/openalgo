# Agent Module (`/agent`)

The build contract for the `/agent` feature. Every implementation task reads
this file first. Where this document and the code disagree, the code is right
and this file is stale.

The feature is an LLM agent with two surfaces, chat and chart, that calls
OpenAlgo's **internal service layer** rather than its own HTTP API, generates
OpenAlgo Python strategies and Flow JSON, and renders rich visualizations
inline in the conversation.

## Non-negotiables

These come from the request and from `CLAUDE.md`. A change that breaks one of
them is wrong even if it passes tests.

1. **No configuration in `.env`.** Provider, model, credentials and every agent
   setting live in the database. `.env` is not read by this module.
2. **Services, not HTTP.** Tools import from `services/*` and call the function.
   No tool makes an HTTP request back into this process.
3. **Nothing blocks the eventlet hub.** Production is
   `gunicorn --worker-class eventlet -w 1`. The agent runs on a real OS thread
   and communicates through a real queue.
4. **Python 3.12+.**
5. **Modular by construction.** Adding a tool is one file plus one registry
   line. Adding a provider is a database row.

## Module layout

```
services/agent/
  __init__.py
  runtime.py            lifecycle; one call from app.py
  settings.py           DB-backed config accessors
  providers.py          provider vocabulary -> LiteLLM kwargs
  catalog.py            model catalog (LiteLLM price/context snapshot)
  builder.py            Agent construction + the tool factory
  stream.py             real-thread bridge; agno events -> frames
  frames.py             the wire contract, standalone, no agno import
  prompts.py            system prompt assembly
  safety/
    __init__.py
    risk.py             pure-python order guard
    audit.py            append-only audit of every mutating call
  tools/
    __init__.py         registry: build_toolkits(context) -> list
    base.py             OpenAlgoToolkit
    market.py account.py orders.py symbols.py options.py
    chart.py viz.py strategy_gen.py flow_gen.py
  generators/
    python_strategy.py  emits a strategies/scripts/*.py
    flow_json.py        emits + validates Flow JSON

database/agent_db.py    schema + store
blueprints/agent.py     session API
upgrade/migrate_agent.py

frontend/src/
  api/agent.ts
  lib/agent/stream.ts       fetch + ReadableStream SSE client
  lib/agent/useAgentStream.ts
  pages/agent/*             Chat, Setup, Settings
  components/agent/*
```

Two things deliberately live outside `services/agent/`:

- **The chart command vocabulary** becomes an `apply(command)` method on the
  existing `/trading` terminal (`frontend/src/lib/trading/terminal.ts`). The
  chart already exists; the agent drives it rather than owning a second one.
- **Flow validation** calls `services/flow_workflow_validator.validate_workflow`.
  There is exactly one Flow schema and it is not here.

## Database schema

Prefix every table `ag_`. The codebase already has `strategy_`, `sm_` and
`flow_` prefixes for unrelated things.

### `ag_provider_model`

The configured model. One row per model the operator has enabled. Adapted from
ragz's `models` table; the capability flags are operator-set, never inferred.

| column | type | null | default | notes |
| --- | --- | --- | --- | --- |
| `id` | Integer | no | pk | |
| `provider_kind` | String(32) | no | | `openai`, `anthropic`, `ollama`, `openai_compatible`, `litellm` |
| `model_name` | String(200) | no | | passed to LiteLLM; carries its own provider prefix for `litellm` |
| `display_name` | String(200) | no | | shown in the picker |
| `base_url` | String(500) | yes | NULL | required for `ollama` and `openai_compatible` |
| `enabled` | Boolean | no | true | |
| `is_default` | Boolean | no | false | exactly one true, enforced in the store |
| `supports_reasoning` | Boolean | no | false | |
| `default_reasoning_effort` | String(16) | no | `off` | `off/low/medium/high` |
| `supports_vision` | Boolean | no | false | |
| `tools_unreliable` | Boolean | no | false | a tool-driven agent must know this |
| `last_tested_at` | DateTime | yes | NULL | naive UTC |
| `last_test_ok` | Boolean | yes | NULL | |
| `last_test_error` | Text | yes | NULL | |
| `created_at` / `updated_at` | DateTime | no | now | naive UTC |

Unique on `(provider_kind, model_name, base_url)`.

The API key is **not** a column here. It lives in `ag_secret`, keyed by name,
exactly as ragz does it, so a key can be shared by several models of one
provider.

**Several providers are configured at once, each with its own key.** This is the
ragz model and it is the requirement: an operator adds OpenAI with an OpenAI key,
Anthropic with an Anthropic key, a local Ollama with no key at all, and a
handful of models under each. All of them sit enabled in the registry
simultaneously; exactly one row carries `is_default`, and the chat surface offers
a picker over every enabled model.

That is why the key is keyed by `provider:{kind}` rather than stored per model:
adding a fourth GPT model must not mean pasting the OpenAI key a fourth time.
A per-model override at `model:{id}` is still honoured when present and wins over
the provider key, which covers two accounts with the same provider.

### `ag_secret`

| column | type | notes |
| --- | --- | --- |
| `id` | Integer | pk |
| `name` | String(200) | unique, indexed. `provider:{provider_kind}` or `model:{id}` |
| `ciphertext` | Text | Fernet |
| `fingerprint` | String(80) | display-safe, never the value |
| `last_used_at` | DateTime | yes |

**Encryption reuses OpenAlgo's existing cipher**, not a new one:

```python
from database.auth_db import encrypt_token, safe_decrypt_token
```

Do not introduce ragz's AES-GCM + KEK-file scheme. It would put a second secret
outside the database, and OpenAlgo already derives Fernet from `API_KEY_PEPPER`
and `FERNET_SALT`, both auto-provisioned per install.

`safe_decrypt_token` returns the raw value when decryption fails, which is what
lets a column move from plaintext to encrypted without a cutover.

**Compare decrypted plaintext, never ciphertext.** Fernet is non-deterministic,
so a ciphertext comparison never matches and causes a pointless rewrite on every
save. That exact mistake produced real `database is locked` errors in
`telegram_db.py`; its fix is the pattern to copy.

`fingerprint(value)` is `f"...{value[-4:]} sha256:{sha256(value)[:12]}"` for a
value longer than 8 characters, else `"...????"`.

### `ag_setting`

Key/value, one row per setting. `key` is the primary key, `value` is Text.
Holds the system-prompt override, default reasoning effort, trading-enabled
flag, and anything added later without a migration.

### `ag_conversation` and `ag_message`

`ag_conversation`: `id`, `user_id` (indexed), `title`, `surface`
(`chat`/`chart`), `agno_session_id`, `created_at`, `updated_at`.

`ag_message`: `id`, `conversation_id` (indexed), `role`, `content` (Text),
`tools` (JSON), `notices` (JSON), `created_at`.

Agno's own `SqliteDb` owns run/requirement state so a paused confirmation
survives across requests. These tables own what the UI lists and renders.
Point `SqliteDb` at its own file under `db/`, not at `openalgo.db`.

### `ag_audit`

Append-only. `id`, `ts`, `phase` (`attempt`/`result`/`decision`), `tool`,
`conversation_id`, `run_id`, `args` (JSON), `risk_verdict`, `ok`, `response`
(JSON), `order_ids` (JSON). Two rows per mutating call, one more per approval
decision. A write failure here is logged and swallowed; it never blocks a trade.

## Provider model

`provider_kind` is a closed vocabulary, not a table:

| kind | needs key | needs base_url | LiteLLM model id |
| --- | --- | --- | --- |
| `openai` | yes | no | `openai/{model_name}` |
| `anthropic` | yes | no | `anthropic/{model_name}` |
| `ollama` | no | yes | `ollama/{model_name}` + `api_base` |
| `openai_compatible` | yes | yes | `openai/{model_name}` + `api_base` |
| `litellm` | yes | no | `{model_name}` verbatim, prefix already inside |

`providers.py` exposes one function:

```python
def litellm_kwargs(row, api_key) -> dict
```

returning the kwargs for `agno.models.litellm.LiteLLM`. Note the argument is
**`api_base`**, not `base_url`; `base_url` belongs to the separate
`LiteLLMOpenAI` proxy class, which we do not use.

There is **no proxy**. ragz syncs a registry to a standalone LiteLLM server; we
construct the model per run from the row and the decrypted key, which needs no
sync step and picks up a config change on the next request.

### The catalog comes from LiteLLM itself

**No provider or model list is stored in the database, and none is hand
maintained in the frontend.** `catalog.py` reads LiteLLM's own in-package data
at runtime. Verified against `litellm==1.99.0`:

```python
import litellm
litellm.LITELLM_CHAT_PROVIDERS   #   94 chat-capable providers
litellm.provider_list            #  152 providers, all modalities
litellm.models_by_provider       #   96 providers / 3021 models
litellm.model_cost               # 3517 entries of per-model metadata
```

Three deliberate choices:

- **Offer `LITELLM_CHAT_PROVIDERS`, not `provider_list`.** The 152 include
  embedding, image, audio and rerank-only providers. Presenting a rerank
  provider as a chat provider is noise.
- **Enrich from `litellm.model_cost`**, which carries `max_input_tokens`,
  `max_output_tokens`, `input_cost_per_token`, `output_cost_per_token`, `mode`
  and `supports_function_calling`.
- **`supports_function_calling` is load-bearing here, not decoration.** This
  agent is entirely tool-driven, so a model without it cannot work. Surface it
  in the picker and refuse to make such a model the default. ragz maintains the
  equivalent as a hand-set `tools_unreliable` flag; we get it for free and it
  never goes stale.

Maintenance is therefore one action: **bump `litellm`**. New providers and
models arrive with the package. No migration, no regeneration script, no
network call, and no catalog rows to keep in sync.

A model absent from the catalog is still addable by hand, because the catalog is
advisory. The database stores only operator intent: which models are enabled,
which is default, the encrypted keys, and test results.

`litellm.get_valid_models()` is **not** the catalog. It returns nothing without
credentials because it is live-account discovery. Its correct use is a
per-provider "what can this key actually reach" action after a key is saved,
which is a genuinely useful verification step and nothing more.

### The provider UI

Copy ragz's *shape*, but not its data source: ragz ships a 6,700-line generated
`provider-catalog.ts`, and we read the same information from LiteLLM at runtime
instead. The layout is what transfers.

- **A provider card grid**, built from `LITELLM_CHAT_PROVIDERS`, searchable,
  each card showing an `n configured` badge when the registry already holds
  models for it. A small local map supplies display names and icons for the
  common brands; anything without an entry falls back to the provider id, so a
  provider added by a future LiteLLM release still appears rather than
  disappearing until someone updates a table.
- **Clicking a card opens one panel** with a single API-key field, a base-URL
  field only where that provider needs one, and a **checklist of that provider's
  models** from `models_by_provider`, each annotated from `model_cost` with its
  context window, price, and whether it supports function calling. A model that
  cannot call functions is shown greyed with the reason, because it cannot drive
  this agent. Models already registered appear checked and disabled.
- **"Add selected" issues one create per checked model, sequentially**, reusing
  the one key. Sequential rather than parallel so a mid-batch failure stops
  cleanly and ordering stays deterministic.
- **An "add custom model" escape hatch** in the same panel, because the catalog
  is advisory and an operator must be able to name a model it has never heard of.

The provider list itself is a **static frontend constant**, not a database
table, exactly as ragz's generated `provider-catalog.ts` is. It maps a brand to a
`provider_kind`, whether a key or base URL is required, and a suggested model
list. Nothing about it is sent to the backend; the backend only ever sees the
five `provider_kind` values.

A registered-models table below the grid lists every configured model with its
provider, key fingerprint, test status, an `enabled` checkbox and a `default`
radio.

### Resolution order

Explicit request, then the `is_default` row, then a typed error. A named model
that is missing or disabled is an error, never a silent fall-through to the
default. Resolution happens **before any stream byte is written**, so a bad
model id fails as a clean HTTP error rather than mid-stream.

## The setup gate

`/agent` is unusable until a model is configured and tested.

- `GET /agent/api/status` returns `{configured: bool, models: [...], default_model_id, trading_enabled}`.
- The React route renders **Setup** when `configured` is false, chat otherwise.
- Every chat route returns **409** with a clear message when unconfigured. The
  frontend must not be the only thing enforcing this.

### Testing credentials

ragz has no such action, so this is ours to design. `POST /agent/api/models/{id}/test`:

- decrypts the key in memory, never logs it,
- issues the **cheapest possible real call**: a completion capped at one token,
- on success writes `last_tested_at`, `last_test_ok=True`, clears the error,
- on failure stores the provider's own message in `last_test_error` verbatim,
  because "invalid API key" and "model not found" need different fixes and a
  generic failure message helps nobody,
- returns `{ok, message, latency_ms}`.

A model may be saved untested. It may not be made default untested.

The template to copy is the SMTP flow in `blueprints/auth.py`: a separate save
route, a separate explicit test route with its own validation, a real upstream
call, and a `{success, message}` JSON result. `POST /auth/test-smtp` and
`utils/email_utils.send_test_email` are the precedent, and `Profile.tsx`'s SMTP
tab is the UI precedent.

Two rules from that precedent that matter here:

- **A secret is never sent back to the client, not even masked.** The GET
  returns a boolean presence flag and a fingerprint, nothing else. The password
  input starts empty even when a key is configured, and blank on save means
  "keep the existing key".
- **Surface a diagnostic, not just a verdict.** `/auth/debug-smtp` exists
  because "it failed" does not tell an operator whether the host was
  unreachable, the credentials were rejected, or the name was wrong. The test
  result carries the provider's own message so the three cases stay
  distinguishable.

### Gating

`Layout.tsx` is the structural precedent: a route-group guard that redirects on
a store-cached backend flag, populated once by `AuthSync` from
`/auth/session-status`. `/auth/check-setup` plus `pages/Setup.tsx` is the
first-run precedent, a cheap boolean endpoint checked on mount that navigates to
a dedicated setup route.

`/agent` follows both: an `AgentRoute` guard renders the setup page when
`configured` is false, and the nav entry is **always shown, never filtered**,
matching how Telegram, WhatsApp, Flow and Python Strategies are already listed.
Only capability-gated items like Leverage are filtered, and that is a fact about
the broker rather than about setup state.

## Streaming

### Transport

`POST /agent/api/chat/stream`, SSE. Frames are `data: {json}\n\n` with **no
`event:` line**; every frame is discriminated on a `type` field. The client is
`fetch` plus a `ReadableStream` reader, not `EventSource`, because the request
carries a body.

Headers: `Cache-Control: no-cache`, `Connection: keep-alive`,
`X-Accel-Buffering: no`.

### The eventlet crossing

This is the part most likely to be broken by a well-meaning change.

```
green request handler                     real OS thread
---------------------                     --------------
route builds the Agent            ->      agent.run(stream=True)
                                          translate each agno event
                                          real_queue.put(frame)
drain with get_nowait()           <-
yield "data: {...}\n\n"
```

- The thread is `utils.real_threading.Thread`; the queue is its `Queue`. Both
  resolve to the unpatched originals under eventlet.
- The green side **never** blocks on the queue. It uses `get_nowait()` and
  sleeps a short interval, so the hub keeps running.
- A heartbeat comment frame goes out when the queue is empty for a while, so an
  idle stream is not closed by a proxy.
- On client disconnect (`GeneratorExit`) the route calls `agent.cancel_run(run_id)`
  and the `finally` block joins the thread with a timeout. Without that a
  dropped connection leaks a thread per turn in a worker that never restarts.

Agno's sync `agent.run(stream=True)` returns a plain `Iterator[RunOutputEvent]`.
We do not use `arun`. There is no asyncio anywhere in this module.

### Frames

`frames.py` defines these and nothing else imports agno:

| type | payload |
| --- | --- |
| `start` | `run_id`, `session_id`, `conversation_id` |
| `token` | `delta` |
| `tool_start` | `id`, `name`, `args` |
| `tool_end` | `id`, `name`, `ok`, `result`, `duration` |
| `reasoning` | `delta` |
| `ui` | `delta` (OpenUI Lang text, see below) |
| `chart_command` | `commands: [...]` |
| `confirm` | `run_id`, `session_id`, `requirements: [...]` |
| `notice` | `level`, `message` |
| `error` | `message`, `kind` |
| `done` | `reason` (`stop`/`cancelled`/`incomplete`) |

Three measured agno behaviours the translator must handle:

- A **paused run terminates the stream** with a `confirm` frame and **no
  `done`**. The client must not treat that as a failure.
- `continue_run` defaults `stream_events` to `False`. Pass it explicitly.
- `ToolCallCompleted` with an error is followed by a separate `ToolCallError`.
  Suppress the second so a failure is not reported twice.

## Tools

### The base

`tools/base.py` provides `OpenAlgoToolkit(Toolkit)`, which owns what every tool
repeats:

- `service_call(fn, *args, **kwargs)` -> unwraps OpenAlgo's
  `(success, response, status)` tuple, returning the payload or raising
  `RetryAgentRun` with a message the model can act on,
- `to_json(obj)` -> JSON-safe, NaN-safe, capped at 12000 characters with a
  well-formed truncation marker rather than a cut-off string,
- audit hooks for mutating tools,
- the `api_key` and `conversation_id` for the current run.

Docstrings **are** the schema. Every argument needs a real type hint and a
matching Google-style `Args:` line, or the generated schema is unusable.

### The registry

`tools/__init__.py` exposes:

```python
def build_toolkits(context) -> list[Toolkit]
```

and `builder.py` passes it as a **callable factory** to `Agent(tools=...)`, so
it is re-evaluated on every run against `run_context.session_state`. A session
that has not enabled trading never sees order tools in its schema at all; the
chart surface sees chart tools and no order tools. Adding a capability is a file
plus a registry entry.

### Confirmation and risk

Every mutating tool is named in its toolkit's `requires_confirmation_tools`.
Agno pauses; the UI approves; **then** `safety/risk.py` runs inside the tool
body before the service is called. The guard is pure Python and reads no prompt,
so nothing the model or user says can talk past it.

Order of checks: kill switch, trading enabled, analyzer mode if required,
symbol, exchange, product, quantity, session cap, duplicate window, notional and
price deviation, affordability against available funds. The affordability check
**fails open** on a broker error, because refusing a human-approved order
because a quote endpoint hiccuped is worse than allowing it.

## Security

### The meta-rule

Borrowed from ragz, and it governs this section and this whole document:

> **A security claim here must resolve to a test, or say "not implemented".**
> Never state an unbuilt control in the present tense. It reads as evidence the
> control exists, and reviewers stop looking.

ragz adopted that rule after discovering its own security documentation pointed
at a document that was never tracked, so every claim in it resolved to nothing.
Anything below that is not yet backed by a test is marked **NOT IMPLEMENTED**
until it is.

An LLM that can place orders has a threat model no other feature here has. The
governing assumption is simple and must not be softened anywhere in the
implementation:

> **The model is untrusted input, not a trusted component.** Everything it emits
> is a suggestion. Nothing it says may widen its own permissions.

### Prompt injection is the primary threat

The agent reads symbol names, order rejection text, news, generated strategy
output and tool results, any of which can carry text authored by someone else.
Instructions hidden in that text will reach the model. Treat it as certain, not
possible.

There is exactly one defence that holds, and it is structural rather than
textual:

- **The risk guard runs inside the tool body, after human approval, before the
  service call, and reads no prompt.** No phrasing in a conversation, a symbol
  name or a tool result can alter its verdict. Prompt wording is a nicety; this
  is the control.
- **Tool availability is decided by session state, not by the model.** A session
  without trading enabled has no order tool in its schema at all. The model
  cannot ask for a capability it was not given, because the capability does not
  exist in its function list.
- **No tool may enable trading, change the analyzer mode, alter risk limits,
  rotate a key, or edit agent settings.** Configuration is a human action
  through the settings UI. There is no self-modification path.
- **Confirmation cannot be waived by content.** `requires_confirmation_tools` is
  a static list on the toolkit, not a runtime decision.

Tool results are wrapped and labelled as data before they re-enter context, and
the system prompt states that instructions appearing inside tool output are to
be treated as data. That is defence in depth, not the defence.

#### Delimiting untrusted text

One escaping primitive, used at **every** boundary where text that entered the
system as data goes back into a prompt. Ported from ragz's `wrap_untrusted_block`:

```python
def wrap_untrusted(tag: str, text: str) -> str:
    closer = f"</{tag}>"
    return f"<{tag}>\n{text.replace(closer, f'<\\/{tag}>')}\n</{tag}>"
```

The closer is neutralised so the content cannot forge a block boundary and
escape its own wrapper. Any attribute interpolated into the opening tag, a
symbol name, a filename, a broker rejection string, is XML-attribute escaped
first, because an unescaped `"` in an attribute is the same break-out in a
different position.

This applies to tool results, order rejection text, symbol and instrument names,
generated code echoed back for review, and **the user's own earlier messages**.
The boundary is not "documents versus everything else", it is anything that
entered the system as data, from anyone, ever.

The anti-injection rules in the system prompt are **never truncated** when the
context budget is trimmed. Everything else gets shortened first.

#### The taint boundary

ragz's sharpest idea, and it transfers directly. Where the model supplies a
string that becomes an outbound query or lookup, do not filter it. **Construct
it**, so that every token in the result is provably a substring of the user's
own words:

Keep only whitespace-delimited tokens from the model's requested string that
also appear, case-insensitively, in the user's original message; fall back to
the user's message verbatim if nothing survives. A token the model invented, or
copied out of a poisoned tool result, cannot reach the outbound call by
construction rather than by pattern matching.

This is what defeats "a hostile string in a tool result tells the model to look
up the operator's positions under an attacker-chosen query". Apply it to any
tool argument that leaves the process.

### Third-party data egress

Every token of context leaves the machine and reaches the model provider. For
this product that includes positions, holdings, P&L, order history and account
balances. That is a material disclosure and the operator must choose it
knowingly.

- The setup screen states plainly which provider and model the data will be sent
  to, before a key can be saved.
- **A local provider is a first-class option.** `ollama` needs no key and sends
  nothing off the machine, and the provider grid presents it as such.
- **Broker credentials, OpenAlgo API keys, auth tokens and feed tokens are never
  placed in the context window**, not in the system prompt, not in a tool
  result, not in an error message. Tools receive credentials through the toolkit
  instance, never through model-visible arguments.
- Tool results are filtered before returning: any key whose name matches a
  secret-shaped pattern is dropped rather than serialised.

### Generated code never runs itself

Generating a Python strategy is generating code that will execute as a
subprocess with the operator's live API key injected. That is arbitrary code
execution by design.

- **The generator writes a file and stops.** It never starts a strategy. Running
  one stays a separate, explicit human action in `/python`.
- The response shows the full source for review before anything is saved.
- Path handling follows `blueprints/python_strategy.py`: `secure_filename`, strip
  to `[A-Za-z0-9_-]`, timestamp suffix, and a `resolve()` containment check
  against `strategies/scripts/` even though we control the name, because a later
  refactor can reintroduce traversal.
- Generated Flow JSON is validated by the real validator before import, and an
  imported workflow is created inactive.

### Provider base URL is an SSRF surface

`openai_compatible` and `ollama` accept an operator-supplied `base_url`, and the
server will make requests to it.

- Validate the scheme is `http` or `https` and reject anything else.
- Reject credentials embedded in the URL.
- The cloud metadata address `169.254.169.254` is refused outright.
- **Fail closed on the unknown.** An unparseable address and a DNS resolution
  failure are both treated as blocked, never as "cannot tell, so allow".
- A private or loopback host is **allowed**, because a local Ollama is the point,
  but the setup UI states that the server will connect to it. This is a
  single-user, self-hosted product where the operator already has server access,
  so the goal is preventing an accident, not defending against the operator.

### Secrets

- Encrypted at rest with the existing Fernet, derived from `API_KEY_PEPPER` and a
  per-install `FERNET_SALT`.
- **Never returned by any endpoint**, not masked, not partial. A GET returns a
  boolean presence flag and a fingerprint.
- Never logged, never written to an audit row, never included in an exception
  message. The audit writer redacts secret-shaped keys from arguments before
  storing them.
- Decrypted only at the moment of use, held in a local variable, never cached on
  a long-lived object.
- The password input starts empty even when a key is configured; blank on save
  means keep the existing key.

#### One decryption path, pinned by a test

Decryption of an agent secret happens in **exactly one function**, named with a
leading underscore, and a test asserts by source scan that no file outside a
named allowlist contains its name:

```python
def test_decryption_callers_are_exactly_the_allowlist():
    offenders = [
        str(p) for p in SRC.rglob("*.py")
        if "_decrypt_agent_secret" in p.read_text(encoding="utf-8")
        and p not in ALLOWED
    ]
    assert offenders == []
```

It is a plain source grep, not import inspection, so aliasing the import does
not evade it: the alias statement still contains the name. Adding a caller makes
CI fail until the file is added to the allowlist, which forces a visible,
deliberate diff line. Adding a caller is a security review, not a refactor.

#### A traceback can leak a secret

CLAUDE.md requires `logger.exception()` for error logging, and that is right
everywhere in this codebase except one narrow case, which the agent module has:
`exc_info` captures local variables, so a traceback raised from a frame that
holds a **decrypted API key in a local** writes that key into `errors.jsonl`.

In the credential-set and credential-test paths only, log with
`logger.error("...", extra={"error": str(exc)})` and no traceback, with a
comment naming this reason. Everywhere else in the module, `logger.exception()`
as normal. ragz applies exactly this carve-out around its password paths.

### Transport and session

- Every route is `@check_session_validity` and CSRF-protected. **Nothing here is
  exempted.** There is no webhook and no unauthenticated entry point.
- Conversation ownership is checked on every read and write, and a conversation
  that is not yours answers **404, never 403**, so the id space cannot be probed.
- A shared rate limit covers the blueprint, with a tighter limit on the streaming
  and test routes, which are the expensive ones.

### Bounding the loop

An agent that loops is a cost and a risk, not merely a bug.

- `tool_call_limit` is set on the agent and enforced across the whole run.
- A per-session cap on orders, and a duplicate-order window, both live in the
  risk guard.
- Every run is cancellable, and a client disconnect cancels it server-side
  rather than leaving it running and billing.

### Rendering

- Markdown only, with no raw-HTML plugin. Nothing the model emits is trusted as
  markup.
- OpenUI Lang renders through a fixed component library. The model chooses among
  known components and cannot introduce new ones at runtime.
- Generated code is displayed in a code block, never evaluated in the browser.

### Fail open or fail closed, decided per control

Not uniformly for the module. Decide by what each control protects, and write
the reason next to it:

| control | direction | why |
| --- | --- | --- |
| risk guard, all checks except affordability | **closed** | it is the only thing standing between a confused model and a real order |
| affordability check with missing market data | **open** | refusing a human-approved order because a quote lookup hiccuped is the worse failure, and it has already passed every other gate |
| SSRF guard on an unknown host | **closed** | an unknown target is not a safe target |
| unrecognised order status from a broker | treat as **working** | reading an unknown exit as dead lets a second exit open a reverse position |
| audit write failure | **open**, swallowed | the trail is best effort; the risk guard is what enforces policy |
| provider unreachable during a credential test | **closed**, reported | the operator is asking a question and deserves the real answer |

### Do not port these

ragz is multi-tenant SaaS. Several of its strongest controls exist to mediate
between different people in one organisation and would add surface without
adding safety here, where the deployment is single-user and the operator already
has server access:

- tenant isolation, composite tenant foreign keys, org-scoped query contexts
- role templates, permission catalogues, separation-of-duty carve-outs on
  reading the audit log
- per-organisation quotas and usage allocation, org-level resource caps
- consent gates whose purpose is stopping one tenant spending another's budget

What is kept from the quota machinery is the shape, not the tenancy: a
persistent cap on a costly or side-effecting action, checked before the call and
incremented only after it succeeds, so a failure cannot burn the budget. For
this module that is the per-session order cap and the duplicate-order window.

### Audit

Every mutating call writes an attempt row before the service is touched and a
result row after, plus a decision row when a human approves or rejects. The
trail is append-only and survives a failed order, a refused one and a rejected
one. An audit write failure is logged and swallowed so it can never block a
trade, which means the trail is best-effort by design and the risk guard, not
the audit, is what enforces policy.

## Generators

### Python strategies

Emit a script matching `strategies/README.md`: read `OPENALGO_API_KEY`,
`HOST_SERVER`/`OPENALGO_HOST` and `WEBSOCKET_URL` from the environment, never
hardcode a credential. Write to `strategies/scripts/` using the existing
sanitize-and-contain rules from `blueprints/python_strategy.py`: `secure_filename`,
strip to `[A-Za-z0-9_-]`, timestamp suffix, and a `resolve()` containment check
against the directory even though we control the name.

Call into the existing launcher. Do not duplicate the subprocess machinery.

### Flow JSON

`docs/prompt/flow-import-format.md` is written to be fed to an LLM as a system
prompt; use it directly rather than paraphrasing the schema. Generate, then POST
to `/flow/api/workflows/import` (new) or `/replace` (iterating on one), and feed
the returned `errors[]` of `{path, code, message}` straight back as tool
feedback so the model self-corrects. The validator is the ground truth; an
invalid workflow cannot ship.

Never invent a node type. If a requirement has no matching node, say so in
prose.

## Web search

Three providers, configured in the same database-backed settings UI as the LLM
providers. **No web search key ever goes in `.env`**, including Perplexity's.

| provider | key | shape of result |
| --- | --- | --- |
| DuckDuckGo | none | links |
| Tavily | required | links, optionally a short answer |
| Perplexity | required | a synthesised answer with citations |

Keys live in `ag_secret` under `websearch:{provider}`, encrypted with the same
Fernet, returned to the UI as a fingerprint and a boolean, and testable with the
same cheapest-real-call pattern as a model. DuckDuckGo appears in the UI with no
key field and is the default, so search works out of the box with nothing
configured and nothing leaving the machine to a paid API.

Perplexity is not the same kind of tool as the other two. It returns a
synthesised answer with citations rather than a list of links, so it is a
**separate tool** with its own name and description. Presenting a synthesised
answer as though it were search results would let a single upstream summary
enter the context wearing the authority of primary sources.

### The safety envelope

Web search is the only tool that leaves the process, so it carries ragz's full
set of controls and they are not optional:

- **The taint boundary applies here first.** The model's requested query never
  reaches the provider. The outgoing query is constructed so that every token in
  it provably appears in the operator's own message, with a fallback to that
  message verbatim. This is what stops injected tool output from exfiltrating
  account data inside a search string.
- **Redaction runs before the construction**, not after, so patterns that depend
  on punctuation still match: emails, bearer tokens, provider-prefixed keys,
  `key=value` pairs, and long high-entropy strings.
- **A per-turn budget and a persistent daily cap.** The per-turn budget alone is
  bypassed by simply sending another message, which is why ragz added the
  persistent one. The cap is checked before the call and incremented only after
  it succeeds, so a provider failure cannot burn it.
- **Results are lower-trust than platform data.** They are wrapped in the same
  untrusted-content block as everything else, and additionally labelled as web
  content so the model does not present a random page with the authority of the
  broker's own position book.
- **The decision is logged, never the query.**

## Visualization

The agent can emit **OpenUI Lang**, which the client renders as charts, tables
and cards inline in the conversation.

- Backend responsibility is only the system prompt and forwarding text. There is
  no Python SDK; none is needed.
- Packages: `@openuidev/react-lang`, `@openuidev/react-ui`,
  `@openuidev/react-headless`, plus `zod@^4` and `zustand@^4.5.5`. React 19 is
  supported.
- `<Renderer response={growingString} library={lib} isStreaming={bool} />` is
  the only renderer. Feed it the **whole accumulated string** each token; its
  parser diffs internally and is O(new characters).
- **Charts must not animate.** Every OpenUI genui-lib wrapper hardcodes
  `isAnimationActive: false`, and that is the look being reproduced. Where
  animation is on elsewhere the config is `animationBegin: 0`,
  `animationDuration: 1500`, `animationEasing: "ease"`.
- Series colours come from `getDistributedColors`, which centres on the
  palette midpoint and fans outward. A two-series chart on the default `ocean`
  palette uses indices 4 and 6, not 0 and 1. Sequential assignment is wrong.
- `ThemeProvider` is nesting-aware; mount it around the chat panel only, so
  `--openui-*` variables do not leak into the rest of OpenAlgo.

The agent emits UI through a `render_ui` tool rather than in its prose, so
ordinary answers stay markdown and a visualization is a deliberate act.

## Rendering generated code

The reference here is deliberately **not** ragz. Its code rendering is minimal:
no syntax highlighter of any kind, no language badge, no filename, no line
numbers, no collapse, and a plain `<pre>` in which a Python fence and a JSON
fence render identically. It also re-parses the entire accumulated message on
every streamed token with no memoization, which is quadratic and invisible only
because a RAG answer is short. A generated strategy is not short.

Two things from it are worth keeping, and they are both security controls:

- `skipHtml`, no `rehype-raw`, and no `rehype-sanitize` either. HTML is never
  parsed into elements, so there is no allowlist to get subtly wrong.
- **`img: () => null`.** Markdown images are blocked entirely, not just raw
  `<img>` tags, because an image URL is an exfiltration channel: a model steered
  by injected content embeds a secret in a URL the browser then fetches to an
  attacker's host. This module feeds tool output back into context, so it is
  exposed to exactly that. Both are pinned by a test.

### The editor, not a code block

OpenAlgo already ships `@uiw/react-codemirror` with `@codemirror/lang-python`
and `@codemirror/lang-json`, themed against `useThemeStore`, wrapped as
`components/ui/python-editor.tsx` and `json-editor.tsx`. **No new dependency is
needed and none should be added.**

A generated strategy renders in the same `PythonEditor` the `/python` page uses,
and generated Flow JSON in the same `JsonEditor` as Flow's replace-from-JSON
dialog, both read-only in the message. The code the agent produces therefore
looks exactly like the code the operator will edit, with the same theme, the
same font and the same highlighting, rather than like a chat attachment.

Around it: a header carrying the filename and language, a copy action, and
actions that belong to the artifact rather than to the chat, "Save to
strategies" and "Open in editor". Long output collapses with a line count and
expands on request, because a 300-line strategy must not bury the conversation.

Ordinary prose stays markdown. Only a generated artifact gets the editor.

### Streaming without the quadratic cost

Do not commit React state per token.

- Accumulate deltas into a ref and flush on a fixed cadence, roughly one
  animation frame. The stream is still smooth and the parse count drops by
  orders of magnitude.
- Split the message into a **stable prefix** and a **streaming tail** at the
  last completed block boundary. Re-parse only the tail; the prefix is rendered
  once and memoized.
- A code artifact is **not** re-highlighted per token. While its fence is open
  it renders as plain monospace text, and CodeMirror mounts once the block
  closes. Highlighting a half-written file on every keystroke is wasted work and
  it flickers.
- Instruct the model to emit one artifact per fenced block with a real language
  tag and a filename as the first comment line, which is what makes "has this
  block closed" trivial to detect.

## Chart surface

**There is no second chart and no second chart page.** The agent is a docked
right-hand panel on the existing `/trading` terminal, hosted by
`frontend/src/components/trading/panelShell.tsx` exactly as `WatchlistPanel` and
`OptionChainPanel` are, with its own rail button, its own remembered width, and
the same `PANEL_HEADER` horizon so it reads as shipped rather than bolted on.

`components/trading/AgentPanel.tsx` holds: a header with the assistant name and
a close control, an empty state, a row of suggested-prompt chips derived from
the current chart context ("Analyse this chart", "Draw demand and supply",
"Identify candlestick patterns", "Analyse my drawings"), the message thread, and
a composer.

It shares the chat surface's stream client and frame vocabulary; only the
rendering differs, because a narrow panel shows one collapsed status line per
turn rather than a full tool timeline.

The panel reads `terminal.context()` **fresh at send time**, never captured at
mount, so the agent always sees the chart as it currently is. Commands returning
from the model are applied through a single promise queue rooted at the
terminal's own init, so commands from different turns cannot interleave and one
stalled fetch cannot wedge every later turn.

`ChartCommand` is a closed union applied by the existing terminal:

```
draw | clear | set_symbol | set_interval | set_chart_type
| add_indicator | remove_indicator | update_indicator | focus
```

`apply(command)` switches on `op` and **ignores an unknown op** rather than
throwing, so a newer backend cannot break an older client mid-turn. Drawing ids
are namespaced `ai:{group}:{index}` so agent markup never collides with the
user's own drawings and `clear` never removes theirs.

Geometry is computed from real bars server-side. The model narrates; it does not
invent a price.

## HTTP surface

All under `/agent/api`, all `@check_session_validity`, all behind a shared rate
limit, CSRF on by default.

| method | path | purpose |
| --- | --- | --- |
| GET | `/status` | the setup gate |
| GET/POST | `/models` | list, create |
| PATCH/DELETE | `/models/<id>` | update, remove |
| POST | `/models/<id>/test` | validate credentials |
| GET | `/catalog` | picker metadata |
| GET/PUT | `/settings` | agent settings |
| GET/POST | `/conversations` | list, create |
| GET/DELETE | `/conversations/<id>` | fetch, delete |
| POST | `/chat/stream` | SSE |
| POST | `/chat/confirm` | SSE, resume a paused run |
| POST | `/chat/<run_id>/cancel` | cancel |

Register the blueprint in `app.py` beside `flow_bp`. Register the React routes
in `blueprints/react_app.py` as well, or an unauthenticated hit on `/agent`
counts toward an IP ban through `Error404Tracker`.

## Startup

One call from `app.py`, mirroring `services/strategy_module/runtime.py`:

```python
from services.agent.runtime import start_agent_module
```

Nothing starts at import. Every step is guarded independently; a platform that
will not boot because the agent failed to start is worse than one that boots
without it. Add `("Agent DB", ensure_agent_tables_exists)` to the
`db_init_functions` list.

## Migration

Roughly 290k live deployments upgrade with `cd upgrade && uv run migrate_all.py`.
A schema change that only exists in `init_db()` never reaches any of them,
because `create_all` skips a database whose tables already exist and seeding
functions typically only run against an empty table. **Every schema change in
this module ships as a script in `upgrade/`, registered in `migrate_all.py`.
This applies to the first release and to every change after it.**

`upgrade/migrate_agent.py`:

- Idempotent, and safe to re-run. Check whether the change is already present
  with `PRAGMA table_info` / `inspect(engine)` and return quietly if so.
- `--status` reports what *would* change and is completely free of side effects.
- Resolves a relative `sqlite:///db/openalgo.db` to an **absolute** path against
  `PROJECT_ROOT`, because the documented invocation is run from `upgrade/` and a
  relative path would silently create `upgrade/db/openalgo.db` instead.
- Its own engine with `NullPool`, disposed in a `finally`.
- Imports `_pragmas` so it waits on the lock the way the running app does.
- **Not** in `REQUIRED_MIGRATIONS`. The agent is optional and its absence must
  not fail an upgrade for an operator who never uses it.

### The three orderings it must survive

A new module makes this easier than a column change, but only if all three
arrival orders are handled, and the second is the one that gets missed:

1. **Fresh install.** Tables do not exist. The migration creates them.
2. **App started first, migration second.** `init_db()` has already created the
   tables through `create_all`. The migration must find them present and report
   nothing to do, not fail and not recreate.
3. **Migration run twice.** Identical to the second run of any ordering above.

### Testing it

Testing on an empty database proves almost nothing. A migration that works on a
fresh database and fails on a populated one is the common failure, so:

- Copy a **real** `openalgo.db` with live data to a scratch path.
- Run the migration against the copy, then `--status` again, and confirm the
  second run reports nothing.
- Start from the app-created-tables state as well, not only the empty state.
- Confirm no existing table is touched. This module adds tables and must not
  alter or read any other feature's schema.

### For later changes

When a column is added to an `ag_` table after release, the same discipline
applies with two additions from CLAUDE.md that do not apply to the first
release: never clobber a value an operator may have customised, so guard the
update on the old value; and backfill from the row's own data rather than a
uniform default, because a default is usually wrong for existing rows. SQLite
cannot alter a `CHECK` constraint or add a `UNIQUE` column in place, which is
why the vocabularies in this module are validated in Python rather than declared
as SQL constraints.

## Testing

`test/test_agent_*.py`, one file per concern. Use the fixture skeleton from
`test/test_strategy_module_api.py`: a session-scoped throwaway SQLite via
`create_db_engine()`, function-scoped table truncation, a minimal single
blueprint Flask app, `_log_in()` writing the three session keys
`utils.session.is_session_valid` expects, and `monkeypatch.setattr(limiter,
"enabled", False)`.

Never call a real provider in a test. The LiteLLM construction is tested by
asserting the kwargs, and the stream by feeding synthetic agno events through
the translator.
