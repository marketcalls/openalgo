/**
 * The message composer.
 *
 * The textarea is **uncontrolled**, held by a ref rather than by state. A
 * controlled textarea re-renders the composer on every keystroke, and the
 * composer sits inside a thread that can be holding a long generated strategy;
 * paying a render for each character typed is a cost with nothing to show for
 * it. State changes here only when something visible actually changes, which is
 * the send button crossing between having text and not.
 *
 * Autogrow works the only way it can: the height is set to `0px` first so the
 * element collapses, and `scrollHeight` is then the height the content wants.
 * Reading `scrollHeight` without that reset returns the current height, so the
 * box grows and never shrinks.
 *
 * Enter sends and Shift+Enter inserts a newline, with one exception that is not
 * optional: while an IME composition is open, Enter commits the composition and
 * must not send. Indian language input and every CJK keyboard rely on that.
 *
 * It also registers itself as the destination for a prefill, which is how a
 * Buy or Sell control inside an answer starts an order without being wired to
 * an order tool. See `lib/agent/composer.ts`: text arrives, the operator reads
 * it and presses send, and the turn goes through the approval gate like any
 * other. **Nothing that arrives that way is sent by this component.**
 */

import { Loader2, Send, Square } from 'lucide-react'
import type { ReactNode } from 'react'
import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react'
import { Button } from '@/components/ui/button'
import { subscribeComposerPrefill } from '@/lib/agent/composer'
import { cn } from '@/lib/utils'

/** The textarea stops growing here and scrolls inside itself. */
const MAX_HEIGHT_PX = 200

export interface ComposerProps {
  /** Called with the trimmed text. The composer clears itself afterwards. */
  onSend: (text: string) => void
  /** Called when the operator stops a running turn. */
  onStop: () => void
  /** True while a turn is streaming. The button becomes stop. */
  running: boolean
  /** Blocks sending entirely, for a surface that is not ready to run a turn. */
  disabled?: boolean
  placeholder?: string
  className?: string
  /**
   * Controls rendered on the composer's own bottom row, under the text.
   * The model and reasoning picker lives here rather than in the page header
   * because it belongs to the message being written, not to the page: an
   * operator setting the effort is thinking about the sentence in front of
   * them, and a control three regions away does not read as part of it.
   */
  controls?: ReactNode
  /**
   * Whether a turn sent from here can reach an order tool.
   *
   * False on a surface built without them, such as the chart panel. It travels
   * with the prefill registration so an answer's Buy and Sell controls can ask
   * one question, "can this surface order", rather than inferring it from the
   * existence of a box to type in.
   */
  canOrder?: boolean
}

export function Composer({
  onSend,
  onStop,
  running,
  controls,
  canOrder = true,
  disabled = false,
  placeholder = 'Ask about your positions, a symbol, a strategy or a workflow',
  className,
}: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  // Mirrors `hasText` so the change handler can compare without reading state,
  // which is what keeps the re-render to the boundary crossing only.
  const hasTextRef = useRef(false)
  const [hasText, setHasText] = useState(false)

  const resize = useCallback(() => {
    const element = textareaRef.current
    if (!element) return
    // Collapse first. `scrollHeight` on an element at its current height only
    // ever reports that height, so the box would grow and never shrink.
    element.style.height = '0px'
    element.style.height = `${Math.min(element.scrollHeight, MAX_HEIGHT_PX)}px`
  }, [])

  useLayoutEffect(() => {
    resize()
  }, [resize])

  const handleInput = useCallback(() => {
    resize()
    const filled = (textareaRef.current?.value ?? '').trim().length > 0
    if (filled !== hasTextRef.current) {
      hasTextRef.current = filled
      setHasText(filled)
    }
  }, [resize])

  const submit = useCallback(() => {
    const element = textareaRef.current
    if (!element || running || disabled) return
    const text = element.value.trim()
    if (!text) return

    element.value = ''
    hasTextRef.current = false
    setHasText(false)
    resize()
    onSend(text)
  }, [disabled, onSend, resize, running])

  useEffect(
    () =>
      subscribeComposerPrefill((text) => {
        const element = textareaRef.current
        if (!element) return
        // Never discard what the operator was already writing. An empty box
        // takes the request as its whole content; a box with something in it
        // gets the request on a new line under it.
        const existing = element.value.replace(/\s+$/, '')
        element.value = existing ? `${existing}\n${text}` : text
        handleInput()
        element.focus()
        // Caret at the end, because the first thing anyone changes is the
        // quantity and it is the last thing they should have to reach for.
        element.setSelectionRange(element.value.length, element.value.length)
      }, canOrder),
    [handleInput, canOrder]
  )

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLTextAreaElement>) => {
      if (event.key !== 'Enter' || event.shiftKey) return
      // An open IME composition owns this Enter: it commits the candidate.
      if (event.nativeEvent.isComposing) return
      event.preventDefault()
      submit()
    },
    [submit]
  )

  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="flex flex-col gap-1.5 rounded-xl border border-input bg-background p-2 shadow-xs focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50">
        <textarea
          ref={textareaRef}
          rows={1}
          onInput={handleInput}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          placeholder={placeholder}
          aria-label="Message the agent"
          className="max-h-[200px] min-h-[24px] flex-1 resize-none bg-transparent px-1.5 py-1 text-sm leading-relaxed text-foreground outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
        />
        {/* Controls left, send right, both under the text. min-w-0 so a long
            model name truncates inside its own button rather than pushing the
            send control off the edge. */}
        <div className="flex items-center gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-1.5">{controls}</div>
          {running ? (
            <Button
              type="button"
              size="icon-sm"
              variant="outline"
              onClick={onStop}
              aria-label="Stop the running turn"
              title="Stop"
            >
              <Square className="h-3.5 w-3.5 fill-current" aria-hidden />
            </Button>
          ) : (
            <Button
              type="button"
              size="icon-sm"
              onClick={submit}
              disabled={disabled || !hasText}
              aria-label="Send the message"
              title="Send"
            >
              <Send className="h-3.5 w-3.5" aria-hidden />
            </Button>
          )}
        </div>
      </div>
      <p className="px-1 text-[11px] text-muted-foreground">
        {running ? (
          <span className="inline-flex items-center gap-1.5">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
            Running. Stop ends the turn on the server, not just here.
          </span>
        ) : (
          'Enter to send, Shift and Enter for a new line.'
        )}
      </p>
    </div>
  )
}
