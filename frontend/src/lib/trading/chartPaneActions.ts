/**
 * The study rows of the chart's right-click menu, and how a folded pane is
 * kept with the chart's saved studies.
 *
 * Pure over a narrow view of the chart, so the rules (which pane may move
 * which way, which may fold, what a protected study allows) are tested
 * without a canvas.
 */

import type { IndicatorPolicy } from 'openalgo-charts'

/** The part of a study the menu reads. */
export interface PaneStudy {
  readonly id: string
  readonly name: string
  readonly paneIndex: number
  policy(): Readonly<IndicatorPolicy>
}

/** The part of the chart the menu reads. */
export interface PaneChart {
  panes(): readonly unknown[]
  primaryPaneIndex(): number
  movablePrimaryPane(): boolean
  paneCollapsed(index: number): boolean
  indicators(): readonly PaneStudy[]
}

export interface PaneMove {
  disabled: boolean
  reason?: string
}

export interface StudyMenu {
  /** The study right-clicked, or the only study in the pane; null on a pane of several. */
  study: { id: string; name: string; configurable: boolean; removable: boolean } | null
  /** Pane rows, present on a study pane only: the price pane keeps its place and never folds. */
  pane: {
    index: number
    up: PaneMove
    down: PaneMove
    collapsed: boolean
  } | null
}

/**
 * The rows for a right-click on `paneIndex`, on `instanceId` when a study's
 * plot or legend was hit. Null when there is nothing study-shaped there: the
 * price pane with no study under the pointer.
 */
export function studyMenuAt(
  chart: PaneChart,
  paneIndex: number,
  instanceId?: string | null
): StudyMenu | null {
  const count = chart.panes().length
  if (!(paneIndex >= 0 && paneIndex < count)) return null
  const price = chart.primaryPaneIndex()
  const studies = chart.indicators()
  let hit = instanceId ? studies.find((s) => s.id === instanceId) : undefined
  if (!hit && paneIndex !== price) {
    const inPane = studies.filter((s) => s.paneIndex === paneIndex)
    if (inPane.length === 1) hit = inPane[0]
  }
  const study = hit
    ? {
        id: hit.id,
        name: hit.name,
        configurable: hit.policy().configurable !== false,
        removable: hit.policy().removable !== false,
      }
    : null
  // A study drawn over the price is on the price pane: settings and remove,
  // but no pane rows, since the pane is the price's.
  const studyPane = hit ? hit.paneIndex : paneIndex
  if (studyPane === price) return study ? { study, pane: null } : null
  const pinned = !chart.movablePrimaryPane()
  const move = (direction: -1 | 1): PaneMove => {
    const target = studyPane + direction
    if (target < 0) return { disabled: true, reason: 'Already the top pane' }
    if (target >= count) return { disabled: true, reason: 'Already the bottom pane' }
    if (pinned && target === price) return { disabled: true, reason: 'The price pane stays on top' }
    return { disabled: false }
  }
  return {
    study,
    pane: {
      index: studyPane,
      up: move(-1),
      down: move(1),
      collapsed: chart.paneCollapsed(studyPane),
    },
  }
}

/* ── folded panes, kept with the saved studies ─────────────────────────── */

/**
 * The studies in folded panes, by instance id. A pane has no identity of its
 * own in the per-pane save, which is a list of studies; its studies do, and
 * they travel with it through a move. Empty when nothing is folded, which is
 * also what a save from before folding reads as.
 */
export function foldedStudyIds(chart: PaneChart): string[] {
  const price = chart.primaryPaneIndex()
  const ids: string[] = []
  for (const s of chart.indicators()) {
    if (s.paneIndex !== price && chart.paneCollapsed(s.paneIndex)) ids.push(s.id)
  }
  return ids
}

/** The saved list, or nothing when it is missing or not a list of ids. */
export function readFoldedStudyIds(raw: string | null): string[] {
  if (!raw) return []
  try {
    const value = JSON.parse(raw) as unknown
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : []
  } catch {
    return []
  }
}

/** The panes to fold again after a restore: those holding any saved id. */
export function panesToFold(chart: PaneChart, ids: readonly string[]): number[] {
  if (ids.length === 0) return []
  const wanted = new Set(ids)
  const price = chart.primaryPaneIndex()
  const panes = new Set<number>()
  for (const s of chart.indicators()) {
    if (wanted.has(s.id) && s.paneIndex !== price) panes.add(s.paneIndex)
  }
  return [...panes].sort((a, b) => a - b)
}
