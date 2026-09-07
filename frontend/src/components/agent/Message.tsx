/**
 * One turn in the agent conversation.
 *
 * A user turn is a right-aligned bubble, because it is a short thing the
 * operator said and the shape is what makes a thread readable at a glance. An
 * assistant turn renders inline with no bubble: the answer is the page rather
 * than a card sitting on it, and wrapping a three-hundred-line strategy in a
 * chat bubble makes it look like an attachment instead of the artifact it is.
 *
 * Security, and neither of these is optional
 * ------------------------------------------
 *
 * The model is untrusted input. It reads tool output, symbol names and broker
 * rejection text, any of which can carry someone else's instructions, so what
 * it emits is rendered and never interpreted:
 *
 * - **`skipHtml`, and no `rehype-raw`.** Raw HTML is never parsed into
 *   elements, so there is no allowlist to get subtly wrong. `rehype-sanitize`
 *   is deliberately absent too: nothing is being sanitised because nothing is
 *   being parsed.
 * - **`img: () => null`.** Markdown images are blocked outright, not just raw
 *   `<img>` tags. An image URL is an exfiltration channel: a model steered by
 *   injected content embeds a secret in a URL and the browser fetches it to
 *   the attacker's host without anybody clicking anything. This module feeds
 *   tool output back into the context, so it is exposed to exactly that.
 *
 * Streaming, and why the fence matters
 * ------------------------------------
 *
 * A code artifact is not re-highlighted per token. While its fence is still
 * open the block renders as plain monospace text, and CodeMirror mounts only
 * once the block closes. Highlighting a half-written file on every token is
 * wasted work and it visibly flickers, so the message is split at the start of
 * the unterminated fence: everything before it is finished markdown, and the
 * tail is the artifact still being written.
 *
 * Visualizations, and why they are not simply appended
 * ----------------------------------------------------
 *
 * A turn can draw more than once, and the answer usually reads as "here is the
 * chart, and here is what it says". Each entry of `message.viz` records how
 * much prose had been written when it arrived, so the prose is cut at those
 * offsets and the blocks go back where the model drew them. Stacking every
 * chart after the answer would put the third one's commentary above it.
 *
 * The cut is taken inside the finished markdown only. An anchor past the start
 * of an open fence is clamped to it, so a chart that landed while a code block
 * was still being written appears just before that block rather than splitting
 * it in half and leaving markdown to parse two unterminated fences.
 */

import { ChevronRight } from 'lucide-react'
import { type ComponentProps, Fragment, memo, useCallback, useMemo, useState } from 'react'
import Markdown, { type Components, type ExtraProps } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ConfirmRequirement } from '@/api/agent'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import type { AgentMessage } from '@/lib/agent/useAgentStream'
import type { AgentVizItem } from '@/lib/agent/viz'
import { cn } from '@/lib/utils'
import { AttachmentChip } from './AttachmentChip'
import { CodeArtifact } from './CodeArtifact'
import { MessageActions } from './MessageActions'
import { MessageEditor } from './MessageEditor'
import { ToolTimeline } from './ToolTimeline'
import { UsageBadge } from './UsageBadge'
import { VizBlock } from './viz/VizBlock'

// ---------------------------------------------------------------------------
// Markdown
// ---------------------------------------------------------------------------

function CodeRenderer({ className, children }: ComponentProps<'code'> & ExtraProps) {
  const text = String(children ?? '')
  const language = /language-([\w+#-]+)/.exec(className ?? '')?.[1] ?? null
  // react-markdown routes fenced blocks and inline spans through the same
  // component. A fence carries a language class, or, with no info string, at
  // least one newline; an inline span has neither.
  const isBlock = language !== null || text.includes('\n')

  if (!isBlock) {
    return (
      <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em] text-foreground">
        {children}
      </code>
    )
  }
  return <CodeArtifact code={text.replace(/\n$/, '')} language={language} />
}

const MARKDOWN_COMPONENTS: Components = {
  // See the module docstring. Blocking markdown images, not only raw <img>,
  // is what closes the exfiltration channel; do not soften this to a filter.
  img: () => null,
  // The artifact is a block element and cannot legally live inside a <pre>,
  // so the <pre> is unwrapped and the code component renders the whole thing.
  pre: ({ children }) => <>{children}</>,
  code: CodeRenderer,
  a: ({ children, href }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-primary underline underline-offset-2 hover:no-underline"
    >
      {children}
    </a>
  ),
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-md border border-border">
      <table className="w-full text-xs">{children}</table>
    </div>
  ),
}

const PROSE_CLASSES = cn(
  'text-sm leading-relaxed text-foreground break-words',
  '[&>*:first-child]:mt-0 [&>*:last-child]:mb-0',
  '[&_p]:my-3',
  '[&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-5',
  '[&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-5',
  '[&_li]:my-1',
  '[&_h1]:mt-5 [&_h1]:mb-2 [&_h1]:text-base [&_h1]:font-semibold',
  '[&_h2]:mt-5 [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-semibold',
  '[&_h3]:mt-4 [&_h3]:mb-2 [&_h3]:text-sm [&_h3]:font-semibold',
  '[&_h4]:mt-4 [&_h4]:mb-2 [&_h4]:text-sm [&_h4]:font-semibold',
  '[&_strong]:font-semibold [&_em]:italic',
  '[&_blockquote]:my-3 [&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground',
  '[&_hr]:my-4 [&_hr]:border-border',
  '[&_th]:border-b [&_th]:border-border [&_th]:bg-muted/50 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-medium',
  '[&_td]:border-b [&_td]:border-border [&_td]:px-2 [&_td]:py-1',
  '[&_tr:last-child_td]:border-b-0'
)

/**
 * Markdown prose, memoized on the text so a re-render that changed nothing else
 * does not re-parse the answer.
 */
const Prose = memo(function Prose({ text }: { text: string }) {
  if (!text) return null
  return (
    <div className={PROSE_CLASSES}>
      <Markdown remarkPlugins={[remarkGfm]} skipHtml components={MARKDOWN_COMPONENTS}>
        {text}
      </Markdown>
    </div>
  )
})

// ---------------------------------------------------------------------------
// Splitting a streaming answer at its open fence
// ---------------------------------------------------------------------------

interface FenceSplit {
  /** Everything up to the unterminated fence. Complete markdown. */
  closed: string
  /** The open fence's info string, or null when there is no open fence. */
  openLanguage: string | null
  /** The code written so far inside the open fence. */
  openCode: string
  hasOpenFence: boolean
}

const FENCE_LINE = /^ {0,3}(`{3,}|~{3,})(.*)$/

/**
 * Split a message at the start of a fence that has not closed yet.
 *
 * This is what keeps a streaming artifact out of the markdown parser until it
 * is finished. The prefix is stable, complete markdown that parses to the same
 * tree on every flush; the tail is the block still being written.
 *
 * @param text - The accumulated assistant prose.
 * @returns The finished prefix, and the open block if there is one.
 */
export function splitAtOpenFence(text: string): FenceSplit {
  const lines = text.split('\n')
  let fenceStart = -1
  let marker = ''

  for (let index = 0; index < lines.length; index += 1) {
    const match = FENCE_LINE.exec(lines[index])
    if (!match) continue
    if (fenceStart < 0) {
      fenceStart = index
      marker = match[1]
      continue
    }
    // A closer uses the same character, is at least as long, and names no
    // language. Anything else inside a fence is content, including a fence
    // drawn with the other character.
    const closes =
      match[1][0] === marker[0] && match[1].length >= marker.length && match[2].trim() === ''
    if (closes) {
      fenceStart = -1
      marker = ''
    }
  }

  if (fenceStart < 0) {
    return { closed: text, openLanguage: null, openCode: '', hasOpenFence: false }
  }

  const info = FENCE_LINE.exec(lines[fenceStart])?.[2] ?? ''
  const language = info.trim().split(/\s+/)[0] || null
  return {
    closed: lines.slice(0, fenceStart).join('\n'),
    openLanguage: language,
    openCode: lines.slice(fenceStart + 1).join('\n'),
    hasOpenFence: true,
  }
}

// ---------------------------------------------------------------------------
// Interleaving the visualizations with the prose
// ---------------------------------------------------------------------------

/** One prose run and the visualization that follows it, if any. */
interface TurnPart {
  key: string
  /** Finished markdown. Empty when two blocks arrived with nothing between. */
  text: string
  viz: AgentVizItem | null
}

/**
 * Cut the finished prose at each visualization's anchor.
 *
 * The anchors are non-decreasing because prose only grows, but they are read
 * off the wire, so each one is clamped forward to the previous cut and back to
 * the end of the finished markdown. That keeps the parts in order whatever the
 * offsets say, and keeps every cut outside an open code fence.
 *
 * @param prose - The finished markdown, before any unterminated fence.
 * @param viz - The turn's visualizations, in arrival order.
 * @returns The parts, in render order. Each prose run keeps a stable key, so
 *   a flush that appended one token re-parses the tail and nothing else.
 */
export function splitByViz(prose: string, viz: readonly AgentVizItem[]): TurnPart[] {
  if (viz.length === 0) {
    return prose ? [{ key: 'prose-0', text: prose, viz: null }] : []
  }

  const parts: TurnPart[] = []
  let cursor = 0
  viz.forEach((item, index) => {
    const at = Math.min(Math.max(item.at, cursor), prose.length)
    parts.push({ key: `viz-${index}`, text: prose.slice(cursor, at), viz: item })
    cursor = at
  })

  const tail = prose.slice(cursor)
  if (tail) parts.push({ key: 'prose-tail', text: tail, viz: null })
  return parts
}

// ---------------------------------------------------------------------------
// Turn parts
// ---------------------------------------------------------------------------

function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-2 py-1 text-xs text-muted-foreground">
      <span className="flex gap-1" aria-hidden>
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground/70 [animation-delay:0ms]" />
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground/70 [animation-delay:200ms]" />
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground/70 [animation-delay:400ms]" />
      </span>
      <span>Thinking</span>
    </div>
  )
}

function Reasoning({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  if (!text) return null

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className="rounded-lg border border-border bg-muted/30"
    >
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs text-muted-foreground transition-colors hover:bg-muted/60">
        <ChevronRight
          className={cn('h-3.5 w-3.5 shrink-0 transition-transform', open && 'rotate-90')}
          aria-hidden
        />
        Reasoning
      </CollapsibleTrigger>
      <CollapsibleContent>
        <p className="border-t border-border px-3 py-2 text-xs leading-relaxed whitespace-pre-wrap break-words text-muted-foreground">
          {text}
        </p>
      </CollapsibleContent>
    </Collapsible>
  )
}

const NOTICE_CLASSES: Record<string, string> = {
  info: 'border-border bg-muted/40 text-muted-foreground',
  warning:
    'border-amber-500/60 bg-amber-50 text-amber-900 dark:border-amber-600/60 dark:bg-amber-950/40 dark:text-amber-200',
  error:
    'border-red-500/60 bg-red-50 text-red-900 dark:border-red-600/60 dark:bg-red-950/40 dark:text-red-200',
}

function Notices({ notices }: { notices: AgentMessage['notices'] }) {
  if (notices.length === 0) return null
  return (
    <div className="space-y-1.5">
      {notices.map((notice, index) => (
        <p
          key={`${notice.level}-${index}-${notice.message.slice(0, 24)}`}
          className={cn(
            'rounded-md border px-2.5 py-1.5 text-xs leading-relaxed',
            NOTICE_CLASSES[notice.level] ?? NOTICE_CLASSES.info
          )}
        >
          {notice.message}
        </p>
      ))}
    </div>
  )
}

/**
 * The approval prompt for a run that paused on a mutating tool call.
 *
 * The stream ends on a confirm frame with no done frame, so without this the
 * run is parked with nothing able to release it. Approving here is only a
 * decision: the risk guard still runs inside the tool body afterwards, reads no
 * prompt, and can still refuse.
 */
function PendingConfirm({
  pending,
  onConfirm,
}: {
  pending: NonNullable<AgentMessage['pending']>
  onConfirm: (decisions: Record<string, boolean>) => void
}) {
  const decide = useCallback(
    (approved: boolean) => {
      const decisions: Record<string, boolean> = {}
      for (const requirement of pending.requirements) {
        decisions[requirement.id || requirement.tool_call_id] = approved
      }
      onConfirm(decisions)
    },
    [onConfirm, pending.requirements]
  )

  return (
    <div className="space-y-2 rounded-lg border border-amber-500/60 bg-amber-50 p-3 dark:border-amber-600/60 dark:bg-amber-950/40">
      <p className="text-xs font-medium text-amber-900 dark:text-amber-200">
        This turn is waiting for your approval.
      </p>
      <ul className="space-y-1">
        {pending.requirements.map((requirement: ConfirmRequirement) => (
          <li
            key={requirement.id || requirement.tool_call_id}
            className="rounded-md border border-amber-500/40 bg-background/60 p-2 dark:border-amber-600/40"
          >
            <p className="text-xs font-medium text-foreground">{requirement.tool_name}</p>
            <pre className="mt-1 max-h-40 overflow-auto font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words text-muted-foreground">
              {JSON.stringify(requirement.args ?? {}, null, 2)}
            </pre>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Button type="button" size="sm" onClick={() => decide(true)}>
          Approve
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={() => decide(false)}>
          Reject
        </Button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// The message
// ---------------------------------------------------------------------------

export interface MessageProps {
  message: AgentMessage
  /** Resume a paused run. Omitted where the surface cannot approve anything. */
  onConfirm?: (decisions: Record<string, boolean>) => void
  /**
   * Replace this question and discard everything after it. Omitted where the
   * surface cannot edit, and while a turn is streaming.
   */
  onEdit?: (messageId: string, text: string) => void
  /** Ask the last question again. Offered on a turn that failed. */
  onRetry?: () => void
  /** True while any turn is streaming. Editing mid-run would race the answer. */
  busy?: boolean
  className?: string
}

/**
 * Render one turn.
 *
 * @param message - The turn, live or rehydrated from a stored conversation.
 */
export const Message = memo(function Message({
  message,
  onConfirm,
  onEdit,
  onRetry,
  busy = false,
  className,
}: MessageProps) {
  const [editing, setEditing] = useState(false)
  const split = useMemo(
    () => (message.role === 'assistant' ? splitAtOpenFence(message.content) : null),
    [message.role, message.content]
  )
  const parts = useMemo(
    () => splitByViz(split?.closed ?? '', message.viz),
    [split?.closed, message.viz]
  )

  if (message.role === 'user') {
    if (editing && onEdit) {
      // Full width while editing. The bubble is right-aligned and capped at
      // 85%, which is right for reading and cramped for writing.
      return (
        <div className={cn('flex justify-end', className)} data-message-id={message.id}>
          <MessageEditor
            value={message.content}
            onCancel={() => setEditing(false)}
            onSend={(text) => {
              setEditing(false)
              onEdit(message.id, text)
            }}
            className="w-full"
          />
        </div>
      )
    }

    return (
      <div
        className={cn('group flex flex-col items-end gap-1', className)}
        data-message-id={message.id}
      >
        {/* Above the bubble, because a file is context for the question rather
            than part of it. There is no image to show: the server records what
            a file was and never its bytes. */}
        {message.attachments.length > 0 && (
          <div className="flex max-w-[85%] flex-wrap justify-end gap-1.5">
            {message.attachments.map((item) => (
              <AttachmentChip
                key={`${item.name}-${item.size}`}
                name={item.name}
                kind={item.kind}
                size={item.size}
              />
            ))}
          </div>
        )}
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words text-primary-foreground">
          {message.content}
        </div>
        <MessageActions
          text={message.content}
          onEdit={onEdit ? () => setEditing(true) : undefined}
          disabled={busy}
        />
      </div>
    )
  }

  const empty =
    !message.content && !message.reasoning && message.tools.length === 0 && message.viz.length === 0

  return (
    <div className={cn('group space-y-3', className)} data-message-id={message.id}>
      {message.reasoning && <Reasoning text={message.reasoning} />}
      {message.tools.length > 0 && <ToolTimeline tools={message.tools} />}
      {/* Fragments, not wrappers: the turn's `space-y-3` spaces DOM children,
          so a div per part would move every gap one level down. */}
      {parts.map((part) => (
        <Fragment key={part.key}>
          {part.text ? <Prose text={part.text} /> : null}
          {part.viz ? <VizBlock item={part.viz} streaming={message.streaming} /> : null}
        </Fragment>
      ))}
      {split?.hasOpenFence && (
        <CodeArtifact code={split.openCode} language={split.openLanguage} streaming />
      )}
      {message.streaming && empty && <ThinkingIndicator />}
      <Notices notices={message.notices} />
      {message.pending && onConfirm && (
        <PendingConfirm pending={message.pending} onConfirm={onConfirm} />
      )}
      {message.usage && <UsageBadge usage={message.usage} />}
      {/* Actions last, so they sit under the answer rather than over it. Not
          offered mid-stream: copying half an answer is rarely what was meant. */}
      {!message.streaming && (
        <MessageActions text={message.content} onRetry={onRetry} disabled={busy} />
      )}
    </div>
  )
})
