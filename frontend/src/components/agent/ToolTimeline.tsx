/**
 * The tool calls a turn made, as a collapsed timeline.
 *
 * A turn that reads positions, resolves a symbol and fetches a quote made three
 * calls the operator usually does not want to read, and occasionally must. So
 * the timeline is collapsed by default and its summary line still says what is
 * happening: how many calls there were, and which one is running right now.
 *
 * Each row expands to its arguments and its result. A result shaped like rows,
 * which is what most platform reads return, renders as a real table rather than
 * as JSON, because a position book read as JSON is unreadable at a glance.
 * Anything else falls back to formatted JSON.
 *
 * Nothing here is trusted as markup. Every value is rendered as text, so a tool
 * result carrying HTML or a prompt-injection payload is displayed rather than
 * interpreted.
 */

import { CheckCircle2, ChevronRight, Loader2, XCircle } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { ToolCall } from '@/api/agent'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'

/** Rows beyond this are not rendered: a timeline is a summary, not a report. */
const MAX_TABLE_ROWS = 25

/** Columns beyond this make a table unreadable, so the result stays JSON. */
const MAX_TABLE_COLUMNS = 10

/**
 * Turn a registered tool name into something a person reads.
 *
 * `get_option_chain` becomes `Get option chain`. Deliberately mechanical: a
 * hand-maintained map of display names goes stale the moment a tool is added,
 * and a tool name in this module is already written to be read.
 *
 * @param name - The tool's registered name.
 * @returns The name with separators replaced and the first letter capitalised.
 */
export function humanizeToolName(name: string): string {
  const words = name.replace(/[_-]+/g, ' ').trim()
  if (!words) return 'Tool call'
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/**
 * Render a duration the way a timeline should: short, and never false.
 *
 * @param duration - Wall clock seconds, or null when the call was not measured.
 * @returns A compact duration, or an empty string when there is nothing to say.
 */
function formatDuration(duration: number | null | undefined): string {
  if (typeof duration !== 'number' || !Number.isFinite(duration) || duration < 0) return ''
  if (duration < 1) return `${Math.round(duration * 1000)} ms`
  return `${duration.toFixed(duration < 10 ? 2 : 1)} s`
}

/**
 * Format any value as JSON without ever throwing into a render.
 *
 * A tool result reaches here after the server has already made it JSON safe,
 * but a circular structure assembled client side would still take the whole
 * message down, and a stack trace instead of an answer is the worse outcome.
 */
function toJsonText(value: unknown): string {
  try {
    const text = JSON.stringify(value, null, 2)
    return typeof text === 'string' ? text : String(value)
  } catch {
    return String(value)
  }
}

/** Render one cell as text. Never as markup, and never as `[object Object]`. */
function cellText(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return toJsonText(value)
}

type ResultRow = Record<string, unknown>

function isPlainRow(value: unknown): value is ResultRow {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/**
 * Find the rows in a tool result, if it has any.
 *
 * Two shapes count: an array of objects, and the platform's usual envelope of
 * an object with a single array under `data`. Anything else is not row shaped
 * and renders as JSON.
 *
 * @param result - The tool's return value.
 * @returns The rows, or null when the result is not row shaped.
 */
function asRows(result: unknown): ResultRow[] | null {
  const candidate =
    Array.isArray(result) ||
    (isPlainRow(result) && Array.isArray((result as { data?: unknown }).data))
      ? Array.isArray(result)
        ? result
        : ((result as { data: unknown[] }).data as unknown[])
      : null

  if (!candidate || candidate.length === 0) return null
  if (!candidate.every(isPlainRow)) return null

  const columns = new Set<string>()
  for (const row of candidate.slice(0, MAX_TABLE_ROWS)) {
    for (const key of Object.keys(row)) columns.add(key)
  }
  if (columns.size === 0 || columns.size > MAX_TABLE_COLUMNS) return null

  return candidate as ResultRow[]
}

/** Column order is first seen order, which is the order the tool chose. */
function columnsOf(rows: readonly ResultRow[]): string[] {
  const columns: string[] = []
  for (const row of rows.slice(0, MAX_TABLE_ROWS)) {
    for (const key of Object.keys(row)) {
      if (!columns.includes(key)) columns.push(key)
    }
  }
  return columns
}

function ResultTable({ rows }: { rows: readonly ResultRow[] }) {
  const columns = useMemo(() => columnsOf(rows), [rows])
  const shown = rows.slice(0, MAX_TABLE_ROWS)

  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <Table className="text-xs">
        <TableHeader>
          <TableRow className="bg-muted/50">
            {columns.map((column) => (
              <TableHead key={column} className="h-8 px-2 text-[11px] font-medium">
                {column}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {shown.map((row, index) => (
            <TableRow key={`${index}-${cellText(row[columns[0]])}`}>
              {columns.map((column) => (
                <TableCell key={column} className="px-2 py-1 text-[11px]">
                  {cellText(row[column])}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {rows.length > shown.length && (
        <p className="border-t border-border px-2 py-1 text-[11px] text-muted-foreground">
          Showing {shown.length} of {rows.length} rows.
        </p>
      )}
    </div>
  )
}

function JsonBlock({ value, label }: { value: unknown; label: string }) {
  return (
    <div className="space-y-1">
      <p className="text-[11px] font-medium text-muted-foreground">{label}</p>
      <pre className="max-h-64 overflow-auto rounded-md border border-border bg-muted/40 p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words text-foreground">
        {toJsonText(value)}
      </pre>
    </div>
  )
}

function StatusIcon({ tool }: { tool: ToolCall }) {
  if (tool.ok === undefined) {
    return (
      <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" aria-hidden />
    )
  }
  if (tool.ok) {
    return (
      <CheckCircle2
        className="h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-500"
        aria-hidden
      />
    )
  }
  return <XCircle className="h-3.5 w-3.5 shrink-0 text-red-600 dark:text-red-500" aria-hidden />
}

function ToolRow({ tool }: { tool: ToolCall }) {
  const [open, setOpen] = useState(false)
  const rows = useMemo(
    () => (tool.ok === false ? null : asRows(tool.result)),
    [tool.ok, tool.result]
  )
  const duration = formatDuration(tool.duration)
  const hasArgs = tool.args !== undefined && Object.keys(tool.args).length > 0
  const hasResult = tool.result !== undefined && tool.result !== null

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-muted/60">
        <ChevronRight
          className={cn(
            'h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform',
            open && 'rotate-90'
          )}
          aria-hidden
        />
        <StatusIcon tool={tool} />
        <span className="truncate font-medium text-foreground">{humanizeToolName(tool.name)}</span>
        {tool.ok === false && (
          <span className="shrink-0 text-[11px] text-red-600 dark:text-red-500">failed</span>
        )}
        <span className="ml-auto shrink-0 tabular-nums text-[11px] text-muted-foreground">
          {duration}
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="space-y-2 px-2 pt-1 pb-3 pl-9">
          {hasArgs ? (
            <JsonBlock value={tool.args} label="Arguments" />
          ) : (
            <p className="text-[11px] text-muted-foreground">No arguments.</p>
          )}
          {rows ? (
            <div className="space-y-1">
              <p className="text-[11px] font-medium text-muted-foreground">Result</p>
              <ResultTable rows={rows} />
            </div>
          ) : hasResult ? (
            <JsonBlock value={tool.result} label="Result" />
          ) : tool.ok === undefined ? (
            <p className="text-[11px] text-muted-foreground">Running.</p>
          ) : (
            <p className="text-[11px] text-muted-foreground">No result returned.</p>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

export interface ToolTimelineProps {
  tools: readonly ToolCall[]
  className?: string
}

/**
 * The turn's tool calls, collapsed.
 *
 * @param tools - In dispatch order. A call with no `ok` is still running.
 */
export function ToolTimeline({ tools, className }: ToolTimelineProps) {
  const [open, setOpen] = useState(false)
  if (tools.length === 0) return null

  const running = tools.find((tool) => tool.ok === undefined)
  const failed = tools.filter((tool) => tool.ok === false).length
  const label = running
    ? humanizeToolName(running.name)
    : `${tools.length} tool call${tools.length === 1 ? '' : 's'}`

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className={cn('rounded-lg border border-border bg-muted/30', className)}
    >
      <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors hover:bg-muted/60">
        <ChevronRight
          className={cn(
            'h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform',
            open && 'rotate-90'
          )}
          aria-hidden
        />
        {running ? (
          <Loader2
            className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground"
            aria-hidden
          />
        ) : failed > 0 ? (
          <XCircle className="h-3.5 w-3.5 shrink-0 text-red-600 dark:text-red-500" aria-hidden />
        ) : (
          <CheckCircle2
            className="h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-500"
            aria-hidden
          />
        )}
        <span className="truncate text-muted-foreground">{label}</span>
        {!running && failed > 0 && (
          <span className="shrink-0 text-[11px] text-red-600 dark:text-red-500">
            {failed} failed
          </span>
        )}
        {!open && !running && tools.length > 1 && (
          <span className="ml-auto shrink-0 text-[11px] text-muted-foreground">details</span>
        )}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="border-t border-border p-1">
          {tools.map((tool) => (
            <ToolRow key={tool.id} tool={tool} />
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
