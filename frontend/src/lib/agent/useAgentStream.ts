/**
 * The hook that drives one agent conversation.
 *
 * It owns the message list, the run lifecycle and the accumulation of every
 * frame `stream.ts` delivers. A page supplies a composer and a renderer; this
 * supplies everything between them.
 *
 * **The one rule that matters most here: React state is not committed per
 * token.** Deltas are folded into a mutable draft held in a ref and the draft
 * is committed on an animation frame, so a burst of a hundred tokens produces
 * one render rather than a hundred. The reason is the renderer, not the hook: a
 * markdown parse of the accumulated answer on every token is quadratic in the
 * length of the answer, and a generated strategy is long. The final flush is
 * synchronous rather than scheduled, because an animation frame never fires in
 * a background tab and the tail of a turn must not wait for the tab to come
 * back.
 *
 * Two behaviours of the backend the hook is built around:
 *
 * - **A paused run ends its stream with a `confirm` frame and no `done`.** That
 *   is a decision waiting to be made, not a failure. The turn stops running,
 *   the message carries what is pending, and `confirm()` resumes it in place.
 * - **Aborting the fetch does not stop the run.** `stop()` aborts locally for
 *   an immediate stop to the UI, and posts the cancel route so the model stops
 *   being billed.
 *
 * Visualizations fold into **one ordered list**, `AgentMessage.viz`, whatever
 * engine draws them: a `viz` frame appends an item, and `ui` deltas accumulate
 * into the trailing OpenUI item. Each records the length of the prose when it
 * arrived, so the thread can put a chart back where the model drew it. Adding
 * a fourth renderer is a `kind` and a branch in `VizBlock`, and nothing here.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  type AgentSurface,
  type ConfirmRequirement,
  cancelRun,
  type ReasoningEffort,
  type ToolCall,
} from '@/api/agent'
import {
  type AgentAttachment,
  type AgentAttachmentMeta,
  attachmentMeta,
  attachmentPayload,
} from './attachments'
import {
  type AgentChartCommand,
  type AgentFrame,
  type AgentStreamPath,
  type NoticeFrame,
  streamAgentFrames,
  type UsageFrame,
} from './stream'
import { type AgentVizItem, OPENUI_VIZ, openUiMarkup, openUiSpec, vizItemFromFrame } from './viz'

/** Fallback cadence where `requestAnimationFrame` is missing, in ms. */
const FRAME_MS = 16

const hasAnimationFrame = typeof requestAnimationFrame === 'function'

function requestFrame(callback: () => void): number {
  return hasAnimationFrame ? requestAnimationFrame(callback) : setTimeout(callback, FRAME_MS)
}

function cancelFrame(handle: number): void {
  if (hasAnimationFrame) cancelAnimationFrame(handle)
  else clearTimeout(handle)
}

// ---------------------------------------------------------------------------
// Shapes
// ---------------------------------------------------------------------------

export type AgentRole = 'user' | 'assistant'

/**
 * Usage for one turn, in the wire's own field names.
 *
 * A reloaded conversation carries the same object in its notices sidecar, so
 * one renderer serves the live turn and the persisted one without an adapter
 * between them. `cost_usd` is null when the price is unknown; render it as
 * unknown, never as zero.
 */
export type AgentUsage = Omit<UsageFrame, 'type'>

export type AgentNotice = Omit<NoticeFrame, 'type'>

/** What a paused run is waiting on, carried by the message that paused. */
export interface AgentPendingConfirm {
  runId: string
  sessionId: string
  requirements: ConfirmRequirement[]
}

export interface AgentMessage {
  /** Stable across the whole turn, which is what keeps React keys honest. */
  id: string
  role: AgentRole
  content: string
  /** The reasoning trace, kept apart from the answer. */
  reasoning: string
  /**
   * Every visualization in this turn, in arrival order.
   *
   * One list holds all three renderers rather than a field per engine, because
   * each carries its own `kind` and each records the point in `content` it
   * arrived at, which is what lets the thread interleave charts with the prose
   * instead of stacking them all after it. OpenUI markup is one of them: `ui`
   * deltas accumulate into the trailing `openui` item, so a turn that draws,
   * writes, then draws again renders in that order.
   */
  viz: AgentVizItem[]
  /** In dispatch order. A call with no `ok` yet is still running. */
  tools: ToolCall[]
  /**
   * The files this question carried, on a user message.
   *
   * Metadata only, and that is what the server keeps too: a stored row records
   * a file's name, kind, type, size and digest and never its bytes. So the
   * thread shows that a file was sent and which one, and a reloaded
   * conversation shows exactly the same thing as the live one.
   */
  attachments: AgentAttachmentMeta[]
  notices: AgentNotice[]
  usage: AgentUsage | null
  /** Set when this turn paused for approval; null once it is decided. */
  pending: AgentPendingConfirm | null
  /** True while the turn is still streaming into this message. */
  streaming: boolean
  runId: string | null
  sessionId: string | null
}

let messageSeq = 0

/**
 * Build a message.
 *
 * Exported so a page hydrating a stored conversation builds the same shape the
 * live stream produces, rather than a second one the renderer has to know
 * about.
 *
 * @param role - Who the message is from.
 * @param content - The prose, empty for an assistant turn about to stream.
 * @param overrides - Any field to set on top of the empty message.
 * @returns A message with a fresh id unless one is given in `overrides`.
 */
export function createAgentMessage(
  role: AgentRole,
  content = '',
  overrides: Partial<AgentMessage> = {}
): AgentMessage {
  messageSeq += 1
  return {
    id: `${role}-${messageSeq}`,
    role,
    content,
    reasoning: '',
    viz: [],
    tools: [],
    attachments: [],
    notices: [],
    usage: null,
    pending: null,
    streaming: false,
    runId: null,
    sessionId: null,
    ...overrides,
  }
}

export interface UseAgentStreamOptions {
  /** Which surface the run belongs to. Decides which tools it is given. */
  surface?: AgentSurface
  /**
   * The conversation to continue. Read once, as the initial value; use
   * `setConversation` to switch afterwards, and leave it null to have the first
   * send open a new conversation in the same round trip.
   */
  conversationId?: number | null
  /** The model row to run. Omitted means the configured default. */
  modelId?: number | null
  reasoningEffort?: ReasoningEffort | null
  /**
   * Whether this session is asking for order tools. The backend ANDs this with
   * the operator's own setting, so asking is not the same as getting.
   */
  tradingEnabled?: boolean
  /**
   * The chart panel's context, read **fresh at send time** rather than captured
   * at mount, so the agent sees the chart as it currently is.
   */
  getChartContext?: () => Record<string, unknown> | null
  /** Applied by the `/trading` terminal. */
  onChartCommand?: (commands: AgentChartCommand[]) => void
  /** Every frame, before the hook folds it in, for a panel that needs the raw feed. */
  onFrame?: (frame: AgentFrame) => void
}

/**
 * What one turn carries besides its words.
 *
 * Both fields are optional on the wire and both default the way the backend
 * defaults them: no `attachments` key means none, and an absent `web_search`
 * means on. So a caller that has neither sends exactly the body it sent before
 * either existed.
 */
export interface AgentTurnOptions {
  /** Files to send with this message. The bytes travel; nothing is stored. */
  attachments?: readonly AgentAttachment[]
  /**
   * False withholds the web search tools from this turn.
   *
   * Only false is transmitted. `/chat/confirm` needs none of this: the server
   * recovers the switch from the stored row and ANDs it with whatever the body
   * sends, so approving a paused order cannot hand the resumed run a tool the
   * question withheld.
   */
  webSearch?: boolean
}

export interface UseAgentStreamResult {
  messages: AgentMessage[]
  running: boolean
  conversationId: number | null
  error: string | null
  /** Send a message and stream the answer. Ignored while a turn is running. */
  send: (text: string, turn?: AgentTurnOptions) => Promise<void>
  /** Abort locally and cancel the run server side. */
  stop: () => Promise<void>
  /** Resume the paused run. Decisions are keyed by requirement or tool call id. */
  confirm: (decisions: Record<string, boolean>, note?: string) => Promise<void>
  /** Drop the conversation and start a new one on the next send. */
  reset: () => void
  /** Switch to another conversation, optionally with its stored messages. */
  setConversation: (id: number | null, messages?: AgentMessage[]) => void
}

// ---------------------------------------------------------------------------
// The hook
// ---------------------------------------------------------------------------

export function useAgentStream(options: UseAgentStreamOptions = {}): UseAgentStreamResult {
  const [messages, setMessages] = useState<AgentMessage[]>([])
  const [running, setRunning] = useState(false)
  const [conversationId, setConversationId] = useState<number | null>(
    options.conversationId ?? null
  )
  const [error, setError] = useState<string | null>(null)

  // Everything the callbacks read goes through a ref, so they stay stable for
  // the lifetime of the hook and a re-render never tears down a live run.
  const optionsRef = useRef(options)
  optionsRef.current = options
  const messagesRef = useRef(messages)
  messagesRef.current = messages
  const conversationIdRef = useRef(conversationId)
  conversationIdRef.current = conversationId

  const runningRef = useRef(false)
  const abortRef = useRef<AbortController | null>(null)

  // The streaming message, mutated in place. Nothing in React state points at
  // this object: `flushNow` commits a copy, so a render never observes a half
  // written message and memoized children still see a new identity per flush.
  const draftRef = useRef<AgentMessage | null>(null)
  const dirtyRef = useRef(false)
  const frameHandleRef = useRef<number | null>(null)

  /** Commit the draft now, cancelling any flush already scheduled. */
  const flushNow = useCallback(() => {
    if (frameHandleRef.current !== null) {
      cancelFrame(frameHandleRef.current)
      frameHandleRef.current = null
    }
    const draft = draftRef.current
    if (!draft || !dirtyRef.current) return
    dirtyRef.current = false
    const snapshot: AgentMessage = {
      ...draft,
      tools: draft.tools.map((tool) => ({ ...tool })),
      notices: [...draft.notices],
      // Each item is copied; its `spec` deliberately is not. A chart's spec
      // never changes, and `CandleViz` keys its whole chart lifecycle on that
      // object's identity, so cloning it here would tear the chart down and
      // rebuild it on every streamed token. Growing OpenUI markup is handled
      // the other way round: the `ui` case assigns a **new** spec object, so
      // the payload that did change carries a new identity anyway.
      viz: draft.viz.map((item) => ({ ...item })),
    }
    setMessages((prev) => prev.map((item) => (item.id === snapshot.id ? snapshot : item)))
  }, [])

  /** Ask for a commit on the next animation frame, at most one per frame. */
  const scheduleFlush = useCallback(() => {
    dirtyRef.current = true
    if (frameHandleRef.current !== null) return
    frameHandleRef.current = requestFrame(() => {
      frameHandleRef.current = null
      flushNow()
    })
  }, [flushNow])

  const handleFrame = useCallback(
    (frame: AgentFrame) => {
      optionsRef.current.onFrame?.(frame)
      const draft = draftRef.current
      if (!draft) return

      switch (frame.type) {
        case 'start': {
          draft.runId = frame.run_id
          draft.sessionId = frame.session_id
          // A conversation is created by the first send, so this is where a new
          // one learns its id.
          const id = Number(frame.conversation_id)
          if (Number.isFinite(id) && id !== conversationIdRef.current) {
            conversationIdRef.current = id
            setConversationId(id)
          }
          // Re-key the question just sent to the row the server stored it as,
          // so it can be edited later. Local ids are counters like `user-3`,
          // and truncation names rows by database id; without this the newest
          // question is the one message that cannot be edited.
          //
          // It is committed straight to state rather than through the draft:
          // the draft is the ASSISTANT message being streamed, and the question
          // is already in the list above it.
          const storedUser = Number(frame.user_message_id)
          if (Number.isFinite(storedUser) && storedUser > 0) {
            setMessages((prev) => {
              // A plain reverse scan: findLastIndex needs a newer lib target
              // than this project sets, and one loop is not worth moving it.
              let index = -1
              for (let scan = prev.length - 1; scan >= 0; scan -= 1) {
                if (prev[scan].role === 'user') {
                  index = scan
                  break
                }
              }
              if (index < 0 || prev[index].id === `stored-${storedUser}`) return prev
              const next = [...prev]
              next[index] = { ...next[index], id: `stored-${storedUser}` }
              return next
            })
          }
          scheduleFlush()
          break
        }
        case 'token':
          draft.content += frame.delta
          scheduleFlush()
          break
        case 'reasoning':
          draft.reasoning += frame.delta
          scheduleFlush()
          break
        case 'ui': {
          // Deltas accumulate into the trailing OpenUI block, and anything
          // else on the list closes it: a chart drawn between two render_ui
          // calls means two blocks, not one with a chart wedged inside it.
          const open = draft.viz[draft.viz.length - 1]
          if (open && open.kind === OPENUI_VIZ) {
            open.spec = openUiSpec(openUiMarkup(open.spec) + frame.delta)
          } else {
            draft.viz = [
              ...draft.viz,
              {
                kind: OPENUI_VIZ,
                spec: openUiSpec(frame.delta),
                title: '',
                source: '',
                at: draft.content.length,
              },
            ]
          }
          scheduleFlush()
          break
        }
        case 'viz':
          // `at` is what puts the chart back where the model drew it. The
          // spec itself is never inspected here: an unknown kind is stored
          // and the renderer decides it can draw nothing, which is what lets
          // a newer backend add a kind without a client release.
          draft.viz = [...draft.viz, vizItemFromFrame(frame, draft.content.length)]
          scheduleFlush()
          break
        case 'tool_start':
          draft.tools = [...draft.tools, { id: frame.id, name: frame.name, args: frame.args ?? {} }]
          scheduleFlush()
          break
        case 'tool_end': {
          // Matched by call id, never by name or position: one turn can run the
          // same tool more than once and the results come back interleaved.
          const started = draft.tools.find((tool) => tool.id === frame.id)
          if (started) {
            started.ok = frame.ok
            started.result = frame.result
            started.duration = frame.duration
          } else {
            draft.tools = [
              ...draft.tools,
              {
                id: frame.id,
                name: frame.name,
                ok: frame.ok,
                result: frame.result,
                duration: frame.duration,
              },
            ]
          }
          scheduleFlush()
          break
        }
        case 'chart_command':
          optionsRef.current.onChartCommand?.(frame.commands ?? [])
          break
        case 'confirm':
          // The stream ends here with no done frame. Not a failure: the run is
          // parked until the operator decides.
          draft.pending = {
            runId: frame.run_id,
            sessionId: frame.session_id,
            requirements: frame.requirements ?? [],
          }
          draft.streaming = false
          scheduleFlush()
          break
        case 'notice':
          draft.notices = [...draft.notices, { level: frame.level, message: frame.message }]
          scheduleFlush()
          break
        case 'usage':
          // Each usage frame is the running total for the turn, so the newest
          // replaces the last rather than adding to it. cost_usd stays null
          // when the model has no price: the UI must show that as unknown.
          draft.usage = {
            input_tokens: frame.input_tokens,
            output_tokens: frame.output_tokens,
            total_tokens: frame.total_tokens,
            cached_tokens: frame.cached_tokens,
            reasoning_tokens: frame.reasoning_tokens,
            cost_usd: frame.cost_usd,
            model: frame.model,
            ttft_ms: frame.ttft_ms,
          }
          scheduleFlush()
          break
        case 'error':
          setError(frame.message)
          draft.streaming = false
          scheduleFlush()
          break
        case 'done':
          draft.streaming = false
          scheduleFlush()
          break
      }
    },
    [scheduleFlush]
  )

  /**
   * Open an assistant message, stream one turn into it and close it.
   *
   * @param path - Which streaming route to post to.
   * @param body - The request body for that route.
   * @param prelude - Messages to append ahead of the assistant one, which is
   *   the user's message on a send and nothing on a resume.
   */
  const runTurn = useCallback(
    async (path: AgentStreamPath, body: Record<string, unknown>, prelude: AgentMessage[]) => {
      const draft = createAgentMessage('assistant', '', { streaming: true })
      draftRef.current = draft
      dirtyRef.current = false

      // The empty assistant message goes in with the user's, in one commit.
      // That empty bubble is what renders the thinking state.
      setMessages((prev) => [...prev, ...prelude, { ...draft }])

      const controller = new AbortController()
      abortRef.current = controller
      runningRef.current = true
      setRunning(true)

      try {
        await streamAgentFrames({ path, body, signal: controller.signal, onFrame: handleFrame })
      } catch (cause) {
        // A stream failure arrives as an error frame, so anything thrown here
        // came out of a frame handler and is a client side bug worth showing.
        setError(cause instanceof Error ? cause.message : 'The agent stream failed')
      } finally {
        draft.streaming = false
        dirtyRef.current = true
        // Synchronous, not scheduled: an animation frame does not fire in a
        // background tab, and the tail of the answer must not wait for one.
        flushNow()
        draftRef.current = null
        if (abortRef.current === controller) abortRef.current = null
        runningRef.current = false
        setRunning(false)
      }
    },
    [flushNow, handleFrame]
  )

  const send = useCallback(
    async (text: string, turn: AgentTurnOptions = {}) => {
      const message = text.trim()
      if (!message || runningRef.current) return
      setError(null)

      const {
        surface = 'chat',
        modelId,
        reasoningEffort,
        tradingEnabled,
        getChartContext,
      } = optionsRef.current
      const chartContext = getChartContext?.() ?? null

      const body: Record<string, unknown> = {
        message,
        surface,
        // Null opens a new conversation; the start frame carries its id back.
        conversation_id: conversationIdRef.current,
        trading_enabled: Boolean(tradingEnabled),
      }
      if (modelId != null) body.model_id = modelId
      if (reasoningEffort) body.reasoning_effort = reasoningEffort
      if (chartContext) body.chart_context = chartContext

      const files = turn.attachments ?? []
      if (files.length > 0) body.attachments = files.map(attachmentPayload)
      // Only the off case is sent. Absent means on, which is the default the
      // backend already had, so a caller that never touches the switch sends
      // the body it always sent.
      if (turn.webSearch === false) body.web_search = false

      await runTurn('/chat/stream', body, [
        createAgentMessage('user', message, { attachments: files.map(attachmentMeta) }),
      ])
    },
    [runTurn]
  )

  const confirm = useCallback(
    async (decisions: Record<string, boolean>, note?: string) => {
      if (runningRef.current) return
      const paused = [...messagesRef.current].reverse().find((item) => item.pending !== null)
      const pending = paused?.pending
      const conversation = conversationIdRef.current
      if (!paused || !pending || conversation === null) return

      setError(null)
      // The decision has been made, so the prompt comes off the message before
      // the resumed run starts writing to a new one.
      setMessages((prev) =>
        prev.map((item) => (item.id === paused.id ? { ...item, pending: null } : item))
      )

      const { surface = 'chat', modelId, tradingEnabled } = optionsRef.current
      const body: Record<string, unknown> = {
        run_id: pending.runId,
        session_id: pending.sessionId,
        conversation_id: conversation,
        decisions,
        surface,
        trading_enabled: Boolean(tradingEnabled),
      }
      if (modelId != null) body.model_id = modelId
      if (note) body.note = note

      await runTurn('/chat/confirm', body, [])
    },
    [runTurn]
  )

  const stop = useCallback(async () => {
    const runId = draftRef.current?.runId ?? null
    abortRef.current?.abort()
    if (!runId) return
    try {
      await cancelRun(runId)
    } catch {
      // Best effort, and deliberately silent. The server also cancels a run
      // when the client hangs up, and an error about a turn the operator has
      // already stopped is noise on top of what they asked for.
    }
  }, [])

  /** Forget the live run without touching the server. */
  const discardRun = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    draftRef.current = null
    dirtyRef.current = false
    if (frameHandleRef.current !== null) {
      cancelFrame(frameHandleRef.current)
      frameHandleRef.current = null
    }
  }, [])

  const reset = useCallback(() => {
    discardRun()
    conversationIdRef.current = null
    setConversationId(null)
    setMessages([])
    setError(null)
  }, [discardRun])

  const setConversation = useCallback(
    (id: number | null, next: AgentMessage[] = []) => {
      discardRun()
      conversationIdRef.current = id
      setConversationId(id)
      setMessages(next)
      setError(null)
    },
    [discardRun]
  )

  // Abort whatever is in flight on unmount. No cancel is posted: the route
  // cancels the run itself when the client hangs up, and a fetch from a
  // component that is going away has nowhere to deliver the answer.
  useEffect(
    () => () => {
      abortRef.current?.abort()
      if (frameHandleRef.current !== null) cancelFrame(frameHandleRef.current)
    },
    []
  )

  return {
    messages,
    running,
    conversationId,
    error,
    send,
    stop,
    confirm,
    reset,
    setConversation,
  }
}
