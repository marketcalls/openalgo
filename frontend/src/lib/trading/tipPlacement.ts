/**
 * Where a hover label goes: beside its control on the side asked for, flipped
 * to the opposite side when that one has no room, and slid along the edge so
 * it never leaves the window.
 */

export type TipSide = 'top' | 'bottom' | 'left' | 'right'

export interface TipBox {
  left: number
  top: number
  width: number
  height: number
}

/** Space kept between the label and its control, and between the label and the window edge. */
const GAP = 6
const EDGE = 4

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(value, Math.max(min, max)))
}

function fits(
  side: TipSide,
  anchor: TipBox,
  width: number,
  height: number,
  view: { width: number; height: number }
) {
  if (side === 'bottom') return anchor.top + anchor.height + GAP + height <= view.height - EDGE
  if (side === 'top') return anchor.top - GAP - height >= EDGE
  if (side === 'right') return anchor.left + anchor.width + GAP + width <= view.width - EDGE
  return anchor.left - GAP - width >= EDGE
}

const OPPOSITE: Record<TipSide, TipSide> = {
  top: 'bottom',
  bottom: 'top',
  left: 'right',
  right: 'left',
}

/** The label's top-left corner in window pixels, and the side it ended up on. */
export function placeTip(
  anchor: TipBox,
  size: { width: number; height: number },
  view: { width: number; height: number },
  side: TipSide = 'bottom'
): { left: number; top: number; side: TipSide } {
  const chosen =
    fits(side, anchor, size.width, size.height, view) ||
    !fits(OPPOSITE[side], anchor, size.width, size.height, view)
      ? side
      : OPPOSITE[side]
  if (chosen === 'top' || chosen === 'bottom') {
    const left = clamp(
      anchor.left + anchor.width / 2 - size.width / 2,
      EDGE,
      view.width - size.width - EDGE
    )
    const top =
      chosen === 'bottom' ? anchor.top + anchor.height + GAP : anchor.top - GAP - size.height
    return { left, top, side: chosen }
  }
  const top = clamp(
    anchor.top + anchor.height / 2 - size.height / 2,
    EDGE,
    view.height - size.height - EDGE
  )
  const left =
    chosen === 'right' ? anchor.left + anchor.width + GAP : anchor.left - GAP - size.width
  return { left, top, side: chosen }
}
