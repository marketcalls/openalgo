/**
 * What a pane says while its chart is not simply showing bars.
 *
 * A pane is in one of four states: showing a chart (ready), waiting for bars
 * (loading), holding a reply with no bars in it (empty), or holding a request
 * that failed (error). The terminal reports the state of each load; the pane
 * draws it as an overlay over the chart rather than as a toast, because a toast
 * is gone in four seconds and the blank or stale chart it explained stays.
 *
 * Nothing here touches the DOM, so the wording and the timing are tested
 * without a chart.
 */

export type ChartStateKind = 'ready' | 'loading' | 'empty' | 'error'

export interface ChartStateView {
  kind: ChartStateKind
  /** The instrument asked for, as the trader typed or picked it. */
  symbol: string
  interval: string
  /** For empty and error: the cause, already in a trader's words. */
  message?: string
}

/**
 * A warm load lands in a few milliseconds. The dots appear only for one that
 * takes longer than this, so a quick switch never flashes them.
 */
export const LOADING_DELAY_MS = 120

export const CHART_READY: ChartStateView = Object.freeze({
  kind: 'ready',
  symbol: '',
  interval: '',
}) as ChartStateView

const NETWORK = /failed to fetch|networkerror|network request failed|load failed/i

/**
 * The cause of a failed load in a trader's words: no status code, no
 * endpoint, no exception class. The full error has already gone to the
 * console by the time this sees it.
 */
export function traderReason(raw: string): string {
  if (NETWORK.test(raw)) {
    return 'OpenAlgo could not be reached. Check that the server is running and the network is up'
  }
  const text = raw
    .replace(/^\s*(?:history error|[a-z]*error)\s*:\s*/i, '')
    // The request helper's own wording: `history failed (500): ...`.
    .replace(/(?:\/api\/v\d+\/)?[\w/.-]+\s+failed\s*\(\d{3}\)\s*:?/gi, '')
    .replace(/\/api\/v\d+\/[\w/.-]*/gi, '')
    .replace(/\s*\((?:HTTP\s*)?\d{3}\)/gi, '')
    .replace(/\b(?:HTTP|status(?: code)?)\s*\d{3}\b:?/gi, '')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^[:\-,\s]+|[.:,\s]+$/g, '')
  if (!text) return 'The broker did not return bars'
  return text[0].toUpperCase() + text.slice(1)
}

/** A load that failed. `reason` is the cleaned error text. */
export function chartLoadFailed(symbol: string, interval: string, reason: string): ChartStateView {
  return { kind: 'error', symbol, interval, message: traderReason(reason) }
}

/** A load that came back with no bars. */
export function chartNoData(symbol: string, interval: string, message?: string): ChartStateView {
  return message === undefined
    ? { kind: 'empty', symbol, interval }
    : { kind: 'empty', symbol, interval, message }
}

export interface ChartStateCopy {
  title: string
  text: string
  /** `alert` interrupts a screen reader; `status` waits its turn. */
  role: 'status' | 'alert'
}

/** The words the overlay shows for a state: cause first, then what to do. */
export function chartStateCopy(view: ChartStateView): ChartStateCopy {
  const symbol = view.symbol.trim()
  const interval = view.interval.trim()
  if (view.kind === 'loading') {
    const what = [symbol, interval].filter(Boolean).join(' ')
    return { title: what ? `Loading ${what}` : 'Loading chart', text: '', role: 'status' }
  }
  if (view.kind === 'empty') {
    return {
      title: `No data for ${symbol || 'this symbol'}${interval ? ` on ${interval}` : ''}`,
      text: `${view.message ?? 'The broker returned no bars for this range'}. Try another interval, or check the symbol.`,
      role: 'status',
    }
  }
  if (view.kind === 'error') {
    return {
      title: `Could not load ${symbol || 'the chart'}${interval ? ` on ${interval}` : ''}`,
      text: `${view.message ?? 'The broker did not return bars'}. Try again in a moment.`,
      role: 'alert',
    }
  }
  return { title: '', text: '', role: 'status' }
}

export interface ChartStateGate {
  /** The terminal's latest state. Loading shows only once it has lasted. */
  set(view: ChartStateView): void
  /** The trader closed the card. The chart underneath stays as it was. */
  dismiss(): void
  destroy(): void
}

/**
 * Turns load states into what is on screen. `show(null)` means nothing.
 *
 * A new load hides any card at once, so a retry never leaves the old failure
 * up beside the dots, and the dots wait `delay` before they appear.
 */
export function createChartStateGate(
  show: (view: ChartStateView | null) => void,
  delay = LOADING_DELAY_MS
): ChartStateGate {
  let timer: ReturnType<typeof setTimeout> | null = null
  let shown: ChartStateView | null = null
  let dead = false
  const clear = () => {
    if (timer !== null) clearTimeout(timer)
    timer = null
  }
  const put = (view: ChartStateView | null) => {
    if (dead || view === shown) return
    shown = view
    show(view)
  }
  return {
    set(view) {
      if (dead) return
      clear()
      if (view.kind === 'ready') {
        put(null)
        return
      }
      if (view.kind === 'loading') {
        if (shown && shown.kind !== 'loading') put(null)
        timer = setTimeout(() => {
          timer = null
          put(view)
        }, delay)
        return
      }
      put(view)
    },
    dismiss() {
      clear()
      put(null)
    },
    destroy() {
      clear()
      dead = true
    },
  }
}
