/**
 * The bottom dock's remembered state, kept pure so the page and the shell
 * read one definition and a test can pin it without a DOM.
 *
 * Two keys: which tab is open (or that the dock is closed) and how tall it
 * was last dragged. Both outlive a release, so everything read back is
 * checked before it is trusted, the way RightRail's isPanelId does for the
 * side panels.
 */

export const DOCK_TABS = [
  { id: 'orders', label: 'Orders' },
  { id: 'positions', label: 'Positions' },
  { id: 'trades', label: 'Trades' },
  { id: 'gtt', label: 'GTT' },
] as const

export type DockTab = (typeof DOCK_TABS)[number]['id']

export const DOCK_KEY = 'oa-trading-dock'
export const DOCK_HEIGHT_KEY = 'oa-trading-dock-height'

/** The collapsed strip: tab labels and their counts, nothing else. */
export const DOCK_STRIP_HEIGHT = 28
/** Shorter than this and a table shows its header and nothing under it. */
export const DOCK_MIN_HEIGHT = 120
/** Taller than this and the chart, which is the point of the page, is squeezed. */
export const DOCK_MAX_FRACTION = 0.6
export const DOCK_DEFAULT_HEIGHT = 240

/** Whether a remembered value still names a tab. */
export function isDockTab(value: string | null | undefined): value is DockTab {
  return DOCK_TABS.some((tab) => tab.id === value)
}

/** The tallest the dock may be in a viewport of this height. */
export function dockMaxHeight(viewportHeight: number): number {
  return Math.max(DOCK_MIN_HEIGHT, Math.floor(viewportHeight * DOCK_MAX_FRACTION))
}

export function clampDockHeight(height: number, viewportHeight: number): number {
  const max = dockMaxHeight(viewportHeight)
  if (!Number.isFinite(height)) return Math.min(max, DOCK_DEFAULT_HEIGHT)
  return Math.min(max, Math.max(DOCK_MIN_HEIGHT, Math.round(height)))
}

/** The open tab, or null for closed. Unreadable storage reads as closed. */
export function readDockTab(): DockTab | null {
  try {
    const saved = localStorage.getItem(DOCK_KEY)
    return isDockTab(saved) ? saved : null
  } catch {
    return null
  }
}

export function writeDockTab(tab: DockTab | null): void {
  try {
    localStorage.setItem(DOCK_KEY, tab ?? 'closed')
  } catch {
    // Storage refused (private mode, quota): the dock still works for this
    // visit, it just does not survive a reload.
  }
}

export function readDockHeight(viewportHeight: number): number {
  try {
    const saved = Number(localStorage.getItem(DOCK_HEIGHT_KEY))
    return clampDockHeight(saved > 0 ? saved : DOCK_DEFAULT_HEIGHT, viewportHeight)
  } catch {
    return clampDockHeight(DOCK_DEFAULT_HEIGHT, viewportHeight)
  }
}

export function writeDockHeight(height: number): void {
  try {
    localStorage.setItem(DOCK_HEIGHT_KEY, String(height))
  } catch {
    // As above.
  }
}

/**
 * What one Escape closes, once the page has already yielded to any open
 * Radix surface and to an armed drawing tool.
 *
 * The dock goes first only while it is the topmost thing with focus: focus
 * is inside it, or it is the only thing open. With a side panel open and
 * focus on the chart, Escape keeps closing the panel the way it always has,
 * and the next Escape takes the dock.
 */
export function escapeTarget(state: {
  dock: boolean
  panel: boolean
  focusInDock: boolean
}): 'dock' | 'panel' | null {
  if (state.dock && (state.focusInDock || !state.panel)) return 'dock'
  if (state.panel) return 'panel'
  return null
}
