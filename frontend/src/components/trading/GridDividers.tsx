/**
 * Draggable dividers between the charts of a multi-chart grid.
 *
 * They live in the gaps the grid already leaves between charts, so they cost
 * the plot nothing: a divider is the 8px gap itself, made something to grab.
 * Drag to resize the charts either side, double-click to put every chart back
 * to the layout's own sizes. A divider is also a focusable separator, moved
 * with the arrow keys.
 */
import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  type DividerSegment,
  dividerSegments,
  type GridWeights,
  resizeTracks,
} from '@/lib/trading/gridSizes'
import { cn } from '@/lib/utils'

/** Must match the grid's `p-2` and `gap-2`. */
const PAD = 8
const GAP = 8
/** The smallest a chart is allowed to be dragged to. */
const MIN_TRACK_PX = 120
/** How far one arrow key moves a divider. */
const KEY_STEP_PX = 16

interface Props {
  cells: readonly (readonly string[])[]
  weights: GridWeights
  /** Every pointer move while dragging, so the charts follow the hand. */
  onChange(weights: GridWeights): void
  /** The drag or key press is over: keep the split. */
  onCommit(weights: GridWeights): void
  /** Double-click: back to the layout's own sizes. */
  onReset(): void
}

interface Box {
  width: number
  height: number
}

/** Pixels the tracks of one axis share, after the padding and the gaps. */
function trackSpace(size: number, count: number): number {
  return Math.max(0, size - 2 * PAD - GAP * (count - 1))
}

/** The pixel offset of the start of each track, and its size. */
function trackOffsets(weights: readonly number[], size: number): { start: number; size: number }[] {
  const space = trackSpace(size, weights.length)
  const sum = weights.reduce((total, weight) => total + weight, 0) || 1
  let at = PAD
  return weights.map((weight) => {
    const px = (weight / sum) * space
    const track = { start: at, size: px }
    at += px + GAP
    return track
  })
}

export function GridDividers({ cells, weights, onChange, onCommit, onReset }: Props) {
  const layer = useRef<HTMLDivElement>(null)
  const [box, setBox] = useState<Box | null>(null)
  const segments = useMemo(() => dividerSegments(cells), [cells])
  const latest = useRef({ weights, onChange, onCommit, onReset })
  latest.current = { weights, onChange, onCommit, onReset }

  // Measured before paint, so the dividers are in place in the first frame.
  useLayoutEffect(() => {
    const node = layer.current
    if (!node) return
    const measure = () => {
      const rect = node.getBoundingClientRect()
      setBox((previous) =>
        previous && previous.width === rect.width && previous.height === rect.height
          ? previous
          : { width: rect.width, height: rect.height }
      )
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(node)
    return () => observer.disconnect()
  }, [])

  const columns = box ? trackOffsets(weights.columns, box.width) : []
  const rows = box ? trackOffsets(weights.rows, box.height) : []

  /** The weights after moving one divider by `delta` pixels. */
  const moved = (segment: DividerSegment, delta: number, from: GridWeights): GridWeights => {
    if (!box) return from
    if (segment.axis === 'column') {
      const space = trackSpace(box.width, from.columns.length)
      return {
        ...from,
        columns: resizeTracks(from.columns, segment.index, delta, space, MIN_TRACK_PX),
      }
    }
    const space = trackSpace(box.height, from.rows.length)
    return { ...from, rows: resizeTracks(from.rows, segment.index, delta, space, MIN_TRACK_PX) }
  }

  return (
    <div ref={layer} className="pointer-events-none absolute inset-0 z-30" data-grid-dividers>
      {box &&
        segments.map((segment) => {
          const vertical = segment.axis === 'column'
          const across = vertical ? columns : rows
          const along = vertical ? rows : columns
          const before = across[segment.index]
          const first = along[segment.from]
          const last = along[segment.to]
          if (!before || !first || !last) return null
          const position = before.start + before.size
          const start = first.start
          const length = last.start + last.size - first.start
          const total = (vertical ? weights.columns : weights.rows).reduce((a, b) => a + b, 0) || 1
          const share =
            ((vertical ? weights.columns : weights.rows)
              .slice(0, segment.index + 1)
              .reduce((a, b) => a + b, 0) /
              total) *
            100
          return (
            // biome-ignore lint/a11y/useSemanticElements: a focusable, draggable splitter is a separator with a value; an hr cannot take focus, keys or a grip.
            <div
              key={`${segment.axis}-${segment.index}-${segment.from}`}
              role="separator"
              tabIndex={0}
              aria-orientation={vertical ? 'vertical' : 'horizontal'}
              aria-label={vertical ? 'Resize chart columns' : 'Resize chart rows'}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(share)}
              data-divider={`${segment.axis}-${segment.index}`}
              className={cn(
                'group pointer-events-auto absolute flex touch-none items-center justify-center outline-none',
                vertical ? 'cursor-col-resize' : 'cursor-row-resize'
              )}
              style={
                vertical
                  ? { left: position, top: start, width: GAP, height: length }
                  : { top: position, left: start, height: GAP, width: length }
              }
              onDoubleClick={() => latest.current.onReset()}
              onPointerDown={(event) => {
                if (event.button !== 0) return
                event.preventDefault()
                const target = event.currentTarget
                target.setPointerCapture?.(event.pointerId)
                const origin = vertical ? event.clientX : event.clientY
                const startWeights = latest.current.weights
                let current = startWeights
                let frame = 0
                const move = (e: PointerEvent) => {
                  current = moved(
                    segment,
                    (vertical ? e.clientX : e.clientY) - origin,
                    startWeights
                  )
                  if (frame) return
                  frame = requestAnimationFrame(() => {
                    frame = 0
                    latest.current.onChange(current)
                  })
                }
                const end = () => {
                  if (frame) cancelAnimationFrame(frame)
                  target.removeEventListener('pointermove', move)
                  target.removeEventListener('pointerup', end)
                  target.removeEventListener('pointercancel', end)
                  if (current !== startWeights) latest.current.onCommit(current)
                }
                target.addEventListener('pointermove', move)
                target.addEventListener('pointerup', end)
                target.addEventListener('pointercancel', end)
              }}
              onKeyDown={(event) => {
                const back = vertical ? 'ArrowLeft' : 'ArrowUp'
                const forward = vertical ? 'ArrowRight' : 'ArrowDown'
                if (event.key !== back && event.key !== forward) return
                // Kept here: the same arrows nudge a selected drawing on the chart.
                event.preventDefault()
                event.stopPropagation()
                const step = (event.shiftKey ? 4 : 1) * KEY_STEP_PX
                latest.current.onCommit(
                  moved(segment, event.key === back ? -step : step, latest.current.weights)
                )
              }}
            >
              <span
                aria-hidden="true"
                className={cn(
                  'rounded-full bg-primary/0 transition-colors group-hover:bg-primary/60 group-focus-visible:bg-primary',
                  vertical ? 'h-10 max-h-full w-[3px]' : 'h-[3px] w-10 max-w-full'
                )}
              />
            </div>
          )
        })}
    </div>
  )
}
