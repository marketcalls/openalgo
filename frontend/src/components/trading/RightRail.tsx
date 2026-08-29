/**
 * The side panel rail on the right edge of the charting terminal.
 *
 * Mirrors DrawingRail on the left, sharing its button metrics and hover label
 * through railStyles so the two edges of the workspace cannot drift apart. The
 * difference is what a click means: a drawing tool arms, a rail button here
 * opens or closes the panel beside it, and clicking the open panel's own button
 * closes it.
 */

import { List, Table2 } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'
import { RAIL_BTN, RAIL_BTN_ON, RAIL_ICON_STROKE, RailTip } from './railStyles'

/** Which panel the rail is showing, or null when the workspace is all chart. */
export type PanelId = 'watchlist' | 'options'

interface Props {
  active: PanelId | null
  onSelect(panel: PanelId | null): void
}

const PANELS: Array<{ id: PanelId; label: string; icon: typeof List }> = [
  // A plain list and a table. Nothing here is a metaphor: the watchlist is a
  // list of instruments and the option chain is a table of strikes.
  { id: 'watchlist', label: 'Watchlist', icon: List },
  { id: 'options', label: 'Option chain', icon: Table2 },
]

export function RightRail({ active, onSelect }: Props) {
  /**
   * Where focus goes when a panel closes.
   *
   * The panel unmounts with focus inside it, so without this focus falls to
   * <body> and the next Tab restarts at the top of the document. Escape
   * closing a panel is the common case, and it happens with the keyboard.
   */
  const buttonsRef = useRef<Record<string, HTMLButtonElement | null>>({})
  const previous = useRef<PanelId | null>(active)

  useEffect(() => {
    const closed = previous.current
    previous.current = active
    if (active !== null || closed === null) return
    // Only reclaim focus if it was lost to the body with the panel.
    if (document.activeElement === document.body) buttonsRef.current[closed]?.focus()
  }, [active])

  return (
    <div className="flex w-10 shrink-0 flex-col items-center gap-0.5 no-scrollbar overflow-y-auto border-l bg-background/40 py-1">
      {PANELS.map(({ id, label, icon: Icon }) => {
        const isOpen = active === id
        return (
          <div key={id} className="group relative">
            <button
              type="button"
              ref={(node) => {
                buttonsRef.current[id] = node
              }}
              // Clicking the open panel's own button closes it. The rail is the
              // only way back to a full-width chart, so the button that opened
              // a panel has to be the button that puts it away.
              onClick={() => onSelect(isOpen ? null : id)}
              className={cn(RAIL_BTN, isOpen && RAIL_BTN_ON)}
              aria-label={label}
              aria-expanded={isOpen}
              // Only while the panel exists. Pointing aria-controls at an id
              // that is not in the document is worse than omitting it.
              aria-controls={isOpen ? `oa-panel-${id}` : undefined}
            >
              <Icon className="h-[18px] w-[18px]" strokeWidth={RAIL_ICON_STROKE} />
            </button>
            {/* Opens left: this rail is against the viewport edge, so a tip
                opening right would be clipped. */}
            <RailTip text={label} chord={isOpen ? 'Esc' : undefined} side="left" />
          </div>
        )
      })}
    </div>
  )
}
