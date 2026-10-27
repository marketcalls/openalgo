/**
 * Countdown to the forming candle's close, for the scalping terminal's charts.
 *
 * /trading gets this from openalgo-charts (`axisChrome.barCountdown`), which
 * draws a second row inside the last-price tag. The scalper charts are plain
 * lightweight-charts, so this is the same reading built from a series
 * primitive: one price-axis label placed a pixel below the series' own last
 * price tag. The axis already stacks overlapping labels apart, centred on that
 * tag, so the countdown lands directly underneath it in the same colour and
 * reads as one two-row tag.
 *
 * The arithmetic mirrors the engine's, so both terminals count the same bar
 * down to the same second.
 */
import type {
  ISeriesPrimitive,
  ISeriesPrimitiveAxisView,
  SeriesAttachedParameter,
  Time,
} from 'lightweight-charts'

/** What the countdown needs to know about the last bar on the chart. */
export interface CountdownBar {
  /** Bar open time, in the chart's own time base. */
  time: number
  close: number
  /** Drawn in the up colour when true, the down colour otherwise. */
  up: boolean
}

/**
 * Seconds until the bar that opened at `lastBarTime` closes, or null when the
 * inputs cannot produce one. Once the clock passes that bar's close, the count
 * carries on against the next bucket, so a bar that has not yet printed a tick
 * still shows the time left in the current one.
 *
 * `lastBarTime` and `now` must share a time base: the scalper's bar times carry
 * the IST shift, so the caller shifts the wall clock by the same amount.
 */
export function barSecondsLeft(
  lastBarTime: number,
  intervalSec: number,
  now: number
): number | null {
  if (!Number.isFinite(intervalSec) || intervalSec <= 0) return null
  if (!Number.isFinite(lastBarTime) || !Number.isFinite(now)) return null
  const elapsed = now - lastBarTime
  return elapsed < 0 ? intervalSec - elapsed : intervalSec - (elapsed % intervalSec)
}

const pad = (n: number) => (n < 10 ? `0${n}` : String(n))

/**
 * MM:SS, with an hours field only when there is an hour or more to go. The
 * scalper's longest bar is 15 minutes, and the shorter form keeps the price
 * axis as narrow as the prices on it.
 */
export function formatCountdown(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return '--:--'
  const t = Math.max(0, Math.ceil(seconds))
  const h = Math.floor(t / 3600)
  const mm = `${pad(Math.floor((t % 3600) / 60))}:${pad(t % 60)}`
  return h > 0 ? `${pad(h)}:${mm}` : mm
}

// A space as wide as a digit, so padding lines up with the price's digits.
const FIGURE_SPACE = String.fromCharCode(0x2007)

/**
 * Centre `text` in figure spaces to the length of `price`. The axis sizes each
 * label's background to its own text, so a countdown narrower than the price
 * above it would leave the tick labels behind it showing through, and the two
 * would read as two tags instead of one.
 */
export function padToPrice(text: string, price: string): string {
  const gap = price.length - text.length
  if (gap <= 0) return text
  const before = Math.floor(gap / 2)
  return FIGURE_SPACE.repeat(before) + text + FIGURE_SPACE.repeat(gap - before)
}

export interface BarCountdownOptions {
  /** The last bar on the chart, or null when there is none. */
  lastBar: () => CountdownBar | null
  /** The bar interval in seconds. */
  intervalSec: () => number
  /** Now, in the same time base as the bar times. */
  now: () => number
  upColor: string
  downColor: string
}

class CountdownAxisView implements ISeriesPrimitiveAxisView {
  private _coordinate: number | null = null
  private _text = ''
  private _color = ''

  update(coordinate: number | null, text: string, color: string): void {
    this._coordinate = coordinate
    this._text = text
    this._color = color
  }

  // One pixel below the last price tag, so the axis's label alignment puts the
  // countdown under the tag rather than above it.
  coordinate(): number {
    return (this._coordinate ?? 0) + 1
  }

  text(): string {
    return this._text
  }

  textColor(): string {
    return '#ffffff'
  }

  backColor(): string {
    return this._color
  }

  visible(): boolean {
    return this._coordinate != null && this._text !== ''
  }

  tickVisible(): boolean {
    return false
  }
}

/**
 * Series primitive that draws the countdown under the series' last price tag.
 * Call `refresh()` once a second; a live tick repaints the chart anyway.
 */
export class BarCountdown implements ISeriesPrimitive<Time> {
  private readonly _opts: BarCountdownOptions
  private readonly _view = new CountdownAxisView()
  private readonly _views: readonly ISeriesPrimitiveAxisView[] = [this._view]
  private _param: SeriesAttachedParameter<Time> | null = null

  constructor(opts: BarCountdownOptions) {
    this._opts = opts
  }

  attached(param: SeriesAttachedParameter<Time>): void {
    this._param = param
  }

  detached(): void {
    this._param = null
  }

  /** Repaint so the label shows the current second. */
  refresh(): void {
    this._param?.requestUpdate()
  }

  updateAllViews(): void {
    const bar = this._opts.lastBar()
    const series = this._param?.series
    if (!bar || !series) {
      this._view.update(null, '', '')
      return
    }
    const left = barSecondsLeft(bar.time, this._opts.intervalSec(), this._opts.now())
    if (left == null) {
      this._view.update(null, '', '')
      return
    }
    this._view.update(
      series.priceToCoordinate(bar.close),
      padToPrice(formatCountdown(left), series.priceFormatter().format(bar.close)),
      bar.up ? this._opts.upColor : this._opts.downColor
    )
  }

  priceAxisViews(): readonly ISeriesPrimitiveAxisView[] {
    return this._views
  }
}
