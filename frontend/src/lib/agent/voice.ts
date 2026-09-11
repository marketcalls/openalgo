/**
 * The browser half of the voice surface: one WebRTC connection and the
 * delegation loop that hangs off it.
 *
 * The speech model decides nothing. It is minted in **client delegation** mode,
 * so when it hears something that wants an answer it emits
 * `session.delegation.created` and waits for this file to supply one. The
 * answer comes from the same agno agent the text surface uses, reached through
 * the same `/agent/api/chat/stream` route with `surface: "voice"`, and comes
 * back over the data channel as `session.commentary.append`. Nothing about the
 * brain changes because the trader spoke instead of typed.
 *
 * Four things about this connection shape the code, and each of them is the
 * reason a more obvious implementation would be wrong:
 *
 * - **No audio passes through OpenAlgo.** The peer connection is browser to
 *   vendor. The server's entire involvement is one POST that swaps this
 *   browser's SDP offer for the vendor's answer, which is what keeps the voice
 *   surface clear of every eventlet hazard a server-held socket would carry.
 * - **The offer is posted once ICE gathering has finished**, not trickled. The
 *   mint route is a single request/response with nowhere to put a later
 *   candidate, so the offer has to be complete when it leaves. Gathering is
 *   nonetheless capped: a network with no reachable STUN server leaves the
 *   state at `gathering` indefinitely, and an offer carrying host candidates
 *   alone still connects on a LAN, so waiting forever trades a working session
 *   for a hung button.
 * - **There are no turn-finished events on this channel.** Transcripts arrive
 *   as deltas and simply stop, so a bubble is closed by a pause rather than by
 *   a frame. {@link TURN_PAUSE_MS} is that pause, and it is per role: the
 *   trader talking does not close the agent's bubble.
 * - **The SSE parser is `stream.ts`.** A spoken turn is an ordinary turn on an
 *   ordinary route, so it goes through `streamAgentFrames` like every typed
 *   one. A second parser here would be a second place for the frame vocabulary
 *   to drift out of step with `services/agent/frames.py`.
 *
 * This module is framework-free on purpose: it owns sockets, tracks and timers,
 * none of which belong to a render. `components/agent/VoiceButton.tsx`
 * subscribes to it and draws the result.
 */

import { fetchCSRFToken } from '@/api/client'
import { AGENT_API_BASE, type AgentFrame, streamAgentFrames } from './stream'

const API_BASE_URL = import.meta.env.VITE_API_URL || ''

/**
 * How long a transcript may go quiet before its bubble is closed.
 *
 * The vendor sends no turn-finished event, so this is the only boundary there
 * is. Short enough that a finished sentence settles while the trader is still
 * looking at it, long enough to survive the gap between two clauses.
 */
export const TURN_PAUSE_MS = 1500

/**
 * The cap on ICE gathering before the offer is posted regardless.
 *
 * See the module docstring: an incomplete offer that connects beats a complete
 * one that never arrives.
 */
const ICE_GATHERING_TIMEOUT_MS = 3000

/**
 * The character budget for anything spoken.
 *
 * Mirrors `SPEAKABLE_CHAR_BUDGET` in `services/agent/voice.py`. The wire limit
 * on `session.commentary.append` is 500 tokens; the real limit is how much a
 * person sits through before interrupting, which is much less.
 */
const SPEAKABLE_BUDGET = 480

/** Transcript lines kept for display. Older ones are dropped, not stored. */
const MAX_TRANSCRIPT_LINES = 50

/** The data channel the vendor speaks its session events over. */
const EVENT_CHANNEL = 'oai-events'

// ---------------------------------------------------------------------------
// Shapes
// ---------------------------------------------------------------------------

/**
 * Where a voice session is.
 *
 * `thinking` is the agno turn running and is the one state that is not about
 * audio at all; `speaking` covers both the moment an answer has been handed
 * over and the vendor reading it out.
 */
export type VoiceState = 'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking' | 'error'

/** What the button renders: one state and, when there is one, one reason. */
export interface VoiceStatus {
  state: VoiceState
  /** Plain language, safe to show. Null unless `state` is `error`. */
  error: string | null
}

/** One side of one spoken exchange, closed by a pause rather than an event. */
export interface VoiceTranscriptLine {
  /** Stable while the line is open, which is what keeps React keys honest. */
  id: string
  /** `trader` is the microphone, `agent` is what was spoken back. */
  role: 'trader' | 'agent'
  text: string
  /** False while more deltas may still arrive on this line. */
  final: boolean
}

export interface VoiceControllerOptions {
  /**
   * The model row a spoken turn runs on, or null for the configured default.
   *
   * The same value the composer's picker holds, so the voice surface and the
   * typed one answer on the same brain rather than silently diverging.
   */
  modelId?: number | null
  /**
   * Whether this session asks for order tools.
   *
   * Asking is not getting: the backend ANDs this with `trading_enabled` and
   * with `voice_trading_enabled`, so a request that asks while either switch is
   * off still receives no mutating tools.
   */
  tradingEnabled?: boolean
  /** Continue an existing conversation instead of opening a new one. */
  conversationId?: number | string | null
  /**
   * Every frame of every spoken turn, in arrival order.
   *
   * Only used when this file runs the turn itself, which it does not when
   * `ask` is supplied.
   */
  onFrame?: (frame: AgentFrame) => void
  /**
   * Run one spoken turn and return what should be said aloud.
   *
   * **This is how a spoken turn becomes a visible one.** When it is supplied,
   * this file does not stream anything: it hands the transcribed question to
   * the page, which runs it through the very same `send` a typed question uses,
   * so the question appears as a user message, the answer streams into the same
   * message list, and the tool timeline and any chart render exactly as they do
   * for typing. Without it a spoken turn would be invisible on screen, which is
   * the whole reason the surface is worth having.
   *
   * @param question - What the trader said, as transcribed.
   * @returns The answer text. It is shortened for speech before it is spoken.
   */
  ask?: (question: string) => Promise<string>
  /**
   * One finalised line of the spoken conversation, as it was transcribed.
   *
   * Called for **every** line, including the ones that never become an agent
   * turn. A speech model handles much of an exchange itself, and none of that
   * reaches the message list, so a record built only from turns would be the
   * subset of a conversation that happened to need a tool.
   */
  onSpokenLine?: (role: 'trader' | 'agent', text: string) => void
  /**
   * Hang up after this many seconds with nobody speaking. 0 never hangs up.
   *
   * An open microphone is billed for as long as it is open: silence is still
   * audio being streamed to the provider. A trading screen stays open all day,
   * so a microphone left on by accident is a real cost rather than untidiness.
   */
  idleTimeoutSeconds?: number
}

/** The connection, its state machine, and the delegation loop. */
export interface VoiceController {
  /** Open the microphone, mint the session and connect. Idempotent. */
  start: () => Promise<void>
  /** Close everything and release the microphone. Safe to call when idle. */
  stop: () => void
  /** The current status, for a first render before anything has changed. */
  status: () => VoiceStatus
  /** The transcript so far, newest last. */
  transcript: () => VoiceTranscriptLine[]
  /** Subscribe to status changes. Returns its own unsubscribe. */
  onStatus: (listener: (status: VoiceStatus) => void) => () => void
  /** Subscribe to transcript changes. Returns its own unsubscribe. */
  onTranscript: (listener: (lines: VoiceTranscriptLine[]) => void) => () => void
  /** The conversation spoken turns are being stored against, once there is one. */
  conversationId: () => number | string | null
  /**
   * Tell the trader a tool is running, so a slow lookup is not silence.
   *
   * Called by the page while the turn it is running reports tool activity. A
   * no-op unless a spoken turn is waiting on an answer.
   */
  sayWorking: (toolName: string) => void
  /**
   * Listen for a spoken approval of one paused run.
   *
   * Each finalised thing the trader says while this is set is offered to the
   * server, which decides. `approve` runs only on a server-side yes.
   */
  awaitApproval: (runId: string, approve: () => void) => void
  /** Stop listening, because the run was answered on screen or abandoned. */
  cancelApproval: () => void
}

// ---------------------------------------------------------------------------
// Speech
// ---------------------------------------------------------------------------

/**
 * Trim an answer to something worth hearing.
 *
 * The full answer is already on screen, so this is a length guard rather than a
 * summary, and it is the only path to the data channel. Markdown is stripped
 * instead of spoken because a speech model reading asterisks and pipe
 * characters aloud is the most obvious way this feature sounds broken.
 *
 * Mirrors `speakable()` in `services/agent/voice.py`. Both exist because the
 * text takes this route to the vendor and never that one; they are kept to the
 * same rules so the trader hears the same shape of answer either way.
 *
 * @param text - The agent's answer, as written for the screen.
 * @returns Plain text no longer than the budget, cut at a sentence where one is
 *   available.
 */
export function speakable(text: string): string {
  let raw = (text ?? '').trim()
  if (!raw) return ''

  // Fenced code and tables are unspeakable; drop them rather than read them.
  raw = raw.replace(/```[\s\S]*?```/g, ' ')
  raw = raw
    .split('\n')
    .filter((line) => !line.trimStart().startsWith('|'))
    .join('\n')
  raw = raw.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
  raw = raw.replace(/[*_`#>]+/g, ' ')
  raw = raw.replace(/^\s*[-+]\s+/gm, '')
  raw = raw.replace(/\s+/g, ' ').trim()

  if (raw.length <= SPEAKABLE_BUDGET) return raw

  const clipped = raw.slice(0, SPEAKABLE_BUDGET)
  const cut = Math.max(
    clipped.lastIndexOf('. '),
    clipped.lastIndexOf('? '),
    clipped.lastIndexOf('! ')
  )
  if (cut > SPEAKABLE_BUDGET / 2) return clipped.slice(0, cut + 1).trim()
  return `${clipped.slice(0, clipped.lastIndexOf(' ')).trim()}...`
}

/**
 * What to say while a tool is running.
 *
 * Never spoken verbatim: `session.thinking.append` is paraphrased by the speech
 * model, so this only has to carry the sense of what is happening. It exists
 * because silence during a slow tool reads as a dropped connection.
 *
 * @param name - The tool name as the frame carries it.
 * @returns One short line.
 */
function thinkingLine(name: string): string {
  const readable = (name || 'that').replace(/_/g, ' ').trim()
  return `Still working. Looking up ${readable} now.`
}

// ---------------------------------------------------------------------------
// Plumbing
// ---------------------------------------------------------------------------

function describe(cause: unknown, fallback: string): string {
  if (cause instanceof Error && cause.message) return cause.message
  if (typeof cause === 'string' && cause) return cause
  return fallback
}

/**
 * Turn a `getUserMedia` rejection into something an operator can act on.
 *
 * The browser's own messages name internal constraints, so the three cases
 * worth distinguishing are named here and everything else falls through.
 *
 * @param cause - Whatever `getUserMedia` rejected with.
 * @returns A plain language reason.
 */
function microphoneRefusal(cause: unknown): string {
  const name = (cause as { name?: string } | null)?.name ?? ''
  // Checked before the permission cases, because an insecure page never gets
  // as far as asking: the browser refuses the device outright and the operator
  // is left toggling a permission that was never the problem. OpenAlgo is
  // commonly reached on a LAN address over plain http, which is exactly the
  // shape that fails here while localhost works.
  if (!window.isSecureContext || name === 'SecurityError') {
    return (
      'Your browser will not allow the microphone on this address. Open ' +
      'OpenAlgo at http://127.0.0.1:5000, or set up https for your domain. ' +
      'A plain http address that is not on this machine can never use a ' +
      'microphone, whatever the settings say.'
    )
  }
  if (name === 'NotAllowedError') {
    return (
      'The microphone was blocked. Allow it for this site in your browser, ' +
      'and check your computer lets the browser use the microphone at all: ' +
      'that switch is in privacy settings on Windows and on a Mac.'
    )
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') {
    return 'No microphone was found. Plug one in, or check it is selected as the input device.'
  }
  if (name === 'NotReadableError') {
    return 'Another app is using the microphone. Close it and try again.'
  }
  return describe(cause, 'The microphone could not be opened. Try again.')
}

/**
 * Wait for ICE gathering, but not forever.
 *
 * @param pc - The connection whose local candidates are being gathered.
 * @returns A promise that settles on completion or on the cap, whichever first.
 */
function waitForIceGathering(pc: RTCPeerConnection): Promise<void> {
  if (pc.iceGatheringState === 'complete') return Promise.resolve()
  return new Promise((resolve) => {
    let timer: ReturnType<typeof setTimeout> | undefined
    const finish = () => {
      if (timer !== undefined) clearTimeout(timer)
      pc.removeEventListener('icegatheringstatechange', onChange)
      resolve()
    }
    const onChange = () => {
      if (pc.iceGatheringState === 'complete') finish()
    }
    pc.addEventListener('icegatheringstatechange', onChange)
    timer = setTimeout(finish, ICE_GATHERING_TIMEOUT_MS)
  })
}

/**
 * Read one field out of a data channel event, wherever the vendor put it.
 *
 * Session events nest their payload differently by type, so a reader that
 * insists on one path breaks on the next event it meets. Absence is an empty
 * string, never a throw: a malformed event is worth less than the session.
 *
 * @param event - The parsed event object.
 * @param paths - Candidate dotted paths, in order of preference.
 * @returns The first string found, or an empty string.
 */
function readString(event: Record<string, unknown>, paths: string[]): string {
  for (const path of paths) {
    let node: unknown = event
    for (const segment of path.split('.')) {
      if (!node || typeof node !== 'object') {
        node = undefined
        break
      }
      node = (node as Record<string, unknown>)[segment]
    }
    if (typeof node === 'string' && node) return node
  }
  return ''
}

/** Unique enough for one session, which is all an event id has to be. */
function nextEventId(): string {
  return `evt_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
}

// ---------------------------------------------------------------------------
// The controller
// ---------------------------------------------------------------------------

/**
 * Build a voice controller.
 *
 * Nothing happens until {@link VoiceController.start} is called, and calling it
 * twice is a no-op rather than a second connection: the microphone button is a
 * toggle and a double click must not leave an orphan peer connection holding
 * the device.
 *
 * @param options - The model, the trading ask and the frame sink.
 * @returns The controller.
 */
export function createVoiceController(options: VoiceControllerOptions = {}): VoiceController {
  let state: VoiceState = 'idle'
  let errorMessage: string | null = null

  const statusListeners = new Set<(status: VoiceStatus) => void>()
  const transcriptListeners = new Set<(lines: VoiceTranscriptLine[]) => void>()

  let pc: RTCPeerConnection | null = null
  let channel: RTCDataChannel | null = null
  let microphone: MediaStream | null = null
  // Bumped by every teardown. `start` is a chain of awaits and a trader can
  // press stop, or navigate away, during any of them - most likely during the
  // microphone permission prompt, which is the one await that waits on a human.
  // Comparing this against the value captured at entry is how each await learns
  // that the session it belongs to was abandoned while it was suspended.
  let generation = 0
  let audio: HTMLAudioElement | null = null

  let lines: VoiceTranscriptLine[] = []
  /** The open bubble per role, closed by {@link TURN_PAUSE_MS} of silence. */
  const open: Record<
    'trader' | 'agent',
    { id: string; timer: ReturnType<typeof setTimeout> } | null
  > = { trader: null, agent: null }

  /**
   * What the trader has said since the last delegation was dispatched.
   *
   * The delegation event does not carry the question, so the transcript is the
   * question. It is cleared on dispatch so a second delegation asks about the
   * second utterance rather than repeating the first one with it.
   */
  let question = ''
  let delegation: AbortController | null = null
  /** The delegation a page-run turn is answering, for `sayWorking`. */
  let activeDelegation: string | null = null
  /** The run waiting on a spoken approval, and what to do when it gets one. */
  let pendingApproval: { runId: string; approve: () => void } | null = null
  /** Hangs up a session nobody is using. Cleared by every sign of life. */
  let idleTimer: ReturnType<typeof setTimeout> | undefined

  /**
   * Restart the idle countdown.
   *
   * Called by anything that means the session is still wanted: a word from
   * either side, a turn being run. A session that hangs up keeps its thread and
   * its transcript, so starting again costs a button press and loses nothing.
   */
  function touchIdle(): void {
    if (idleTimer !== undefined) clearTimeout(idleTimer)
    const seconds = options.idleTimeoutSeconds ?? 0
    if (seconds <= 0) return
    idleTimer = setTimeout(() => {
      if (state === 'idle') return
      const minutes = Math.round(seconds / 60)
      const quiet =
        minutes >= 1 ? `${minutes} minute${minutes === 1 ? '' : 's'}` : `${seconds} seconds`
      teardown()
      setState(
        'idle',
        `Voice stopped after ${quiet} of quiet. Press the microphone to start again.`
      )
    }, seconds * 1000)
  }
  let conversation: number | string | null = options.conversationId ?? null
  let lineCounter = 0

  // -- notification --------------------------------------------------------

  function emitStatus(): void {
    const snapshot: VoiceStatus = { state, error: errorMessage }
    for (const listener of statusListeners) listener(snapshot)
  }

  function emitTranscript(): void {
    const snapshot = [...lines]
    for (const listener of transcriptListeners) listener(snapshot)
  }

  function setState(next: VoiceState, reason: string | null = null): void {
    if (state === next && errorMessage === reason) return
    state = next
    errorMessage = next === 'error' ? reason : null
    emitStatus()
  }

  /** An unrecoverable failure: say why, then put everything back. */
  function fail(reason: string): void {
    teardown()
    setState('error', reason)
  }

  // -- transcript ----------------------------------------------------------

  function closeLine(role: 'trader' | 'agent'): void {
    const holder = open[role]
    if (!holder) return
    clearTimeout(holder.timer)
    const finished = lines.find((line) => line.id === holder.id)
    if (finished?.text.trim()) {
      options.onSpokenLine?.(role, finished.text.trim())
      if (role === 'trader' && pendingApproval) void offerApproval(finished.text.trim())
    }
    open[role] = null
    lines = lines.map((line) => (line.id === holder.id ? { ...line, final: true } : line))
    emitTranscript()
  }

  /**
   * Append one transcript delta, opening a bubble when none is open.
   *
   * @param role - Which side spoke.
   * @param delta - The text fragment the vendor sent.
   */
  function appendDelta(role: 'trader' | 'agent', delta: string): void {
    touchIdle()
    if (!delta) return
    let holder = open[role]
    if (!holder) {
      lineCounter += 1
      const id = `${role}-${lineCounter}`
      lines = [...lines, { id, role, text: '', final: false }].slice(-MAX_TRANSCRIPT_LINES)
      holder = { id, timer: setTimeout(() => closeLine(role), TURN_PAUSE_MS) }
      open[role] = holder
    } else {
      clearTimeout(holder.timer)
      holder.timer = setTimeout(() => closeLine(role), TURN_PAUSE_MS)
    }
    const id = holder.id
    lines = lines.map((line) => (line.id === id ? { ...line, text: line.text + delta } : line))
    emitTranscript()
  }

  // -- data channel --------------------------------------------------------

  /**
   * Send one event to the speech model.
   *
   * A closed channel is dropped silently. The alternative is throwing inside a
   * stream callback for a session the trader has already ended.
   *
   * @param payload - The event object.
   */
  function send(payload: Record<string, unknown>): void {
    if (!channel || channel.readyState !== 'open') return
    try {
      channel.send(JSON.stringify(payload))
    } catch {
      // A channel that closed between the check and the send is the trader
      // hanging up, which is not a failure worth reporting.
    }
  }

  function handleEvent(raw: string): void {
    let parsed: unknown
    try {
      parsed = JSON.parse(raw)
    } catch {
      return
    }
    if (!parsed || typeof parsed !== 'object') return
    const event = parsed as Record<string, unknown>
    const type = typeof event.type === 'string' ? event.type : ''

    switch (type) {
      case 'session.output_transcript.delta': {
        // The agent is speaking what it was handed. Deltas arriving is the only
        // evidence there is that the vendor got as far as saying it.
        const delta = readString(event, ['delta', 'text', 'transcript'])
        if (delta) {
          appendDelta('agent', delta)
          if (state !== 'thinking') setState('speaking')
        }
        break
      }
      case 'session.input_transcript.delta': {
        const delta = readString(event, ['delta', 'text', 'transcript'])
        if (delta) {
          appendDelta('trader', delta)
          question += delta
          if (state === 'speaking') setState('listening')
        }
        break
      }
      case 'session.delegation.created': {
        const id = readString(event, ['delegation.id', 'delegation_id', 'id'])
        if (id) void answer(id)
        break
      }
      case 'error': {
        const message = readString(event, ['error.message', 'message'])
        fail(message || 'Something went wrong with voice. Press the microphone to start again.')
        break
      }
    }
  }

  // -- the delegation loop -------------------------------------------------

  /**
   * Answer one delegation with an agno turn.
   *
   * This is the whole feature in one function: the accumulated transcript is
   * posted to the same `/chat/stream` route a typed question uses, its frames
   * are read with the same parser, and the answer comes back over the data
   * channel for the speech model to read out.
   *
   * A delegation arriving while one is in flight **aborts the one in flight**.
   * That is the trader interrupting, which is the behaviour a speech model is
   * chosen for; queueing would have the agent answer a question that has been
   * replaced.
   *
   * @param delegationId - The id every reply on this turn is tagged with.
   */
  async function answer(delegationId: string): Promise<void> {
    delegation?.abort()
    const controller = new AbortController()
    delegation = controller
    activeDelegation = delegationId

    const asked = question.trim()
    question = ''
    if (!asked) {
      // Nothing was transcribed, so there is nothing to ask. Saying so is the
      // only honest answer; silence reads as a broken connection.
      send({
        type: 'session.commentary.append',
        event_id: nextEventId(),
        delegation_id: delegationId,
        content: 'I did not catch that. Say it again.',
      })
      setState('speaking')
      return
    }

    setState('thinking')

    if (options.ask) {
      // The page owns the turn. It renders every part of it and hands back only
      // the words, so nothing about the on-screen answer is duplicated here.
      let spokenText = ''
      let askFailure = ''
      try {
        spokenText = await options.ask(asked)
      } catch (cause) {
        askFailure = describe(cause, 'That did not work.')
      }
      if (controller.signal.aborted) return
      if (delegation === controller) delegation = null
      send({
        type: 'session.commentary.append',
        event_id: nextEventId(),
        delegation_id: delegationId,
        content:
          speakable(spokenText) || speakable(askFailure) || 'I have nothing to say about that.',
      })
      setState('speaking')
      return
    }

    const body: Record<string, unknown> = {
      message: asked,
      surface: 'voice',
      // Null opens a conversation; the start frame carries its id back, and
      // every later spoken turn continues it rather than opening its own.
      conversation_id: conversation,
      trading_enabled: Boolean(options.tradingEnabled),
    }
    if (options.modelId != null) body.model_id = options.modelId

    let prose = ''
    let failure = ''

    await streamAgentFrames({
      path: '/chat/stream',
      body,
      signal: controller.signal,
      onFrame: (frame) => {
        options.onFrame?.(frame)
        switch (frame.type) {
          case 'start':
            conversation = frame.conversation_id
            break
          case 'token':
            prose += frame.delta
            break
          case 'tool_start':
            // Not spoken verbatim; the speech model paraphrases it. Without it
            // a slow tool is indistinguishable from a dropped call.
            send({
              type: 'session.thinking.append',
              event_id: nextEventId(),
              delegation_id: delegationId,
              content: thinkingLine(frame.name),
            })
            break
          case 'confirm':
            // The run paused for approval. The card on screen is what decides
            // it; all the voice surface does is say that it is waiting.
            failure = failure || 'That needs approval on screen before I can run it.'
            break
          case 'error':
            failure = frame.message
            break
        }
      },
    })

    if (controller.signal.aborted) return
    if (delegation === controller) delegation = null

    const spoken = speakable(prose) || speakable(failure) || 'I have nothing to say about that.'
    send({
      type: 'session.commentary.append',
      event_id: nextEventId(),
      delegation_id: delegationId,
      content: spoken,
    })
    setState('speaking')
  }

  // -- lifecycle -----------------------------------------------------------

  /**
   * Exchange the local offer for the vendor's answer.
   *
   * @param offer - The complete local SDP.
   * @returns The answer SDP.
   * @throws Error - Carrying the route's own message, which is written for an
   *   operator: a missing key, a switched-off feature, a refused credential.
   */
  async function mint(offer: string): Promise<string> {
    const csrfToken = await fetchCSRFToken()
    const response = await fetch(`${API_BASE_URL}${AGENT_API_BASE}/voice/session`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/sdp',
        Accept: 'application/sdp',
        'X-CSRFToken': csrfToken,
      },
      body: offer,
    })

    const body = await response.text()
    if (response.ok) {
      // `fetch` follows redirects, and `ok` is true for wherever it landed. A
      // session that has expired sends this POST to the login page, which
      // answers 200 with the single-page app, and that HTML was being handed
      // straight to setRemoteDescription - which reports it as a broken SDP
      // line and sends the operator hunting for a WebRTC fault that is not
      // there. Two cheap checks turn it into the sentence it should always
      // have been.
      const contentType = response.headers.get('content-type') ?? ''
      if (response.redirected || !contentType.includes('sdp') || !body.startsWith('v=0')) {
        throw new Error('You have been signed out. Reload the page and sign in again.')
      }
      if (!body.trim()) throw new Error('Voice could not start. Try again in a minute.')
      // SDP is a CRLF-terminated format and the final terminator is part of
      // it, so the body is normalised rather than trimmed. Trimming it is the
      // same mistake in the browser that produced "unmarshal SDP: EOF" on the
      // server.
      return `${body.replace(/\r\n/g, '\n').replace(/\s+$/, '').replace(/\n/g, '\r\n')}\r\n`
    }
    const text = body.trim()
    // The route answers `application/sdp` on success and the standard JSON
    // envelope on refusal, so the body is read both ways rather than assumed.
    let message = text
    try {
      const parsed = JSON.parse(text) as { message?: unknown }
      if (typeof parsed?.message === 'string' && parsed.message) message = parsed.message
    } catch {
      // Not JSON, so the body is already the message.
    }
    throw new Error(message || 'Voice could not start. Try again in a minute.')
  }

  async function start(): Promise<void> {
    if (state !== 'idle' && state !== 'error') return
    setState('connecting')

    const mine = generation
    /** Whether this attempt still owns the session, or was torn down mid-await. */
    const abandoned = (): boolean => generation !== mine

    if (!window.isSecureContext) {
      fail(microphoneRefusal(null))
      return
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      fail('This browser cannot use a microphone. Try Chrome, Edge or Firefox.')
      return
    }
    if (typeof RTCPeerConnection === 'undefined') {
      fail('This browser is too old for the voice agent. Try Chrome, Edge or Firefox.')
      return
    }

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (cause) {
      if (abandoned()) return
      fail(microphoneRefusal(cause))
      return
    }

    // The permission prompt is the longest wait in this function and the one a
    // trader is most likely to abandon. `teardown` could not have released this
    // stream, because it did not exist yet: releasing it is this branch's job,
    // and skipping it leaves the browser's recording indicator on over a UI
    // that says idle.
    if (abandoned()) {
      for (const track of stream.getTracks()) track.stop()
      return
    }
    microphone = stream

    try {
      const connection = new RTCPeerConnection()
      pc = connection

      for (const track of microphone.getAudioTracks()) {
        connection.addTrack(track, microphone)
      }

      // Built before the offer, so the channel is negotiated in it. A channel
      // created after the answer is applied never opens.
      const events = connection.createDataChannel(EVENT_CHANNEL)
      channel = events
      events.addEventListener('open', () => {
        setState('listening')
        touchIdle()
      })
      events.addEventListener('message', (message: MessageEvent) => {
        if (typeof message.data === 'string') handleEvent(message.data)
      })

      const element = new Audio()
      element.autoplay = true
      audio = element
      connection.addEventListener('track', (event: RTCTrackEvent) => {
        const [remote] = event.streams
        if (!remote) return
        element.srcObject = remote
        // The click that started the session is the gesture that authorises
        // playback, so a rejection here is a browser policy this code cannot
        // argue with. It ends the session rather than only reporting: a
        // connection nobody can hear is still holding the microphone, and
        // leaving it open would let the trader talk into a session that can
        // never answer.
        element.play().catch((cause: unknown) => {
          fail(
            describe(cause, 'Your browser would not play the reply. Check the tab is not muted.')
          )
        })
      })
      connection.addEventListener('connectionstatechange', () => {
        if (connection !== pc) return
        const phase = connection.connectionState
        if (phase === 'failed' || phase === 'disconnected' || phase === 'closed') {
          // Only a live session reports this. A teardown closes the connection
          // itself and has already put the state back.
          if (state !== 'idle')
            fail('The voice connection dropped. Press the microphone to start again.')
        }
      })

      const offer = await connection.createOffer()
      if (abandoned()) return
      await connection.setLocalDescription(offer)
      if (abandoned()) return
      await waitForIceGathering(connection)
      if (abandoned()) return

      const local = connection.localDescription?.sdp ?? offer.sdp ?? ''
      if (!local) {
        fail('The microphone could not connect. Reload the page and try again.')
        return
      }

      const sdp = await mint(local)
      // The trader may have pressed stop during the round trip, in which case
      // this connection is already closed and applying an answer to it throws.
      if (abandoned() || connection !== pc) return
      await connection.setRemoteDescription({ type: 'answer', sdp })
    } catch (cause) {
      // A stop part-way through the handshake makes the next call reject with
      // InvalidStateError. That is the trader getting what they asked for, not
      // a fault, so it must not paint the button red.
      if (abandoned()) return
      fail(describe(cause, 'Voice could not start. Try again in a minute.'))
    }
  }

  /** Release everything. Called by both `stop` and `fail`. */
  function teardown(): void {
    if (idleTimer !== undefined) {
      clearTimeout(idleTimer)
      idleTimer = undefined
    }
    // First, before anything is released: an await that resumes after this
    // point must be able to tell that its session is gone.
    generation += 1

    delegation?.abort()
    delegation = null

    for (const role of ['trader', 'agent'] as const) {
      const holder = open[role]
      if (holder) clearTimeout(holder.timer)
      open[role] = null
    }

    if (channel) {
      try {
        channel.close()
      } catch {
        // Already closed with the connection.
      }
      channel = null
    }
    if (pc) {
      try {
        pc.close()
      } catch {
        // Already closed.
      }
      pc = null
    }
    // Stopping the tracks is what turns the browser's recording indicator off.
    // Closing the connection alone leaves the device held.
    if (microphone) {
      for (const track of microphone.getTracks()) track.stop()
      microphone = null
    }
    if (audio) {
      audio.pause()
      audio.srcObject = null
      audio = null
    }
    question = ''
  }

  /**
   * Offer one utterance to the server as an approval for the waiting run.
   *
   * **The page does not decide.** It reports what it heard and which run it
   * heard it against; whether that is the phrase, whether the window is still
   * open and whether spoken approval is switched on at all are read server-side
   * from stored settings, so a defect here cannot turn a sentence into an
   * order. The card on screen remains the other way, and the only way once the
   * window has closed.
   *
   * @param transcript - The finalised line the trader just said.
   */
  async function offerApproval(transcript: string): Promise<void> {
    const waiting = pendingApproval
    if (!waiting) return
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch(`${API_BASE_URL}${AGENT_API_BASE}/voice/approve`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
        body: JSON.stringify({ run_id: waiting.runId, transcript }),
      })
      if (!response.ok) return
      const payload = await response.json()
      if (!payload?.data?.approved) return
    } catch {
      // A failed check is not an approval. Nothing to report: the trader can
      // say it again, or tap the card.
      return
    }
    if (pendingApproval !== waiting) return
    pendingApproval = null
    waiting.approve()
  }

  function stop(): void {
    teardown()
    setState('idle')
  }

  return {
    start,
    stop,
    status: () => ({ state, error: errorMessage }),
    transcript: () => [...lines],
    onStatus: (listener) => {
      statusListeners.add(listener)
      return () => statusListeners.delete(listener)
    },
    onTranscript: (listener) => {
      transcriptListeners.add(listener)
      return () => transcriptListeners.delete(listener)
    },
    conversationId: () => conversation,
    awaitApproval: (runId, approve) => {
      const id = String(runId || '').trim()
      pendingApproval = id ? { runId: id, approve } : null
    },
    cancelApproval: () => {
      pendingApproval = null
    },
    sayWorking: (toolName: string) => {
      // Sent as thinking rather than commentary: the speech model paraphrases
      // it in its own words if it uses it at all, which is what stops a slow
      // tool sounding like a dropped call without the agent reading out a
      // function name.
      if (!activeDelegation) return
      send({
        type: 'session.thinking.append',
        event_id: nextEventId(),
        delegation_id: activeDelegation,
        content: thinkingLine(toolName),
      })
    },
  }
}
