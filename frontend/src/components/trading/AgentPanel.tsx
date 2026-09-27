/**
 * The assistant, docked beside the chart.
 *
 * **There is no second chat implementation here.** The thread is
 * `useAgentStream` on `surface: 'chart'`, the turns are the same `Message`
 * component the `/agent` page renders and the box at the bottom is the same
 * `Composer`. What this file adds is the two things a chart panel needs and a
 * page does not: a context read off the terminal, and commands handed back to
 * it. Everything else it inherits, which is the point: a fix to how a tool call
 * or a code artifact renders lands on both surfaces at once.
 *
 * Three behaviours are worth stating, because each has an obvious wrong version:
 *
 * - **The context is read fresh at send time**, never captured at mount.
 *   `getChartContext` is called by the hook inside `send`, so an operator who
 *   loads a symbol, changes the interval and then asks "what do you make of
 *   this" is asking about what is on screen. A context captured when the panel
 *   opened would have the agent confidently analysing the instrument they used
 *   to be looking at.
 *
 * - **A chip fills the composer. It does not send.** They are starting points,
 *   not buttons, and the operator names the instrument or narrows the question
 *   before pressing send. It reuses the same prefill channel the answer's own
 *   controls use, so there is one way text gets into that box.
 *
 * - **This surface is offered no order tools at all.** It never asks for
 *   trading, so the backend never builds an order tool into the run's schema.
 *   That is structural rather than a matter of prompt wording, and it is why
 *   there is no approval prompt on this panel and no reason for one.
 *
 * A narrow column is the constraint the layout answers to. The header carries
 * no instrument, because the pane toolbar beside it already does; the chips
 * wrap and step aside while a turn runs; and the tool timeline each turn
 * renders is already a single collapsed line before this panel touches it.
 */

import { AlertCircle, Bot, SquarePen } from 'lucide-react'
import { useCallback, useRef } from 'react'
import { AgentSetupGate, useAgentConfigured } from '@/components/agent/AgentSetupGate'
import { Composer, type ComposerTurn } from '@/components/agent/Composer'
import { Message } from '@/components/agent/Message'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { prefillComposer } from '@/lib/agent/composer'
import type { AgentChartCommand } from '@/lib/agent/stream'
import { useAgentStream } from '@/lib/agent/useAgentStream'
import { usePinNewestQuestion } from '@/lib/agent/useThreadScroll'
import type { ChartContext } from '@/lib/trading/chartContract'
import { cn } from '@/lib/utils'
import { PANEL_HEADER, PanelShell } from './panelShell'

/**
 * The starting prompts, and deliberately four.
 *
 * Each is a thing the agent can actually do on the chart in front of the
 * operator rather than an index of everything it knows, and each is written as
 * the sentence a person would type. `fill` receives the live context so the
 * instrument and the interval are the ones on screen at the moment the chip is
 * pressed, which is also why the labels stay generic: a label naming a symbol
 * would go stale between renders, and the prompt cannot.
 */
const CHIPS: { label: string; fill: (context: ChartContext | null) => string }[] = [
  {
    label: 'Analyse this chart',
    fill: (context) =>
      context
        ? `Analyse the ${context.symbol} ${context.interval} chart: trend, structure and momentum.`
        : 'Analyse the chart I am looking at: trend, structure and momentum.',
  },
  {
    label: 'Draw demand and supply',
    fill: () => 'Draw the demand and supply zones on this chart.',
  },
  {
    label: 'Candlestick patterns',
    fill: () => 'Identify the candlestick patterns on this chart and mark them.',
  },
  {
    label: 'Read my drawings',
    fill: () => 'Look at the drawings I have made on this chart and tell me what you make of them.',
  },
]

export interface AgentPanelProps {
  /**
   * The chart as it currently is. Called at send time, so it must read the
   * terminal rather than close over a value.
   */
  getChartContext: () => ChartContext | null
  /** Applied by the terminal. Drawing, and clearing what it drew. */
  onChartCommand: (commands: AgentChartCommand[]) => void
  /**
   * The chart as a PNG, for the composer's "Attach chart screenshot".
   *
   * **This is why that menu item exists here and not on `/agent`.** The chat
   * page has no chart to photograph, and an item that opens a file dialog
   * instead would be lying about what it does. Resolved through the same
   * focused-pane lookup as the context, so the screenshot is of the chart the
   * question is about.
   */
  onCaptureChart?: () => Promise<File | null>
}

export function AgentPanel({ getChartContext, onChartCommand, onCaptureChart }: AgentPanelProps) {
  const { configured, loading } = useAgentConfigured()
  const threadRef = useRef<HTMLDivElement>(null)

  const { messages, running, error, send, stop, reset } = useAgentStream({
    surface: 'chart',
    // Never `tradingEnabled`. The chart surface is offered no order tools, and
    // asking for them here would be asking for a capability this panel has no
    // approval flow for. An order request belongs on the chat page.
    getChartContext,
    onChartCommand,
  })

  usePinNewestQuestion(threadRef, messages)

  const handleSend = useCallback(
    (text: string, turn: ComposerTurn) => void send(text, turn),
    [send]
  )
  const handleStop = useCallback(() => void stop(), [stop])

  return (
    <PanelShell
      id="oa-panel-agent"
      label="Assistant"
      storageKey="oa-trading-agent-width"
      defaultWidth={400}
    >
      {/* Header: what this is, and the way back to an empty thread. Its rule
          lands on the same line as every pane toolbar's.

          It deliberately does not name the instrument. The pane toolbar an inch
          to the left already does, and a second copy here would be one more
          thing to keep in step with a symbol the operator can change at any
          moment without saying anything to the agent. */}
      <div className={PANEL_HEADER}>
        <Bot className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">Assistant</span>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground"
          onClick={reset}
          disabled={running || messages.length === 0}
          aria-label="Start a new conversation"
          title="New conversation"
        >
          <SquarePen className="h-4 w-4" aria-hidden />
        </Button>
      </div>

      {!loading && !configured ? (
        <AgentSetupGate compact />
      ) : (
        <>
          {/* The one scrolling region. Positioned, because the pin reads
              offsetTop against it. */}
          <div
            ref={threadRef}
            className="relative min-h-0 flex-1 overflow-x-hidden overflow-y-auto"
          >
            {messages.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center gap-2 px-5 text-center">
                <Bot className="h-8 w-8 text-muted-foreground/50" aria-hidden />
                <p className="text-sm font-medium">Ask about this chart</p>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  It reads the symbol, interval and bars you are looking at, and it can mark up the
                  chart. It places no orders here.
                </p>
              </div>
            ) : (
              <div className="space-y-5 px-3 py-3">
                {messages.map((message) => (
                  <Message key={message.id} message={message} busy={running} />
                ))}
                {/* Lets the newest question reach the top even when the answer
                    under it is a line long. */}
                <div className="h-[40vh]" aria-hidden />
              </div>
            )}
          </div>

          <div className="shrink-0 space-y-2 border-t border-border px-3 py-2.5">
            {error && (
              <Alert variant="destructive" className="py-2">
                <AlertCircle className="h-4 w-4" aria-hidden />
                <AlertDescription className="text-xs">{error}</AlertDescription>
              </Alert>
            )}
            {/* Above the box, and withheld while a turn runs: a chip that
                appeared under a streaming answer would move the composer down
                mid-read for a suggestion that cannot be acted on yet. */}
            {!running && (
              <div className="flex flex-wrap gap-1.5">
                {CHIPS.map((chip) => (
                  <button
                    key={chip.label}
                    type="button"
                    onClick={() => prefillComposer(chip.fill(getChartContext()))}
                    className={cn(
                      'rounded-full border border-border px-2.5 py-1 text-[11px] leading-none',
                      'text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
                      'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring'
                    )}
                  >
                    {chip.label}
                  </button>
                ))}
              </div>
            )}
            <Composer
              onSend={handleSend}
              onStop={handleStop}
              running={running}
              placeholder="Ask about this chart"
              // No picker on this surface, so the turn runs on the configured
              // default and the composer asks about that row.
              modelId={null}
              onCaptureChart={onCaptureChart}
              // The surface asks for no order tools, so an answer's Buy and
              // Sell controls are withheld here. They write an order request
              // into this box, and a request this panel can only refuse is
              // worse than no button: it reads as a route to a trade.
              canOrder={false}
            />
          </div>
        </>
      )}
    </PanelShell>
  )
}
