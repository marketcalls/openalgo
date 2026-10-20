/**
 * The colour a comparison line is drawn in.
 *
 * A comparison is only readable if you can tell which line is which, and there
 * are two ways that fails. One is two comparisons sharing a colour. The other
 * is subtler and was the reported one: a comparison drawn in the **chart's own
 * default line colour**, which on the dark theme is the same blue the engine
 * paints any line nobody coloured. The first comparison was handed exactly that
 * blue, so it looked like a line the chart had drawn by accident rather than an
 * instrument somebody asked for, and a comparison that arrived with no colour
 * at all was indistinguishable from it.
 *
 * So this module owns two rules, and they are the whole of it:
 *
 * 1. **Never a colour the chart would have used anyway.** The reserved hues
 *    below are the engine's own default line colours, on either theme.
 * 2. **Never a colour already on this chart.** Chosen against what is taken,
 *    not by counting: counting hands the third comparison the second's colour
 *    as soon as the first is removed, which is the common way to use this.
 */

/** One colour as hue, saturation and lightness, the space the spacing is in. */
interface Hsl {
  h: number
  s: number
  l: number
}

/**
 * Hues the chart already spends on lines, which a comparison must stay clear of.
 *
 * These are `theme.lineColor` for the dark and light themes: the blue the
 * engine paints any line nobody coloured. Hues rather than exact strings,
 * because a near miss is the problem: a comparison two degrees off that blue
 * reads as that blue, and nobody counting lines on a chart is matching hex.
 *
 * The candle colours are deliberately absent. A candle is a filled body and a
 * comparison is a hairline, so they do not get confused the way two lines do,
 * and reserving their hues as well would cost the palette the whole green half
 * of the wheel for a confusion nobody has.
 */
const RESERVED_HUES = [
  219, // default line, dark theme
  225, // default line, light theme
]

/** How far from a reserved hue a comparison colour has to sit, in degrees. */
const CLEARANCE = 25

/**
 * The curated colours, in the order they are handed out.
 *
 * Five, so the common chart gets colours somebody chose rather than colours a
 * formula produced. Five rather than a longer list because the gaps are what
 * make them tell apart, and a sixth curated entry would have had to sit beside
 * one of these: the generator below fills in past that, and nobody comparing
 * six instruments at once is reading them by colour anyway.
 *
 * Every one is checked against the reserved hues by a test rather than by this
 * sentence, because a palette entry is exactly the kind of constant somebody
 * adjusts by eye later.
 */
export const COMPARISON_PALETTE: readonly string[] = [
  '#f5a623', // amber
  '#a3e635', // lime
  '#22d3ee', // cyan
  '#a78bfa', // violet
  '#f472b6', // pink
]

/** Shortest distance between two hues on the wheel, in degrees. */
function hueGap(a: number, b: number): number {
  const raw = Math.abs((((a - b) % 360) + 360) % 360)
  return Math.min(raw, 360 - raw)
}

/** Whether a hue is far enough from every colour the chart spends itself. */
export function isReservedHue(hue: number): boolean {
  return RESERVED_HUES.some((reserved) => hueGap(hue, reserved) < CLEARANCE)
}

function hex(value: number): string {
  return Math.round(value * 255)
    .toString(16)
    .padStart(2, '0')
}

/** An HSL triple as the `#rrggbb` the chart takes. */
function toHex({ h, s, l }: Hsl): string {
  const c = (1 - Math.abs(2 * l - 1)) * s
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1))
  const m = l - c / 2
  const sector = Math.floor((((h % 360) + 360) % 360) / 60)
  const [r, g, b] = [
    [c, x, 0],
    [x, c, 0],
    [0, c, x],
    [0, x, c],
    [x, 0, c],
    [c, 0, x],
  ][sector]
  return `#${hex(r + m)}${hex(g + m)}${hex(b + m)}`
}

/**
 * The golden angle, which is what makes an unbounded sequence of hues spread
 * out instead of clustering. Stepping by a whole fraction of the circle repeats;
 * stepping by this never lands twice in the same place and keeps consecutive
 * entries far apart, which is the property that matters when the colours are
 * handed out one at a time and seen together.
 */
const GOLDEN_ANGLE = 137.508

/**
 * Where the generated hues start.
 *
 * Chosen so the first one lands around 135 degrees, the widest gap the palette
 * leaves, rather than a degree or two off a colour already on the chart.
 */
const GENERATED_SEED = 357.5

/**
 * A colour for the next comparison: unused, and never one the chart spends.
 *
 * `taken` is every colour already on this chart. Compared case-insensitively,
 * because a colour that has been through a workspace document and back may not
 * come back in the case it went out in, and two lines the same colour is
 * exactly what this exists to prevent.
 */
export function nextComparisonColor(taken: Iterable<string>): string {
  const used = new Set<string>()
  for (const colour of taken) {
    if (typeof colour === 'string' && colour.trim()) used.add(colour.trim().toLowerCase())
  }

  for (const colour of COMPARISON_PALETTE) {
    if (!used.has(colour)) return colour
  }

  // Past the palette. Bounded rather than `while (true)`: a caller that somehow
  // holds every colour this can produce gets the last one tried instead of a
  // frozen tab, and a duplicate colour is a far smaller problem than a hang.
  let hue = GENERATED_SEED
  let candidate = COMPARISON_PALETTE[0]
  for (let attempt = 0; attempt < 512; attempt++) {
    hue = (hue + GOLDEN_ANGLE) % 360
    if (isReservedHue(hue)) continue
    candidate = toHex({ h: hue, s: 0.72, l: 0.6 })
    if (!used.has(candidate)) return candidate
  }
  return candidate
}
