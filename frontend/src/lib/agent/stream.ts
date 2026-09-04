/**
 * The /agent SSE client.
 *
 * Not `EventSource`. The two streaming routes are POSTs carrying a JSON body -
 * the message, the conversation, the model, the chart context - and
 * `EventSource` can only issue a bodyless GET. So the transport is `fetch` plus
 * a `ReadableStream` reader, which is also what lets the request carry the CSRF
 * header every session route requires.
 *
 * The wire format is defined by `services/agent/frames.py` and this file is its
 * only client-side definition. Three things about it shape the parser:
 *
 * - **There is no `event:` line.** Every frame is one `data:` line whose
 *   remainder is a JSON object discriminated on a `type` field, so a consumer
 *   runs one switch over `AgentFrame`.
 * - **A line starting with `:` is a heartbeat comment**, written when the queue
 *   has been idle so a reverse proxy does not close a stream while the model
 *   thinks. It is dropped silently and costs no frame type.
 * - **A frame is always exactly one line.** The server serialises with
 *   `json.dumps`, which escapes newlines, so a `\n` in the byte stream is
 *   always a real line boundary and never part of a payload.
 *
 * Nothing here throws for a stream that fails. A pre-stream HTTP failure - the
 * 409 setup gate, a 429, a 400 - is turned into an `error` frame and handed to
 * the same `onFrame` callback as a mid-stream one, so the caller has a single
 * channel to render and never two error paths that must agree.
 *
 * The vocabularies and the payload types a stored message shares with the live
 * stream (`Usage`, `ConfirmRequirement`, `NoticeLevel`, ...) are declared in
 * `api/agent.ts` and imported here. A reloaded conversation and a running one
 * therefore render from one set of types rather than two that drift.
 */

import type { ConfirmRequirement, DoneReason, ErrorKind, NoticeLevel, Usage } from '@/api/agent'
import { fetchCSRFToken } from '@/api/client'

const API_BASE_URL = import.meta.env.VITE_API_URL || ''

/** Every route in `blueprints/agent.py` lives under this prefix. */
export const AGENT_API_BASE = '/agent/api'

/** Re-exported so a component rendering frames needs one import, not two. */
export type { ConfirmRequirement, DoneReason, ErrorKind, NoticeLevel, Usage }

/** What a paused run is waiting for. The confirm frame's own payload type. */
export type AgentRequirement = ConfirmRequirement

// ---------------------------------------------------------------------------
// Frame vocabulary
//
// One interface per dataclass in services/agent/frames.py, discriminated on
// `type`. Every field the server writes is present, because `Frame.to_dict`
// emits all of them: there are no optional keys on the wire.
// ---------------------------------------------------------------------------

/**
 * One instruction for the `/trading` terminal.
 *
 * Deliberately open: the terminal ignores an `op` it does not recognise rather
 * than throwing, so a newer backend cannot break an older client mid-turn.
 */
export interface AgentChartCommand {
  op: string
  [key: string]: unknown
}

/** First frame of every run, sent before any model output. */
export interface StartFrame {
  type: 'start'
  run_id: string
  session_id: string
  conversation_id: number | string
  /**
   * The stored row for the question that opened this run, empty on a surface
   * that persists nothing. Editing addresses rows by database id, and the
   * client's own message ids are local counters, so this is the only way a
   * live message can later be edited.
   */
  user_message_id?: number | string
}

/** One chunk of assistant prose. The client appends; it never replaces. */
export interface TokenFrame {
  type: 'token'
  delta: string
}

/** A tool call has been dispatched. */
export interface ToolStartFrame {
  type: 'tool_start'
  id: string
  name: string
  args: Record<string, unknown>
}

/**
 * A tool call has returned. Exactly one of these follows each tool_start.
 *
 * Agno reports a failed call twice, as a completed event carrying an error and
 * then a separate error event; the server suppresses the second, so a single
 * failure never arrives as two frames.
 */
export interface ToolEndFrame {
  type: 'tool_end'
  id: string
  name: string
  ok: boolean
  result: unknown
  /** Wall clock seconds, or null when the call was not measured. */
  duration: number | null
}

/** One chunk of the model's reasoning trace, appended like a token. */
export interface ReasoningFrame {
  type: 'reasoning'
  delta: string
}

/**
 * One chunk of OpenUI Lang markup from the `render_ui` tool.
 *
 * Feed the renderer the whole accumulated string on every frame, not this
 * delta; its parser diffs internally and is O(new characters).
 */
export interface UiFrame {
  type: 'ui'
  delta: string
}

/**
 * A complete chart a tool built, ready to draw.
 *
 * The counterpart to `UiFrame`, and the difference is the point. A `ui` frame
 * streams markup the model composed, so its numbers are whatever it typed. A
 * `viz` frame carries a payload a tool built from a `services/` call, so the
 * model never types a price and a chart cannot show a candle the platform did
 * not return. It also keeps the series out of the model's context: the tool
 * answers with one line while the payload travels here.
 *
 * `kind` selects the renderer and **an unknown kind renders nothing**, so a
 * newer backend cannot break an older client mid-turn. `spec` is free-form
 * JSON; `lib/agent/viz.ts` validates it per kind before anything draws.
 */
export interface VizFrame {
  type: 'viz'
  /** `candles`, `plotly`, or something this client has not been taught. */
  kind: string
  /** The renderer's payload. Self-contained: nothing further is fetched. */
  spec: Record<string, unknown>
  /** Heading shown above the chart. May be empty. */
  title: string
  /** The service the data came from, so provenance is never a guess. */
  source: string
}

/** Commands for the `/trading` terminal to apply. */
export interface ChartCommandFrame {
  type: 'chart_command'
  commands: AgentChartCommand[]
}

/**
 * The run paused and needs approval for a mutating tool call.
 *
 * This frame **terminates the stream** and no done frame follows it. That is
 * not a failure: the client resumes by posting the decisions to
 * `/chat/confirm`.
 */
export interface ConfirmFrame {
  type: 'confirm'
  run_id: string
  session_id: string
  requirements: ConfirmRequirement[]
}

/** An out-of-band message about the run rather than from the model. */
export interface NoticeFrame {
  type: 'notice'
  level: NoticeLevel
  message: string
}

/**
 * What the turn has consumed so far, in tokens and money.
 *
 * Every usage frame carries the **running total for the turn**, not a delta, so
 * render the latest and discard the one before it. `cost_usd` is null when the
 * model is absent from LiteLLM's price table, and null must render as unknown,
 * never as zero.
 *
 * The payload is `Usage` itself, which is also what a stored message carries in
 * its notices, so one renderer serves the live turn and the reloaded one.
 */
export type UsageFrame = { type: 'usage' } & Usage

/** The run failed. The upstream message is carried verbatim. */
export interface ErrorFrame {
  type: 'error'
  message: string
  kind: ErrorKind
}

/** Last frame of a run that reached an end. */
export interface DoneFrame {
  type: 'done'
  reason: DoneReason
}

/** Every frame the agent stream can deliver. */
export type AgentFrame =
  | StartFrame
  | TokenFrame
  | ToolStartFrame
  | ToolEndFrame
  | ReasoningFrame
  | UiFrame
  | VizFrame
  | ChartCommandFrame
  | ConfirmFrame
  | NoticeFrame
  | UsageFrame
  | ErrorFrame
  | DoneFrame

// ---------------------------------------------------------------------------
// The client
// ---------------------------------------------------------------------------

/** The two streaming routes. A closed set, so a typo is a compile error. */
export type AgentStreamPath = '/chat/stream' | '/chat/confirm'

export interface AgentStreamRequest {
  /** Which streaming route to post to, relative to `/agent/api`. */
  path: AgentStreamPath
  /** The JSON request body. */
  body: unknown
  /**
   * Aborts the fetch. It does not stop the run server side: post
   * `cancelRun` from `api/agent.ts` for that.
   */
  signal?: AbortSignal
  /** Called once per frame, in arrival order. */
  onFrame: (frame: AgentFrame) => void
}

/** Build an error frame for a failure the server never got to report itself. */
function errorFrame(message: string, kind: ErrorKind): ErrorFrame {
  return { type: 'error', message, kind }
}

function describe(cause: unknown): string {
  if (cause instanceof Error && cause.message) return cause.message
  if (typeof cause === 'string' && cause) return cause
  return 'Unknown error'
}

/**
 * Whether a failure is the caller's own abort rather than a real fault.
 *
 * An aborted run is a user pressing stop, so it produces no error frame. The
 * signal is checked as well as the exception because not every runtime raises a
 * DOMException named AbortError.
 */
function isAbort(cause: unknown, signal?: AbortSignal): boolean {
  if (signal?.aborted) return true
  return (cause as { name?: string } | null)?.name === 'AbortError'
}

/**
 * Parse one line of the stream.
 *
 * Silently drops anything that is not a well formed frame: a blank line, a
 * heartbeat comment, a `data:` line whose JSON will not parse, and an object
 * with no string `type`. A malformed frame is worth less than the rest of the
 * answer, and throwing here would end a stream over one bad line.
 *
 * @param line - One line, without its newline.
 * @returns The frame, or null when the line carries none.
 */
function parseFrame(line: string): AgentFrame | null {
  // Tolerate CRLF, which a proxy may introduce even though the server writes LF.
  const text = line.endsWith('\r') ? line.slice(0, -1) : line
  if (!text || text.startsWith(':')) return null
  if (!text.startsWith('data:')) return null

  const payload = text.slice(5).trim()
  if (!payload) return null

  let parsed: unknown
  try {
    parsed = JSON.parse(payload)
  } catch {
    return null
  }
  if (!parsed || typeof parsed !== 'object') return null
  if (typeof (parsed as { type?: unknown }).type !== 'string') return null
  return parsed as AgentFrame
}

/**
 * Read a pre-stream HTTP failure as an error frame.
 *
 * The blueprint answers 409 for the setup gate, 404 for a conversation that is
 * not yours, 400 for a bad request and 429 when rate limited, each with a
 * `message` worth showing verbatim. The status code is the fallback for a body
 * that is not the JSON envelope, such as an HTML error page from a proxy.
 */
async function httpFailureFrame(response: Response): Promise<ErrorFrame> {
  let message = ''
  let kind: ErrorKind = 'internal'
  try {
    const body = await response.text()
    const parsed = body ? JSON.parse(body) : null
    if (parsed && typeof parsed === 'object') {
      const envelope = parsed as { message?: unknown; kind?: unknown }
      if (typeof envelope.message === 'string') message = envelope.message
      if (typeof envelope.kind === 'string') kind = envelope.kind as ErrorKind
    }
  } catch {
    // A body that is not JSON tells us nothing the status has not already.
    message = ''
  }
  if (!message) {
    message = `The agent request failed with status ${response.status}`
  }
  return errorFrame(message, kind)
}

/**
 * Stream one turn, delivering every frame to `onFrame`.
 *
 * Resolves when the stream ends, for any reason: a done frame, a confirm frame
 * that terminated the run, an abort, or a failure that was reported as an error
 * frame. It rejects only if `onFrame` itself throws.
 *
 * @param request - Route, body, abort signal and frame callback.
 */
export async function streamAgentFrames({
  path,
  body,
  signal,
  onFrame,
}: AgentStreamRequest): Promise<void> {
  let csrfToken = ''
  try {
    csrfToken = await fetchCSRFToken()
  } catch (cause) {
    onFrame(errorFrame(`Could not obtain a CSRF token: ${describe(cause)}`, 'internal'))
    return
  }
  if (!csrfToken) {
    onFrame(
      errorFrame('Could not obtain a CSRF token. Refresh the page and try again.', 'internal')
    )
    return
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${AGENT_API_BASE}${path}`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        'X-CSRFToken': csrfToken,
      },
      body: JSON.stringify(body),
      signal,
    })
  } catch (cause) {
    if (isAbort(cause, signal)) return
    onFrame(errorFrame(`Could not reach the agent: ${describe(cause)}`, 'internal'))
    return
  }

  if (!response.ok) {
    onFrame(await httpFailureFrame(response))
    return
  }
  if (!response.body) {
    onFrame(errorFrame('The agent stream returned no body', 'internal'))
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      // `stream: true` keeps a multi-byte character split across two chunks
      // intact, which a symbol name or a currency sign can be.
      buffer += decoder.decode(value, { stream: true })

      let newline = buffer.indexOf('\n')
      while (newline >= 0) {
        const frame = parseFrame(buffer.slice(0, newline))
        buffer = buffer.slice(newline + 1)
        if (frame) onFrame(frame)
        newline = buffer.indexOf('\n')
      }
    }
    // Flush the decoder and dispatch whatever is left. A stream that ends
    // without a trailing newline would otherwise lose its last frame, which is
    // the done frame far more often than not.
    buffer += decoder.decode()
    const last = parseFrame(buffer)
    if (last) onFrame(last)
  } catch (cause) {
    if (!isAbort(cause, signal)) {
      onFrame(errorFrame(`The agent stream ended early: ${describe(cause)}`, 'internal'))
    }
  } finally {
    // Releases the reader's lock on the body. It rejects on an already aborted
    // stream, which is not worth reporting over a turn that has ended.
    reader.cancel().catch(() => undefined)
  }
}
