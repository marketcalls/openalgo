/**
 * How the lines of a comparison are scaled against the chart they sit on.
 *
 * Four choices, each a different question:
 *
 * - **Price**: every line on the chart's own price axis, in real prices. For two
 *   things that trade near each other, a future against its index or two
 *   listings of one company.
 * - **Percentage**: every line rebased to its first shared bar, read as the
 *   percent moved since then.
 * - **Indexed to 100**: the same rebasing, read as 100 at the start.
 * - **Own scale**: each line fitted to its own range, for the shape of the move
 *   rather than its size.
 *
 * A saved chart only ever recorded `price` or `percent`, and what it called
 * `price` drew each line on a scale of its own. That is Own scale here, so a
 * chart saved before the choice existed opens drawing exactly what it drew.
 * The two newer choices travel next to the old field (`scale`) in this
 * browser's per-chart memory. A named workspace document has room only for the
 * old two values, so there Price is kept as `price` and Indexed to 100 as
 * `percent`, which reopen as Own scale and Percentage.
 */

import type { PriceRange, PriceScale, PriceScaleMode } from 'openalgo-charts'

export type ComparisonScale = 'price' | 'percent' | 'indexed' | 'own'
export type StoredComparisonMode = 'price' | 'percent'

/** In menu order, with the words a trader reads. */
export const COMPARISON_SCALES: readonly { value: ComparisonScale; label: string; hint: string }[] =
  [
    { value: 'price', label: 'Price', hint: 'Real prices on the chart price axis' },
    { value: 'percent', label: 'Percentage', hint: 'Percent moved since the first shared bar' },
    { value: 'indexed', label: 'Indexed to 100', hint: 'Every line starts at 100' },
    { value: 'own', label: 'Own scale', hint: 'Each line fitted to its own range' },
  ]

export function isComparisonScale(value: unknown): value is ComparisonScale {
  return value === 'price' || value === 'percent' || value === 'indexed' || value === 'own'
}

/** The choice a stored pair stands for. No `scale` is a chart saved before there was one. */
export function comparisonScaleOf(mode: StoredComparisonMode, scale?: unknown): ComparisonScale {
  if (isComparisonScale(scale) && storedComparisonMode(scale) === mode) return scale
  return mode === 'percent' ? 'percent' : 'own'
}

/** The value written where only the two original modes fit. */
export function storedComparisonMode(scale: ComparisonScale): StoredComparisonMode {
  return scale === 'percent' || scale === 'indexed' ? 'percent' : 'price'
}

/** The pane mode the engine holds while comparisons are on it, or null for none. */
export function rebasingMode(
  scale: ComparisonScale
): Extract<PriceScaleMode, 'percentage' | 'indexed-to-100'> | null {
  return scale === 'percent' ? 'percentage' : scale === 'indexed' ? 'indexed-to-100' : null
}

/** One comparison as the shared price axis reads it. */
export interface AxisSource {
  visible: boolean
  scale: PriceScale
  /** The comparison's close at a primary bar time, or null for a gap. */
  closeAt(time: number): number | null
}

/** The widest range holding the primary's own and every value given. */
export function unionRange(base: PriceRange | null, values: Iterable<number>): PriceRange | null {
  let min = base?.min ?? Number.POSITIVE_INFINITY
  let max = base?.max ?? Number.NEGATIVE_INFINITY
  for (const value of values) {
    if (!Number.isFinite(value)) continue
    if (value < min) min = value
    if (value > max) max = value
  }
  return min <= max ? { min, max } : null
}

/** What the shared axis needs from the chart. `Chart` satisfies it. */
export interface AxisHost {
  getVisibleLogicalRange(): { from: number; to: number }
  readonly dataLayer: { indexToTime(index: number): number | undefined }
}

/**
 * Puts comparison lines on the chart's own price axis (the Price choice).
 *
 * The engine gives every comparison a hidden scale of its own and never the
 * pane's axis, which is right for the rebasing modes and for Own scale. For
 * real prices on one axis this primitive does two things each frame: it widens
 * the price pane's fit to hold the comparison closes on screen (`autoscaleInfo`),
 * and once the pane has fitted it hands every comparison scale exactly the range
 * the price axis shows (`afterAutoscale`). Equal ranges on equal modes map one
 * price to one height, which is all a shared axis is.
 *
 * Only linear and logarithmic axes are shared. A trader who has set the price
 * axis itself to percent is reading percent already, and a price laid over it
 * would be a number in the wrong unit, so the lines keep their own fit.
 */
export class SharedPriceAxis {
  private readonly host: AxisHost
  private readonly primary: () => PriceScale | null
  private readonly sources: () => readonly AxisSource[]
  private readonly logScales = new Set<PriceScale>()

  constructor(
    host: AxisHost,
    primary: () => PriceScale | null,
    sources: () => readonly AxisSource[]
  ) {
    this.host = host
    this.primary = primary
    this.sources = sources
  }

  zOrder(): 'bottom' {
    return 'bottom'
  }

  draw(): void {}

  private shared(): PriceScale | null {
    const primary = this.primary()
    const mode = primary?.options.mode
    return mode === 'linear' || mode === 'logarithmic' ? primary : null
  }

  private visibleTimes(): number[] {
    const range = this.host.getVisibleLogicalRange()
    const first = Math.max(0, Math.ceil(range.from))
    const last = Math.floor(range.to)
    const times: number[] = []
    for (let index = first; index <= last && times.length < 20_000; index++) {
      const time = this.host.dataLayer.indexToTime(index)
      if (time !== undefined && Number.isFinite(time)) times.push(time)
    }
    return times
  }

  autoscaleInfo(): PriceRange | null {
    if (!this.shared()) return null
    const sources = this.sources().filter((source) => source.visible)
    if (!sources.length) return null
    const times = this.visibleTimes()
    function* closes() {
      for (const source of sources)
        for (const time of times) {
          const close = source.closeAt(time)
          if (close !== null) yield close
        }
    }
    return unionRange(null, closes())
  }

  afterAutoscale(): void {
    const primary = this.shared()
    if (!primary) return
    const range = primary.priceRange()
    if (!Number.isFinite(range.min) || !Number.isFinite(range.max)) return
    for (const source of this.sources()) {
      const scale = source.scale
      const log = primary.options.mode === 'logarithmic'
      if (log !== this.logScales.has(scale)) {
        scale.setOptions({ mode: log ? 'logarithmic' : 'linear' })
        if (log) this.logScales.add(scale)
        else this.logScales.delete(scale)
      }
      if (scale.options.inverted !== primary.options.inverted)
        scale.setOptions({ inverted: primary.options.inverted })
      scale.setComputedRange({ min: range.min, max: range.max })
    }
  }

  /** Put back what this changed on the comparison scales, as it comes off the chart. */
  release(): void {
    for (const scale of this.logScales) scale.setOptions({ mode: 'linear' })
    this.logScales.clear()
    for (const source of this.sources())
      if (source.scale.options.inverted) source.scale.setOptions({ inverted: false })
  }
}

/** The legend reading for one comparison: its close and its change from the bar before. */
export function comparisonReading(
  close: number | null,
  previous: number | null
): { close: number; change: number | null } | null {
  if (close === null || !Number.isFinite(close)) return null
  const change =
    previous !== null && Number.isFinite(previous) && previous !== 0
      ? ((close - previous) / previous) * 100
      : null
  return { close, change }
}
