/**
 * Colours handed to the canvas keep their transparency.
 *
 * The app states `--border` as white at a tenth opacity, which is a hairline on
 * a dark panel. `resolveCssColor` used to read the painted pixel as three
 * channels and pass on `rgb(245,255,255)`, so the tenth became a solid
 * near-white line. The chart drew its axis in it, and the chart's own dialogs
 * derive the border of every input, select and textarea from the same value, so
 * every control in them was outlined in near-white while the app's controls
 * beside them wore the tenth. It never looked broken enough to report, which is
 * why it lasted.
 *
 * jsdom has no canvas, so the module's own reads return the string untouched
 * and no test here could reach the arithmetic. This file gives it one: a 1x1
 * context that composites source-over for real, which is the only way to
 * exercise both paints and the solve between them.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { resolveCssColor } from './chartTheme'

type Rgba = [number, number, number, number]

/** Reads the colour formats a canvas accepts. Anything else is unparseable. */
function parse(value: string): Rgba | null {
  const fn = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+))?\s*\)$/i.exec(
    value.trim()
  )
  if (fn) {
    return [Number(fn[1]), Number(fn[2]), Number(fn[3]), fn[4] === undefined ? 1 : Number(fn[4])]
  }
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value.trim())
  if (hex === null) return null
  const digits =
    hex[1].length === 3
      ? [...hex[1]].map((one) => Number.parseInt(one + one, 16))
      : [0, 2, 4].map((at) => Number.parseInt(hex[1].slice(at, at + 2), 16))
  return [digits[0], digits[1], digits[2], 1]
}

/** What a real canvas gives back when `fillStyle` is read. */
function format([r, g, b, a]: Rgba): string {
  const byte = (v: number) => Math.round(v).toString(16).padStart(2, '0')
  return a >= 1 ? `#${byte(r)}${byte(g)}${byte(b)}` : `rgba(${r}, ${g}, ${b}, ${a})`
}

/** A 1x1 rendering context that composites, so the two paints mean something. */
class FakeContext {
  public pixel: Rgba = [0, 0, 0, 0]
  private paint: Rgba = [0, 0, 0, 1]

  public get fillStyle(): string {
    return format(this.paint)
  }

  public set fillStyle(value: string) {
    // A real canvas ignores an unparseable value and keeps the last one, which
    // is the whole of the module's guard against a colour it cannot read.
    const parsed = parse(value)
    if (parsed !== null) this.paint = parsed
  }

  public fillRect(): void {
    const [r, g, b, a] = this.paint
    const [pr, pg, pb, pa] = this.pixel
    const out = a + pa * (1 - a)
    const over = (source: number, under: number): number =>
      out === 0 ? 0 : (source * a + under * pa * (1 - a)) / out
    this.pixel = [over(r, pr), over(g, pg), over(b, pb), out]
  }

  public clearRect(): void {
    this.pixel = [0, 0, 0, 0]
  }

  public getImageData(): { data: number[] } {
    const [r, g, b, a] = this.pixel
    return { data: [Math.round(r), Math.round(g), Math.round(b), Math.round(a * 255)] }
  }
}

let original: typeof HTMLCanvasElement.prototype.getContext

beforeEach(() => {
  original = HTMLCanvasElement.prototype.getContext
  HTMLCanvasElement.prototype.getContext = function getContext() {
    return new FakeContext() as unknown as CanvasRenderingContext2D
  } as typeof HTMLCanvasElement.prototype.getContext
})

afterEach(() => {
  HTMLCanvasElement.prototype.getContext = original
})

describe('a colour with alpha survives the trip to the canvas', () => {
  it('keeps a tenth-opacity border a tenth, and keeps it white', () => {
    // The reported case. Against the behaviour that shipped this is
    // `rgb(245,255,255)`: the right hue at ten times the strength.
    // 0.102 rather than 0.1: alpha crosses the wire as one of 256 steps, and
    // 0.1 is not one of them. A tenth to within half a step is the most any
    // reader of a painted pixel can promise, and the old answer was not out by
    // half a step, it was out by a factor of ten.
    const answer = resolveCssColor('rgba(255, 255, 255, 0.1)')
    expect(answer).toMatch(/^rgba\(255,255,255,0\.1\d*\)$/)
    expect(Number(/([\d.]+)\)$/.exec(answer)?.[1])).toBeCloseTo(0.1, 2)
  })

  it('recovers the colour exactly, not the premultiplied one', () => {
    // Reading a cleared canvas asks the browser to undo its own
    // premultiplication, and at a tenth opacity that rounding turned pure
    // white into 245. Painting over two known backgrounds does not.
    const answer = resolveCssColor('rgba(255, 255, 255, 0.1)')
    expect(answer).toContain('255,255,255')
    expect(answer).not.toContain('245')
  })

  it('handles the alpha values a theme actually uses', () => {
    for (const alpha of [0.05, 0.1, 0.15, 0.25, 0.5, 0.75]) {
      const answer = resolveCssColor(`rgba(120, 180, 240, ${alpha})`)
      const match = /^rgba\((\d+),(\d+),(\d+),([\d.]+)\)$/.exec(answer)
      expect(match, `${alpha} produced ${answer}`).not.toBeNull()
      // The recovered colour is a painted byte divided by the alpha, so the
      // lower the alpha the more a single step of rounding is multiplied: at
      // a twentieth, one step out of 255 is five steps of colour. The
      // tolerance follows the alpha for that reason rather than being one
      // loose number that would let a real error through at half opacity.
      const slack = Math.ceil(1 / alpha)
      expect(Math.abs(Number(match?.[1]) - 120)).toBeLessThanOrEqual(slack)
      expect(Math.abs(Number(match?.[2]) - 180)).toBeLessThanOrEqual(slack)
      expect(Math.abs(Number(match?.[3]) - 240)).toBeLessThanOrEqual(slack)
      expect(Number(match?.[4])).toBeCloseTo(alpha, 2)
    }
  })
})

describe('a colour without alpha is left exactly as it was', () => {
  it('comes back as rgb, with no alpha suffix to parse', () => {
    // Every other token in the theme is opaque, and the chart has parsed
    // `rgb(...)` from this function since it was written. An `rgba(r,g,b,1)`
    // would be correct and would still be a change to what every caller reads.
    expect(resolveCssColor('rgb(10, 10, 10)')).toBe('rgb(10,10,10)')
    expect(resolveCssColor('#a1a1a1')).toBe('rgb(161,161,161)')
  })
})

describe('what it does with a colour it cannot read', () => {
  it('falls back to black rather than passing the string on', () => {
    // The canvas keeps the last `fillStyle` when handed something it cannot
    // parse, so the black set first is what an unreadable colour becomes. The
    // alternative is handing the chart a string it will also fail to parse,
    // at which point something downstream draws in a default nobody chose.
    expect(resolveCssColor('not-a-colour')).toBe('rgb(0,0,0)')
    // And it does not inherit the last colour that WAS readable, which is what
    // a probe element does on its own: assigning a value the browser rejects
    // leaves the old one in place, so the caller would get a real colour from
    // the wrong token with nothing to say so.
    expect(resolveCssColor('#a1a1a1')).toBe('rgb(161,161,161)')
    expect(resolveCssColor('definitely not a colour')).toBe('rgb(0,0,0)')
  })

  it('reports a fully transparent colour as transparent', () => {
    // Not black. A caller that draws it draws nothing, which is what a zero
    // alpha asked for, and `rgb(0,0,0)` would be a visible black line.
    expect(resolveCssColor('rgba(255, 0, 0, 0)')).toBe('rgba(0,0,0,0)')
  })
})
