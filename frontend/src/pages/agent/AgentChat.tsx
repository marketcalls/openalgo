/**
 * The agent conversation view.
 *
 * A scrolling thread with the composer pinned under it, the model picker and
 * the conversation's running cost in the header.
 *
 * Two behaviours are worth stating because the obvious implementations of both
 * are wrong:
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
 * The turn's model is resolved before the first stream byte, so switching the
 * picker mid-conversation applies to the next turn and never disturbs the one
 * in flight.
 */

import { AlertCircle, Bot, SquarePen } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Composer } from '@/components/agent/Composer'
import { Message } from '@/components/agent/Message'
import { ModelPicker } from '@/components/agent/ModelPicker'
import { ConversationUsageBadge, sumUsage } from '@/components/agent/UsageBadge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { useAgentStream } from '@/lib/agent/useAgentStream'

/**
 * How far the newest question sits from the top of the thread, in pixels.
 * Enough that it does not touch the header, small enough that the answer below
 * it gets the viewport.
 */
const PIN_OFFSET_PX = 8

export default function AgentChat() {
  const [modelId, setModelId] = useState<number | null>(null)
  const { messages, running, error, send, stop, confirm, reset } = useAgentStream({
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
    // The thread is the offset parent, so offsetTop is already relative to it.
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

  return (
    <div className="mx-auto flex h-[calc(100vh-11rem)] min-h-[26rem] w-full max-w-3xl flex-col">
      <header className="flex items-center gap-3 border-b border-border pb-3">
        <h1 className="text-base font-semibold tracking-tight">Agent</h1>
        <div className="ml-auto flex items-center gap-3">
          <ConversationUsageBadge totals={totals} className="hidden sm:flex" />
          <ModelPicker value={modelId} onChange={setModelId} disabled={running} />
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            onClick={reset}
            disabled={running || messages.length === 0}
            aria-label="Start a new conversation"
            title="New conversation"
          >
            <SquarePen className="h-4 w-4" aria-hidden />
          </Button>
        </div>
      </header>

      <div ref={threadRef} className="relative flex-1 overflow-y-auto py-4">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
            <Bot className="h-10 w-10 text-muted-foreground/50" aria-hidden />
            <p className="text-sm font-medium">Ask the agent</p>
            <p className="max-w-sm text-sm leading-relaxed text-muted-foreground">
              It reads your platform through the same service layer the rest of OpenAlgo uses, and
              it can write an OpenAlgo strategy or a Flow workflow for you to review.
            </p>
          </div>
        ) : (
          <div className="space-y-6 px-1">
            {messages.map((message) => (
              <Message key={message.id} message={message} onConfirm={handleConfirm} />
            ))}
            {/* Lets the newest question reach the top of the viewport even when
                the answer under it is only a line long. */}
            <div className="h-[40vh]" aria-hidden />
          </div>
        )}
      </div>

      <div className="space-y-2 border-t border-border pt-3">
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
  )
}
