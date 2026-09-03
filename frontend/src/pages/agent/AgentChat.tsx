/**
 * The agent conversation view.
 *
 * A scrolling thread with the composer pinned under it, the model picker and
 * the conversation's running cost in the header.
 *
 * Four behaviours are worth stating because the obvious implementations of
 * them are wrong:
 *
 * - **Auto-scroll fires on a new turn, not on a new token.** Following the tail
 *   of a streaming answer drags the text the operator is reading out from under
 *   them, and a long answer makes that unusable. Instead the newest question is
 *   pinned near the top of the viewport when it is asked, so the answer fills
 *   the space below it as it arrives and the reader's eye never has to move.
 *   The trailing spacer is what lets the last question reach the top even when
 *   the answer is short.
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

import { AlertCircle, Bot, SlidersHorizontal } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { Composer } from '@/components/agent/Composer'
import { ConversationSidebar } from '@/components/agent/ConversationSidebar'
import { Message } from '@/components/agent/Message'
import { ModelPicker } from '@/components/agent/ModelPicker'
import { ConversationUsageBadge, sumUsage } from '@/components/agent/UsageBadge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { type AgentMessage, useAgentStream } from '@/lib/agent/useAgentStream'
import { cn } from '@/lib/utils'

/**
 * How far the newest question sits from the top of the thread, in pixels.
 * Enough that it does not touch the header, small enough that the answer below
 * it gets the viewport.
 */
const PIN_OFFSET_PX = 8

/**
 * The reading column shared by the thread and the composer.
 *
 * They must be the same width or the box you type into stops lining up with
 * the answers it produces.
 */
const COLUMN = 'mx-auto w-full max-w-3xl'

export default function AgentChat() {
  const [modelId, setModelId] = useState<number | null>(null)
  const { messages, running, error, conversationId, send, stop, confirm, reset, setConversation } =
    useAgentStream({
      surface: 'chat',
      modelId,
    })

  const threadRef = useRef<HTMLDivElement>(null)

  const totals = useMemo(() => sumUsage(messages.map((message) => message.usage)), [messages])

  // Only the newest question's identity drives the scroll, so a hundred token
  // flushes into the answer below it move nothing.
  const newestQuestionId = useMemo(() => {
    for (let index = messages.length - 1; index >= 0; index -= 1) {
      if (messages[index].role === 'user') return messages[index].id
    }
    return null
  }, [messages])

  useEffect(() => {
    if (!newestQuestionId) return
    const thread = threadRef.current
    if (!thread) return
    const question = thread.querySelector<HTMLElement>(`[data-message-id="${newestQuestionId}"]`)
    if (!question) return
    // The thread is positioned, so it is the offset parent of every message
    // inside it however many unpositioned wrappers sit between them, and
    // offsetTop is already relative to it.
    thread.scrollTo({ top: Math.max(question.offsetTop - PIN_OFFSET_PX, 0), behavior: 'smooth' })
  }, [newestQuestionId])

  const handleSend = useCallback(
    (text: string) => {
      void send(text)
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
            <ModelPicker value={modelId} onChange={setModelId} disabled={running} />
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
          {messages.length === 0 ? (
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
              {messages.map((message) => (
                <Message key={message.id} message={message} onConfirm={handleConfirm} />
              ))}
              {/* Lets the newest question reach the top of the viewport even
                  when the answer under it is only a line long. */}
              <div className="h-[40vh]" aria-hidden />
            </div>
          )}
        </div>

        <div className="shrink-0 border-t border-border">
          <div className={cn(COLUMN, 'space-y-2 px-4 py-3')}>
            {error && (
              <Alert variant="destructive" className="py-2">
                <AlertCircle className="h-4 w-4" aria-hidden />
                <AlertDescription className="text-xs">{error}</AlertDescription>
              </Alert>
            )}
            <ConversationUsageBadge totals={totals} className="px-1 sm:hidden" />
            <Composer onSend={handleSend} onStop={handleStop} running={running} />
          </div>
        </div>
      </div>
    </div>
  )
}
