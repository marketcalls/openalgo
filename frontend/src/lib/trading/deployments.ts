/**
 * One strategy's deployments, as the panel lists them.
 *
 * **A deployment is a script, an instrument and an interval.** One strategy is
 * deployed on several instruments, and on one instrument at several timeframes,
 * all at once. Each has its own position, its own book, its own log and its own
 * decision to stop, so each is a row.
 *
 * The list used to be one row per file. Deploying a strategy a second time
 * silently replaced the first, and the two shared an order tag: a trader
 * looking at a run on a commodity future saw the stock orders the same file had
 * placed that morning, with nothing on the screen to say which position they
 * were reading.
 *
 * **Built from both sides, and neither alone is enough.** The settings say what
 * is deployed and the registry says what is up. A run whose settings were
 * removed while it was still running appears in one and not the other, and it
 * is exactly the row a trader most needs a Stop button for.
 */

import type { RunningStrategy, RunSettings } from '@/api/openscriptRunner'

/** A strategy deployed on one instrument at one interval: what a row is. */
export interface Deployment {
  /** What the server calls it. Everything addressing this run uses it. */
  id: string
  /** The script it runs, which is the name a trader reads. */
  file: string
  settings: RunSettings | null
  run: RunningStrategy | null
}

/**
 * Every deployment, running first and then by the strategy each one runs.
 *
 * Running first because a panel is read top down and a trader opening it is
 * asking what is holding a position, not what could. Then by file and
 * instrument, so two deployments of one strategy sit together.
 */
export function deploymentsOf(
  settings: readonly RunSettings[],
  running: readonly RunningStrategy[]
): Deployment[] {
  const byId = new Map<string, Deployment>()

  for (const one of settings) {
    // An older server, or one answering a deployment saved before these
    // existed, carries no id. The file is then the whole of the identity,
    // which is what it was, so the row is still shown rather than dropped.
    const id = one.deployment || one.file
    byId.set(id, { id, file: one.file, settings: one, run: null })
  }

  for (const one of running) {
    const id = one.deployment || one.id
    const held = byId.get(id)
    if (held) held.run = one
    else byId.set(id, { id, file: one.file, settings: null, run: one })
  }

  return [...byId.values()].sort((a, b) => {
    const up = Number(Boolean(b.run)) - Number(Boolean(a.run))
    if (up !== 0) return up
    return a.file.localeCompare(b.file) || whereOf(a).localeCompare(whereOf(b))
  })
}

/** What one deployment trades, from whichever side knows it. */
export function whereOf(one: Deployment): string {
  const held = one.run ?? one.settings
  return String(held?.symbol ?? '')
}

/**
 * Whether a row matches what was typed in the search box.
 *
 * Both the strategy and the instrument, because a trader running one strategy
 * on eight instruments searches for the instrument, and one running eight
 * strategies on one instrument searches for the strategy.
 */
export function matches(one: Deployment, search: string): boolean {
  const wanted = search.trim().toLowerCase()
  if (!wanted) return true
  return one.file.toLowerCase().includes(wanted) || whereOf(one).toLowerCase().includes(wanted)
}
