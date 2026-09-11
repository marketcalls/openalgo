/**
 * The agent conversation view.
 *
 * A scrolling thread with the composer pinned under it, the model picker and
 * the conversation's running cost in the header.
 *
 * Four behaviours are worth stating because the obvious implementations of
 * them are wrong:
 *
 * - **Auto-scroll fires on a new turn, not on a new token**, which is
 *   `usePinNewestQuestion`, shared with the chart panel. The trailing spacer
 *   below the thread is this page's half of that bargain: it is what lets the
 *   last question reach the top even when the answer is one line.
 *
 * - **Stop is a server-side action.** `stop()` aborts the fetch for an
 *   immediate end in the browser and posts the cancel route, because a run that
 *   is merely unwatched is still running and still being billed.
 *
 * - **The height comes from the viewport, not from a `calc()`.** The page sits
 *   under `FullWidthLayout`, which is an `h-screen` flex column with
 *   `overflow-hidden`, so this view is one `flex-1 min-h-0` row and every
 *   region inside it either shrinks to its content or takes the remainder.
 *   Exactly one element scrolls, the thread. A `min-height` guess drifts the
 *   moment the header or the composer changes height, and the composer walking
 *   off the bottom of a phone is how that drift shows up.
 *
 * - **The header total is the conversation's, not the session's.** A thread
 *   opened from the sidebar arrives with each stored turn's usage already on
 *   it, so the same sum covers turns typed an hour ago and turns typed a minute
 *   ago. A total that only counted what streamed since the page loaded would
 *   quietly report a long conversation as cheap.
 *
 * Full width is for the chrome, not for the prose. The header spans the
 * viewport and the conversation column does not: a 2000px line length is
 * unreadable, so messages and the composer share one capped, centred column
 * while the sidebar and the header bar use the space around it.
 *
 * The turn's model is resolved before the first stream byte, so switching the
 * picker mid-conversation applies to the next turn and never disturbs the one
 * in flight.
 */

import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Bot, SlidersHorizontal } from 'lucide-react'
import { Fragment, useCallback, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import {
  agentErrorMessage,
  agentQueryKeys,
  getSettings,
  getVoiceConfig,
  type ReasoningEffort,
  recordVoiceTranscript,
  truncateConversation,
} from '@/api/agent'
import { Composer, type ComposerTurn } from '@/components/agent/Composer'
import { ConversationSidebar } from '@/components/agent/ConversationSidebar'
import { Message } from '@/components/agent/Message'
import { ModelPicker } from '@/components/agent/ModelPicker'
import { ConversationUsageBadge, sumUsage } from '@/components/agent/UsageBadge'
import { VoiceButton } from '@/components/agent/VoiceButton'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { type AgentMessage, useAgentStream } from '@/lib/agent/useAgentStream'
import { usePinNewestQuestion } from '@/lib/agent/useThreadScroll'
import type { VoiceController, VoiceTranscriptLine } from '@/lib/agent/voice'
import { cn } from '@/lib/utils'

/**
 * The reading column shared by the thread and the composer.
 *
 * They must be the same width or the box you type into stops lining up with
 * the answers it produces.
 */
const COLUMN = 'mx-auto w-full max-w-3xl'

export default function AgentChat() {
  const [modelId, setModelId] = useState<number | null>(null)
  // Per turn, not persisted: effort belongs to the question being asked.
  const [effort, setEffort] = useState<ReasoningEffort>('off')
  const [editError, setEditError] = useState<string | null>(null)

  // The trading switch lives on the config page; the chat only reads it.
  const settings = useQuery({
    queryKey: agentQueryKeys.settings(),
    queryFn: getSettings,
    staleTime: 30_000,
  })
  const { messages, running, error, conversationId, send, stop, confirm, reset, setConversation } =
    useAgentStream({
      surface: 'chat',
      modelId,
      reasoningEffort: effort === 'off' ? null : effort,
      // Asking is not the same as getting: the backend ANDs this with the
      // operator's own trading setting, so a session that asks while trading is
      // off still receives no order tools. Reading it from settings is what
      // makes the config switch actually reach a turn; before this the flag was
      // never set and the order tools could not be offered at all, so an order
      // request came back as a refusal rather than an approval prompt.
      tradingEnabled: settings.data?.data.trading_enabled ?? false,
      // Watched only while a spoken turn is running. The frames still drive the
      // message list the ordinary way; this reads two things off the side of
      // them - the words to speak, and the fact that a tool is taking a while.
      onFrame: (frame) => {
        if (!spokenAnswer.current) return
        if (frame.type === 'token') spokenAnswer.current.text += frame.delta
        else if (frame.type === 'tool_start') voiceController.current?.sayWorking(frame.name)
        else if (frame.type === 'confirm') {
          // A spoken turn paused for approval. The card renders as it always
          // does; this additionally lets the trader answer it out loud, with
          // the server deciding whether what they said was the phrase.
          const runId = frame.run_id
          const ids = frame.requirements.map((requirement) => requirement.id)
          voiceController.current?.awaitApproval(
            runId,
            () => {
              void confirm(Object.fromEntries(ids.map((id) => [id, true])))
            },
            // The question that opened this turn. When the operator put the
            // approval word at the head of it, that is the approval, and the
            // order runs without a read-back.
            spokenQuestion.current
          )
          spokenAnswer.current.text ||= awaitingApprovalLine.current
        }
      },
    })

  /**
   * Where a spoken turn's answer is collected while it streams.
   *
   * Null except while one is running, which is also what keeps `onFrame` free
   * for typed turns. Read after the send resolves rather than from `messages`,
   * because React state has not necessarily flushed by then and the words are
   * wanted the instant the turn ends.
   */
  const spokenAnswer = useRef<{ text: string } | null>(null)
  const voiceController = useRef<VoiceController | null>(null)

  /**
   * Every line of the spoken conversation, in order.
   *
   * Kept beside `messages` rather than folded into them because they are
   * different records: a message is what the agent decided, a line is what was
   * said out loud, and a speech model paraphrases the one into the other. Both
   * are worth seeing, and only one of them is a turn.
   */
  const [spokenLines, setSpokenLines] = useState<VoiceTranscriptLine[]>([])

  // The same cache entry the config panel and the mic button read, so renaming
  // the agent over there reaches the transcript labels without a reload.
  const voiceConfig = useQuery({
    queryKey: agentQueryKeys.voice(),
    queryFn: getVoiceConfig,
    staleTime: 30_000,
  })
  const voiceName = voiceConfig.data?.data.voice_agent_name || 'Agent'

  /**
   * How many messages existed when each spoken line was first seen.
   *
   * Speech and messages are interleaved by **anchoring**, not by sorting on a
   * clock. Sorting was the first attempt and it was wrong: a message carries no
   * timestamp, so one had to be invented at first render, and any drift between
   * that and the moment a line opened reordered the thread. Messages now render
   * in exactly the order `messages` holds them, which is the order that was
   * always correct, and each line is placed after the message that had just
   * been said when it was heard.
   */
  const lineAnchors = useRef(new Map<string, number>())

  /** Spoken lines grouped by the message index they follow. */
  const linesByAnchor = useMemo(() => {
    const grouped = new Map<number, VoiceTranscriptLine[]>()
    for (const line of spokenLines) {
      let anchor = lineAnchors.current.get(line.id)
      if (anchor === undefined) {
        anchor = messages.length
        lineAnchors.current.set(line.id, anchor)
      }
      const bucket = grouped.get(anchor)
      if (bucket) bucket.push(line)
      else grouped.set(anchor, [line])
    }
    // The controller keeps only the most recent lines, so an anchor for a line
    // that has scrolled out of it will never be read again. Dropping them here
    // keeps this map the same size as the transcript instead of growing for as
    // long as the page is open.
    if (lineAnchors.current.size > spokenLines.length) {
      const live = new Set(spokenLines.map((line) => line.id))
      for (const id of lineAnchors.current.keys()) {
        if (!live.has(id)) lineAnchors.current.delete(id)
      }
    }
    return grouped
  }, [messages.length, spokenLines])

  /** What to speak while a run waits for approval, read at frame time. */
  const awaitingApprovalLine = useRef('That needs your approval before I can place it.')

  /** The spoken question that opened the running turn, for the fast path. */
  const spokenQuestion = useRef('')

  const handleSpokenLine = useCallback((role: 'trader' | 'agent', text: string) => {
    void recordVoiceTranscript(role, text, conversationIdRef.current)
  }, [])

  const conversationIdRef = useRef<number | null>(null)
  conversationIdRef.current = conversationId ?? null

  /**
   * Run one spoken question as an ordinary turn and return what to say.
   *
   * This is what puts a spoken exchange on screen. The question goes through
   * the same `send` a typed one uses, so it appears as a user message, the
   * answer streams into the same list, and the tool timeline and any chart
   * render exactly as they do for typing. Only the words come back here.
   */
  const askByVoice = useCallback(
    async (question: string): Promise<string> => {
      const collector = { text: '' }
      spokenAnswer.current = collector
      spokenQuestion.current = question
      try {
        // The voice surface for this turn only: it decides the tools and asks
        // for an answer short enough to listen to. The conversation, the model
        // and the message list are shared with the typed surface.
        await send(question, { surface: 'voice', webSearch: lastWebSearch.current })
      } finally {
        spokenAnswer.current = null
      }
      return collector.text
    },
    [send]
  )

  const threadRef = useRef<HTMLDivElement>(null)

  const totals = useMemo(() => sumUsage(messages.map((message) => message.usage)), [messages])

  usePinNewestQuestion(threadRef, messages)

  /**
   * The web-search switch as the last sent turn had it.
   *
   * The composer owns that switch, so a retry or an edit, which do not go
   * through the composer, would otherwise silently re-enable search on a
   * conversation the operator had turned it off for.
   */
  const lastWebSearch = useRef(true)

  const handleSend = useCallback(
    (text: string, turn: ComposerTurn) => {
      lastWebSearch.current = turn.webSearch
      void send(text, turn)
    },
    [send]
  )

  const handleStop = useCallback(() => {
    void stop()
  }, [stop])

  const handleConfirm = useCallback(
    (decisions: Record<string, boolean>) => {
      void confirm(decisions)
    },
    [confirm]
  )

  // The sidebar has already fetched the conversation and hydrated it, so the
  // thread is switched in one commit: the id the next message continues, and
  // the stored turns with their tools, notices and usage on them.
  /** The newest answer, the only one worth offering a retry on. */
  const lastAssistantId = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].role === 'assistant') return messages[index].id
    }
    return null
  }, [messages])

  /** The most recent question, which is what a retry replaces. */
  const lastUserMessage = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].role === 'user') return messages[index]
    }
    return null
  }, [messages])

  /**
   * Replace a question and discard everything after it.
   *
   * The truncation happens on the SERVER first and the local state is rebuilt
   * from what it removed. Splicing locally and letting the server catch up
   * would look identical and be wrong: agno keeps its own copy of the
   * conversation, and a purely local edit leaves the model still answering the
   * question that was just rewritten.
   *
   * A message with no numeric id has never been stored, which happens when a
   * turn is still in flight. There is nothing to truncate, so it is refused
   * rather than silently sending a second question into the same thread.
   */
  const handleEdit = useCallback(
    (messageId: string, text: string) => {
      // Message ids are `stored-<row>` once the server has told us the row, and
      // a local counter like `user-3` before that. Only the first can be
      // truncated, because truncation names rows by database id.
      const match = /^stored-(\d+)$/.exec(messageId)
      const numericId = match ? Number(match[1]) : Number.NaN
      if (!conversationId || !Number.isFinite(numericId)) {
        // Never a silent return. An edit that quietly reverts is exactly what
        // this looked like before the id was carried back from the server.
        setEditError('That message cannot be edited yet. Wait for the turn to finish, then retry.')
        return
      }
      setEditError(null)
      void truncateConversation(conversationId, numericId)
        .then(() => {
          setConversation(
            conversationId,
            messages.slice(
              0,
              messages.findIndex((item) => item.id === messageId)
            )
          )
          send(text, { webSearch: lastWebSearch.current })
        })
        .catch((cause) => {
          // The answer is still on screen and the question unchanged, which is
          // the right place to fail: nothing has been half-removed.
          setEditError(agentErrorMessage(cause, 'Could not edit that message'))
        })
    },
    [conversationId, messages, send, setConversation]
  )

  /**
   * Answer the last question again, after a failure or an unsatisfying answer.
   *
   * This is an edit that changes nothing, so it goes through `handleEdit`
   * rather than beside it. Sending the text again on its own looked right and
   * was not: it appended a second copy of the question and a second answer, so
   * one retry left the thread holding the same question twice, and agno was
   * still carrying the answer the operator had just rejected. Replacing the
   * question with itself removes the old answer on the server first, which is
   * what "try again" means.
   */
  const handleRetry = useCallback(() => {
    if (!lastUserMessage) return
    handleEdit(lastUserMessage.id, lastUserMessage.content)
  }, [handleEdit, lastUserMessage])

  const handleSelectConversation = useCallback(
    (id: number, loaded: AgentMessage[]) => {
      setConversation(id, loaded)
    },
    [setConversation]
  )

  return (
    <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
      {/* The sidebar owns its own width and its own right border; the column
          beside it is min-w-0 so a wide tool result shrinks the thread rather
          than pushing the page sideways. */}
      <ConversationSidebar
        activeId={conversationId}
        surface="chat"
        busy={running}
        onNewChat={reset}
        onSelect={handleSelectConversation}
      />

      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        {/* Chrome spans the surface. Only the reading column is capped. */}
        <header className="flex shrink-0 items-center gap-3 border-b border-border px-4 py-2.5">
          <h1 className="text-base font-semibold tracking-tight">Agent</h1>
          <div className="ml-auto flex min-w-0 items-center gap-3">
            {/* What the whole conversation has cost, hydrated turns included.
                New chat lives in the sidebar, which is the one place a thread
                is started, opened or deleted. */}
            {totals.turns > 0 && (
              <div className="hidden items-center gap-1.5 sm:flex">
                <span className="text-[11px] leading-none tracking-wide text-muted-foreground uppercase">
                  Total
                </span>
                <ConversationUsageBadge totals={totals} />
              </div>
            )}
            {/* The only route from the conversation to its own settings. The
                profile menu carries one too, but an operator who is looking at
                the chat does not think to open a dropdown three regions away,
                and the setup screen that used to offer this link is exactly the
                screen a configured instance never sees again. It sits beside
                the model picker because adding a model is what the config page
                is most often opened to do. */}
            <Button
              asChild
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground"
            >
              <Link to="/agent/config" aria-label="Agent settings">
                <SlidersHorizontal className="h-4 w-4" aria-hidden />
              </Link>
            </Button>
          </div>
        </header>

        {/* The one scrolling element on the page. overflow-x-hidden is the
            backstop: a message that cannot break scrolls inside its own
            container rather than widening the body. */}
        <div ref={threadRef} className="relative min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
          {/* Spoken lines count as content. A conversation that is only
              speech - "hi Ava", an acknowledgement, a question the speech model
              answered itself - produces no messages at all, and showing the
              empty state over it loses the whole exchange. */}
          {messages.length === 0 && spokenLines.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
              <Bot className="h-10 w-10 text-muted-foreground/50" aria-hidden />
              {conversationId === null ? (
                <>
                  <p className="text-sm font-medium">Ask the agent</p>
                  <p className="max-w-sm text-sm leading-relaxed text-muted-foreground">
                    It reads your platform through the same service layer the rest of OpenAlgo uses,
                    and it can write an OpenAlgo strategy or a Flow workflow for you to review.
                  </p>
                </>
              ) : (
                /* A conversation is open and holds nothing. Saying so matters:
                   the welcome copy above is what an operator sees with nothing
                   selected at all, so reusing it here reads as a thread that
                   failed to load rather than one that is genuinely empty. A row
                   gets into this state when a run was interrupted before its
                   first message was stored. */
                <>
                  <p className="text-sm font-medium">This conversation is empty</p>
                  <p className="max-w-sm text-sm leading-relaxed text-muted-foreground">
                    Nothing was stored against it, which happens when a run was interrupted before
                    it answered. Ask something below to carry on in this thread.
                  </p>
                </>
              )}
            </div>
          ) : (
            <div className={cn(COLUMN, 'space-y-6 px-4 py-4')}>
              {/* A quiet record of what was actually said out loud, placed
                  after the message that had just been said when it was heard.
                  Messages themselves render in the order `messages` holds them
                  and are never reordered. */}
              {(linesByAnchor.get(0) ?? []).map((line) => (
                <SpokenLine key={line.id} line={line} agentName={voiceName} />
              ))}
              {messages.map((message, index) => (
                <Fragment key={message.id}>
                  <Message
                    message={message}
                    onConfirm={handleConfirm}
                    onEdit={message.role === 'user' ? handleEdit : undefined}
                    onRetry={
                      message.role === 'assistant' && message.id === lastAssistantId
                        ? handleRetry
                        : undefined
                    }
                    busy={running}
                  />
                  {(linesByAnchor.get(index + 1) ?? []).map((line) => (
                    <SpokenLine key={line.id} line={line} agentName={voiceName} />
                  ))}
                </Fragment>
              ))}
              {/* Lets the newest question reach the top of the viewport even
                  when the answer under it is only a line long. */}
              <div className="h-[40vh]" aria-hidden />
            </div>
          )}
        </div>

        <div className="shrink-0 border-t border-border">
          <div className={cn(COLUMN, 'space-y-2 px-4 py-3')}>
            {(error || editError) && (
              <Alert variant="destructive" className="py-2">
                <AlertCircle className="h-4 w-4" aria-hidden />
                <AlertDescription className="text-xs">{error || editError}</AlertDescription>
              </Alert>
            )}
            <ConversationUsageBadge totals={totals} className="px-1 sm:hidden" />
            <Composer
              onSend={handleSend}
              onStop={handleStop}
              running={running}
              // The same row the picker is showing, so the attach control and
              // the turn agree about which model has to read the file.
              modelId={modelId}
              controls={
                <>
                  <ModelPicker
                    value={modelId}
                    onChange={setModelId}
                    effort={effort}
                    onEffortChange={setEffort}
                    disabled={running}
                  />
                  {/* Renders nothing unless voice is configured and switched
                      on. A spoken turn runs on the same model the picker beside
                      it is showing, so the answer does not change character
                      when the question is spoken instead of typed. */}
                  <VoiceButton
                    modelId={modelId}
                    tradingEnabled={settings.data?.data.trading_enabled ?? false}
                    ask={askByVoice}
                    onSpokenLine={handleSpokenLine}
                    onTranscript={setSpokenLines}
                    onController={(controller) => {
                      voiceController.current = controller
                    }}
                    disabled={running}
                  />
                </>
              }
            />
          </div>
        </div>
      </div>
    </div>
  )
}

/**
 * One line of the spoken conversation.
 *
 * Deliberately quieter than a message: it is a record of what was said in the
 * room, not of what the agent decided, and the two are different things even
 * when they describe the same turn.
 */
function SpokenLine({ line, agentName }: { line: VoiceTranscriptLine; agentName: string }) {
  return (
    <p
      className={cn(
        'border-l-2 border-muted pl-3 text-xs leading-relaxed',
        line.role === 'trader' ? 'text-foreground/80' : 'text-muted-foreground',
        !line.final && 'opacity-60'
      )}
    >
      <span className="mr-1.5 font-medium opacity-70">
        {line.role === 'trader' ? 'You' : agentName}
      </span>
      {line.text}
    </p>
  )
}
