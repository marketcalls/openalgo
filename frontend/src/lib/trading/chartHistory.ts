/**
 * One undo timeline per chart pane: studies added, removed and edited, pane
 * moves and folds, price scale changes, the chart type, the interval and the
 * drawings, walked by Ctrl+Z, Ctrl+Y and Ctrl+Shift+Z and by the undo
 * buttons alike.
 *
 * The library's `ChartHistory` records what it can see on the chart. This
 * terminal rebuilds its chart for a chart type or a theme and restores its
 * studies asynchronously, so the timeline is kept here rather than on any
 * one chart: each rebuilt chart is followed once its content is back, and a
 * study keeps its id through the rebuild, which is what the steps follow.
 * The chart type and the interval are the terminal's own switches, which the
 * history cannot observe, so they are recorded as commands.
 *
 * Nothing on the timeline reaches an order. Orders are not chart state: no
 * step places, modifies or cancels one, and none is ever pushed here.
 *
 * The widget tier holding `ChartHistory` is loaded on first use, the way the
 * bottom bar loads it, so a chart paints before any of this is fetched. Until
 * then a press falls back to the drawing controller's own undo.
 */

import type { Chart } from 'openalgo-charts'
import type { DrawingController } from 'openalgo-charts/draw'
import type { ChartHistory, ChartHistoryCommand } from 'openalgo-charts/widget'

export type HistoryDirection = 'undo' | 'redo'

/** What a key event asks of the timeline, or null when it is not an undo chord. */
export function historyChord(e: {
  key: string
  ctrlKey?: boolean
  metaKey?: boolean
  shiftKey?: boolean
  altKey?: boolean
}): HistoryDirection | null {
  if (e.altKey || !(e.ctrlKey || e.metaKey)) return null
  const key = e.key.toLowerCase()
  if (key === 'z') return e.shiftKey ? 'redo' : 'undo'
  if (key === 'y' && !e.shiftKey) return 'redo'
  return null
}

export interface TerminalHistoryOptions {
  /** What `ready` reports may have changed. */
  onChange(): void
  /** A step could not be applied; the chart has been put back as it was. */
  onError(message: string): void
}

type Draw = DrawingController | null

export class TerminalHistory {
  private history: ChartHistory | null = null
  /** The chart the timeline follows, once its content is restored. */
  private chart: Chart | null = null
  /** The chart and controller asked for last, while the tier loads. */
  private wanted: { chart: Chart; draw: Draw } | null = null
  private loading: Promise<void> | null = null
  private destroyed = false
  private readonly opts: TerminalHistoryOptions

  constructor(opts: TerminalHistoryOptions) {
    this.opts = opts
  }

  /**
   * Follow `chart` (and its drawing controller) from now on, keeping the
   * steps already taken. Called once a rebuilt chart has its studies back,
   * so nothing the rebuild did becomes a step.
   */
  follow(chart: Chart, draw: Draw): Promise<void> {
    if (this.destroyed || chart.isDestroyed) return Promise.resolve()
    this.wanted = { chart, draw }
    if (this.history) {
      this.attach()
      return Promise.resolve()
    }
    this.loading ??= import('openalgo-charts/widget')
      .then(({ ChartHistory: History }) => {
        const wanted = this.wanted
        if (this.destroyed || !wanted || wanted.chart.isDestroyed) return
        const history = new History(wanted.chart, {
          draw: wanted.draw,
          onError: ({ direction }) =>
            this.opts.onError(
              `That change could not be ${direction === 'undo' ? 'undone' : 'redone'}. The chart is as it was before.`
            ),
        })
        this.history = history
        this.chart = wanted.chart
        history.subscribe(() => this.opts.onChange())
        this.opts.onChange()
      })
      .catch(() => {
        // Without the tier the drawing controller's own undo still works.
        this.loading = null
      })
    return this.loading
  }

  /** Stop following: the chart is being rebuilt and is not the one on screen. */
  pause(): void {
    this.chart = null
    this.opts.onChange()
  }

  private attach(): void {
    const wanted = this.wanted
    if (!this.history || !wanted || wanted.chart.isDestroyed) return
    this.history.attach(wanted.chart, wanted.draw)
    this.chart = wanted.chart
    this.opts.onChange()
  }

  /** The timeline, while it follows `chart`. */
  private on(chart: Chart | null): ChartHistory | null {
    const h = this.history
    return h && !h.isDestroyed && chart !== null && this.chart === chart && !chart.isDestroyed
      ? h
      : null
  }

  /** Whether the timeline follows `chart` right now. */
  following(chart: Chart | null): boolean {
    return this.on(chart) !== null
  }

  /**
   * One press. The timeline when it follows `chart`; the drawing controller's
   * own history before the tier has loaded; nothing while a rebuild is
   * between charts.
   */
  press(direction: HistoryDirection, chart: Chart | null, draw: Draw): boolean {
    const h = this.on(chart)
    if (h) return direction === 'undo' ? h.undo() : h.redo()
    if (this.history || !draw) return false
    return direction === 'undo' ? draw.undo() : draw.redo()
  }

  /** Whether that press would do anything, for a button's enabled state. */
  ready(direction: HistoryDirection, chart: Chart | null, draw: Draw): boolean {
    const h = this.on(chart)
    if (h) return direction === 'undo' ? h.canUndo() : h.canRedo()
    if (this.history || !draw) return false
    return direction === 'undo' ? draw.canUndo() : draw.canRedo()
  }

  /** Run a change the terminal makes for itself, which no press takes back. */
  ignore<T>(fn: () => T): T {
    const h = this.history
    return h && !h.isDestroyed && this.chart !== null ? h.ignore(fn) : fn()
  }

  /** Run `fn` as one step. */
  transact<T>(chart: Chart | null, fn: () => T, label?: string): T {
    const h = this.on(chart)
    return h ? h.transact(fn, label) : fn()
  }

  /**
   * Record a switch the history cannot see (chart type, interval). The
   * caller asks `following` before it switches, because the switch itself
   * may rebuild the chart (a chart type does) and the timeline then follows
   * another chart by the time the step is recorded: the step is still the
   * trader's, made on the chart the timeline was following.
   */
  push(command: ChartHistoryCommand): void {
    const h = this.history
    if (h && !h.isDestroyed) h.push(command)
  }

  destroy(): void {
    this.destroyed = true
    this.history?.destroy()
    this.history = null
    this.chart = null
    this.wanted = null
  }
}
