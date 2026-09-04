// api/agent.ts
// Agent module API: the setup gate, the model registry, settings and
// conversations under /agent/api.
//
// Every route here is session authenticated and CSRF protected, so all of them
// go through webClient. There is no API-key surface for this module.
//
// The streaming turn is deliberately absent. `POST /agent/api/chat/stream` and
// `/chat/confirm` answer Server-Sent Events, which axios cannot read
// incrementally, so they live in lib/agent/stream.ts as a fetch plus a
// ReadableStream reader. The types both files need (ChatMessage, ToolCall,
// Usage, ConfirmRequirement) are declared and exported here.
//
// Two backend rules shape these types:
//
//   * Every route answers an envelope, `{status: 'success', ...}` on the way
//     out and `{status: 'error', message}` on the way back. The payload sits
//     under `data` on most routes; `status` and the test result are flat.
//   * A secret is never returned, not masked and not partial. A model row
//     carries a presence boolean and a fingerprint, which is why AgentModel has
//     no key field and why the write payloads carry `api_key` and the read type
//     does not.

import { webClient } from './client'

// =============================================================================
// Vocabularies
// =============================================================================

/** The five provider kinds `ag_provider_model.provider_kind` accepts. */
export type ProviderKind = 'openai' | 'anthropic' | 'ollama' | 'openai_compatible' | 'litellm'

/** Reasoning effort, per model and optionally per run. */
export type ReasoningEffort = 'off' | 'low' | 'medium' | 'high'

/** Which surface a conversation belongs to: the chat page or the chart panel. */
export type AgentSurface = 'chat' | 'chart'

/** Where a submitted key is stored: shared by the provider, or for one model. */
export type ApiKeyScope = 'provider' | 'model'

/** A message role as `ag_message.role` records it. */
export type MessageRole = 'user' | 'assistant' | 'system' | 'tool'

/** Severity of a notice frame shown beside the conversation. */
export type NoticeLevel = 'info' | 'warning' | 'error'

/** Which layer failed, so the client can suggest the right fix. */
export type ErrorKind = 'config' | 'input' | 'provider' | 'tool' | 'internal'

/** What a paused tool call is waiting for. */
export type RequirementKind = 'confirmation' | 'user_input' | 'external_execution'

/** Why a run ended. A paused run ends on a confirm frame and sends no done. */
export type DoneReason = 'stop' | 'cancelled' | 'incomplete'

// =============================================================================
// Status
// =============================================================================

export interface AgentStatus {
  /** True only for an enabled default model whose credential test passed. */
  configured: boolean
  model_count: number
  default_model_id: number | null
  /** The operator's database setting, not a per-session request. */
  trading_enabled: boolean
  /** False when the optional agno package is not installed on the server. */
  agent_available: boolean
  /** False when no OpenAlgo API key exists, so no tool can reach the platform. */
  has_openalgo_api_key: boolean
}

// =============================================================================
// Catalog
//
// Read from LiteLLM's own in-package data at request time. There is no catalog
// table and no generated frontend constant, so bumping litellm is the whole
// maintenance story.
// =============================================================================

export interface CatalogProvider {
  /** The LiteLLM provider id, which is what the models route is keyed by. */
  id: string
  display_name: string
  /** An icon slug the frontend resolves to its own asset, or an empty string. */
  icon: string
  /** The suggested provider_kind for models of this provider. Advisory. */
  provider_kind: ProviderKind
  needs_key: boolean
  needs_base_url: boolean
  /** How many of this provider's models are conversational. */
  model_count: number
  /** How many models LiteLLM lists in every mode, including embeddings. */
  total_model_count: number
}

export interface CatalogModel {
  /** The model name as LiteLLM lists it, which is what model_name stores. */
  id: string
  provider: string
  /** `id` with the provider prefix applied, for a `litellm` provider_kind. */
  qualified_id: string
  /** The model_cost key the enrichment came from, or null when unpriced. */
  catalog_key: string | null
  mode: string | null
  max_input_tokens: number | null
  max_output_tokens: number | null
  /** USD per million tokens. null means the catalog has no price, not zero. */
  input_price_per_million: number | null
  output_price_per_million: number | null
  /**
   * Load-bearing rather than decoration: this agent is entirely tool driven,
   * so false means the model cannot drive it and null means nobody knows.
   */
  supports_function_calling: boolean | null
  supports_vision: boolean | null
  supports_reasoning: boolean | null
  /** True when LiteLLM carries cost and capability metadata for this model. */
  in_catalog: boolean
  is_chat: boolean
}

export interface ProviderCatalogResponse {
  /** False when litellm is not importable on the server; `data` is then empty. */
  available: boolean
  data: CatalogProvider[]
}

export interface ModelCatalogResponse {
  available: boolean
  /** null when the requested provider is not one LiteLLM knows about. */
  provider: CatalogProvider | null
  data: CatalogModel[]
}

// =============================================================================
// Model registry
// =============================================================================

/**
 * One configured model, exactly as `GET /agent/api/models` returns it.
 *
 * There is no key on this type because there is none in the response. The row
 * describes its credential with `has_api_key` and `api_key_fingerprint` and
 * nothing else, so a component cannot render a secret it was never given.
 * `api_key` is declared as `never` so an attempt to put a value on a model row
 * fails to compile rather than reaching a render.
 */
export interface AgentModel {
  id: number
  provider_kind: ProviderKind
  /** Passed to LiteLLM. Carries its own provider prefix for `litellm`. */
  model_name: string
  display_name: string
  base_url: string | null
  enabled: boolean
  /** Exactly one row is default, and an untested model cannot be it. */
  is_default: boolean
  supports_reasoning: boolean
  default_reasoning_effort: ReasoningEffort
  supports_vision: boolean
  tools_unreliable: boolean
  /** Naive UTC ISO string, or null when the model has never been tested. */
  last_tested_at: string | null
  /** null before the first test; false after one that failed. */
  last_test_ok: boolean | null
  /** The provider's own message, verbatim, with the key removed. */
  last_test_error: string | null
  has_api_key: boolean
  /** Display safe, never the value: `...abcd sha256:0123456789ab`. */
  api_key_fingerprint: string | null
  /** Which secret answers for this model: `provider:openai` or `model:7`. */
  api_key_source: string | null
  created_at: string
  updated_at: string
  /** Never present. Declared so nothing can assign a key onto a model row. */
  api_key?: never
}

export interface CreateModelPayload {
  provider_kind: ProviderKind
  model_name: string
  /** Defaults to model_name on the server when blank. */
  display_name?: string
  /** Required for `ollama` and `openai_compatible`, refused otherwise. */
  base_url?: string | null
  default_reasoning_effort?: ReasoningEffort
  enabled?: boolean
  supports_reasoning?: boolean
  supports_vision?: boolean
  tools_unreliable?: boolean
  /** Write only. One paste serves every model of a provider at scope. */
  api_key?: string
  /** `provider` by default, which is what makes one key serve many models. */
  api_key_scope?: ApiKeyScope
}

export interface UpdateModelPayload {
  display_name?: string
  base_url?: string | null
  default_reasoning_effort?: ReasoningEffort
  enabled?: boolean
  supports_reasoning?: boolean
  supports_vision?: boolean
  tools_unreliable?: boolean
  /**
   * Write only, and blank means keep the existing key rather than clear it.
   * The input starts empty even when a key is configured, so a save that read
   * blank as "clear it" would unconfigure the provider on every unrelated edit.
   */
  api_key?: string
  api_key_scope?: ApiKeyScope
}

export interface ModelTestResult {
  ok: boolean
  /** On failure this is the provider's own message, which the operator needs. */
  message: string
  latency_ms: number
  /** The refreshed row. Absent when the request never reached the provider. */
  data?: AgentModel
}

// =============================================================================
// Settings
// =============================================================================

/**
 * Every agent setting, as `GET /agent/api/settings` renders it.
 *
 * Money and percentage values travel as decimal strings, not floats, so a limit
 * an operator typed is stored and shown exactly as typed. Parse them only where
 * arithmetic is actually needed.
 */
export interface AgentSettings {
  /** The master switch. Off on a fresh install. */
  trading_enabled: boolean
  require_analyzer_mode: boolean
  /** null when unset. The defaults payload carries an empty string instead. */
  system_prompt: string | null
  default_reasoning_effort: ReasoningEffort
  max_orders_per_session: number
  max_order_quantity: number
  /** Decimal string, for example '500000.00'. */
  max_order_value: string
  /** Decimal string, 0 to 100. */
  max_price_deviation_pct: string
  duplicate_order_window_seconds: number
  allowed_exchanges: string[]
  allowed_products: string[]
  /** Empty means every symbol. The blocklist is the targeted tool. */
  symbol_allowlist: string[]
  symbol_blocklist: string[]
  /** Decimal string, 0 to 100. */
  max_funds_utilization_pct: string
  allow_bulk_destructive: boolean
  kill_switch: boolean
  kill_switch_file: string
}

/**
 * A partial settings write.
 *
 * The server parses and validates every field before it writes any of them, so
 * a request carrying one bad value changes nothing at all, and an unknown key
 * is rejected rather than ignored. A decimal field accepts a number as well as
 * a string; send an empty string to clear `system_prompt`.
 */
export type AgentSettingsUpdate = Partial<
  Omit<AgentSettings, 'max_order_value' | 'max_price_deviation_pct' | 'max_funds_utilization_pct'>
> & {
  max_order_value?: string | number
  max_price_deviation_pct?: string | number
  max_funds_utilization_pct?: string | number
}

export interface AgentSettingsResponse {
  data: AgentSettings
  /** What each field reverts to, shipped alongside so the screen needs no copy. */
  defaults: AgentSettings
}

// =============================================================================
// Web search
//
// Separate from AgentSettings on purpose, and separate on the wire too. A key
// must not travel in the same payload as a display setting, so the config PUT
// takes no key at all and each provider's key has its own route: a presence
// boolean and a fingerprint on the way out, a write-only value on the way in.
//
// No web search key ever goes in `.env`, including Perplexity's. They live in
// `ag_secret` under `websearch:{provider}`, encrypted with the same Fernet as
// every other agent credential.
// =============================================================================

/** The three providers `ag_setting.websearch_provider` accepts. */
export type WebSearchProviderId = 'duckduckgo' | 'tavily' | 'perplexity'

/**
 * What a provider gives back, and why that decides which tool it answers.
 *
 * A list of links and a synthesised answer are different kinds of result, so
 * they are different tools: presenting one upstream summary as though it were
 * search results would let it enter the model's context wearing the authority
 * of primary sources.
 */
export type WebSearchResultKind = 'links' | 'answer'

/** The two web search tools the agent exposes. */
export type WebSearchTool = 'web_search' | 'web_research'

/**
 * One selectable provider, with its key described and never shown.
 *
 * There is no key on this type because there is none in the response, exactly
 * as with AgentModel. `api_key` is declared as `never` so an attempt to put a
 * value on a provider row fails to compile rather than reaching a render.
 */
export interface WebSearchProvider {
  id: WebSearchProviderId
  label: string
  /** False only for DuckDuckGo, which is why search works with nothing set up. */
  needs_key: boolean
  result_kind: WebSearchResultKind
  /** Which tool this provider answers. Perplexity answers web_research. */
  tool: WebSearchTool
  /** One sentence an operator can choose on. */
  description: string
  has_api_key: boolean
  /** Display safe, never the value: `...abcd sha256:0123456789ab`. */
  api_key_fingerprint: string | null
  /** Naive UTC ISO string, or null when the key has never been handed over. */
  api_key_last_used_at: string | null
  /** True when the provider can run: it needs no key, or one is stored. */
  ready: boolean
  /** Never present. Declared so nothing can assign a key onto a provider row. */
  api_key?: never
}

/**
 * Today's outbound search count against the daily cap.
 *
 * The per-turn budget alone is bypassed by sending another message, which is
 * why the daily one is persisted. It is counted on the IST date and resets
 * itself with no scheduled job.
 */
export interface WebSearchUsage {
  /** The IST date the count belongs to, `YYYY-MM-DD`. */
  date: string
  count: number
  /** `daily_cap - count`, never negative. */
  remaining: number
}

export interface WebSearchConfig {
  /** Which provider answers web_search. Perplexity leaves it on DuckDuckGo. */
  provider: WebSearchProviderId
  /** The model web_research runs. */
  perplexity_model: string
  /** How many searches one turn may make. */
  max_calls_per_turn: number
  /** How many searches one day may make, counted in the database. */
  daily_cap: number
  usage: WebSearchUsage
  providers: WebSearchProvider[]
}

/** What each configurable field reverts to. */
export interface WebSearchDefaults {
  provider: WebSearchProviderId
  perplexity_model: string
  max_calls_per_turn: number
  daily_cap: number
}

/**
 * A partial web search configuration write.
 *
 * The server validates every field before it writes any of them, an unknown key
 * is rejected rather than ignored, and an out-of-range cap is refused rather
 * than clamped. Send an empty `perplexity_model` to restore the shipped default.
 */
export type WebSearchConfigUpdate = Partial<WebSearchDefaults>

export interface WebSearchConfigResponse {
  data: WebSearchConfig
  defaults: WebSearchDefaults
}

export interface WebSearchTestResult {
  ok: boolean
  provider: WebSearchProviderId
  /** On failure this is the provider's own reason, which the operator needs. */
  message: string
  latency_ms: number
  /** Links for a search provider, citations for Perplexity. */
  result_count: number
  /** The refreshed config: a passing test updates the key's last use. */
  data: WebSearchConfig
}

// =============================================================================
// The ChatGPT subscription
//
// LiteLLM exposes a ChatGPT Plus or Pro plan as its own provider, `chatgpt`,
// separate from `openai`. The same ten models, a different billing path: an
// `openai/` model bills API credits against a key you paste, a `chatgpt/` model
// bills the plan and is authorised through an OAuth device flow instead.
//
// There is therefore no key to type and none to show. What the operator is
// given is what an API key row gives them, a fingerprint, and what they do is a
// device-code sign-in: press Connect, read a short code, enter it at OpenAI's
// own page, and this screen notices when it is approved.
//
// The credential is a refresh token. It is encrypted in `ag_secret`, it is
// never returned by any route, and none of the types below has a field for it.
// =============================================================================

/**
 * The states one sign-in moves through. `pending` is the only non-terminal one.
 *
 * Mirrors the `LOGIN_*` constants in `services/agent/chatgpt_oauth.py`. Poll
 * while the state is `pending` and stop on anything else.
 */
export type ChatGptLoginState =
  | 'idle'
  | 'pending'
  | 'authorised'
  | 'expired'
  | 'failed'
  | 'cancelled'

/**
 * A snapshot of the one sign-in the server will run at a time.
 *
 * `user_code` is shown to the authenticated operator and is deliberately never
 * logged: a device code is a standing phishing target, so it belongs on the
 * screen of the person who asked for it and nowhere else.
 */
export interface ChatGptLogin {
  state: ChatGptLoginState
  /** The code to type at `verification_url`. Empty outside a pending sign-in. */
  user_code: string
  /** OpenAI's own device page. Opened in a new tab, never framed. */
  verification_url: string
  /** Unix seconds the device code was issued. */
  started_at: number | null
  /** Unix seconds the device code stops being accepted, about 15 minutes on. */
  expires_at: number | null
  /** Why a terminal state is what it is. Empty while pending. */
  message: string
}

/**
 * Whether a plan is connected, and what is in flight.
 *
 * There is no token on this type because there is none in the response.
 * `api_key` is declared as `never` for the same reason it is on AgentModel: an
 * attempt to put a credential on this object fails to compile.
 */
export interface ChatGptStatus {
  authorised: boolean
  /**
   * Display safe, never the value: `...abcd sha256:0123456789ab`, exactly the
   * form an API key row shows. Taken over the refresh token, so it survives an
   * access-token refresh and stays the identifier seen at sign-in.
   */
  fingerprint: string
  /** The OpenAI account the plan belongs to, when the record names one. */
  account_id: string | null
  /** Unix seconds the access token expires. Null when the record has none. */
  expiry: number | null
  /** True once the credential is in `ag_secret` rather than only on disk. */
  stored_in_database: boolean
  /** Where LiteLLM's own auth file lives. Shown so a stale one is findable. */
  token_dir: string
  login: ChatGptLogin
  /** Never present. Declared so nothing can assign a token onto this object. */
  api_key?: never
}

/** What cancelling reports: the snapshot, and whether a poll was really stopped. */
export interface ChatGptCancelResult {
  data: ChatGptLogin
  /** False when nothing was running, which is a success rather than an error. */
  stopped: boolean
}

// =============================================================================
// Conversations, messages and the shared stream vocabulary
// =============================================================================

export interface Conversation {
  id: number
  user_id: string
  title: string | null
  surface: AgentSurface
  /** Agno's own session id, needed to resume a paused run. */
  agno_session_id: string | null
  created_at: string
  updated_at: string
}

/**
 * One tool call, as both the live stream and a stored message describe it.
 *
 * `tool_start` supplies id, name and args; the matching `tool_end` adds ok,
 * result and duration, and a stored message carries the merged entry. The
 * outcome fields are therefore optional: their absence means the call is still
 * open, not that it succeeded.
 */
export interface ToolCall {
  id: string
  name: string
  args?: Record<string, unknown>
  /** False when the call raised or returned an error. */
  ok?: boolean
  /** JSON safe and length capped by the server. */
  result?: unknown
  /** Wall clock seconds, or null when the call was not measured. */
  duration?: number | null
}

/**
 * Which of two places a turn was billed to.
 *
 * `metered` is a per-token price against a provider key. `subscription` is a
 * ChatGPT Plus or Pro plan, which has no per-token price at all: the turn is
 * covered by a monthly fee that was paid whether or not it happened.
 *
 * The distinction is not cosmetic. Eight of the ten `chatgpt/` models share a
 * bare name with an `openai/` model, so two rows in the registry can both read
 * GPT-5.4 and bill to different places. This field is what tells them apart
 * after the fact, on the turn itself.
 */
export type UsageBilling = 'subscription' | 'metered'

/**
 * What a turn consumed, in tokens and money.
 *
 * Every usage frame carries the running total for the turn, not a delta, so a
 * client renders the latest and discards the one before it.
 *
 * `cost_usd` is null when the model is absent from LiteLLM's price table.
 * **Render that as unknown, never as zero.** Showing tokens and admitting the
 * price is not known beats inventing a number.
 *
 * A subscription turn is the one case where null does not mean unknown: there
 * is no per-token price to know, so `billing` is what separates "nobody
 * published a price" from "this turn came out of a plan you already pay for".
 * Both still refuse to render $0.00, which would say the turn was free.
 */
export interface Usage {
  /** Prompt tokens billed, including cached ones. */
  input_tokens: number
  output_tokens: number
  total_tokens: number
  cached_tokens: number
  reasoning_tokens: number
  /** Computed locally from LiteLLM's price table. null means unknown. */
  cost_usd: number | null
  /** The model id the provider billed, as the provider reported it. */
  model: string | null
  /** Milliseconds from the start of the run to its first token. */
  ttft_ms: number | null
  /**
   * Which billing path the turn took. Optional because a message stored before
   * this field existed has none, and an older row must still render.
   */
  billing?: UsageBilling
}

/** One pending decision on a paused run. */
export interface ConfirmRequirement {
  /** Agno's requirement id. Empty when only the flat tool list was available. */
  id: string
  tool_call_id: string
  tool_name: string
  /** Model supplied and already redacted by the server. */
  args: Record<string, unknown>
  kind: RequirementKind
}

/** Approve or reject one pending call, in the list form `/chat/confirm` takes. */
export interface ConfirmDecision {
  /** The requirement id, or the tool call id when there is no requirement id. */
  id: string
  approved: boolean
  /** The tool name, recorded on the audit row. */
  tool?: string
}

/**
 * Everything a stored turn carries beside its prose, in the order it happened.
 *
 * The server folds the turn's non-token frames into `ag_message.notices`, each
 * keeping its own `type` discriminator, so a reloaded conversation re-renders
 * from the same union the live stream produced. `ui` is the one that differs:
 * the stream sends deltas and the stored entry carries the accumulated string.
 *
 * A `viz` entry is the live frame's dict verbatim, capped at `MAX_STORED_VIZ`
 * per turn by `_TurnRecorder`, so one renderer branch serves a chart that is
 * streaming and the same chart after a reload. An entry with a `type` this
 * client does not know is ignored rather than rendered as text, which is what
 * lets the backend record something new without breaking an older client.
 */
/**
 * One file a stored turn carried, as `stored_metadata` wrote it.
 *
 * No bytes: an attachment is described on the row and never kept there. `kind`
 * is `image` or `text` as the server sniffed it, and is read defensively
 * because the row is free-form JSON written by whatever vocabulary was live.
 */
export interface StoredAttachment {
  name: string
  kind: string
  mime: string
  size: number
  /** Short content hash, so the same file twice is recognisable as the same. */
  digest: string
}

export type MessageNotice =
  | { type: 'notice'; level: NoticeLevel; message: string }
  | { type: 'attachments'; items: StoredAttachment[] }
  | { type: 'error'; message: string; kind: ErrorKind }
  | { type: 'confirm'; run_id: string; session_id: string; requirements: ConfirmRequirement[] }
  | { type: 'ui'; content: string }
  | { type: 'viz'; kind: string; spec: Record<string, unknown>; title: string; source: string }
  | ({ type: 'usage' } & Usage)

export interface ChatMessage {
  id: number
  conversation_id: number
  role: MessageRole
  content: string
  tools: ToolCall[]
  notices: MessageNotice[]
  created_at: string
}

export interface ConversationDetail {
  conversation: Conversation
  messages: ChatMessage[]
}

/** A route that reports what it did rather than returning a row. */
export interface AgentAck {
  status: string
  message: string
}

export interface CancelRunResult {
  status: string
  message: string
  run_id: string
}

// =============================================================================
// API Functions
// =============================================================================

const AGENT_API_BASE = '/agent/api'

/**
 * The setup gate: whether /agent has a usable model yet.
 *
 * Cheap enough to poll on mount. The flags travel flat on the envelope rather
 * than under `data`.
 */
export async function getStatus(): Promise<AgentStatus> {
  const response = await webClient.get<AgentStatus>(`${AGENT_API_BASE}/status`)
  return response.data
}

/**
 * Every chat-capable provider LiteLLM knows about, for the setup grid.
 */
export async function listProviders(): Promise<ProviderCatalogResponse> {
  const response = await webClient.get<ProviderCatalogResponse>(
    `${AGENT_API_BASE}/catalog/providers`
  )
  return {
    available: Boolean(response.data?.available),
    data: response.data?.data ?? [],
  }
}

/**
 * One provider's models, enriched with context window, price and tool support.
 *
 * @param provider - The LiteLLM provider id, from listProviders.
 * @param chatOnly - Hide embedding, image and audio models. True by default.
 */
export async function listCatalogModels(
  provider: string,
  chatOnly = true
): Promise<ModelCatalogResponse> {
  const response = await webClient.get<ModelCatalogResponse>(`${AGENT_API_BASE}/catalog/models`, {
    params: { provider, chat_only: chatOnly ? 'true' : 'false' },
  })
  return {
    available: Boolean(response.data?.available),
    provider: response.data?.provider ?? null,
    data: response.data?.data ?? [],
  }
}

/**
 * Every configured model, with its key described and never shown.
 */
export async function listModels(): Promise<AgentModel[]> {
  const response = await webClient.get<{ data: AgentModel[] }>(`${AGENT_API_BASE}/models`)
  return response.data.data ?? []
}

/**
 * Register a model, optionally storing the key it will use.
 *
 * A new model is never the default: the server promotes it on its first passing
 * test, or the operator sets it explicitly. Adding several models of one
 * provider means one create per model, sequentially, reusing the same key.
 *
 * A 500 carrying a `data` payload is the one partial outcome: the row was
 * created and its per-model key could not be stored. The row stands and the key
 * can be set with a PATCH.
 */
export async function createModel(payload: CreateModelPayload): Promise<AgentModel> {
  const response = await webClient.post<{ data: AgentModel }>(`${AGENT_API_BASE}/models`, payload)
  return response.data.data
}

/**
 * Update a registered model, and replace its key only when one is supplied.
 */
export async function updateModel(id: number, payload: UpdateModelPayload): Promise<AgentModel> {
  const response = await webClient.patch<{ data: AgentModel }>(
    `${AGENT_API_BASE}/models/${id}`,
    payload
  )
  return response.data.data
}

/**
 * Remove a model, its per-model key override and its default status.
 *
 * The server hands the default to another tested, enabled model when the
 * deleted one held it.
 */
export async function deleteModel(id: number): Promise<AgentAck> {
  const response = await webClient.delete<AgentAck>(`${AGENT_API_BASE}/models/${id}`)
  return response.data
}

/**
 * Validate a model's credentials with the cheapest possible real call.
 *
 * A failed test is a 200 carrying `ok: false` and the provider's own message,
 * not an HTTP error: "invalid API key" and "model not found" need different
 * fixes and the operator asked a question that deserves the real answer.
 */
export async function testModel(id: number): Promise<ModelTestResult> {
  const response = await webClient.post<ModelTestResult>(`${AGENT_API_BASE}/models/${id}/test`)
  return response.data
}

/**
 * Make one model the default. Refused with 409 for an untested model.
 */
export async function setDefaultModel(id: number): Promise<AgentModel> {
  const response = await webClient.post<{ data: AgentModel }>(
    `${AGENT_API_BASE}/models/${id}/default`
  )
  return response.data.data
}

/**
 * Every agent setting, with the shipped defaults alongside.
 */
export async function getSettings(): Promise<AgentSettingsResponse> {
  const response = await webClient.get<AgentSettingsResponse>(`${AGENT_API_BASE}/settings`)
  return { data: response.data.data, defaults: response.data.defaults }
}

/**
 * Persist a partial settings update and return the full settings after it.
 */
export async function updateSettings(values: AgentSettingsUpdate): Promise<AgentSettings> {
  const response = await webClient.put<{ data: AgentSettings }>(
    `${AGENT_API_BASE}/settings`,
    values
  )
  return response.data.data
}

/**
 * The web search configuration, with every key described and none shown.
 *
 * Carries the selected provider, the tunables, today's usage against the daily
 * cap, and one entry per selectable provider. The shipped defaults travel
 * alongside, as they do on getSettings.
 */
export async function getWebSearchConfig(): Promise<WebSearchConfigResponse> {
  const response = await webClient.get<WebSearchConfigResponse>(`${AGENT_API_BASE}/websearch`)
  return { data: response.data.data, defaults: response.data.defaults }
}

/**
 * Select the provider, and set the tunables around it.
 *
 * This never carries a key: keys have their own functions below. An unknown
 * provider is refused with 400 rather than written, because a stored value the
 * tool module does not recognise would leave it quietly falling back to
 * DuckDuckGo while the screen claimed otherwise.
 */
export async function updateWebSearchConfig(
  values: WebSearchConfigUpdate
): Promise<WebSearchConfig> {
  const response = await webClient.put<{ data: WebSearchConfig }>(
    `${AGENT_API_BASE}/websearch`,
    values
  )
  return response.data.data
}

/**
 * Store one provider's key.
 *
 * Refused with 400 for DuckDuckGo, which takes no key, and for a blank value:
 * this route takes only a key, and clearing one is clearWebSearchKey, which
 * says so. The server compares the decrypted plaintext before it writes, so
 * re-saving an unchanged key touches no row.
 *
 * @param provider - `tavily` or `perplexity`.
 * @param apiKey - The plaintext key. Write only, and never returned.
 */
export async function setWebSearchKey(
  provider: WebSearchProviderId,
  apiKey: string
): Promise<WebSearchConfig> {
  const response = await webClient.put<{ data: WebSearchConfig }>(
    `${AGENT_API_BASE}/websearch/providers/${encodeURIComponent(provider)}/key`,
    { api_key: apiKey }
  )
  return response.data.data
}

/**
 * Remove one provider's key.
 *
 * Idempotent: clearing a key that is not there succeeds. A paid provider left
 * selected with no key degrades to DuckDuckGo and says so in the tool result.
 */
export async function clearWebSearchKey(provider: WebSearchProviderId): Promise<WebSearchConfig> {
  const response = await webClient.delete<{ data: WebSearchConfig }>(
    `${AGENT_API_BASE}/websearch/providers/${encodeURIComponent(provider)}/key`
  )
  return response.data.data
}

/**
 * Validate one provider with a single real query.
 *
 * The same shape as testModel, and the same rule: a failed test is a 200
 * carrying `ok: false` and the provider's own message, not an HTTP error. The
 * query runs through the very functions the tools dispatch to, so Perplexity is
 * exercised on the research path rather than the link path.
 *
 * @param provider - The provider to test. DuckDuckGo needs no key.
 * @param apiKey - A key to test in place of the stored one, so a key the
 *   operator has just typed can be checked before it is saved. Never stored by
 *   this call.
 */
export async function testWebSearchProvider(
  provider: WebSearchProviderId,
  apiKey?: string
): Promise<WebSearchTestResult> {
  const response = await webClient.post<WebSearchTestResult>(
    `${AGENT_API_BASE}/websearch/providers/${encodeURIComponent(provider)}/test`,
    apiKey ? { api_key: apiKey } : {}
  )
  return response.data
}

// -----------------------------------------------------------------------------
// The ChatGPT subscription
// -----------------------------------------------------------------------------

const CHATGPT_BASE = `${AGENT_API_BASE}/chatgpt`

/**
 * Read a payload that may travel flat or under `data`.
 *
 * The agent routes are not uniform about this: `status` and the model test are
 * flat, everything else sits under `data`. These four routes are being written
 * alongside this file, so rather than hardcode a guess that turns into a blank
 * panel if it is wrong, unwrap whichever arrived.
 *
 * @param body - The parsed response body.
 * @param probe - A field the payload itself is known to carry.
 * @returns The payload.
 */
function chatGptPayload<T>(body: unknown, probe: keyof T & string): T {
  const envelope = body as { data?: unknown } | null | undefined
  const nested = envelope?.data
  if (nested && typeof nested === 'object' && probe in (nested as object)) return nested as T
  return body as T
}

/**
 * Whether a ChatGPT plan is connected, and what a sign-in is doing.
 *
 * Cheap enough to poll, and the panel does exactly that while a sign-in is
 * pending. It carries a fingerprint and never a token.
 */
export async function getChatGptStatus(): Promise<ChatGptStatus> {
  const response = await webClient.get(`${CHATGPT_BASE}/status`)
  const status = chatGptPayload<ChatGptStatus>(response.data, 'authorised')
  // The service layer names this `access_token_expires_at`; the route reports
  // `expiry`. Read whichever is present so the expiry line is not silently
  // blank if the two names ever drift apart again.
  const raw = status as ChatGptStatus & { access_token_expires_at?: number | null }
  return { ...status, expiry: raw.expiry ?? raw.access_token_expires_at ?? null }
}

/**
 * Start a device-flow sign-in, and answer as soon as the code is issued.
 *
 * The poll that waits for the operator to approve it runs on a real OS thread
 * server side, so this returns in milliseconds with a code to display rather
 * than holding the request open for up to fifteen minutes.
 *
 * @param force - Start again even though a plan is already connected, which is
 *   how an operator moves this instance to a different ChatGPT account.
 */
export async function startChatGptLogin(force = false): Promise<ChatGptLogin> {
  const response = await webClient.post(`${CHATGPT_BASE}/login`, { force })
  return chatGptPayload<ChatGptLogin>(response.data, 'state')
}

/**
 * Stop a sign-in that is still waiting for its code to be approved.
 *
 * `stopped` is false when nothing was running, which is a success: the operator
 * asked for it to be stopped and it is stopped.
 */
export async function cancelChatGptLogin(): Promise<ChatGptCancelResult> {
  const response = await webClient.post<ChatGptCancelResult>(`${CHATGPT_BASE}/cancel`, {})
  return response.data
}

/**
 * Disconnect the plan: forget the stored credential and the cached token file.
 *
 * Idempotent, and `removed` is false when there was nothing to remove. Any
 * `chatgpt/` model stays registered and stops working until a plan is connected
 * again, which is the honest outcome: the row is operator intent and this call
 * only revokes the credential behind it.
 */
export async function removeChatGptSession(): Promise<boolean> {
  const response = await webClient.delete<{ removed?: boolean }>(`${CHATGPT_BASE}/session`)
  return response.data?.removed === true
}

export interface ListConversationsParams {
  surface?: AgentSurface
  /** Clamped server side to between 1 and 200. Defaults to 100. */
  limit?: number
}

/**
 * The signed-in user's conversations, most recently updated first.
 */
export async function listConversations(
  params: ListConversationsParams = {}
): Promise<Conversation[]> {
  const response = await webClient.get<{ data: Conversation[] }>(
    `${AGENT_API_BASE}/conversations`,
    { params }
  )
  return response.data.data ?? []
}

/**
 * Open a conversation on one surface.
 *
 * Optional: the stream creates one when the request names none, so the first
 * message of a new conversation is a single round trip.
 */
export async function createConversation(
  payload: { surface?: AgentSurface; title?: string } = {}
): Promise<Conversation> {
  const response = await webClient.post<{ data: Conversation }>(
    `${AGENT_API_BASE}/conversations`,
    payload
  )
  return response.data.data
}

/**
 * One conversation and its messages, oldest first.
 *
 * A conversation belonging to somebody else answers 404, not 403, so a rejected
 * id says nothing about whether the row exists.
 */
export async function getConversation(id: number): Promise<ConversationDetail> {
  const response = await webClient.get<{ data: Conversation; messages: ChatMessage[] }>(
    `${AGENT_API_BASE}/conversations/${id}`
  )
  return {
    conversation: response.data.data,
    messages: response.data.messages ?? [],
  }
}

export interface TruncateResult {
  /** How many messages were removed, the edited one included. */
  removed: number
  /** How many agno runs were forgotten alongside them. */
  runs_forgotten: number
}

/**
 * Remove a message and everything after it, from both stores.
 *
 * This is the first half of editing a question: the answer that followed it,
 * and everything after that, has to go before the new question is asked, or the
 * thread reads as an edited question sitting above its old answer.
 *
 * The server truncates agno's session store as well as the transcript, so the
 * model stops seeing the superseded exchange. A purely local splice would look
 * identical here and silently leave the model answering the old question.
 */
export async function truncateConversation(
  conversationId: number,
  messageId: number
): Promise<TruncateResult> {
  const response = await webClient.delete<TruncateResult>(
    `${AGENT_API_BASE}/conversations/${conversationId}/messages/${messageId}`
  )
  return response.data
}

/**
 * Delete a conversation and its messages. Its audit rows stay: they are a trade
 * record and they outlive the conversation the trade was typed into.
 */
export async function deleteConversation(id: number): Promise<AgentAck> {
  const response = await webClient.delete<AgentAck>(`${AGENT_API_BASE}/conversations/${id}`)
  return response.data
}

/**
 * Stop a running turn server side.
 *
 * Best effort, and success either way: a run that has already finished, or that
 * never existed, satisfies the caller's intent that it not continue, and a 404
 * would let the run id space be probed for what is live.
 */
export async function cancelRun(runId: string): Promise<CancelRunResult> {
  const response = await webClient.post<CancelRunResult>(
    `${AGENT_API_BASE}/chat/${encodeURIComponent(runId)}/cancel`
  )
  return response.data
}

/**
 * The message a failed agent call should show.
 *
 * Every route answers `{status: 'error', message}`, including the 409 setup
 * gate and the 429 rate limit, so the server's own sentence is almost always
 * the useful one. Falls back to the transport error and then to the caller's
 * own text.
 */
export function agentErrorMessage(error: unknown, fallback: string): string {
  const wrapped = error as
    | { response?: { data?: { message?: unknown } }; message?: unknown }
    | null
    | undefined
  const fromServer = wrapped?.response?.data?.message
  if (typeof fromServer === 'string' && fromServer.trim()) return fromServer
  const fromTransport = wrapped?.message
  if (typeof fromTransport === 'string' && fromTransport.trim()) return fromTransport
  return fallback
}

// =============================================================================
// React Query Keys
// =============================================================================

export const agentQueryKeys = {
  all: ['agent'] as const,
  status: () => [...agentQueryKeys.all, 'status'] as const,
  catalog: () => [...agentQueryKeys.all, 'catalog'] as const,
  providers: () => [...agentQueryKeys.catalog(), 'providers'] as const,
  // Keyed on the exact request the response answers, so opening a second
  // provider's panel fetches instead of showing the first provider's models.
  catalogModels: (provider: string, chatOnly = true) =>
    [...agentQueryKeys.catalog(), 'models', provider, chatOnly] as const,
  models: () => [...agentQueryKeys.all, 'models'] as const,
  model: (id: number) => [...agentQueryKeys.models(), id] as const,
  settings: () => [...agentQueryKeys.all, 'settings'] as const,
  // One key for the whole web search config. Every mutation here (provider,
  // tunables, a stored key, a passing test that updates a key's last use)
  // answers with the same refreshed object, so one cache entry stays correct
  // and a second key would only be a second thing to invalidate.
  websearch: () => [...agentQueryKeys.all, 'websearch'] as const,
  // One key for the subscription. The panel polls it while a sign-in is
  // pending, and the registry and the model picker read the same cache entry to
  // describe the credential a `chatgpt/` row runs on, which has no key of its
  // own to fingerprint.
  chatgpt: () => [...agentQueryKeys.all, 'chatgpt'] as const,
  conversations: (params: ListConversationsParams = {}) =>
    [...agentQueryKeys.all, 'conversations', params] as const,
  conversation: (id: number) => [...agentQueryKeys.all, 'conversations', id] as const,
}
