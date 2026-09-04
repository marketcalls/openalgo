/**
 * The message composer.
 *
 * The textarea is **uncontrolled**, held by a ref rather than by state. A
 * controlled textarea re-renders the composer on every keystroke, and the
 * composer sits inside a thread that can be holding a long generated strategy;
 * paying a render for each character typed is a cost with nothing to show for
 * it. State changes here only when something visible actually changes, which is
 * the send button crossing between having text and not, and a file being
 * attached or taken off.
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
 *
 * ## The "+" menu
 *
 * Everything a turn can carry beyond its words lives behind one control at the
 * left of the bottom row, beside the model picker: files, a chart screenshot on
 * a surface that has a chart, and the web-search switch. The switch is a
 * checkbox rather than a link because it changes this turn rather than going
 * somewhere, and it is here rather than in settings for the same reason the
 * reasoning effort is: it belongs to the question being written.
 *
 * **The composer owns both, and hands them to `onSend`.** A surface mounting
 * this component gets the whole menu without wiring anything, which is what
 * keeps the chat page and the chart panel from drifting apart.
 *
 * Three things about attaching that are worth stating:
 *
 * - **Three ways in, one path.** Picking, dragging and pasting all end at
 *   `addFiles`, so the caps, the refusal message and the vision check cannot
 *   apply to one route and not another. Paste is the one that matters most: a
 *   screenshot arrives on the clipboard, not as a file on disk.
 * - **A refusal happens here when the browser can already tell**, which is
 *   count and size. What a file *is* stays the server's decision, because it
 *   reads the bytes and this can only read what the operating system guessed.
 * - **Attaching is withheld from a model that cannot see**, with the reason in
 *   the menu naming the model. See `lib/agent/useVisionCapable.ts` for why that
 *   answer is assembled rather than read off the model row.
 */

import { Camera, Globe, Loader2, Paperclip, Plus, Send, Square } from 'lucide-react'
import type { ChangeEvent, ClipboardEvent, DragEvent, ReactNode } from 'react'
import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  type AgentAttachment,
  ATTACHMENT_ACCEPT,
  attachmentTotal,
  filesFrom,
  formatBytes,
  MAX_TOTAL_BYTES,
  readAttachment,
  rejectReason,
} from '@/lib/agent/attachments'
import { subscribeComposerPrefill } from '@/lib/agent/composer'
import { useVisionCapable } from '@/lib/agent/useVisionCapable'
import { cn } from '@/lib/utils'
import { AttachmentChip } from './AttachmentChip'

/** The textarea stops growing here and scrolls inside itself. */
const MAX_HEIGHT_PX = 200

/** Everything a turn carries besides its text. */
export interface ComposerTurn {
  /** The files attached to this message, empty when there are none. */
  attachments: AgentAttachment[]
  /** False withholds the web search tools from this turn entirely. */
  webSearch: boolean
}

export interface ComposerProps {
  /** Called with the trimmed text and what the turn carries. The composer clears itself afterwards. */
  onSend: (text: string, turn: ComposerTurn) => void
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
  /**
   * The model this turn will run on, or null for the configured default.
   *
   * Read for one question only: whether an image may be attached at all.
   */
  modelId?: number | null
  /**
   * Capture the surface's chart as a PNG.
   *
   * Its presence is what puts "Attach chart screenshot" in the menu, so the
   * item exists only where there is a chart to capture. Resolves to null when
   * there is nothing on screen to take.
   */
  onCaptureChart?: () => Promise<File | null>
}

export function Composer({
  onSend,
  onStop,
  running,
  controls,
  canOrder = true,
  disabled = false,
  modelId = null,
  onCaptureChart,
  placeholder = 'Ask about your positions, a symbol, a strategy or a workflow',
  className,
}: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // Mirrors `hasText` so the change handler can compare without reading state,
  // which is what keeps the re-render to the boundary crossing only.
  const hasTextRef = useRef(false)
  const [hasText, setHasText] = useState(false)

  const [attachments, setAttachments] = useState<AgentAttachment[]>([])
  // Mirrors the list so a second drop landing before React has committed the
  // first still counts what the first added.
  const attachmentsRef = useRef<AgentAttachment[]>(attachments)
  const [attachError, setAttachError] = useState<string | null>(null)
  const [webSearch, setWebSearch] = useState(true)

  // A drag entering a child fires dragleave on the parent, so the highlight is
  // counted in and out rather than toggled, or it flickers over every chip.
  const dragDepthRef = useRef(0)
  const [dragging, setDragging] = useState(false)

  const { canSee, label } = useVisionCapable(modelId)
  const visionRefusal = label
    ? `${label} cannot read images. Pick a model that supports vision to attach a file.`
    : 'This model cannot read images.'

  const total = useMemo(() => attachmentTotal(attachments), [attachments])

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

  /**
   * Take files from a pick, a drop or a paste.
   *
   * Stops at the first refusal rather than skipping past it: a drop of five
   * files where the third is too large should say so about the third, not
   * silently attach the other four and leave the operator to notice.
   */
  const addFiles = useCallback(
    async (incoming: File[]) => {
      if (incoming.length === 0) return
      if (!canSee) {
        setAttachError(visionRefusal)
        return
      }
      const accepted: AgentAttachment[] = []
      let refusal: string | null = null
      for (const file of incoming) {
        const reason = rejectReason([...attachmentsRef.current, ...accepted], file)
        if (reason) {
          refusal = reason
          break
        }
        try {
          accepted.push(await readAttachment(file))
        } catch (cause) {
          refusal = cause instanceof Error ? cause.message : 'That file could not be read.'
          break
        }
      }
      if (accepted.length > 0) {
        const next = [...attachmentsRef.current, ...accepted]
        attachmentsRef.current = next
        setAttachments(next)
      }
      setAttachError(refusal)
    },
    [canSee, visionRefusal]
  )

  const removeAttachment = useCallback((id: string) => {
    attachmentsRef.current = attachmentsRef.current.filter((item) => item.id !== id)
    setAttachments(attachmentsRef.current)
    setAttachError(null)
  }, [])

  const submit = useCallback(() => {
    const element = textareaRef.current
    if (!element || running || disabled) return
    const text = element.value.trim()
    if (!text) return

    const carried = attachmentsRef.current
    element.value = ''
    hasTextRef.current = false
    setHasText(false)
    attachmentsRef.current = []
    setAttachments([])
    setAttachError(null)
    resize()
    onSend(text, { attachments: carried, webSearch })
  }, [disabled, onSend, resize, running, webSearch])

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

  /**
   * A pasted file becomes an attachment rather than text.
   *
   * The default is prevented only when there is a file, so pasting words still
   * pastes words. A screenshot on the clipboard often carries a filename
   * alongside it, and letting the default run would drop that name into the
   * message as well as attaching the image.
   */
  const handlePaste = useCallback(
    (event: ClipboardEvent<HTMLTextAreaElement>) => {
      const files = filesFrom(event.clipboardData)
      if (files.length === 0) return
      event.preventDefault()
      void addFiles(files)
    },
    [addFiles]
  )

  const handleDragEnter = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer?.types?.includes('Files')) return
    dragDepthRef.current += 1
    setDragging(true)
  }, [])

  const handleDragLeave = useCallback(() => {
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1)
    if (dragDepthRef.current === 0) setDragging(false)
  }, [])

  const handleDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer?.types?.includes('Files')) return
    // Without this the browser navigates to the dropped file instead.
    event.preventDefault()
  }, [])

  const handleDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      dragDepthRef.current = 0
      setDragging(false)
      const files = filesFrom(event.dataTransfer)
      if (files.length === 0) return
      event.preventDefault()
      void addFiles(files)
    },
    [addFiles]
  )

  const handlePicked = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      const picked = Array.from(event.target.files ?? [])
      // Cleared so picking the same file twice in a row still fires a change.
      event.target.value = ''
      void addFiles(picked)
    },
    [addFiles]
  )

  const captureChart = useCallback(async () => {
    if (!onCaptureChart) return
    try {
      const file = await onCaptureChart()
      if (!file) {
        setAttachError('There was no chart to capture.')
        return
      }
      await addFiles([file])
    } catch (cause) {
      setAttachError(
        cause instanceof Error ? cause.message : 'The chart screenshot could not be taken.'
      )
    }
  }, [addFiles, onCaptureChart])

  return (
    <div className={cn('space-y-1.5', className)}>
      {/* A drop target, not a control: the same files go in through the menu
          item, which the keyboard reaches. */}
      <div
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        className={cn(
          'flex flex-col gap-1.5 rounded-xl border border-input bg-background p-2 shadow-xs',
          'focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/50',
          dragging && 'border-ring ring-[3px] ring-ring/50'
        )}
      >
        {attachments.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 pb-0.5">
            {attachments.map((item) => (
              <AttachmentChip
                key={item.id}
                name={item.name}
                kind={item.kind}
                size={item.size}
                src={item.dataUrl}
                onRemove={() => removeAttachment(item.id)}
              />
            ))}
            {/* What is left, not what is used: the cap is the number that
                decides whether the next file fits. */}
            <span
              className={cn(
                'text-[11px] text-muted-foreground',
                total > MAX_TOTAL_BYTES * 0.8 && 'text-destructive'
              )}
            >
              {formatBytes(total)} of {formatBytes(MAX_TOTAL_BYTES)}
            </span>
          </div>
        )}

        <textarea
          ref={textareaRef}
          rows={1}
          onInput={handleInput}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          disabled={disabled}
          placeholder={placeholder}
          aria-label="Message the agent"
          className="max-h-[200px] min-h-[24px] flex-1 resize-none bg-transparent px-1.5 py-1 text-sm leading-relaxed text-foreground outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50"
        />

        {/* Controls left, send right, both under the text. min-w-0 so a long
            model name truncates inside its own button rather than pushing the
            send control off the edge. */}
        <div className="flex items-center gap-2">
          <div className="flex min-w-0 flex-1 items-center gap-1.5">
            <DropdownMenu>
              <DropdownMenuTrigger asChild disabled={disabled}>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Add to this message"
                  title="Attach a file or change what this turn can use"
                >
                  <Plus className="h-4 w-4" aria-hidden />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="min-w-[15rem]">
                <DropdownMenuItem
                  disabled={!canSee}
                  onSelect={() => fileInputRef.current?.click()}
                  className="text-xs"
                >
                  <Paperclip className="h-3.5 w-3.5" aria-hidden />
                  Attach files
                </DropdownMenuItem>
                {/* Only where there is a chart. A menu item that cannot do its
                    one job is worse than an absent one. */}
                {onCaptureChart && (
                  <DropdownMenuItem
                    disabled={!canSee}
                    onSelect={() => void captureChart()}
                    className="text-xs"
                  >
                    <Camera className="h-3.5 w-3.5" aria-hidden />
                    Attach chart screenshot
                  </DropdownMenuItem>
                )}
                {!canSee && (
                  <p className="px-2 py-1.5 text-[11px] leading-relaxed text-muted-foreground">
                    {visionRefusal}
                  </p>
                )}
                <DropdownMenuSeparator />
                {/* A switch, not a destination: it decides whether this turn is
                    given the web search tools at all. Off is also cheaper, the
                    two schemas costing about 450 input tokens a turn. */}
                <DropdownMenuCheckboxItem
                  checked={webSearch}
                  onCheckedChange={(next) => setWebSearch(next === true)}
                  className="text-xs"
                >
                  <Globe className="h-3.5 w-3.5" aria-hidden />
                  Web search
                </DropdownMenuCheckboxItem>
              </DropdownMenuContent>
            </DropdownMenu>
            {controls}
          </div>
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

      {/* Off-screen rather than hidden: a display:none input cannot be clicked
          open by the menu item on every browser. */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept={ATTACHMENT_ACCEPT}
        onChange={handlePicked}
        aria-label="Choose files to attach"
        tabIndex={-1}
        className="sr-only"
      />

      {attachError && (
        <p className="px-1 text-[11px] text-destructive" role="alert">
          {attachError}
        </p>
      )}

      <p className="px-1 text-[11px] text-muted-foreground">
        {running ? (
          <span className="inline-flex items-center gap-1.5">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
            Running. Stop ends the turn on the server, not just here.
          </span>
        ) : attachments.length > 0 && !hasText ? (
          'A file is not a question. Say what you want done with it.'
        ) : (
          'Enter to send, Shift and Enter for a new line.'
        )}
        {!webSearch && <span className="ml-2">Web search is off for this conversation.</span>}
      </p>
    </div>
  )
}
