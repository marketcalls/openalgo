/**
 * A backtest's trades, as marks on the chart at the bars they filled on.
 *
 * The report already names every fill: which trade, entry or exit, which way,
 * how many units, at what price, under which tag. This turns that into the
 * chart's own marker vocabulary and does nothing else, so what a reader sees on
 * the price is the same list the trade table under it is drawn from.
 *
 * **The label is two lines, and the order of them is not arbitrary.** The tag
 * sits against the arrow and the signed size sits on the far side, so a column
 * of marks reads outward from the candle in the same order whether the arrow
 * points up or down. A mark above a bar reads size then tag then arrow going
 * down to the price; a mark below reads arrow then tag then size going down and
 * away. The tag is what a reader matches against their own source, so it is the
 * line nearest the thing it is marking.
 *
 * **An entry points at the bar and an exit points away from it.** A buy entry is
 * an arrow up under the bar and a sell entry an arrow down over it, which is the
 * convention every trader already reads. An exit is the same glyph mirrored, so
 * a round trip is a pair that visibly closes.
 *
 * **A fill with no time is dropped.** The chart places a marker by time, and a
 * bar that arrived without one would put the mark at the epoch, dragging the
 * axis flat.
 */

/** One fill of the report's `markers` channel, as much as this reads. */
export interface ReportMarker {
  time?: unknown
  kind?: unknown
  side?: unknown
  units?: unknown
  price?: unknown
  tag?: unknown
  tradeIndex?: unknown
}

/** The chart's own marker shape, the fields this fills. */
export interface ChartMarker {
  time: number
  position: 'aboveBar' | 'belowBar'
  price: number
  shape: 'arrowUp' | 'arrowDown'
  size: 'tiny' | 'small' | 'medium' | 'big'
  color: string
  text: string
  id: string
}

/**
 * The two colours, as tokens rather than literals where the caller has them.
 *
 * Defaults are the chart's own up and down, so a mark reads as the direction it
 * is without a legend. A caller with the app's theme to hand passes its own.
 */
export interface MarkerColours {
  up: string
  down: string
}

const DEFAULT_COLOURS: MarkerColours = { up: '#26a69a', down: '#ef5350' }

/** A number, or nothing. Absence is never zero: zero is a real price and size. */
function finite(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const asNumber = Number(value)
  return Number.isFinite(asNumber) ? asNumber : null
}

/**
 * The signed size a reader sees, in the sign of what the order did.
 *
 * A buy of two reads `+2` and a sell of two reads `-2`, which is the position
 * the order moved toward rather than the arithmetic of the book. Written with
 * an explicit plus, because a column holding `2` and `-2` reads as a typo.
 */
export function signedSize(side: unknown, units: unknown): string {
  const size = finite(units)
  if (size === null) return ''
  const magnitude = Math.abs(size)
  const shown = Number.isInteger(magnitude) ? String(magnitude) : String(magnitude)
  return side === 'sell' ? `-${shown}` : `+${shown}`
}

/**
 * One label: what the fill is against the arrow, the signed size on the far side.
 *
 * **The tag is deliberately not drawn, because it is a name for a position and
 * not a caption for an order.** `close(tag = "longEntry")` means "close whatever
 * longEntry is holding", so the close is *required* to repeat the entry's tag:
 * the language has no other way to say which position to flatten. Drawing it
 * put the same word on both orders of a round trip, where it distinguished
 * nothing, and put the name of a long beside a sell on every reversal.
 *
 * So the label says what a reader actually wants to know and can get nowhere
 * else on the chart: whether this fill opened or closed, and which way.
 *
 * ```
 * Long    +1      opened a long
 * Short   -1      opened a short
 * Exit long  -1   closed a long
 * Exit short +1   closed a short
 * ```
 *
 * Read from `kind` and `side` together, because neither alone says it. A sell
 * is an entry when it opens a short and an exit when it closes a long, and the
 * two are opposite events drawn at opposite ends of a bar.
 *
 * **A caption belongs to the author, and the language has no word for one yet.**
 * There is no `comment` beside `tag` on an order call, so a trader cannot label
 * a fill in their own words the way they can in other languages. Until there
 * is, this describes the fill rather than inventing a name for it. When one
 * arrives, it belongs here, in front of the description rather than instead of
 * it: an author's own word for an order is worth more than a derived one, and
 * the direction is still worth stating beside it.
 */
export function labelFor(marker: ReportMarker, above: boolean): string {
  const size = signedSize(marker.side, marker.units)
  const lines = above ? [size, natureOf(marker)] : [natureOf(marker), size]
  return lines.filter((line) => line !== '').join('\n')
}

/**
 * What one fill did, in the words a trader uses for it.
 *
 * `kind` and `side` are read together because neither alone is the answer: a
 * sell opens a short and closes a long, and calling both "sell" would put the
 * same word on the two opposite ends of a trade.
 */
export function natureOf(marker: ReportMarker): string {
  const selling = marker.side === 'sell'
  if (marker.kind === 'exit') {
    // An exit's side is the side of the order, so the position it closed is the
    // other one: selling closes a long.
    return selling ? 'Exit long' : 'Exit short'
  }
  return selling ? 'Short' : 'Long'
}

/**
 * The report's fills as the chart's markers, in the order they filled.
 *
 * `size` is `small` on purpose. A run over a long history puts many marks on one
 * screen, and the library clamps a glyph to the bar spacing anyway, so asking
 * for a large one buys nothing and hides the candle it is about.
 */
export function chartMarkersFrom(
  markers: readonly ReportMarker[],
  colours: MarkerColours = DEFAULT_COLOURS
): ChartMarker[] {
  const out: ChartMarker[] = []

  for (const marker of markers) {
    const ms = finite(marker.time)
    if (ms === null) continue
    const price = finite(marker.price)
    if (price === null) continue

    const selling = marker.side === 'sell'
    // An entry points at the bar, an exit points away from it, so a round trip
    // is a pair that visibly opens and closes rather than two marks the same
    // way up.
    const entering = marker.kind !== 'exit'
    const above = entering ? selling : !selling

    out.push({
      time: Math.floor(ms / 1000),
      position: above ? 'aboveBar' : 'belowBar',
      price,
      shape: above ? 'arrowDown' : 'arrowUp',
      size: 'small',
      color: selling ? colours.down : colours.up,
      text: labelFor(marker, above),
      // Stable and unique per fill, so redrawing a run replaces its own marks
      // rather than stacking a second set on top of the first.
      id: `bt-${String(marker.tradeIndex ?? 'x')}-${String(marker.kind ?? 'entry')}-${Math.floor(ms / 1000)}`,
    })
  }

  return out
}
