/**
 * Floating properties bar for the selected drawing: what it is, its colour,
 * thickness and dash, fill, extension, levels, order, duplicate, lock, hide
 * and delete. Appears on selection and disappears with it.
 *
 * It floats over the plot beside the selection, above it when there is room
 * and below it when there is not, and never takes a row from the chart. One
 * row at every pane width: in a narrow pane (an eight-chart grid) the less
 * used controls move into More, decided by a container query on the chart
 * area, so the bar measures the pane it sits in rather than the window.
 *
 * Lives inside the pane rather than being portalled, so it stays visible in
 * full screen where only the fullscreen element and its descendants paint.
 */
import {
  BringToFront,
  CopyPlus,
  Ellipsis,
  EyeOff,
  Lock,
  MoveHorizontal,
  PaintBucket,
  Rows3,
  SendToBack,
} from 'lucide-react'
import type { FibLevel } from 'openalgo-charts/draw'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { DrawLevels } from '@/lib/trading/drawingActions'
import type { DrawSelection } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'
import { DrawingLevelsEditor } from './DrawingLevelsEditor'

export interface DrawStylePatch {
  color?: string
  lineWidth?: number
  lineStyle?: 'solid' | 'dashed' | 'dotted'
  locked?: boolean
}

interface Props {
  sel: DrawSelection | null
  onStyle(patch: DrawStylePatch): void
  /** Settings by path, for the controls a tool may not have (fill, extend, labels). */
  onSettings(values: Record<string, unknown>): void
  onDelete(): void
  /** Edit the content of a text-bearing drawing. */
  onEditText(): void
  onDuplicate(): void
  onOrder(where: 'front' | 'back'): void
  onHide(): void
  /** The selection's levels, read when the editor opens. */
  readLevels(): DrawLevels | null
  onLevels(levels: FibLevel[]): void
}

const SWATCHES = [
  '#4f8cff',
  '#26a69a',
  '#ef5350',
  '#f5a623',
  '#ab47bc',
  '#26c6da',
  '#9aa0b4',
  '#ffffff',
]
const WIDTHS = [1, 1.5, 2, 3, 4]
const DASHES: { value: 'solid' | 'dashed' | 'dotted'; label: string }[] = [
  { value: 'solid', label: '──' },
  { value: 'dashed', label: '- -' },
  { value: 'dotted', label: '···' },
]

type Panel = 'color' | 'width' | 'dash' | 'fill' | 'extend' | 'levels' | 'more'

/** Gap between the selection and the bar, and between the bar and the pane edge. */
const GAP = 10
const EDGE = 6
/** The time axis under the plot, which the bar must not cover. */
const AXIS = 28

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max)

/**
 * Where the bar goes: centred over the selection, above it, else below it,
 * else at the top of the pane, and always inside the pane.
 */
export function placeBar(
  box: DrawSelection['box'],
  pane: { width: number; height: number },
  bar: { width: number; height: number }
): { left: number; top: number } {
  let left = (pane.width - bar.width) / 2
  let top = EDGE
  if (box) {
    left = (box.left + box.right) / 2 - bar.width / 2
    if (box.top - GAP - bar.height >= EDGE) top = box.top - GAP - bar.height
    else if (box.bottom + GAP + bar.height <= pane.height - AXIS) top = box.bottom + GAP
  }
  return {
    left: clamp(left, EDGE, Math.max(EDGE, pane.width - bar.width - EDGE)),
    top: clamp(top, EDGE, Math.max(EDGE, pane.height - AXIS - bar.height)),
  }
}

export function DrawingStyleBar({
  sel,
  onStyle,
  onSettings,
  onDelete,
  onEditText,
  onDuplicate,
  onOrder,
  onHide,
  readLevels,
  onLevels,
}: Props) {
  const [open, setOpen] = useState<Panel | null>(null)
  const [levels, setLevels] = useState<DrawLevels | null>(null)
  const [pos, setPos] = useState<{ left: number; top: number; upward: boolean } | null>(null)
  /** The fill opacity while its slider is held, before it is written. */
  const [opacity, setOpacity] = useState<number | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  // A new selection closes whatever was open for the old one.
  const selId = sel?.id ?? null
  // biome-ignore lint/correctness/useExhaustiveDependencies: the selection id is the trigger
  useEffect(() => setOpen(null), [selId])
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(null)
    }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [open])

  // Placed once per selection change, before paint. Not on every pointer move:
  // the bar is a DOM element and the chart repaints far more often than this.
  useLayoutEffect(() => {
    const bar = ref.current
    const pane = bar?.parentElement
    if (!sel || !bar || !pane) return
    const at = placeBar(
      sel.box,
      { width: pane.clientWidth, height: pane.clientHeight },
      { width: bar.offsetWidth, height: bar.offsetHeight }
    )
    // In the lower half of the pane a panel opens upward, so it is not cut off.
    setPos({ ...at, upward: at.top > pane.clientHeight / 2 })
  }, [sel])

  if (!sel) return null

  const toggle = (panel: Panel) => {
    if (panel === 'levels' && open !== 'levels') setLevels(readLevels())
    setOpen(open === panel ? null : panel)
  }
  const btn =
    'flex h-7 shrink-0 items-center justify-center gap-1 rounded px-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground'
  const row =
    'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-xs hover:bg-accent'
  // The less used controls: on the bar in a wide pane, in More in a narrow one.
  const wide = 'hidden @lg:flex'
  const narrow = '@lg:hidden'
  const sep = 'mx-0.5 h-5 w-px shrink-0 bg-border'
  const panel = cn(
    'absolute left-0 z-10 rounded-md border bg-popover p-1 shadow-lg',
    pos?.upward ? 'bottom-full mb-1' : 'top-full mt-1'
  )
  const commitOpacity = () => {
    if (opacity !== null) onSettings({ 'style.fillOpacity': opacity / 100 })
    setOpacity(null)
  }

  return (
    <div
      ref={ref}
      role="toolbar"
      aria-label={`${sel.name} properties`}
      className="absolute z-30 flex items-center gap-0.5 rounded-lg border bg-background/95 p-1 shadow-lg backdrop-blur"
      style={pos ? { left: pos.left, top: pos.top } : { left: 0, top: 0, visibility: 'hidden' }}
    >
      <span className="hidden max-w-[9rem] truncate px-1.5 text-xs font-medium @xl:block">
        {sel.name}
      </span>
      <div className={cn(sep, 'hidden @xl:block')} />

      <button
        type="button"
        title="Colour"
        aria-label="Colour"
        onClick={() => toggle('color')}
        className={btn}
      >
        <span
          className="h-4 w-4 rounded-sm border border-border"
          style={{ background: sel.color }}
        />
      </button>
      <button
        type="button"
        title="Thickness"
        aria-label="Thickness"
        onClick={() => toggle('width')}
        className={btn}
      >
        <span className="text-xs font-medium">{sel.lineWidth}px</span>
      </button>
      <button
        type="button"
        title="Line style"
        aria-label="Line style"
        onClick={() => toggle('dash')}
        className={btn}
      >
        <span className="text-xs">
          {DASHES.find((d) => d.value === sel.lineStyle)?.label ?? '──'}
        </span>
      </button>

      {sel.fill && (
        <button
          type="button"
          title="Fill"
          aria-label="Fill"
          onClick={() => toggle('fill')}
          className={cn(btn, wide, sel.fill.on && 'text-foreground')}
        >
          <PaintBucket className="h-4 w-4" strokeWidth={1.6} />
        </button>
      )}
      {sel.extend && (
        <button
          type="button"
          title="Extend"
          aria-label="Extend"
          onClick={() => toggle('extend')}
          className={cn(btn, wide, (sel.extend.left || sel.extend.right) && 'text-primary')}
        >
          <MoveHorizontal className="h-4 w-4" strokeWidth={1.6} />
        </button>
      )}
      {sel.levels && (
        <button
          type="button"
          title="Levels"
          aria-label="Levels"
          onClick={() => toggle('levels')}
          className={cn(btn, wide)}
        >
          <Rows3 className="h-4 w-4" strokeWidth={1.6} />
        </button>
      )}
      {sel.hasText && (
        <button
          type="button"
          title="Edit text"
          aria-label="Edit text"
          onClick={onEditText}
          className={cn(btn, wide)}
        >
          <svg
            viewBox="0 0 24 24"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.7}
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M5 5.5h14M12 5.5V19" />
          </svg>
        </button>
      )}

      <div className={sep} />

      <button
        type="button"
        title={sel.locked ? 'Unlock' : 'Lock'}
        aria-label={sel.locked ? 'Unlock drawing' : 'Lock drawing'}
        onClick={() => onStyle({ locked: !sel.locked })}
        className={cn(btn, wide, sel.locked && 'text-primary')}
      >
        <svg
          viewBox="0 0 24 24"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.7}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <rect x="4.5" y="10.5" width="15" height="9.5" rx="2" />
          {sel.locked ? (
            <path d="M8 10.5V7a4 4 0 0 1 8 0v3.5" />
          ) : (
            <path d="M8 10.5V7a4 4 0 0 1 7.6-1.7" />
          )}
        </svg>
      </button>
      <button
        type="button"
        title="Delete"
        aria-label="Delete drawing"
        onClick={onDelete}
        className={btn}
      >
        <svg
          viewBox="0 0 24 24"
          className="h-4 w-4"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.7}
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M3.5 6.5h17M9.5 6.5v-3h5v3M6 6.5l1 14h10l1-14" />
        </svg>
      </button>
      <button
        type="button"
        title="More"
        aria-label="More drawing actions"
        aria-expanded={open === 'more'}
        onClick={() => toggle('more')}
        className={btn}
      >
        <Ellipsis className="h-4 w-4" strokeWidth={1.6} />
      </button>

      {open === 'color' && (
        <div className={cn(panel, 'grid w-40 grid-cols-4 gap-1 p-2')}>
          {SWATCHES.map((c) => (
            <button
              type="button"
              key={c}
              aria-label={c}
              onClick={() => {
                onStyle({ color: c })
                setOpen(null)
              }}
              style={{ background: c }}
              className={cn(
                'h-6 w-6 rounded border',
                c === sel.color ? 'ring-2 ring-primary' : 'border-border'
              )}
            />
          ))}
        </div>
      )}

      {open === 'width' && (
        <div className={cn(panel, 'w-24')}>
          {WIDTHS.map((w) => (
            <button
              type="button"
              key={w}
              onClick={() => {
                onStyle({ lineWidth: w })
                setOpen(null)
              }}
              className={cn(row, 'py-1', w === sel.lineWidth && 'text-primary')}
            >
              <span className="w-8 rounded bg-current" style={{ height: w }} />
              {w}px
            </button>
          ))}
        </div>
      )}

      {open === 'dash' && (
        <div className={cn(panel, 'w-24')}>
          {DASHES.map((d) => (
            <button
              type="button"
              key={d.value}
              onClick={() => {
                onStyle({ lineStyle: d.value })
                setOpen(null)
              }}
              className={cn(row, 'py-1', d.value === sel.lineStyle && 'text-primary')}
            >
              {d.label} {d.value}
            </button>
          ))}
        </div>
      )}

      {open === 'fill' && sel.fill && (
        <div className={cn(panel, 'w-44 p-2')}>
          <label className="mb-2 flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={sel.fill.on}
              onChange={(e) => onSettings({ 'style.fill': e.target.checked })}
            />
            Fill
          </label>
          <div className="mb-2 grid grid-cols-4 gap-1">
            {SWATCHES.map((c) => (
              <button
                type="button"
                key={c}
                aria-label={`Fill ${c}`}
                onClick={() => onSettings({ 'style.fill': true, 'style.fillColor': c })}
                style={{ background: c }}
                className={cn(
                  'h-6 w-6 rounded border',
                  sel.fill?.on && c === sel.fill.color ? 'ring-2 ring-primary' : 'border-border'
                )}
              />
            ))}
          </div>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            Opacity
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              aria-label="Fill opacity"
              value={opacity ?? Math.round(sel.fill.opacity * 100)}
              onChange={(e) => setOpacity(Number(e.target.value))}
              // Written when the slider is let go: one undo step per change,
              // not one per pixel of the drag.
              onPointerUp={commitOpacity}
              onKeyUp={commitOpacity}
              className="min-w-0 flex-1"
            />
            <span className="w-8 text-right tabular-nums">
              {opacity ?? Math.round(sel.fill.opacity * 100)}%
            </span>
          </label>
        </div>
      )}

      {open === 'extend' && sel.extend && (
        <div className={cn(panel, 'w-36 p-2')}>
          <label className="mb-1.5 flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={sel.extend.left}
              onChange={(e) => onSettings({ 'style.extendLeft': e.target.checked })}
            />
            Extend left
          </label>
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={sel.extend.right}
              onChange={(e) => onSettings({ 'style.extendRight': e.target.checked })}
            />
            Extend right
          </label>
        </div>
      )}

      {open === 'levels' && levels && (
        <div className={cn(panel, 'p-2')}>
          <DrawingLevelsEditor
            levels={levels}
            onChange={onLevels}
            onLabels={(on) => onSettings({ 'style.showLabels': on })}
          />
        </div>
      )}

      {open === 'more' && (
        <div className={cn(panel, 'left-auto right-0 w-48')}>
          <div className="truncate px-2 pb-1 pt-0.5 text-[11px] font-medium text-muted-foreground @xl:hidden">
            {sel.name}
          </div>
          {sel.fill && (
            <button type="button" className={cn(row, narrow)} onClick={() => setOpen('fill')}>
              <PaintBucket className="h-3.5 w-3.5 opacity-70" />
              Fill...
            </button>
          )}
          {sel.extend && (
            <button type="button" className={cn(row, narrow)} onClick={() => setOpen('extend')}>
              <MoveHorizontal className="h-3.5 w-3.5 opacity-70" />
              Extend...
            </button>
          )}
          {sel.levels && (
            <button type="button" className={cn(row, narrow)} onClick={() => toggle('levels')}>
              <Rows3 className="h-3.5 w-3.5 opacity-70" />
              Levels...
            </button>
          )}
          {sel.hasText && (
            <button
              type="button"
              className={cn(row, narrow)}
              onClick={() => {
                setOpen(null)
                onEditText()
              }}
            >
              <span className="w-3.5 text-center text-[11px] font-semibold opacity-70">T</span>
              Edit text...
            </button>
          )}
          <button
            type="button"
            className={cn(row, narrow)}
            onClick={() => {
              setOpen(null)
              onStyle({ locked: !sel.locked })
            }}
          >
            <Lock className="h-3.5 w-3.5 opacity-70" />
            {sel.locked ? 'Unlock' : 'Lock'}
          </button>
          <button
            type="button"
            className={row}
            onClick={() => {
              setOpen(null)
              onDuplicate()
            }}
          >
            <CopyPlus className="h-3.5 w-3.5 opacity-70" />
            Duplicate
          </button>
          <button
            type="button"
            className={row}
            onClick={() => {
              setOpen(null)
              onOrder('front')
            }}
          >
            <BringToFront className="h-3.5 w-3.5 opacity-70" />
            Bring to front
          </button>
          <button
            type="button"
            className={row}
            onClick={() => {
              setOpen(null)
              onOrder('back')
            }}
          >
            <SendToBack className="h-3.5 w-3.5 opacity-70" />
            Send to back
          </button>
          <button
            type="button"
            className={row}
            onClick={() => {
              setOpen(null)
              onHide()
            }}
          >
            <EyeOff className="h-3.5 w-3.5 opacity-70" />
            Hide
          </button>
        </div>
      )}
    </div>
  )
}
