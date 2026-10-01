/**
 * The colour a comparison line gets.
 *
 * Two failures, both reported from a live chart and both invisible to a test
 * that only checks a colour came back.
 *
 * The first comparison was painted `#4f8cff`, which is the dark theme's own
 * `lineColor`: the colour the engine gives any line nobody coloured. So the
 * one comparison most people ever add looked like something the chart had done
 * by itself. And the colour was chosen by counting what already existed, so
 * adding two, removing the first and adding a third handed the third the
 * second's colour.
 *
 * Both are properties rather than examples, because the palette is exactly the
 * kind of constant somebody adjusts by eye later and a fixed expectation would
 * just be edited to match.
 */

import { describe, expect, it } from 'vitest'
import { COMPARISON_PALETTE, isReservedHue, nextComparisonColor } from './comparisonColors'

/** The hue of a `#rrggbb`, in degrees. */
function hueOf(colour: string): number {
  const [r, g, b] = [1, 3, 5].map((at) => Number.parseInt(colour.slice(at, at + 2), 16) / 255)
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  if (max === min) return 0
  const d = max - min
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4
  return (((h * 60) % 360) + 360) % 360
}

/** The colours `count` comparisons get, added one after another. */
function series(count: number): string[] {
  const out: string[] = []
  for (let i = 0; i < count; i++) out.push(nextComparisonColor(out))
  return out
}

describe('a comparison is never the colour the chart draws by default', () => {
  it('reserves the hue of both themes line colour', () => {
    // The two values in `theme.ts`. Stated here as the literals a reader can
    // check against the engine, not imported, because the point is that this
    // module's idea of them is right.
    expect(isReservedHue(hueOf('#4f8cff'))).toBe(true) // dark
    expect(isReservedHue(hueOf('#2962ff'))).toBe(true) // light
  })

  it('never hands one out, not from the palette and not from the generator', () => {
    // 60 is well past the palette, so this covers the generated tail too.
    for (const colour of series(60)) {
      expect(isReservedHue(hueOf(colour))).toBe(false)
      expect(colour.toLowerCase()).not.toBe('#4f8cff')
      expect(colour.toLowerCase()).not.toBe('#2962ff')
    }
  })

  it('keeps every curated entry clear of them too', () => {
    // The palette is edited by hand and by eye. This is what stops a pleasing
    // blue being added to it one afternoon.
    for (const colour of COMPARISON_PALETTE) {
      expect(isReservedHue(hueOf(colour))).toBe(false)
    }
  })
})

describe('no two comparisons share a colour', () => {
  it('gives sixty comparisons sixty different colours', () => {
    const colours = series(60)
    expect(new Set(colours).size).toBe(60)
  })

  it('reuses the colour of one that was removed, and nothing else', () => {
    // The counting bug, exactly: add two, drop the first, add a third. By
    // count the third is `palette[1]`, which the second already has. Choosing
    // against what is taken frees the first colour and keeps the second.
    const first = nextComparisonColor([])
    const second = nextComparisonColor([first])
    expect(second).not.toBe(first)
    const third = nextComparisonColor([second])
    expect(third).not.toBe(second)
    expect(third).toBe(first)
  })

  it('does not care how a colour was spelled on the way back', () => {
    // A colour that has been through a workspace document may come back in
    // another case. Compared as written, it would read as unused and be handed
    // out twice: two lines the same colour, from a round trip.
    const first = COMPARISON_PALETTE[0]
    expect(nextComparisonColor([first.toUpperCase()])).not.toBe(first)
    expect(nextComparisonColor([` ${first} `])).not.toBe(first)
  })

  it('ignores junk in the taken list rather than treating it as a colour', () => {
    // The list is whatever the chart is holding, which may include a spec that
    // never got a colour. An empty string is not a colour anything is using.
    expect(nextComparisonColor(['', '   '])).toBe(COMPARISON_PALETTE[0])
  })

  it('hands out the curated colours before it generates any', () => {
    expect(series(COMPARISON_PALETTE.length)).toEqual([...COMPARISON_PALETTE])
  })

  it('generates a colour the chart can actually use', () => {
    // Every generated entry has to be a `#rrggbb` the engine parses. A hue
    // conversion off by a sector produces a plausible-looking string that is
    // the wrong colour, which no length check would catch, so the hue is read
    // back out of the string and compared with the one asked for.
    for (const colour of series(40).slice(COMPARISON_PALETTE.length)) {
      expect(colour).toMatch(/^#[0-9a-f]{6}$/)
    }
    const generated = series(12)[COMPARISON_PALETTE.length]
    // The first generated hue is in the palette's widest gap, not beside a
    // colour already on the chart.
    for (const curated of COMPARISON_PALETTE) {
      const gap = Math.abs(hueOf(generated) - hueOf(curated))
      expect(Math.min(gap, 360 - gap)).toBeGreaterThan(25)
    }
  })
})
