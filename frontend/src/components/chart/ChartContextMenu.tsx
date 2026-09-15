/**
 * The chart's right-click menu.
 *
 * The widget tier ships a menu of its own, and it is both short and wrong for
 * this page: its rows are paste, fit, indicators and settings, and paste is for
 * a drawing clipboard nobody reaches for by right-clicking a candle. `/trading`
 * has the menu people actually use, because it runs a bare `Chart` and builds
 * its own in React.
 *
 * This is that menu, for a chart on the widget tier, with the same rows and the
 * same glyphs. The host suppresses the engine's menu in the capture phase
 * before the canvas ever sees the event, so there is exactly one menu rather
 * than two fighting for one click.
 *
 * There are no order rows and no hook to add any. That is the same guarantee
 * `OpenAlgoChart` makes: the capability is absent, not disabled.
 */

import { ChevronDown, RefreshCw, Settings } from 'lucide-react'
import type { Widget } from 'openalgo-charts/widget'
import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import { GridIcon, PencilIcon, VolumeIcon } from './menuIcons'

/** Where the menu was opened, in viewport coordinates. */
export interface ChartMenuAnchor {
  x: number
  y: number
}

export interface ChartContextMenuProps {
  widget: Widget | null
  at: ChartMenuAnchor | null
  onClose(): void
  railVisible: boolean
  onToggleRail(): void
  /**
   * Volume, when the chart has any.
   *
   * Optional together: a chart of a spread's premium or of open interest has no
   * volume to draw, and the row is left out there rather than offered as a
   * switch that turns an empty histogram on and off.
   */
  volumeVisible?: boolean
  onToggleVolume?(): void
}

type GridChoice = 'both' | 'horizontal' | 'vertical' | 'none'

const ROW =
  'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent hover:text-accent-foreground'
const ICON = 'h-3.5 w-3.5 opacity-70'

export function ChartContextMenu({
  widget,
  at,
  onClose,
  railVisible,
  onToggleRail,
  volumeVisible,
  onToggleVolume,
}: ChartContextMenuProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [gridOpen, setGridOpen] = useState(false)

  // Dismiss on a press outside or on Escape, the way every menu does.
  useEffect(() => {
    if (!at) return
    const away = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose()
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    // Deferred so the press that opened the menu does not immediately close it.
    const timer = window.setTimeout(() => document.addEventListener('pointerdown', away), 0)
    document.addEventListener('keydown', key)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('pointerdown', away)
      document.removeEventListener('keydown', key)
    }
  }, [at, onClose])

  useEffect(() => {
    if (!at) setGridOpen(false)
  }, [at])

  if (!at || !widget) return null

  const grid = widget.chart.gridOptions()
  const current: GridChoice =
    grid.vertLines && grid.horzLines
      ? 'both'
      : grid.horzLines
        ? 'horizontal'
        : grid.vertLines
          ? 'vertical'
          : 'none'

  const run = (action: () => void) => {
    action()
    setGridOpen(false)
    onClose()
  }

  const setGrid = (choice: GridChoice) =>
    widget.chart.setGridOptions({
      vertLines: choice === 'both' || choice === 'vertical',
      horzLines: choice === 'both' || choice === 'horizontal',
    })

  // Near the right edge the submenu opens to the left instead of off screen.
  const submenuLeft = at.x + 224 + 4 + 144 > window.innerWidth

  return (
    <div
      ref={ref}
      className="fixed z-50 w-56 rounded-md border bg-popover p-1 shadow-lg"
      style={{ left: at.x, top: at.y }}
    >
      <button
        type="button"
        className={ROW}
        onClick={() => run(() => widget.chart.setVisibleLogicalRange(defaultRange(widget)))}
      >
        <RefreshCw className={ICON} />
        Reset chart view
      </button>

      <button type="button" className={ROW} onClick={() => run(() => widget.openSettings())}>
        <Settings className={ICON} />
        Chart settings...
      </button>

      <button type="button" className={ROW} onClick={() => run(onToggleRail)}>
        <PencilIcon className={ICON} />
        {railVisible ? 'Hide drawing tools' : 'Show drawing tools'}
      </button>

      {onToggleVolume ? (
        <button type="button" className={ROW} onClick={() => run(onToggleVolume)}>
          <VolumeIcon className={ICON} />
          {volumeVisible ? 'Hide volume' : 'Show volume'}
        </button>
      ) : null}

      <div className="relative">
        <button
          type="button"
          className={ROW}
          onClick={(event) => {
            event.stopPropagation()
            setGridOpen((open) => !open)
          }}
        >
          <GridIcon className={ICON} />
          Grid
          <ChevronDown className="-rotate-90 ml-auto h-3.5 w-3.5 opacity-60" />
        </button>
        {gridOpen && (
          <div
            className={cn(
              'absolute top-0 w-36 rounded-md border bg-popover p-1 shadow-lg',
              submenuLeft ? 'right-full mr-1' : 'left-full ml-1'
            )}
          >
            {(
              [
                ['both', 'Grid'],
                ['horizontal', 'Horizontal'],
                ['vertical', 'Vertical'],
                ['none', 'None'],
              ] as const
            ).map(([choice, label]) => (
              <button
                type="button"
                key={choice}
                className={ROW}
                onClick={(event) => {
                  event.stopPropagation()
                  run(() => setGrid(choice))
                }}
              >
                <span className="w-3.5 text-xs">{current === choice ? '✓' : ''}</span>
                {label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/** The newest 500 bars with a little clear air, the view a chart opens on. */
function defaultRange(widget: Widget): { from: number; to: number } {
  const count = widget.chart.dataLayer.length
  const last = Math.max(0, count - 1)
  const visible = Math.min(500, Math.max(1, count))
  return {
    from: Math.max(0, last - visible + 1),
    to: last + Math.max(1, Math.round(visible * 0.05)),
  }
}
