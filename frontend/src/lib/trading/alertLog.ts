/**
 * The history of what fired, kept on the server rather than in the page.
 *
 * **An alert is evaluated by the chart, and the chart is a browser tab.** That
 * is a deliberate limit and nothing here changes it: no alert fires because of
 * this file. What it changes is what is left behind afterwards. A tab closed at
 * four o'clock used to take the afternoon's firings with it, and an alert that
 * fired while the trader was on another screen left nothing at all, so the only
 * record of a price being reached was a toast nobody saw.
 *
 * So the page reports each firing as it happens and reads the list back when
 * the panel opens. It is a log, not a queue: the server never replays one, and
 * a firing that was never reported is simply not in it.
 *
 * **Reporting is best effort and never blocks the alert.** By the time any of
 * this runs the trader has already been told, on the channels they chose. A
 * write that fails must not produce a second, contradictory message about the
 * alert they just heard about, so a failure here is silent by design and the
 * row is the thing that is lost, not the alert.
 */

/** One firing, as the server stores and returns it. */
export interface LoggedFire {
  id: number
  alertId: string
  title: string
  kind: string
  condition: string
  symbol: string
  exchange: string
  interval: string
  price: number | null
  message: string
  /** The channels that accepted the message. Empty means it reached nobody. */
  delivered: string[]
  /** Epoch seconds, UTC. */
  firedAt: number | null
}

/** What the page sends when an alert fires. */
export interface ReportedFire {
  alertId: string
  title: string
  kind: string
  condition: string
  symbol: string
  exchange: string
  interval: string
  price?: number
  message: string
  delivered: string[]
}

async function json(path: string, init?: RequestInit): Promise<unknown> {
  // A relative URL: this application is served from a port, a domain, a
  // subdomain and a container, and an absolute one works only for whoever
  // wrote it.
  const res = await fetch(path, {
    credentials: 'same-origin',
    ...init,
  })
  if (!res.ok) throw new Error(String(res.status))
  return await res.json()
}

/**
 * Write one firing down. Resolves either way.
 *
 * The caller is inside an alert that has already been delivered, so there is
 * nothing useful it could do with a rejection and a toast here would contradict
 * the one the trader just read.
 */
export async function reportFire(fire: ReportedFire): Promise<LoggedFire | null> {
  try {
    const body = (await json('/alerts/fired', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fire),
    })) as { status?: string; fire?: LoggedFire }
    return body?.status === 'success' && body.fire ? body.fire : null
  } catch {
    return null
  }
}

/** This user's firings, newest first. An unreachable server reads as empty. */
export async function fetchLog(): Promise<LoggedFire[]> {
  try {
    const body = (await json('/alerts/log')) as { status?: string; fires?: unknown }
    return Array.isArray(body?.fires) ? (body.fires as LoggedFire[]) : []
  } catch {
    return []
  }
}

/**
 * Clear the log, and say whether the server agreed.
 *
 * Unlike a report, this one is a button the trader pressed, so a failure has to
 * be visible: silently leaving the rows there would have them press it again
 * and believe the platform is ignoring them.
 */
export async function clearLog(): Promise<boolean> {
  try {
    const body = (await json('/alerts/log', { method: 'DELETE' })) as { status?: string }
    return body?.status === 'success'
  } catch {
    return false
  }
}
