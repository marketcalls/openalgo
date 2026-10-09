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
  settings.py           DB-backed config accessors
  providers.py          provider vocabulary -> LiteLLM kwargs
  catalog.py            model catalog (LiteLLM price/context snapshot)
  chatgpt_oauth.py      device flow, token custody, billing verdict
  chatgpt_models.py     plan models LiteLLM's registry does not list
  litellm_tool_args.py  restores parallel tool-call arguments LiteLLM drops
  tool_guard.py         agent-wide hook: a refused argument set -> a correction
  builder.py            Agent construction + the tool factory
  stream.py             real-thread bridge; agno events -> frames
  frames.py             the wire contract, standalone, no agno import
  viz_sink.py           per-run side channel a viz tool's payload travels on
  attachments.py        files the operator adds to a turn
  prompts.py            system prompt assembly
  chart_contract.py     the /trading wire contract, both directions
  chart_geometry.py     levels and zones computed from real bars
  indicators/           registry, compute and descriptions for openalgo.ta
  skills/
    registry.py         SkillSpec: which skill folders, on which surfaces
    loader.py           reads a skill folder live, path-checked, never executes
    prompt.py           the SKILLS prompt section
  mcp/
    registry.py         McpServerSpec: the external data servers
    client.py           sync streamable-HTTP client, breaker, caches
    prompt.py           the EXTERNAL DATA (MCP) prompt section
  safety/
    __init__.py
    risk.py             pure-python order guard
    audit.py            append-only audit of every mutating call
  tools/
    __init__.py         registry: build_toolkits(context) -> list
    base.py             OpenAlgoToolkit, call_service, call_on_hub
    market.py account.py orders.py symbols.py options.py instrument.py
    live.py indicators.py chart.py viz.py option_viz.py openui.py
    websearch.py strategy_gen.py flow_gen.py openscript_gen.py
    skills.py mcp.py

services/openscript_store.py  the one OpenScript write path, shared with /trading
database/agent_db.py    schema + store
blueprints/agent.py     session API
upgrade/migrate_agent.py
scripts/mcp_live_check.py     opt-in live check of the MCP servers

frontend/src/
  api/agent.ts
  lib/agent/stream.ts       fetch + ReadableStream SSE client
  lib/agent/useAgentStream.ts
  lib/agent/subscription.ts telling a plan row from an API row
  pages/agent/               AgentIndex, AgentChat, AgentConfig
  components/agent/          AgentSetupGate is the gate, config/ the settings
                             (config/McpPanel.tsx is the external data switch)
```

There is no `runtime.py` and no `generators/` package. Generation is two
toolkits, `tools/strategy_gen.py` and `tools/flow_gen.py`, and the module has no
lifecycle to start; see **Startup**.

Two things deliberately live outside `services/agent/`:

- **The chart command vocabulary is applied by the existing terminal.**
  `terminal.applyChartCommands(commands)`
  (`frontend/src/lib/trading/terminal.ts`) serialises a frame's commands through
  one promise queue and delegates the per-command decision to
  `frontend/src/lib/trading/chartContract.ts`, which is pure and testable
  without a chart. The chart already exists; the agent drives it rather than
  owning a second one.
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
flag, the external data switch `mcp_enabled`, and anything added later without
a migration. A key with no row reads its default, which is how `mcp_enabled`
reached existing installs already on: see **External data (MCP)**.

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

A ChatGPT plan is **not a sixth kind**. It is stored as `litellm` with the
prefix inside the name, `chatgpt/gpt-5.4`, because that is exactly what the
`litellm` kind already means: the id is passed through verbatim. One thing
changes, and it is the key. `providers._is_subscription` carves a `chatgpt/`
model out of `needs_key`, so the row saves with nothing pasted, and the import
it does that with is lazy and fails closed: a module that cannot be imported
answers False and the row is asked for a key as before. See **The ChatGPT
subscription** below.

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
litellm.models_by_provider       #   96 providers, about 3,000 models
litellm.model_cost               # about 3,500 entries of per-model metadata
```

The first three are fixed by the pinned package. **The model and price counts
are not, and are given as approximations deliberately.** LiteLLM fetches its
cost map from a remote URL during `import litellm` unless
`LITELLM_LOCAL_MODEL_COST_MAP=true` is set, which this repository never sets, so
the numbers move under a pin that has not changed: measured on one install,
3,043 models and 3,560 priced entries with the fetch, 2,799 and 3,175 with the
in-package backup forced. Writing an exact pair here would be a number that goes
stale without anything in this repository changing, which is the failure the
whole catalog design exists to avoid.

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
models arrive with the package. No migration, no regeneration script, and no
catalog rows to keep in sync. The one exception is the ChatGPT plan model list,
which is ours to maintain and whose procedure lives in `CLAUDE.md`.

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
  models for it. `catalog._BRANDS` supplies a display name and an icon slug for
  the brands an operator recognises; anything without an entry falls back to the
  provider id, so a provider added by a future LiteLLM release still appears
  rather than disappearing until someone updates a table. There is no bundled
  logo set: a company logo is somebody else's mark and the catalog grows with
  every release, so the tile is a monogram on a per-provider colour, hashed from
  the id for anything unrecognised.
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

**The provider list is served by the backend, not held in the frontend.**
`catalog.py` decides the display name, the icon slug, the `provider_kind`, and
whether a key or a base URL is required, and `GET /agent/api/catalog/providers`
returns it at request time. That is the whole difference from ragz, whose
equivalent is a 6,700-line generated `provider-catalog.ts`: a generated constant
is a second source of truth that goes stale between LiteLLM bumps, and the
information is already in the package the backend has imported. The only local
map left in the frontend is the accent colour behind a provider's monogram,
which is decorative. The backend still only ever stores one of the five
`provider_kind` values.

A registered-models table below the grid lists every configured model with its
provider, key fingerprint, test status, an `enabled` checkbox and a `default`
radio.

### Resolution order

Explicit request, then the `is_default` row, then a typed error. A named model
that is missing or disabled is an error, never a silent fall-through to the
default. Resolution happens **before any stream byte is written**, so a bad
model id fails as a clean HTTP error rather than mid-stream.

## The ChatGPT subscription

A ChatGPT Plus or Pro plan is a **second billing path, not a second key**.
LiteLLM 1.99.0 ships it as its own provider, `chatgpt`, authenticating by OAuth
device flow against **Codex**, not the ChatGPT web app:

```
openai/gpt-5.4      an API key        -> OpenAI API credits
chatgpt/gpt-5.4     an OAuth sign-in  -> the operator's plan
```

LiteLLM lists ten `chatgpt/*` models, newest `gpt-5.4`. **Eight of the ten share
a bare name with an `openai` model**; only `gpt-5.3-instant` and
`gpt-5.3-codex-spark` are subscription-only. That collision is the problem this
whole feature is shaped around: an operator who registers both ends up with two
rows reading GPT-5.4 that bill to different places, and the prefix is the only
thing in the data that separates them.

`services/agent/chatgpt_oauth.py` owns the credential and the billing verdict.
`services/agent/chatgpt_models.py` is the model supplement; its maintenance
procedure lives in `CLAUDE.md` and is not repeated here.

### The device flow runs on a real OS thread

The flow polls every 5s for up to 900s, LiteLLM's own
`DEVICE_CODE_POLL_SLEEP_SECONDS` and `DEVICE_CODE_TIMEOUT_SECONDS`. Run on the
green side, that stops the single production worker for a quarter of an hour,
orders included, while behaving perfectly on the dev server. It is the trap
`CLAUDE.md` describes, in its most expensive form.

So `start_login` does exactly one bounded HTTP request on the caller's side,
returns the verification URL and the user code, and hands the poll to a
`utils.real_threading.Thread`. Nothing green ever waits on it: `login_status` is
a frozen copy taken under a real lock held across a dict copy, and `cancel_login`
joins with `real_threading.join`, which polls and yields.

Proved in a subprocess with eventlet patched, because `monkey_patch()` is global
and cannot be undone, asserting on elapsed time and hub liveness rather than on
return values, which were always right. The thresholds the tests hold to:

| | |
| --- | --- |
| the same poll inline on the green side | blocks for its whole duration, at most one hub tick, the defect |
| `start_login` returns | under 0.5s, state `pending` |
| while the real thread polls | over 20 hub ticks in 0.8s, at least two polls landed |
| `cancel_login` from a greenlet | the hub keeps ticking throughout |

The first of the three eventlet cases asserts the defect itself, so nothing below
it can pass vacuously.

**A second `start_login` returns the login already in flight** rather than
replacing it. The device endpoint applies a five-minute cooldown after issuing a
code, recorded as `device_code_requested_at`, which LiteLLM's own client
honours, so a second code inside it gets nowhere. And the first code is already
on the operator's screen and may be half typed, so invalidating it turns a slow
login into a failed one. Replacing it is a deliberate act, `force=true`, which
is what a "start over" control sends.

### Listing a model must not start a login

Sharper than the poll, because it needs no operator at all.
`litellm.supports_reasoning(model="chatgpt/gpt-5.4")` resolves the provider
through `ChatGPTConfig._get_openai_compatible_provider_info` to
`Authenticator.get_access_token`, which with no cached token falls through to
`_login_device_code`: a code printed to a stdout nobody is reading, then a
fifteen-minute poll on the calling thread. That call sits behind no gate at all.
`blueprints/agent.py:_with_resolved_capabilities` runs it for every row on
`GET /agent/api/models`, so merely **listing** a registered plan model would
hang the request for a quarter of an hour.

`providers._litellm_opinion` reads the capability out of `litellm.model_cost`
for a subscription id instead of calling the predicate. It is the same answer,
because the predicate is a lookup in that same table once the provider has been
resolved. The lookup has to include LiteLLM's own bare-name fallback: none of
the ten `chatgpt/` entries carries `supports_reasoning`, so reading the prefixed
entry alone answered False for all ten against a predicate that answers True for
eight, silently turning every reasoning model on a plan into a non-reasoning one
and losing a capability the operator is paying for.

`builder.resolve_model` gates a subscription row on `chatgpt_oauth.ensure_ready()`
for the same reason one layer down: without it the run reaches LiteLLM with
nothing to authenticate and starts that same login on the run thread.
`ensure_ready` does no network work and imports no LiteLLM, which is what makes
it safe on the green side, and `test_the_gate_does_no_network_work` pins that by
making the module's own transports raise. A model-registration hook placed there
was caught by that test and moved to `builder.build_model`.

### Token custody

`ag_secret` under `oauth:chatgpt` is the system of record, encrypted with the
same Fernet through `agent_db.set_secret`, which compares **decrypted plaintext**
for the reason the schema section already gives. The file is a cache the module
rebuilds from it, which is what makes a database restored into a fresh container
already authorised.

Containment is a fix, not a precaution. LiteLLM's `Authenticator` writes the
access token, the refresh token and the id token as plain JSON to
`CHATGPT_TOKEN_DIR`, defaulting to
`os.path.expanduser("~/.config/litellm/chatgpt")`. Where HOME is unset that
expansion has already produced a literal `~` directory inside this repository
holding live credentials, one `git add -A` from being committed; the root
`.gitignore` carries a `/~/` rule for the folder it left behind.
`configure_token_dir` **sets** the variable rather than defaulting it, refuses
any path containing a literal tilde, points it at `db/chatgpt_oauth/`, narrows
the directory to `0700`, and writes a nested `.gitignore` containing `*`, so the
directory the module controls needs no tracked file edited to hold a refresh
token. The test asks `git check-ignore` itself rather than asserting about the
ignore file's contents.

Three leaks are pinned rather than assumed. Five re-stores of an unchanged
credential write the row once. `status()`, the `LoginStatus` repr and every log
line across the whole flow carry neither token nor user code, and the user code
is absent deliberately: a device code is a standing phishing target, which is
why LiteLLM's own prompt says so. And a dead transport raised an `OSError` whose
message quoted the request body, literally containing `refresh_token=<token>`,
which `_post` reduces to "A ChatGPT sign-in request failed: OSError". The class
name locates the bug without quoting anything.

Two fingerprints exist for one credential and they differ. The stored value is
the whole auth record as canonical JSON, so the `ag_secret` row fingerprints a
blob. `status()` fingerprints the refresh token, so it survives an access-token
refresh and stays the identifier the operator saw when they signed in. That one
is the one to show.

### Honest billing: tokens, and no cost

`litellm.model_cost` prices `gpt-5.4` and carries an entry for `chatgpt/gpt-5.4`
with no price keys at all. That is deliberate and correct, and
`catalog.estimate_cost` already answers None for it. The bug was downstream:
`stream._apply_reported_cost` patches a null cost from the provider's reported
metrics, and LiteLLM's `completion_cost` answers `0.0` rather than None for a
model it cannot price. A plan turn therefore rendered `$0.00`, which claims the
turn was free when it consumed plan quota. Falling back to the bare name would
have shown the API price instead, which is worse: a plausible number nobody
would question.

The rule is **tokens and no cost, labelled as subscription usage**. `Usage`
gained `billing: str = "metered"`. `chatgpt_oauth.apply_billing` is the single
function that settles it, forcing a null cost whatever anybody computed or
reported, and `_apply_reported_cost` skips a frame already marked
`subscription`. A metered turn passes through untouched, including a genuine
`0.0` from a free model, which is a different claim and a true one.

`EventTranslator` keeps the **resolved** model id alongside the reported one,
because `_usage_frame` overwrites `self._model` with whatever the provider
named, and a bare subscription name cannot be recognised. Measured against
`litellm==1.99.0`: `catalog.get_model_meta("gpt-5.3-instant")` answers None,
because a subscription-only name is in no bare-name entry at all, and
`get_model_meta("gpt-5.4")` answers **OpenAI's** row, priced, because eight of
the ten share their bare name with an API model. Neither answer can be read as
"this turn ran on a plan", and the second reads as the opposite. The `chatgpt/`
prefix is the only working signal. One prefixed name is therefore enough, and a
metered row can never report a `chatgpt/` model, so there is no false positive
to trade against.

The field has to be carried the whole way or a reloaded turn silently loses it:
`Usage` in `api/agent.ts`, `hydrate.ts:toUsage`, and `UsageBadge.tsx`, which
renders "included in your ChatGPT plan" where a price would go. Unknown is read
as metered everywhere, because claiming a turn was covered by a plan when nobody
said so is the reading that costs somebody money.

### The model test streams, and is drained

`blueprints/agent.py:test_model` passes `stream=True`, for the upstream reason
`CLAUDE.md` records and because the agent only ever runs `agent.run(stream=True)`:
a test taking a path the product never takes can fail on a defect no operator
would meet and pass over one they would. The **drain** is the part that is not
in `CLAUDE.md` and is equally load-bearing. An unread iterator would report
success on a credential the provider goes on to reject, which is the one thing
this route exists to catch.

### Telling the two rows apart

The collision is a naming problem, so the answers are in the UI and in one
shared module, `frontend/src/lib/agent/subscription.ts`, rather than repeated in
each component.

- `RegisteredModelsTable` renders `model_name` under `display_name` and badges
  the `chatgpt/` prefix. A plan row has no `api_key_fingerprint`, because its
  credential is not in `ag_secret` under `provider:` or `model:`, so the
  fingerprint it shows comes from the subscription status instead.
- `suggestSubscriptionDisplayName` yields "ChatGPT Plan: GPT-5.4" rather than
  "GPT-5.4". An operator accepting both defaults would otherwise hold two
  identical names billing to different places, and the cheapest place to prevent
  that is where the name is chosen. The prefix leads because that is the half a
  reader scans for, and putting it last puts the distinguishing half exactly
  where the column truncates.
- **The panel sits above the provider grid** on `/agent/config`. The grid draws
  24 cards before offering to show more, so anything under it starts a screen
  and a half down: the trading switch was buried exactly that way once. This
  panel answers a question an operator arrives with, so it sits where they land.

## The setup gate

`/agent` is unusable until a model is configured and tested.

- `GET /agent/api/status` returns `{configured, model_count, default_model_id,
  trading_enabled, agent_available, has_openalgo_api_key, chatgpt_authorised}`.
  It carries a count and not a model list: the picker fetches `/models`, and a
  gate that ships the registry makes every page load pay for it.
- `agent_available` and `has_openalgo_api_key` are reported rather than folded
  into `configured`, because an operator looking at a setup screen after adding
  a model deserves to be told which of the two is missing.
- `chatgpt_authorised` is on the gate rather than behind a second request,
  because a `chatgpt/` model that is registered but not signed in looks
  configured and is not, and the setup screen has to say so on first paint.
  `is_authorised()` does no network work and starts no device login, which is
  what makes it safe to read here.
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

`/agent` follows both, but the guard is a component rather than a route
wrapper. `components/agent/AgentSetupGate.tsx` exports the setup screen and
`useAgentConfigured`, the hook that reads `/status` under one shared query key;
`AgentIndex` renders the gate when `configured` is false and `AgentChat`
otherwise, and the `/trading` panel renders the same gate with `compact`. One
component, so the two surfaces cannot drift, and opening the panel after the
chat costs no second request. An unreachable status reads as **not
configured**: a status call nobody could answer is not evidence of a working
agent behind it, and showing a chat that has nothing to talk to is the failure
that matters.

The nav entry is **always shown, never filtered**, matching how Telegram,
WhatsApp, Flow and Python Strategies are already listed.
Only capability-gated items like Leverage are filtered, and that is a fact about
the broker rather than about setup state.

## Streaming

### Transport

`POST /agent/api/chat/stream`, SSE. Frames are `data: {json}\n\n` with **no
`event:` line**; every frame is discriminated on a `type` field. The client is
`fetch` plus a `ReadableStream` reader, not `EventSource`, because the request
carries a body.

Headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no`.

No `Connection` header. It is hop-by-hop, PEP 3333 forbids a WSGI application
from setting one, and the server already owns it. Sending `keep-alive` on a
chunked stream the server intends to close produces the merged, contradictory
`Connection: keep-alive, close`, and a client that believes the first token
keeps a socket in its pool that the server has already shut: the next request on
it never gets a reply.

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
- On client disconnect (`GeneratorExit`) the route calls
  `stream.request_cancel(agent, run_id)` and the `finally` block joins the
  thread with a timeout. Without that a dropped connection leaks a thread per
  turn in a worker that never restarts.
- **Never `agent.cancel_run` directly from a route.** Agno guards its
  cancellation registry with a `threading.Lock` built after monkey-patching, so
  that lock is green, and the real thread driving the run takes it on every
  cancellation check. A greenlet contending on it is how the hub ends up trying
  to resume a waiter belonging to another OS thread, which raises
  `greenlet.error: Cannot switch to a different thread` and wedges whichever
  side lost. `request_cancel` hands the one dictionary write to a throwaway real
  thread and joins it with a timeout.

Agno's sync `agent.run(stream=True)` returns a plain `Iterator[RunOutputEvent]`.
We do not use `arun`. There is no asyncio anywhere in this module.

### Frames

`frames.py` defines these and nothing else imports agno:

| type | payload |
| --- | --- |
| `start` | `run_id`, `session_id`, `conversation_id`, `user_message_id` |
| `token` | `delta` |
| `tool_start` | `id`, `name`, `args` |
| `tool_end` | `id`, `name`, `ok`, `result`, `duration` |
| `reasoning` | `delta` |
| `viz` | `kind`, `spec`, `title`, `source` (tool-built, see **Visualization**) |
| `ui` | `delta` (OpenUI Lang text, see below) |
| `chart_command` | `commands: [...]` |
| `confirm` | `run_id`, `session_id`, `requirements: [...]` |
| `notice` | `level`, `message` |
| `usage` | `input_tokens`, `output_tokens`, `total_tokens`, `cached_tokens`, `reasoning_tokens`, `cost_usd`, `billing`, `model`, `ttft_ms` |
| `error` | `message`, `kind` |
| `done` | `reason` (`stop`/`cancelled`/`incomplete`) |

### Token usage and cost

Agno reports this without extra work: `ModelRequestCompletedEvent` carries
`input_tokens`, `output_tokens`, `total_tokens`, `time_to_first_token`,
`reasoning_tokens`, `cache_read_tokens` and `cache_write_tokens`, and
`RunCompletedEvent` carries `metrics`.

**Cost is computed locally, never guessed.** `litellm.model_cost` already gives
`input_cost_per_token` and `output_cost_per_token` for the model in use, and the
catalog is read anyway, so cost is arithmetic rather than a second API call.
A model absent from `model_cost` reports tokens with `cost_usd: null`; showing
tokens and admitting the price is unknown beats inventing a number.

**A ChatGPT plan turn has no price at all, which is a third case and not the
second one.** `billing` carries it: `metered` when the turn is billed per token,
`subscription` when it came out of a plan. A null `cost_usd` therefore means one
of two things and the field says which, so the UI can render "unknown" and
"included in your plan" differently instead of collapsing both to a dash. The
value is decided once by `chatgpt_oauth.apply_billing` and persisted on the
message row with the rest of the usage, or a reloaded conversation reports a
plan turn as metered with no price. See **The ChatGPT subscription**.

The UI shows per-turn usage under each answer and a running total for the
conversation. Usage is persisted on the message row so a reloaded conversation
still shows what it cost.

Three measured agno behaviours the translator must handle:

- A **paused run terminates the stream** with a `confirm` frame and **no
  `done`**. The client must not treat that as a failure.
- `continue_run` defaults `stream_events` to `False`. Pass it explicitly.
- `ToolCallCompleted` with an error is followed by a separate `ToolCallError`.
  Suppress the second so a failure is not reported twice.

### Parallel tool calls and the Responses bridge

**The symptom.** A question naming two or more instruments ("history of TCS and
INFY", "expiries for crude, gold and silver") failed every tool call in the
batch, each within milliseconds, with `Missing required argument` for every
parameter. The model retried until it fell back to one call per turn, which
worked. A question naming one instrument never failed, so the defect read as
the model being clumsy rather than as anything in the platform.

**The cause, measured on the wire.** Every GPT-5 model run with a reasoning
effort, and every `chatgpt/` subscription model, reaches LiteLLM's
chat-completions bridge over the Responses API
(`litellm.completion_extras.litellm_responses_transformation`). For one tool
call the backend streams the arguments as `function_call_arguments.delta`
events. For a batch of parallel calls it frequently sends no deltas at all:
each call's complete arguments arrive once in
`response.function_call_arguments.done` and again in
`response.output_item.done`. LiteLLM 1.104.0 builds the chat stream from the
`output_item.added` event (id and name, empty arguments) plus the deltas, and
ignores both `done` events, so agno assembles `arguments: ""` and pydantic
refuses the call before the tool body runs.

**The repair.** `services/agent/litellm_tool_args.py` wraps the bridge's
`chunk_parser`. It records, per stream, which output items have already
delivered argument text, and when a `done` event arrives for one that delivered
none, it emits the complete arguments as a single delta at the tool-call index
the bridge already assigned. Agno concatenates argument fragments by index, so
the call is whole by the time it runs. An item that did stream its deltas is
left alone, so nothing is delivered twice. Where the announcement itself was
missed, the call id and name travel with the arguments.

Three properties keep it a repair rather than a second bridge:

- **Installed from `builder._register_chatgpt_models`**, beside
  `litellm_eventlet.install()`, so it is in place before any model is built and
  never imported from a request path that must stay free of LiteLLM (see
  **Listing a model must not start a login**).
- **Idempotent and quiet on an unfamiliar LiteLLM.** A bridge without
  `_sequential_tool_call_index` logs a warning and is left unpatched, and any
  exception inside the wrapper falls back to LiteLLM's own chunk. A LiteLLM it
  does not recognise costs the repair, never the agent.
- **It has an expiry date, and a test says when.**
  `test/test_agent_litellm_tool_args.py` drives LiteLLM's real iterator with
  event sequences captured from the backend. The first test fails on an
  unpatched LiteLLM; `test_a_streamed_call_is_never_delivered_twice` fails the
  day LiteLLM emits the `done` arguments itself. That failure is the signal to
  delete the module, not to adjust it.

The tool-use section of the prompt tells the model that independent reads may
go out together in one turn, and the tool guard (see **Tools**) names the
fallback, one call at a time, should calls in a batch keep arriving empty for
some other reason.

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
- the `api_key` and `conversation_id` for the current run,
- `call_service(fn, ...)` and `call_on_hub(fn, ..., hub_wait=...)`, the module
  functions that run a callable where the web app's own code runs: on the hub
  under eventlet, inline under gthread and the development server. The first
  waits `AGENT_SERVICE_TIMEOUT_SECONDS`; the second takes its own wait for a
  callable whose own timeout is longer, which must exceed that timeout or a
  slow but healthy call is abandoned.

Docstrings **are** the schema. Every argument needs a real type hint and a
matching Google-style `Args:` line, or the generated schema is unusable.

### The registry

`tools/__init__.py` exposes:

```python
def build_toolkits(context) -> list[Toolkit]
```

and `builder.py` passes it as a **callable factory** to `Agent(tools=...)`, so
it is re-evaluated on every run against `run_context.session_state`. A session
that has not enabled trading never sees order tools in its schema at all, on any
surface. A capability is a boolean on `ToolContext` that a spec names in
`requires`: `trading_enabled`, `web_search_enabled` and `mcp_enabled` today,
each ANDed with the operator's own setting by `builder.build_session_state` so a
request cannot ask its way past a switch that is off. Adding a capability is a
file plus a registry entry.

### Refused arguments come back as a correction

Agno wraps every tool in pydantic's `validate_call`. When a call arrives with an
argument missing, of the wrong type, or with none at all, the tool body never
runs and pydantic's own text becomes the tool result: `5 validation errors for
MarketToolkit.get_history ... [type=missing_argument, input_value=ArgsKwargs(())
...] For further information visit https://errors.pydantic.dev`. A model reading
that has to work out which arguments mattered, and agno logs a full traceback
for what is an ordinary correction.

`services/agent/tool_guard.py:argument_guard` is passed as
`Agent(tool_hooks=[...])`, so it sits outermost on every tool. It rewrites
exactly one case, a `ValidationError` whose title is the tool being called,
into a `RetryAgentRun` that names each missing argument, each wrong one with
pydantic's reason, and each the tool does not take. That is the same channel
every tool already uses for a bad value, so the model reads one kind of
correction rather than two. When the arguments arrived empty it also says so
and suggests making batched calls one at a time, the fallback for the bridge
defect above.

Everything else passes through untouched: the tool's own `RetryAgentRun` or
`StopAgentRun`, a cancellation, and a `ValidationError` raised by some model
deep inside a tool body, which is a defect to see in the log rather than a
correction to hand the model. The hook runs on the agent's thread, does no I/O
and takes no lock. It never sees a paused confirmation: agno pauses before the
tool executes, so an approved call reaches it on resume like any other.
`test/test_agent_tool_guard.py` pins each case.

**Two budgets keep a long thread from teaching the wrong lesson.**

- `max_tool_calls_from_history = DEFAULT_MAX_TOOL_CALLS_FROM_HISTORY` (20) in
  `build_agent`. Agno replays `DEFAULT_NUM_HISTORY_RUNS` (8) earlier runs, and
  without a cap every tool call and result in them goes back to the provider on
  every turn. Agno keeps the newest calls and drops the rest in pairs, so the
  conversation's answers survive, a tool-heavy thread stops re-sending old
  payloads, and a refused call from an earlier turn stops being shown to the
  model as an example to repeat.
- `DEFAULT_MAX_PROMPT_CHARS` is 40000. `render_sections` enforces it by dropping
  a **whole** unpinned section from the end, with only a log line, so an
  overshoot deletes a different section from the one that grew. The cap has
  moved four times, each with the measurement in the constant's comment: 24000
  to 28000 for the OpenUI reference, to 30000 for the live card section, to
  34000 when voice received the OpenUI reference and the tool-use section gained
  its date and retry rules, and to 40000 when the skills and external data
  sections joined, at which point chat measured 32,956 characters and voice
  32,582. Each further skill adds roughly a thousand characters to every surface
  it is offered on. The budget tests in `test_agent_openui_tool.py`,
  `test_agent_skills.py` and `test_agent_mcp.py` render every surface whole and
  fail before production does.

### Argument normalisation

A tool that refuses a spelling the model obviously meant spends a whole turn
learning one word, and for an order tool that refusal lands **after** the
operator approved, so every one costs a second approval. Each toolkit therefore
reads the spellings models really send, translates them to OpenAlgo's own, and
says so in a `notices` entry when it changed something the model may repeat.
Two rules bound it: a translation is applied only where it is unambiguous, and a
genuinely invalid value is still refused with the accepted form spelled out
rather than passed on to fail at the broker.

The type hints were widened to match (`order_id: str | int`,
`price: float | None`, `workflow_json: str | dict`), because pydantic validates
the hint before the body's normaliser runs, and a hint narrower than the
normaliser refuses the call the normaliser exists to accept.

| argument | accepted and translated | where |
| --- | --- | --- |
| date | `YYYY-MM-DD`, an ISO datetime's date, `DD-MM-YYYY`, `YYYY/MM/DD`, `09-Oct-2026`, `today`, `yesterday` (IST) | `market.normalise_date` |
| history range | missing end is today (IST); missing start covers `DEFAULT_HISTORY_BARS` (100) candles at the interval | `market.history_range` |
| interval | `1d`/`day`/`daily` to `D`, weekly to `W`, monthly to `M`, `5min` to `5m`, `2hours` to `2h`; a case-only mismatch such as `5M` corrected to the broker's own. `W` or `M` on a broker that serves neither is fetched daily and rolled up (first open, highest high, lowest low, last close, summed volume) with a notice, so a weekly question is answered rather than refused | `market.normalise_interval`, `market.plan_interval`, `market.roll_up_candles` |
| exchange | `nse index`, `NSE-INDEX` read as `NSE_INDEX`, in every toolkit through one function | `market.clean_exchange` |
| `EXCH:SYM` symbol | market tools: the prefix wins over the exchange argument, with a notice. Order tools: used when the exchange is empty or agrees, **refused** when they disagree, because guessing could trade a different instrument from the one approved | `market.normalise_pair`, `orders.split_exchange_prefix` |
| index underlying | `NIFTY` on `NSE` moved to `NSE_INDEX` (BSE to `BSE_INDEX`), only when the symbol database says the index is listed there, so a stock stays put | `options.index_underlying`, `market.resolve_exchange` |
| expiry | `28OCT26`, `28-OCT-26`, `28OCT2026`, `8OCT26`, `28 OCT 26`, `2026-10-28` all to `DDMMMYY`; a day the calendar lacks is refused | `options.normalise_expiry` |
| expiry keyword | `nearest`, `weekly`, `this week`, `next`, `monthly`, `front month` and the like to `current_week`, `next_week`, `current_month`, `next_month` | `option_viz.EXPIRY_CHOICES` |
| option type | `C`, `CALL`, `CALLS` to `CE`; `P`, `PUT`, `PUTS` to `PE` | `options.normalise_option_type` |
| strike offset | `otm-2`, `OTM 2` to `OTM2`; `ATM0` to `ATM`; a signed `ATM+2` refused with the CE/PE rule, because its direction depends on the right | `options.normalise_offset` |
| whole numbers | `"5"` and `5.0` accepted where an int is wanted | `options.normalise_int` |
| leg side and size | side from `side`, `action` or `transaction_type`; `quantity` or `qty` converted to lots with the master's lot size | `option_viz.leg_side_and_lots` |
| order product | `INTRADAY` to `MIS`, `DELIVERY` to `CNC`, `CARRYFORWARD`/`NORMAL` to `NRML` | `orders.PRODUCT_ALIASES` |
| order price type | `SL M`, `SL-M`, `sl_m`, `SLM`, `STOPLOSS_MARKET` to `SL-M`; `STOPLOSS`, `STOP_LOSS_LIMIT` to `SL` | `orders.PRICE_TYPE_ALIASES` |
| order action | `B` to `BUY`, `S` to `SELL` | `orders.ACTION_ALIASES` |
| nulls | a null price or trigger price reads as zero; a null width, lot count or exchange as the argument's default | order and option tools |
| order id | a numeric id accepted and read as a string | `get_order_status`, `modify_order`, `cancel_order` |
| live symbols and mode | a bare `NSE:INFY` or a comma-separated run is a list; mode `1`, `2`, `3` to `LTP`, `Quote`, `Depth` | `live.symbols_argument`, `live.normalise_mode` |
| indicator params | `length` to `period`, `fast`/`slow`/`signal` to the indicator's own name, `std`/`stddev`/`deviation` to `std_dev`, applied only when exactly one candidate fits | `indicators/compute.resolve_param_aliases` |
| chart words | indicator ids `bb`/`bbands` to `bollinger`, `sar`/`psar` to `parabolic-sar`; zone `consolidation`/`sideways`/`box` to `range`; group plurals and `all` | `viz._INDICATOR_ALIASES`, `chart._ZONE_KIND_ALIASES`, `chart._GROUP_ALIASES` |
| web search count | out of range clamped with a notice rather than refused | `websearch._validated_max_results` |

The order aliases are listed exhaustively for a reason: each maps to exactly one
code, so translating one after approval cannot turn the order the operator read
into a different one. A word that could mean two products is not an alias.

Two order behaviours sit beside the table because they are refusals, not
translations. An order on a quote-only index code (`NSE_INDEX`, `BSE_INDEX`,
`MCX_INDEX`, `GLOBAL_INDEX`) is refused by `orders.index_refusal` naming where
the tradable contracts live (`NFO`, `BFO`, `MCX`, or nowhere for a global
index). And `close_position`, when the position service reads zero, sends
nothing and answers `status: nothing_to_close` with `ok: false`, releasing its
claim on the guard. Zero is not reported as success because it is not proof of
a flat book: several brokers read every position as flat, and a symbol,
exchange or product that differs from the position book also reads as zero. The
result tells the model to check `get_positions` before saying anything is
closed, because telling an operator a position is closed while it is still open
is the dangerous direction to be wrong in.

The cases are pinned in `test/test_agent_tool_arguments.py` (market, chart,
symbol and option tools), `test/test_agent_order_tool_arguments.py` (order,
account, live and Flow) and `test/test_agent_viz_tool_arguments.py`, each
pairing a newly accepted spelling with an invalid one that must still be
refused.

### Confirmation and risk

Every mutating tool is named in its toolkit's `requires_confirmation_tools`.
Agno pauses; the UI approves; **then** `safety/risk.py` runs inside the tool
body before the service is called. The guard is pure Python and reads no prompt,
so nothing the model or user says can talk past it.

**The approval card refuses a call missing a required argument.** Agno pauses
before the arguments are validated, so a call emptied by the bridge defect above
would otherwise be shown as an order with no symbol or quantity, approved, and
only then refused by the tool. `stream._requirement_payloads` therefore adds a
`missing` list to each pending requirement, built by
`tool_guard.missing_arguments` from the tool method's own signature (a value
sent as null or empty counts as missing). `PendingConfirm` in
`components/agent/Message.tsx` disables Approve while that list is non-empty and
names what did not arrive. It is deliberately not "the arguments are empty":
`cancel_all_orders` and `close_all_positions` take no arguments at all, and an
empty-arguments rule made them impossible to approve. It is one component, so
the chat page and the `/trading` panel behave the same; `AgentPanel.test.tsx`
pins both cases and `test_agent_tool_guard.py` pins the server side.

Order of checks: kill switch, trading enabled, analyzer mode if required,
symbol, exchange, product, quantity, session cap, duplicate window, notional and
price deviation, affordability against available funds.

**The guard never fetches a quote.** The reference price, the last traded price
and the available funds all arrive as arguments, because `services/risk/`'s rule
holds here too: a pure evaluator is what makes the verdict identical across
callers and callable from a green thread. The consequence is that the three
checks that need market data **fail open with a warning** when it is absent, not
only the affordability one: with no reference price the notional cap and the
deviation check are both skipped, and with a limit price but no LTP the
deviation check alone is. Refusing a human-approved order because the feed is
down is the worse failure, and such an order has already passed every gate that
does not need a number from outside.

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
system as data goes back into a prompt. Ported from ragz's `wrap_untrusted_block`
and hardened past it:

```python
def wrap_untrusted(tag: str, text: Any, **attributes: Any) -> str
```

Three properties, each answering a way the ragz shape was escapable:

- **Openers are neutralised as well as closers.** A closer that survives ends
  the block and everything after it reads as the conversation; an opener that
  survives is the same break-out one position earlier, and a forged
  `<tool_result source="platform">` inside a web page would let that page claim
  the authority of the platform's own service layer.
- **Every reserved tag is defanged, not only the wrapper's own.** A search
  snippet carrying an intact `<tool_result>` block never breaks the surrounding
  `<web_result>`, so it passed straight through and arrived in context as a
  well-formed block claiming to be the platform's data.
- **Case and whitespace are tolerated, and so are malformed spellings.** The
  reader is a language model, not an XML parser: it reads `</ Tool_Result >`,
  `< /tool_result>` and `<//tool_result>` as the end of the block, and a block
  that can be ended early is a block that can be escaped.

Any attribute interpolated into the opening tag, a symbol name, a filename, a
broker rejection string, is XML-attribute escaped first and stripped of control
characters, because an unescaped `"` in an attribute is the same break-out in a
different position. A tag or attribute name that is not a plain identifier
raises: that is a programming error, not user input, and failing loudly beats
emitting a block whose structure an attacker chose.

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
- **The order tools pass the broker's payload through
  `services.agent.safety.audit.redact` before it reaches the model**, so a key
  that arrives inside a broker response is dropped rather than serialised.
  `redact` strips both shapes, an argument name that looks like a credential and
  a value that looks like one. Only the success path in `tools/orders.py`
  carries a broker structure at all; the refusal and error paths return a
  message they wrote themselves. **No test pins this**, so per the meta-rule
  above, read it as a control the code has and nothing guards against a later
  edit dropping.
- **NOT IMPLEMENTED for the other toolkits.** `OpenAlgoToolkit.to_json` is
  `json_safe` plus a size cap, and it copies every mapping key through
  untouched, so a service payload is serialised verbatim. `redact_arguments` in
  `tools/base.py` is an exact-name list of twelve argument names applied only to
  audit rows, never to a result. Extending the order tools' filter to every
  toolkit is the fix; until it lands this bullet says so, per the meta-rule
  above.
- **A registered MCP server receives what the model asks it, from the
  operator's server.** None is registered today (see **External data (MCP)**).
  Once one is, with the external data switch on (the default), `call_mcp_tool`
  sends the model's arguments, typically a symbol, an index or a date, to that
  server over HTTPS, with a `User-Agent` naming OpenAlgo and its version, from
  the server's own IP. No OpenAlgo key or broker credential goes with it:
  `McpToolkit.inject_api_key` is False and `McpServerSpec` has no credential
  field by design. Nothing about the account is sent unless the model puts it in
  an argument. **NOT IMPLEMENTED: the taint boundary is not applied to MCP
  arguments**, which are passed through as the model wrote them, capped at
  `MAX_ARGUMENT_CHARS` (4000), so a model steered by injected text could place
  account data in one. The operator's control is the switch on
  `/agent/config`, which withholds the toolkit from every surface on the next
  message. Close this gap before registering a server run by a third party the
  operator has no reason to trust.

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
- **The cloud metadata endpoints are refused however they are spelled:**
  `169.254.169.254`, `fd00:ec2::254`, `metadata.google.internal` and
  `metadata`. The host is lower-cased, unbracketed and stripped of a trailing
  dot before the set is consulted, and an IPv4-mapped IPv6 literal is unwrapped
  to its IPv4 address, because `str()` renders `::ffff:169.254.169.254` as
  `::ffff:a9fe:a9fe`, which matches nothing in the set. That spelling reached
  the metadata endpoint until the unwrap was added. Seven spellings are pinned
  by `test_the_metadata_endpoint_is_refused_however_it_is_spelled`.
- **Fail closed on what will not parse.** A URL `urlsplit` refuses, a netloc
  whose hostname raises, and a URL naming no host at all are each blocked rather
  than passed through.
- **The host is not resolved. NOT IMPLEMENTED.** A hostname that resolves to a
  metadata address is not caught, and a hostname that resolves to nothing is
  allowed rather than blocked: `http://no-such-host.invalid/` is accepted.
  Resolving would put a DNS lookup in the save path and would refuse a container
  hostname that is simply not up yet. The guard's own docstring says this; keep
  the two in step.
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
- **A credential this module did not choose the storage for still gets
  contained.** LiteLLM writes the ChatGPT plan's access, refresh and id tokens
  as plain JSON to a directory it picks by expanding `~`, and where HOME is
  unset that produced a literal `~` folder of live credentials inside this
  repository, one `git add -A` from a commit.
  `chatgpt_oauth.configure_token_dir` sets the path rather than defaulting it,
  refuses a literal tilde, puts the file under `db/`, narrows the directory to
  `0700` and writes a nested `.gitignore` of `*`, and `ag_secret` under
  `oauth:chatgpt` is the system of record. Verified by running `git
  check-ignore` in a throwaway repository, not by reading the ignore file.

#### Decryption is confined to one module

`database/agent_db.py` is the only file in this module that imports
`safe_decrypt_token`, and it decrypts in exactly two places: the plaintext
comparison in `set_secret` that stops a pointless rewrite, and `get_secret`.
Plaintext leaves the module only through `get_secret`, `resolve_api_key` and
`get_api_key_for_model`. Five files call one of those: the model test route in
`blueprints/agent.py`, `builder.py` where the model is constructed,
`chatgpt_oauth.py`, `settings.py` and `tools/websearch.py`. Each takes the value
into a local, hands it to the provider, and keeps no copy.

**NOT IMPLEMENTED: no test pins that list.** An allowlist test was designed here
as a source grep for one underscore-prefixed function name, and it cannot be
written that way: the real funnels are public because they are called across
modules, and both names are substrings of unrelated functions in this
repository, `samco_get_secret_key` in `database/auth_db.py` and
`_resolve_api_key` in the WhatsApp, scalping and tick-feed services, so the grep
would report offenders that touch no agent secret. Qualifying the substring to
dodge them is exactly the weakening that makes a grep stop catching an alias. If
it is written, pin the **import** instead: `safe_decrypt_token` outside
`database/agent_db.py` is unambiguous to grep, and one decryption module is a
stronger property than one allowlisted caller list.

#### A traceback can leak a secret

CLAUDE.md requires `logger.exception()` for error logging, and that is right
everywhere in this codebase except one narrow case, which the agent module has:
`exc_info` captures local variables, so a traceback raised from a frame that
holds a **decrypted API key in a local** writes that key into `errors.jsonl`.

In every path whose frame holds a decrypted credential in a local, log with
`logger.error` and no traceback, and put a comment naming this reason next to
it. That is wider than the credential-set and credential-test routes: it also
covers the OpenAlgo API-key read, the web-search key and test routes, the
ChatGPT status, login and sign-out routes, and `builder.build_model`. Everywhere
else in the module, `logger.exception()` as normal. ragz applies exactly this
carve-out around its password paths.

The message carries what locates the fault and nothing else. Where the exception
text can itself quote a credential, it is reduced to the class name:
`chatgpt_oauth._post` answers "A ChatGPT sign-in request failed: OSError"
because the transport's own `OSError` quoted the request body, which contained
the refresh token.

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
| risk guard: kill switch, trading enabled, analyzer, symbol, exchange, product, quantity, session cap, duplicate window | **closed** | it is the only thing standing between a confused model and a real order |
| risk guard: notional cap, price deviation and affordability with no reference price, no LTP or no funds figure | **open**, warned | the guard never fetches a quote, and refusing a human-approved order because the feed is down is the worse failure; it has already passed every other gate |
| SSRF guard on a base URL that will not parse | **closed** | an address that cannot be read is not a safe address |
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

Emit a script matching `strategies/README.md`: read `OPENALGO_API_KEY` and
`HOST_SERVER`/`OPENALGO_HOST` from the environment, and `WEBSOCKET_URL` only
when the script streams, and never hardcode a credential. `strategy_gen` decides
"streams" from the parsed source (`uses_websocket`: a `subscribe_*` call, a
`ws_url=` keyword, a websocket client import or a `ws://` literal). Requiring the
socket address of every script made the model add a read a REST-only strategy
then never used. A derivative trading symbol such as `NIFTY24OCT2425000CE`
assigned to a credential-looking name like `symbol_token` is an instrument, not
a secret, and is not flagged. Write to `strategies/scripts/` using the existing
sanitize-and-contain rules from `blueprints/python_strategy.py`: `secure_filename`,
strip to `[A-Za-z0-9_-]`, timestamp suffix, and a `resolve()` containment check
against the directory even though we control the name.

Call into the existing launcher. Do not duplicate the subprocess machinery.

### Flow JSON

`docs/prompt/flow-import-format.md` is written to be fed to an LLM as a system
prompt; use it directly rather than paraphrasing the schema. Generate, then call
`services.flow_workflow_validator.validate_workflow` **directly**, at the same
strictness `/flow`'s own import endpoint uses (`require_name=True`,
`strict=True`), and feed the returned `errors[]` of `{path, code, message}`
straight back as tool feedback so the model self-corrects. Not over HTTP: an
HTTP call back into this process is what non-negotiable 2 forbids. The validator
is the ground truth; an invalid workflow cannot ship.

Two tools, and the split is the point: `validate_flow` writes nothing, so the
model can iterate as many times as it needs without a confirmation, and
`save_flow` is the one that mutates and is therefore the one in
`requires_confirmation_tools`. An imported workflow arrives inactive.

Never invent a node type. If a requirement has no matching node, say so in
prose.

### OpenScript

`tools/openscript_gen.py:OpenScriptToolkit` offers `list_openscripts` and
`save_openscript`, on the chat page and the `/trading` panel but not voice: a
study is written beside the chart it plots on, and `/trading` is where it
compiles.

**Saved as source, by necessity.** The OpenScript compiler is TypeScript and
runs in the browser. Production carries no JavaScript runtime and this server
has no compiler, so the agent can store a script's source and nothing more. That
is a state the platform already gives a meaning to: a `<name>.oscript` with no
`<name>.oscript.program.json` beside it opens in the `/trading` editor, which
compiles it, plots it and lists any errors, and nothing on the server will run
it until the trader saves it from that editor with a clean console, which is
what writes the compiled program a strategy needs. Every result says so in
`next_step` and carries `compiled: false`, because "saved" must not be read as
"compiled" or "deployed", and the tool's own description tells the model never
to say it compiled or is running.

**One write path.** `services/openscript_store.py:write_script` is the single
implementation of the replace sequence, the name rule (`SAFE_NAME`), the size
limit (`MAX_SOURCE_BYTES`, 256 kB) and the per-file lock (`FILE_LOCKS`), and
both `blueprints/openscript.py` and this toolkit call it. Two copies of a
sequence whose whole purpose is keeping a source and its compiled program in
step is how a runner ends up executing a program built from different text. A
save that replaces a script keeps the old source as `.bak` and **removes any
compiled program**, which no longer matches. `FILE_LOCKS` holds stdlib locks,
green under eventlet, so the toolkit reaches the store through `call_service`
on the hub rather than from the agent's real thread.

`save_openscript` is in `requires_confirmation_tools`, as `save_flow` and
`save_python_strategy` are: it writes a file the trader may later run.
`test/test_agent_openscript_tool.py` pins that the route and the tool write
through the same store objects, that a tool save removes the program a route
save stored, and the surfaces.

## Skills

A skill is a folder of written authoring guidance, a `SKILL.md` plus reference
pages, shared with Claude Code under `.claude/skills/`. Two are offered today:

| skill | folder | surfaces | hands off to |
| --- | --- | --- | --- |
| `openscript` | `.claude/skills/openscript` | chat, chart | `save_openscript` |
| `flow-builder` | `.claude/skills/flow-builder` | chat | `validate_flow`, `save_flow` |

**Progressive disclosure.** `skills/prompt.py:skills_section` puts only each
skill's name, its frontmatter description and its `agent_notes` into a SKILLS
prompt section. `tools/skills.py:SkillsToolkit` offers
`get_skill_instructions` and `get_skill_reference`, so a 34,000-character
reference costs nothing on a turn that does not need it. Long text is **paged,
never truncated**: each call returns a contiguous slice with `total_chars` and
`next_offset`, because a reference cut to fit would hand the model the first
third of a name table and let it believe it had read all of it.

**Read live.** `skills/loader.py` reads the folder on every call, caching parsed
files under a key that includes modification time and size in a
`LockedTTLCache` (real lock, because the prompt summary is built on the request
side and the tools run on the agent's thread). An edited `SKILL.md` applies on
the next message with no restart. A missing or malformed skill is skipped with
one warning per file version and costs that skill, never the run.

**The model names a skill and a path, so both are hostile input.** A skill is
found only through the registry, never by joining a model-chosen name onto a
path, and a skill not offered on the run's surface is not found. A reference
must sit in one of the spec's `reference_dirs` with an allowed suffix, is
resolved through any symlink and checked to remain inside the skill folder, and
is capped at `MAX_FILE_BYTES` (256 kB). **Nothing in a skill folder is ever
executed.**

**Why not agno's own `Skills` toolkit.** Two reasons, both measured against the
installed agno. Its loader reads references only from `references/`, while the
CI generators here write `reference/`, so the name tables an author most needs
would be invisible. And it offers `get_skill_script(..., execute=True)`, which
runs a skill's scripts on the server with arguments the model chooses. That is
code execution chosen by the model, a capability nothing else in this module
grants, and it would be one `scripts/` folder away from live however today's
folders happen to be laid out. Agno's own skills prompt
snippet would not appear anyway, because the builder passes a verbatim system
message.

**The skills were written for a reader that can run commands.** Each
`SkillSpec.agent_notes` maps those steps onto the agent's tools ("You cannot run
validate.mjs ... save it with save_openscript") and is shown both in the prompt
and with the instructions.

**Adding a skill is one `SkillSpec` in `skills/registry.py:SKILLS`**: a name,
the folder, the surfaces and the notes, plus `reference_dirs` and
`reference_suffixes` when the defaults (`reference/` and `references/`; `.md`,
`.txt`, `.json`) do not fit, as `openscript` widens them to serve its compiled
`examples/` as text. The one thing an entry cannot widen alone is the surfaces
the skills toolkit is built for in `tools/__init__.py` (chat and chart).
`test_the_real_registry_never_reaches_a_surface_the_toolkit_is_not_built_for`
fails if it tries, so a skill is never listed in a prompt whose tools cannot
read it, and `test_every_tool_a_skill_note_names_is_offered_where_the_skill_is`
holds the notes to the tools that exist on those surfaces. Each skill adds about
a thousand characters to every surface it is offered on; see the prompt budget
under **Tools**.

## Acceptance

The module is not done until an operator can do all of this, verified in a
browser against a running instance rather than asserted in a test:

**Setup**
- Open `/agent` with nothing configured and be shown the setup screen.
- Pick a provider from a card grid built from LiteLLM's own chat providers.
- Paste one key, tick several models from that provider, and add them in one action.
- Add a second provider with its own key. Both stay configured at once.
- Press Test and see a real pass or a real provider error message, not a generic failure.
- Set a default. An untested model is refused as default.
- Sign in to a ChatGPT Plus or Pro plan with no key pasted, and have the rest of
  the app keep answering while the code sits on OpenAI's page in another tab.
- Register a plan model beside the API model of the same name and tell the two
  apart in the registry without reading the model id.

**Chat**
- Send a message and watch the answer stream token by token.
- See per-turn token usage and cost under the answer, and a running conversation
  total. A plan turn shows tokens and "included in your ChatGPT plan", never
  `$0.00` and never the API price.
- Switch model mid-conversation from a picker and see the next turn use it.
- Stop a running turn and have it actually stop server-side, not just in the browser.
- Reload and find the conversation, its messages and its usage still there.

**Code generation**
- Ask for an `openalgo.ta` indicator snippet and get runnable Python.
- Ask for a full strategy and get a script matching the `strategies/README.md`
  contract: reads `OPENALGO_API_KEY` and `HOST_SERVER` from the environment,
  and `WEBSOCKET_URL` when it streams, and hardcodes no credential.
- Read it syntax-highlighted and whole, not as a grey `<pre>` and not behind an
  inner scroll region that hides the tail.
- Copy it, and ask for it to be saved to `strategies/scripts/`. **It never runs
  itself**; starting it stays a separate human action in `/python`.

**Flow generation**
- Ask for a workflow and get JSON validated against the real Flow validator,
  with any `errors[]` fed back so the model self-corrects rather than shipping
  something invalid.
- Read it highlighted as JSON, **copy it**, and import it. An imported workflow
  arrives inactive.

**Web search**
- Search with DuckDuckGo out of the box, no key, nothing configured.
- Configure Tavily and Perplexity keys in the same settings UI, never `.env`.
- Get links from DuckDuckGo and Tavily, and a cited synthesised answer from
  Perplexity, which is a separate tool because it is a different kind of result.

**Visualization**
- Ask a question whose answer is numeric and get a **rendered chart in the
  conversation**, not a markdown table: "plot NIFTY's last 30 daily closes",
  "compare these three stocks", "show my position sizes as a bar chart".
- The chart is OpenUI's own Recharts component with OpenUI's `ocean` palette,
  its colours assigned by the midpoint-outward rule rather than sequentially,
  and **no entrance animation**, which is what OpenUI's own LLM path does.
  Holds for every shape in the subset except `PieChart`, whose own default is
  `true`; see **OpenUI specifics**.
- It renders progressively as the spec streams, and a half-written block never
  flashes as broken output.
- Tables, metric cards and callouts render the same way.
- The data comes from a tool result, never from the model's memory. A chart of
  invented prices is worse than no chart.

**Chart**
- Open the agent panel on `/trading` beside Watchlist and Option Chain.
- Ask it to analyse the chart and have it read the current symbol and interval.
- Ask it to draw, and see markup appear on the existing chart, namespaced so
  `clear` never removes the operator's own drawings.
- With trading on in `/agent/config`, ask for an order beside the chart and see
  the same approval card as `/agent` in the panel; with it off, be told trading
  is switched off rather than shown a Buy or Sell control.
- Ask for an OpenScript study, see the full source, approve the save, and open
  it in the `/trading` OpenScript editor, where it compiles.

**External data**
- With no server registered (today), `/agent/config` shows no External data
  section and no MCP tool reaches the model.
- Once a server is registered: with the switch on, ask for a figure it publishes
  and get an answer from it rather than from web search; press Test connection
  and see it pass, or fail with a sentence naming whose side the fault is on.

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

Web search sends the operator's words to a third party, so it carries ragz's
full set of controls and they are not optional. (The MCP tools also leave the
process, to whichever MCP server is registered, and do not carry this envelope;
**Third-party data egress** says what that means.)

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

### Requests run on the hub

Tavily and Perplexity are called through `websearch._post`, which hands the
whole request to `base.call_on_hub`. The agent's tools run on a real OS thread,
and the shared `utils/httpx_client` client is green: its connection-pool locks
were built after eventlet patched the standard library, and its event hooks read
Flask's `g`. A request made on that client straight from the agent's thread is
direction A of the eventlet boundary in `CLAUDE.md`: correct on the development
server and under gthread, able to wedge the single worker under eventlet. The
client is **looked up** on the hub as well, because on first use that lookup
builds it, and it has to be built in the world that owns it.

The hub's wait is the request's own timeout plus `HUB_WAIT_MARGIN_SECONDS` (10),
so httpx's timeout fires first and a slow but healthy answer (Perplexity's
research call may take up to `RESEARCH_TIMEOUT_SECONDS`, 60) is not abandoned
while it is still arriving. Under gthread and the development server
`call_on_hub` simply calls inline. DuckDuckGo is not on this path: `ddgs`
brings its own transport and never touches the shared client.
`test/test_agent_websearch_transport.py` pins both the crossing and the longer
wait.

## External data (MCP)

The agent can read read-only data servers over the Model Context Protocol beside
the broker. **No server is registered today**, so the toolkit is not built, the
prompt says nothing about it and the config page shows no External data section.

NSE's two MCP servers (the end-of-day bhavcopy service at
`mcp.nseindia.in/bhavcopy/cm/mcp` and the live cash-market snapshot at
`mcp.nseindia.in/cmmkt/mcp`) were the first entries and were removed on
2026-10-09. In repeated live checks both stalled for 10 to 20 seconds and then
timed out, after a burst of a few quick answers; curl and httpx behaved the
same, so the fault was upstream. Every NSE question cost the trader a long wait
for no answer, which is worse than not offering the source. The framework stays
so a reliable server can be added as one registry entry.

When a server is registered, the prompt section is generated from its spec and
tells the model to use the broker first for quotes, intraday candles, depth,
chains and the account, and to prefer the server over web search for any figure
it publishes; both tool descriptions name the servers offered, built from the
same registry, because a model picks a tool by its description.

**Why a client of our own, not the `mcp` SDK or agno's `MCPTools`.** Both are
asyncio, and eventlet, the default worker, cannot host an event loop in request
code. The transport is plain JSON-RPC 2.0 over HTTP POST answered with JSON or a
short `text/event-stream`, and four methods cover everything (`initialize`,
`notifications/initialized`, `tools/list`, `tools/call`), so
`mcp/client.py:McpClient` speaks them synchronously. Only streamable HTTP is
implemented: the older HTTP+SSE transport is deprecated, and stdio would start a
subprocess per server in a worker that never restarts. Every request goes
through the shared httpx client **on the hub**, for the reason **Requests run on
the hub** gives, and only a plain reply of status, headers and text crosses
back.

**Failure handling is shaped by the gateway.** NSE's gateway answers the same
request in 0.3 s, with a 504 after 10 s, or not at all for 40 s, from one minute
to the next. So each request carries the spec's connect and read timeouts, one tool
call is bounded by `call_deadline_s` (25 s) across its retry and any session
re-initialisation, a timeout or 5xx is retried at most once and only when the
deadline has room, and a per-server **circuit breaker** pauses a server after
three consecutive failures, answers "unavailable" at once for 60 s, then lets one
trial call through. A tool error the server reports counts as an answer, not a
failure. The tool list is cached an hour and a failed fetch remembered 30 s, so
a model asking again straight away is answered at once. Every error is typed and
carries a sentence a trader can read; status codes stay in the log.

**Two tools, whatever the number of servers.** Registering each server's tools
with agno would put three dozen schemas in every request. `tools/mcp.py:McpToolkit`
offers `list_mcp_tools(server, tool="")`, a compact catalogue or one tool in
full, and `call_mcp_tool(server, tool, arguments, page=1)`, which checks the
server and tool against the registry and the live list and passes the
arguments through. They are **not** checked against the server's schema: NSE
marks every argument required while accepting an omitted one, so a local check
would refuse calls the server answers. Building the toolkit does no network
work, so an NSE outage costs only the turn that asked for NSE data. A long
answer is paged, a JSON one by rows of its largest list so every page is still
parsed JSON, and the full text is kept five minutes (`RESULT_CACHE_TTL_S`, at
most `RESULT_CACHE_CHARS` in all) so page two needs no second call; page one
always calls, so a live snapshot is never served from memory. Every result, and
a server's own error text, is wrapped `trust="third-party"` by
`wrap_tool_result`. The tools are read-only and need no approval.

**The operator switch.** `mcp_enabled` in `ag_setting` ships **on**, unlike the
trading switch, because the toolkit is read-only; an unreadable store also
reads as on, since this is not a safety switch that must fail closed. The
builder resolves it in the request with `settings.is_mcp_enabled(fresh=True)`
and ANDs it into the session state, so turning it off withholds the toolkit and
its prompt section from every surface on the next message. agno's run state does
not carry that key back to the tool factory, so `build_agent` also hands the
factory a context holding the effective flag, and the factory falls back to it.
The first version defaulted the missing key to off: every toolkit test passed,
because they called the factory with a state that did carry it, and the model
never received an MCP tool on a real run. `TestTheBuiltAgentOffersTheToolkit`
in `test_agent_mcp.py` drives the factory with an empty run state, as agno does.
`components/agent/config/McpPanel.tsx` is the External data section of
`/agent/config`: the switch, the registered servers from `GET /agent/api/mcp`,
and **Test connection**, `POST /agent/api/mcp/test`, which starts a fresh
session and lists the tools for each server (or the one named), ignoring the
breaker because the operator is asking whether it answers now. A failing server
is a 200 with `ok: false` and a sentence, as the model and web search tests are.

**Adding a server is one `McpServerSpec` in `mcp/registry.py:MCP_SERVERS`.**
The toolkit, the prompt section, the settings page and the connection test all
read that tuple. The key is what the model passes as `server`, so keep it short
and stable. The spec is checked at import: an https URL, a known transport,
positive timeouts, and no tool both allowed and denied. It carries no
credential; a server that needs a key gets one through `ag_secret` and the
settings page, the way web search does. `scripts/mcp_live_check.py` is the
opt-in live check (`uv run python scripts/mcp_live_check.py --server <key>`):
it initialises, lists and makes one read-only call per server through the same
client, and is never run by the test suite. `test/test_agent_mcp.py` covers the
client, breaker, caches, paging and wiring without the network.

## Visualization

Three renderers, chosen by domain. **None of them is new**: all three engines
already ship in this app, and the agent drives what exists rather than growing a
fourth charting stack.

| Domain | Renderer | Already used by |
| --- | --- | --- |
| Candlesticks, OHLC, price with indicators | `openalgo-charts` 1.9.2 | `/trading` |
| Option analytics: payoff, greeks, OI, GEX, max pain, vol surface | Plotly, via `lib/Plot2D.tsx` and `lib/Plot3D.tsx` | `/strategybuilder` and eight option pages |
| Everything else: bar, line, area, pie, tables, cards, callouts | OpenUI genui-lib | new here |

`VizBlock` dispatches six `kind` values, not three: `candles`, `plotly`,
`payoff`, and the three purpose-built cards `instrument`, `live_quotes` and
`live_combo`. The three engines are what is reused; a card that renders one
instrument's own fields is not a fourth charting stack.

### Provenance decides which frame carries it

This is the reason the split matters, and it is not a style preference.

- **`Viz` frame, wire type `viz`.** Built by a **tool**, from a `services/`
  call. The model asks for a chart; it never supplies the numbers. A price
  chart therefore cannot show a candle the platform did not return.
- **`Ui` frame, wire type `ui`.** OpenUI Lang markup the **model composes**, so
  its numbers are whatever the model typed. This is the one tier where the
  provenance rule lives in the prompt rather than in the plumbing, which is why
  it is reserved for general data and never for prices.

A chart of invented prices is worse than no chart, because it reads as
authoritative.

The `Viz` frame also keeps the series out of the model's context: the tool
answers with a one line confirmation while the payload travels on the frame, so
charting five hundred candles costs the conversation almost nothing. A viz tool
that returns its series to the model has missed the point.

`kind` selects the renderer and an unknown `kind` renders nothing, so a newer
backend cannot break an older client mid-turn.

### OpenUI specifics

- Three direct dependencies and no others: `@openuidev/react-lang`,
  `@openuidev/react-ui` and `@openuidev/react-headless`. React 19 is supported.
  `recharts` and `zod` are **not** pinned here and did not need to be:
  `recharts` is a dependency of `@openuidev/react-ui`, and `zod` a peer of that
  package and of `@openuidev/react-lang`, so both arrive with the install.
- **`zustand` is the one thing that did not reconcile.** It has been a direct
  dependency of this frontend since the React app was initialised, currently
  `^5.0.10`, and every store in `src/stores/` is built on it, while
  `@openuidev/react-ui` and `@openuidev/react-headless` both name it a peer at
  `^4.5.5`. `npm ls zustand` reports the installed 5.x as `invalid` against
  those two ranges, and nothing here re-pins or overrides it. Check that before
  reading a `zustand@4.5.7` in the tree as OpenUI's: that one is a separate
  nested copy under `@xyflow/react`, for the Flow editor.
- `<Renderer response={growingString} library={lib} isStreaming={bool} />` is
  the only renderer. Feed it the **whole accumulated string** each token; its
  parser diffs internally and is O(new characters).
- **Generate the prompt from the library**, so it cannot drift from what the
  renderer accepts. The call fails *silently* when wrong: every component name
  comes out as the literal `undefined`, producing a plausible and useless
  prompt. Only these two are correct:

  ```js
  library.prompt(promptOptions)                                    // simplest
  generateSystemPrompt({ library: library.toSpec(), promptOptions })
  ```

  `openuiChatLibrary` is **already a built Library**, so `createLibrary` on it
  throws `input.components is not iterable`. The per-component `signature` the
  prompt is built from exists only on `toSpec()`. Assert the `undefined` count
  is zero in a test.
- **The prompt is generated, committed, and read by the backend.**
  `frontend/scripts/generate-openui-prompt.mjs` writes
  `docs/prompt/openui-lang.md` from the same library object the browser renders
  with, and `prompts.py` reads that file. It is committed rather than built on
  demand because a production server has no Node.js and a plain `git pull` has
  to be enough. `openuiLibrary.test.ts` regenerates and compares, so an
  `@openuidev` upgrade that changes the prompt fails CI rather than silently
  describing a library the renderer no longer has.
- **Prompt cost, measured.** The full 58-component chat library costs 19,096
  characters with the rules and examples OpenUI ships. The 22-component subset
  the agent is given costs 8,184, and the committed file is 8,343 with its
  provenance banner, against the 8,800 the generator enforces. `build_agent`
  caps the whole system prompt at `DEFAULT_MAX_PROMPT_CHARS = 40000`; the
  measured worst cases and the history of the number are under **Tools**.
  Overshooting does not truncate the section that overshot: `render_sections`
  drops a **different** whole unpinned section from the end with only a log
  line, which is why every surface's fit is asserted rather than left for the
  next addition to find in production. Inject it on **chat and voice**, the two
  surfaces whose `render_ui` tool is registered, and never on the chart panel,
  which drives the real `/trading` chart and has no `render_ui`: a surface is
  never taught a tool it does not have.
- **Do not reimplement palettes, and pass animation off where it is on.**
  `isAnimationActive` is a prop, not a hardcoded value, and it defaults to
  `false` on the area, bar, horizontal bar, line, radar, radial and scatter
  components, so those match OpenUI as shipped with nothing passed.
  **`PieChart` defaults it to `true`**, and `PieChart` is in the subset, so a
  pie the agent draws animates on entry against the acceptance criterion below.
  `@openuidev/react-lang` never passes the prop, so the component default is
  what applies. `useChartPalette` already calls
  `getDistributedColors(palette, dataLength)`, which starts at the palette
  midpoint and walks outward with wraparound, so a two-series chart on `ocean`
  uses the middle indices rather than 0 and 1. Sequential assignment is wrong,
  and so is doing this by hand. Named palettes: `ocean`, `orchid`, `emerald`,
  `spectrum`, `sunset`, `vivid`.
- `ThemeProvider` is nesting-aware; mount it around the chat panel only, so
  `--openui-*` variables do not leak into the rest of OpenAlgo.

The agent emits UI through a tool rather than in its prose, so ordinary answers
stay markdown and a visualization is a deliberate act.

## Rendering generated code

The reference here is deliberately **not** ragz. Its code rendering is a plain
`<pre>` with no highlighting of any kind, so a Python fence and a JSON fence look
identical. It also re-parses the entire accumulated message on every streamed
token with no memoization, which is quadratic and invisible only because a RAG
answer is short. A generated strategy is not short.

Two things from it are worth keeping, and they are both security controls:

- `skipHtml`, no `rehype-raw`, and no `rehype-sanitize` either. HTML is never
  parsed into elements, so there is no allowlist to get subtly wrong.
- **`img: () => null`.** Markdown images are blocked entirely, not just raw
  `<img>` tags, because an image URL is an exfiltration channel: a model steered
  by injected content embeds a secret in a URL the browser then fetches to an
  attacker's host. This module feeds tool output back into context, so it is
  exposed to exactly that. Both are pinned by a test.

### A highlighter, not an editor

The plan here was the platform's own `PythonEditor` and `JsonEditor`, so a
generated artifact would look exactly like the code the operator goes on to
edit. What shipped is `components/agent/CodeArtifact.tsx`, Prism through
`react-syntax-highlighter`. Four decisions carry it, and each one is a cost the
editor route would have paid on every message in a thread that only grows.

- **Not CodeMirror.** An editor per block is an editor instance per message,
  each with its own state, extensions and DOM, in a thread that only grows. A
  highlighter renders once to static markup. The chat needs reading, not
  editing, and the cheaper thing is also the better-behaved one. It also cost
  nothing to adopt: `react-syntax-highlighter@^16.1.0` has been a direct
  dependency since the charts phase, declared and unimported, and
  `CodeArtifact.tsx` is its first consumer in `src/`. It imports the
  `PrismLight` build and registers languages one at a time, rather than the
  bundle that carries every grammar Prism ships.
- **No line-number gutter.** Numbers earn their place in an editor, where they
  are how a person cites a line to a colleague or a traceback. In a chat answer
  nobody cites a line, the block is usually copied whole, and the gutter competes
  with the code for the eye. `/python` keeps its numbers, because it is a real
  editor.
- **No height cap, and a test forbids one.** A fixed row cap hid the tail of a
  longer script behind an inner scroll region nobody found: the header said "37
  lines" while the body stopped at 25, so the code read as truncated rather than
  scrollable. `Message.security.test.tsx` walks every rendered element and
  asserts none of them constrains its own height.
- **The header is a language label and a copy button, and nothing else.** No
  filename, no "Save to strategies", no "Open in editor": saving is what the
  `strategy_gen` tool does, with a confirmation and a containment check behind
  it, and putting a second save path in the chrome of a message would be a
  mutating action with neither.

Only the languages the agent actually emits are registered. An unregistered
language falls through to plain monospace rather than being highlighted as
something it is not, which reads worse than no highlighting at all.

Ordinary prose stays markdown. Only a generated artifact gets the highlighter.

### Streaming without the quadratic cost

Do not commit React state per token.

- Accumulate deltas into a ref and flush on a fixed cadence, roughly one
  animation frame. The stream is still smooth and the parse count drops by
  orders of magnitude.
- Split the message into a **stable prefix** and a **streaming tail** at the
  last completed block boundary. Re-parse only the tail; the prefix is rendered
  once and memoized.
- A code artifact is **not** re-highlighted per token. While its fence is open
  it renders as plain monospace text, and the highlighter runs once the block
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
"Candlestick patterns", "Read my drawings"), the message thread, and a composer.

It shares the chat surface's stream client and frame vocabulary; only the
rendering differs, because a narrow panel shows one collapsed status line per
turn rather than a full tool timeline.

The panel calls its `getChartContext` prop **fresh at send time**, never
capturing at mount, so the agent always sees the chart as it currently is.
`Trading.tsx` supplies `panelTarget()?.chartContext()`, so the read resolves the
**focused pane** on every turn exactly as the watchlist and the option chain
already do, rather than a terminal captured when the panel opened. Commands returning
from the model are applied through a single promise queue rooted at the
terminal's own init, so commands from different turns cannot interleave and one
stalled fetch cannot wedge every later turn.

`ChartCommand` is a closed union applied by the existing terminal:

```
draw | clear | indicator
```

`draw` replaces one named agent group's shapes, `clear` removes one group or
every agent group, and `indicator` carries `action: add | remove` with a chart
indicator id. `set_symbol`, `set_interval`, `set_chart_type` and `focus` were
never built: the panel reads the operator's symbol and interval as context on
every turn, and nothing in the vocabulary moves the chart under them. Replacing
rather than appending is what makes a second call to the same tool redraw rather
than stack, so an operator asking twice gets one set of levels.

The two halves land on two different surfaces, so
`terminal.applyChartCommands` filters the indicator ops off to the chart's own
registry first and passes the rest to `chartContract.applyChartCommands`, whose
switch **ignores an unknown op** rather than throwing, so a newer backend cannot
break an older client mid-turn. Drawing ids are namespaced `ai:{group}:{index}`
so agent markup never collides with the user's own drawings and `clear` never
removes theirs.

Geometry is computed from real bars server-side, in
`services/agent/chart_geometry.py`. The model narrates; it does not invent a
price.

The panel has a `ModelPicker` and shares its choice with `/agent` through
`lib/agent/useModelChoice.ts`, remembered in this browser under
`oa-agent-model`. With nothing chosen, or a remembered model that is no longer
enabled, it sends no model and `resolve_model(None)` falls through to the
`is_default` row, so changing the default changes which billing path an
unpinned panel runs on, an API key or a ChatGPT plan.

### Orders on the panel

The panel was first built with no order tools at all, because it had no
approval card and an order tool without one is a tool that cannot be used
safely. It renders the same `Message` component as `/agent` now, approval card
included, so the order toolkit is registered for `ALL_SURFACES` and reaches the
panel exactly as it reaches the chat page: only through the trading capability.

- **The panel asks for trading only when the operator's switch is on.**
  `AgentPanel` reads `trading_enabled` from the agent settings, under the same
  query key the chat page reads, and passes it to `useAgentStream`.
  `build_session_state` ANDs that request with the same setting again, so a
  stale page cannot ask its way past a switch that is off, and a session with
  trading off has no order tool in its schema on this surface either.
- **Every order pauses for the human.** `onConfirm` is wired to the stream's
  `confirm`, the card appears in the panel's thread, and nothing reaches a
  broker until it is approved, after which the risk guard still runs inside the
  tool. A call missing a required argument cannot be approved (see
  **Confirmation and risk**).
- **What a trader sees follows the switch.** With trading off, the empty state
  says it places no orders because trading is off in the agent settings, and an
  answer's Buy and Sell controls are withheld (`canOrder={tradingEnabled}`),
  because a control that writes a request this panel can only refuse reads as a
  route to a trade. The chart section of the prompt tells the model to state the
  exact order first, never to say it was placed until the tool returns, and,
  with trading off, to say it is switched off rather than imply anything was
  placed.

`test/test_agent_chart_surface.py` pins that the order toolkit is offered on
the chart with trading on, withheld with it off, and that every mutating order
tool is in `requires_confirmation_tools` there. `AgentPanel.test.tsx` pins the
request, the card and the refusal of an empty call. The panel also gets the
skills, OpenScript and external data toolkits; it does not get `render_ui`, so
the prompt tells it to answer general data in a short table or prose.

## HTTP surface

All under `/agent/api`, all `@check_session_validity`, all behind a shared rate
limit, CSRF on by default.

| method | path | purpose |
| --- | --- | --- |
| GET | `/status` | the setup gate |
| GET | `/catalog/providers` | every chat-capable provider LiteLLM knows |
| GET | `/catalog/models` | one provider's models. `?provider=` required, `?chat_only=` defaults true |
| GET/POST | `/models` | list, create |
| PATCH/DELETE | `/models/<id>` | update, remove |
| POST | `/models/<id>/test` | validate credentials |
| POST | `/models/<id>/default` | make default, refused if untested |
| GET/PUT | `/settings` | agent settings |
| GET/PUT | `/websearch` | web-search settings |
| PUT/DELETE | `/websearch/providers/<provider>/key` | store, remove a search key |
| POST | `/websearch/providers/<provider>/test` | validate a search key |
| GET | `/mcp` | the external data switch and the registered servers; contacts none |
| POST | `/mcp/test` | test every server, or the one named in `{"server": key}`; on the tighter limit |
| GET | `/chatgpt/status` | is a plan authorised, plus any login in flight |
| POST | `/chatgpt/login` | start the device flow; body `{"force": bool}` |
| POST | `/chatgpt/cancel` | stop a login in flight |
| DELETE | `/chatgpt/session` | sign the subscription out |
| GET/POST | `/conversations` | list, create |
| GET/DELETE | `/conversations/<id>` | fetch, delete |
| DELETE | `/conversations/<id>/messages/<message_id>` | drop one message |
| POST | `/chat/stream` | SSE |
| POST | `/chat/confirm` | SSE, resume a paused run |
| POST | `/chat/<run_id>/cancel` | cancel |

Thirty routes in all, counting each method separately, plus the eight voice
routes documented in `docs/design/56-voice-agent/`. The shared limit is 240 per
minute, with 30 on the streaming routes and 12 on the ones that reach upstream.
The external data switch has no route of its own: it is the `mcp_enabled` field
of `/settings`, like the trading switch.

`login.state` is `idle`, `pending`, `authorised`, `expired`, `failed` or
`cancelled`, and `pending` is the only non-terminal one, so a client stops
polling on anything else. `user_code` is blank in every non-pending state, so a
dead code can never sit on screen looking live. `/chatgpt/login` is on the
tighter 12-per-minute budget because it reaches upstream; it answers 501 when
LiteLLM has no chatgpt provider and 502 when the device code could not be
issued, and reports `reused: true` when it handed back a login already in
flight. `/chatgpt/cancel` answers from `login_status()`, a frozen copy under a
real lock, and deliberately not from `status()`, which Fernet-decrypts to build
its fingerprint: that cost is right for a settings card and wrong for anything
polled. `/chatgpt/session` cancels a login in flight first, so signing out
mid-sign-in leaves nothing behind polling for a code nobody will enter, and it
leaves the registered `chatgpt/` rows alone, because those are operator intent
and only the credential was revoked.

The panel polls `/chatgpt/status` every 2s, but only while `login.state` is
`pending`, and **in the background**. That last part is not a detail: the panel
tells the operator to open OpenAI's page in another tab, so this one is hidden
for the entire wait, and a poll that pauses on a hidden tab is a poll that never
runs during the only period it is needed. Found in a browser, with the code
sitting there approved while the panel counted down.

Register the blueprint in `app.py` beside `flow_bp`. Register the React routes
in `blueprints/react_app.py` as well, or an unauthenticated hit on `/agent`
counts toward an IP ban through `Error404Tracker`.

## Startup

**There is no lifecycle call and nothing starts at import.** `app.py` does
exactly two things for this module: it registers `agent_bp`, and it adds
`("Agent DB", ensure_agent_tables_exists)` to `db_init_functions`. That is the
whole wiring.

The alternative, a `runtime.start_agent_module` mirroring
`services/strategy_module/runtime.py`, was designed and is not built, because
nothing here needs starting: the catalog is read on first use, the model is
constructed per run, and `chatgpt_oauth.ensure_ready()` is called lazily by
`builder.resolve_model`. A platform that will not boot because the agent failed
to start is worse than one that boots without it, and having nothing to start is
the strongest form of that.

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

Three files carry the ChatGPT subscription, split by what each can prove without
a network:

- `test/test_agent_chatgpt_oauth.py` owns the module: custody, the whole device
  flow driven through a `Transport` protocol so no test needs a real login, and
  the threading. Its eventlet cases run in a **subprocess**, because
  `monkey_patch()` is global and cannot be undone, and assert on elapsed time
  and hub ticks rather than on return values, which were always right. The first
  of them asserts the defect itself, so nothing below it can pass vacuously.
  Same shape as `test/test_eventlet_cross_thread_locks.py`.
- `test/test_agent_chatgpt_wiring.py` owns the seams: the keyless carve-out in
  `providers`, the resolution gate, the capability probe answered from the price
  table, the billing frames, and the four routes.
- `test/test_agent_chatgpt_models.py` owns the supplement, including
  `test_an_openai_entry_for_the_same_name_does_not_block_registration`. A guard
  written as `name in model_cost` skipped every model it exists to add, because
  the bare name is already in that map as OpenAI's entry.

**A capability probe is a live device login, so a suite that touches one has to
neutralise it.** The `no_device_flow` fixture asserts on **recorded calls, never
on a raised tripwire**: `_supports_factory` wraps the whole resolution in
`try/except` and `_litellm_opinion` catches too, so a tripwire raised down that
chain is swallowed twice over and proves nothing. Before the fixture existed the
run died on a sixty-second test timeout inside `_poll_for_authorization_code`.
