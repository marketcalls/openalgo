import { describe, expect, it } from 'vitest'
import {
  previewValue,
  STRATEGY_TEMPLATES,
  type StrategyTemplate,
  templatePreviewPath,
} from './strategyTemplates'

function template(id: string) {
  const found = STRATEGY_TEMPLATES.find((candidate) => candidate.id === id)
  if (!found) throw new Error(`Missing strategy template: ${id}`)
  return found
}

/** TemplateGrid renders the path in a viewBox of 0 0 100 40 with the zero line at y = 20. */
const VIEWBOX_WIDTH = 100
const VIEWBOX_HEIGHT = 40
const ZERO_LINE_Y = 20
/** Half the amplitude the icon is allowed to use, so a 2.2 stroke stays inside the viewBox. */
const AMPLITUDE = 16

interface PathPoint {
  command: string
  x: number
  y: number
}

function parsePath(path: string): PathPoint[] {
  return path
    .trim()
    .split(/\s+/)
    .map((token) => {
      const match = /^([ML])(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$/.exec(token)
      if (!match) throw new Error(`Unparseable path token: ${token}`)
      return { command: match[1], x: Number(match[2]), y: Number(match[3]) }
    })
}

function distinctStrikes(candidate: StrategyTemplate): number[] {
  return Array.from(
    new Set(
      candidate.legs.map((leg) => candidate.referenceSpot + leg.strikeOffset * candidate.strikeStep)
    )
  ).sort((left, right) => left - right)
}

/** Value-space samples: profit is up, so a smaller y is a larger value. */
function pathValues(points: PathPoint[]): number[] {
  return points.map((point) => ZERO_LINE_Y - point.y)
}

function interiorPeaks(points: PathPoint[]): number {
  const values = pathValues(points)
  let peaks = 0
  for (let index = 1; index < values.length - 1; index++) {
    if (values[index] > values[index - 1] + 0.05 && values[index] > values[index + 1] + 0.05) {
      peaks++
    }
  }
  return peaks
}

function interiorTroughs(points: PathPoint[]): number {
  const values = pathValues(points)
  let troughs = 0
  for (let index = 1; index < values.length - 1; index++) {
    if (values[index] < values[index - 1] - 0.05 && values[index] < values[index + 1] - 0.05) {
      troughs++
    }
  }
  return troughs
}

function hasInteriorPlateauAbove(points: PathPoint[], floor: number): boolean {
  const values = pathValues(points)
  for (let index = 1; index < points.length - 2; index++) {
    const flat = Math.abs(values[index] - values[index + 1]) < 0.05
    const wide = points[index + 1].x - points[index].x > 5
    if (flat && wide && values[index] > floor) return true
  }
  return false
}

const COMPUTED_TEMPLATES = STRATEGY_TEMPLATES.filter((candidate) => !candidate.illustrativePreview)

describe('strategy template previews', () => {
  it('SB-20 shows the Jade Lizard left-tail loss implied by its short put', () => {
    const jadeLizard = template('jade_lizard')

    expect(previewValue(jadeLizard, 0)).toBeLessThan(
      previewValue(jadeLizard, jadeLizard.referenceSpot)
    )
  })

  it('derives same-expiry preview topology from the normalized legs', () => {
    const longCall = template('long_call')
    const shortCall = {
      ...longCall,
      legs: longCall.legs.map((leg) => ({ ...leg, side: 'SELL' as const })),
    }

    expect(templatePreviewPath(shortCall)).not.toBe(templatePreviewPath(longCall))
    expect(longCall.payoffPath).toBe(templatePreviewPath(longCall))
  })

  it('marks multi-expiry previews as illustrative and keeps same-expiry previews computed', () => {
    for (const candidate of STRATEGY_TEMPLATES) {
      const isMultiExpiry = candidate.legs.some((leg) => (leg.expiryOffset ?? 0) > 0)
      expect(candidate.illustrativePreview).toBe(isMultiExpiry)
    }
  })

  it('keeps exactly the three calendars on a hand-drawn illustrative path', () => {
    const illustrative = STRATEGY_TEMPLATES.filter(
      (candidate) => candidate.illustrativePreview
    ).map((candidate) => candidate.id)

    expect(illustrative).toEqual(['call_calendar', 'put_calendar', 'diagonal_calendar'])
  })

  it('is pure and deterministic across repeated calls', () => {
    for (const candidate of COMPUTED_TEMPLATES) {
      expect(templatePreviewPath(candidate)).toBe(templatePreviewPath(candidate))
      expect(candidate.payoffPath).toBe(templatePreviewPath(candidate))
    }
  })
})

describe('mini payoff icon geometry', () => {
  it.each(STRATEGY_TEMPLATES)('$id draws inside the TemplateGrid viewBox', (candidate) => {
    const points = parsePath(candidate.payoffPath)

    expect(points.length).toBeGreaterThanOrEqual(3)
    expect(points[0].command).toBe('M')
    expect(points.slice(1).every((point) => point.command === 'L')).toBe(true)
    for (const point of points) {
      expect(Number.isFinite(point.x)).toBe(true)
      expect(Number.isFinite(point.y)).toBe(true)
      expect(point.x).toBeGreaterThanOrEqual(0)
      expect(point.x).toBeLessThanOrEqual(VIEWBOX_WIDTH)
      expect(point.y).toBeGreaterThanOrEqual(0)
      expect(point.y).toBeLessThanOrEqual(VIEWBOX_HEIGHT)
    }
    // x is the underlying axis, so vertices never run backwards
    for (let index = 1; index < points.length; index++) {
      expect(points[index].x).toBeGreaterThanOrEqual(points[index - 1].x)
    }
  })

  it.each(COMPUTED_TEMPLATES)('$id spans the full width of the icon', (candidate) => {
    const points = parsePath(candidate.payoffPath)

    expect(points[0].x).toBe(0)
    expect(points[points.length - 1].x).toBe(VIEWBOX_WIDTH)
  })

  it.each(
    COMPUTED_TEMPLATES
  )('$id keeps the drawn curve within the icon amplitude', (candidate) => {
    const points = parsePath(candidate.payoffPath)

    for (const point of points) {
      expect(point.y).toBeGreaterThanOrEqual(ZERO_LINE_Y - AMPLITUDE)
      expect(point.y).toBeLessThanOrEqual(ZERO_LINE_Y + AMPLITUDE)
    }
  })

  it.each(COMPUTED_TEMPLATES)('$id is not drawn as a flat horizontal line', (candidate) => {
    const ys = parsePath(candidate.payoffPath).map((point) => point.y)

    // an unbounded tail must not squash the rest of the shape into a sliver
    expect(Math.max(...ys) - Math.min(...ys)).toBeGreaterThanOrEqual(0.6 * 2 * AMPLITUDE)
  })

  it.each(COMPUTED_TEMPLATES)('$id crosses the zero line', (candidate) => {
    const ys = parsePath(candidate.payoffPath).map((point) => point.y)

    expect(ys.some((y) => y < ZERO_LINE_Y)).toBe(true)
    expect(ys.some((y) => y > ZERO_LINE_Y)).toBe(true)
  })

  it.each(COMPUTED_TEMPLATES)('$id puts one vertex on each leg strike', (candidate) => {
    const points = parsePath(candidate.payoffPath)

    // vertices are the two window edges plus every distinct strike; the payoff
    // is piecewise linear and kinks only at strikes, so nothing else is needed
    expect(points.length).toBe(distinctStrikes(candidate).length + 2)
  })
})

describe('mini payoff icon window (regression for the razor-thin spike)', () => {
  it.each(
    COMPUTED_TEMPLATES
  )('$id draws its strike structure well inside the icon, not against an edge', (candidate) => {
    const interior = parsePath(candidate.payoffPath)
      .slice(1, -1)
      .map((point) => point.x)

    expect(interior.length).toBeGreaterThan(0)
    expect(Math.min(...interior)).toBeGreaterThanOrEqual(5)
    expect(Math.max(...interior)).toBeLessThanOrEqual(95)
  })

  it.each(
    COMPUTED_TEMPLATES.filter((candidate) => distinctStrikes(candidate).length > 1)
  )('$id fills at least 30% of the icon width with its strike structure', (candidate) => {
    const interior = parsePath(candidate.payoffPath)
      .slice(1, -1)
      .map((point) => point.x)

    // The old fixed 0..200 spot window put every butterfly and vertical
    // inside 4-16% of the icon, which drew a razor-thin spike between two
    // long flat lines. The window is now derived per template.
    expect(Math.max(...interior) - Math.min(...interior)).toBeGreaterThanOrEqual(30)
  })

  it.each(
    COMPUTED_TEMPLATES.filter((candidate) => distinctStrikes(candidate).length === 1)
  )('$id centres its single kink rather than parking it at an edge', (candidate) => {
    const interior = parsePath(candidate.payoffPath)
      .slice(1, -1)
      .map((point) => point.x)

    expect(interior).toHaveLength(1)
    expect(interior[0]).toBeGreaterThanOrEqual(20)
    expect(interior[0]).toBeLessThanOrEqual(80)
  })

  it('scales the window to the template instead of sharing one fixed spot range', () => {
    const widths = COMPUTED_TEMPLATES.map((candidate) => {
      const strikes = distinctStrikes(candidate)
      return strikes[strikes.length - 1] - strikes[0]
    })

    // Batman spans 120 normalized points and a vertical spans 8, so a single
    // window can never suit both.
    expect(
      Math.max(...widths) / Math.max(1, Math.min(...widths.filter((w) => w > 0)))
    ).toBeGreaterThan(10)
  })
})

describe('mini payoff icon shape', () => {
  it('draws a long call rising and a short call falling', () => {
    const rising = pathValues(parsePath(template('long_call').payoffPath))
    const falling = pathValues(parsePath(template('short_call').payoffPath))

    for (let index = 1; index < rising.length; index++) {
      expect(rising[index]).toBeGreaterThanOrEqual(rising[index - 1] - 0.05)
    }
    for (let index = 1; index < falling.length; index++) {
      expect(falling[index]).toBeLessThanOrEqual(falling[index - 1] + 0.05)
    }
  })

  it('draws a long put falling and a short put rising', () => {
    const falling = pathValues(parsePath(template('long_put').payoffPath))
    const rising = pathValues(parsePath(template('short_put').payoffPath))

    for (let index = 1; index < falling.length; index++) {
      expect(falling[index]).toBeLessThanOrEqual(falling[index - 1] + 0.05)
    }
    for (let index = 1; index < rising.length; index++) {
      expect(rising[index]).toBeGreaterThanOrEqual(rising[index - 1] - 0.05)
    }
  })

  it('draws a long straddle as a V and a short straddle inverted', () => {
    const longStraddle = parsePath(template('long_straddle').payoffPath)
    const shortStraddle = parsePath(template('short_straddle').payoffPath)

    expect(interiorTroughs(longStraddle)).toBe(1)
    expect(interiorPeaks(longStraddle)).toBe(0)
    expect(interiorPeaks(shortStraddle)).toBe(1)
    expect(interiorTroughs(shortStraddle)).toBe(0)
  })

  it('draws every butterfly with a single interior profit peak', () => {
    for (const id of [
      'bullish_butterfly',
      'bearish_butterfly',
      'call_butterfly',
      'put_butterfly',
      'long_iron_fly',
    ]) {
      const points = parsePath(template(id).payoffPath)

      expect(interiorPeaks(points)).toBe(1)
      expect(Math.min(...points.map((point) => point.y))).toBeLessThan(ZERO_LINE_Y)
    }
  })

  it('draws every condor with a profit plateau', () => {
    for (const id of ['bullish_condor', 'bearish_condor', 'long_iron_condor']) {
      expect(hasInteriorPlateauAbove(parsePath(template(id).payoffPath), 0)).toBe(true)
    }
  })

  it('draws the two-peaked strategies with two peaks', () => {
    for (const id of ['batman_strategy', 'double_fly']) {
      expect(interiorPeaks(parsePath(template(id).payoffPath))).toBe(2)
    }
  })

  it('draws a synthetic long as a straight line through the zero point', () => {
    const points = parsePath(template('long_synthetic').payoffPath)

    expect(points).toHaveLength(3)
    expect(points[1].y).toBeCloseTo(ZERO_LINE_Y, 5)
    expect(points[0].y).toBeGreaterThan(ZERO_LINE_Y)
    expect(points[2].y).toBeLessThan(ZERO_LINE_Y)
  })
})

describe('preview premium', () => {
  it('prices a bought option as a debit so the curve starts below zero', () => {
    const longCall = template('long_call')

    expect(previewValue(longCall, longCall.referenceSpot)).toBeLessThan(0)
  })

  it('prices a sold straddle as a credit so the curve starts above zero', () => {
    const shortStraddle = template('short_straddle')

    expect(previewValue(shortStraddle, shortStraddle.referenceSpot)).toBeGreaterThan(0)
  })

  it('keeps the modelled premium convex so a long butterfly costs a debit', () => {
    const butterfly = template('call_butterfly')
    const body = butterfly.referenceSpot
    const wing = butterfly.strikeStep * 2

    // debit at the wings, profit capped below the wing width at the body
    expect(previewValue(butterfly, body - wing)).toBeLessThan(0)
    expect(previewValue(butterfly, body + wing)).toBeLessThan(0)
    expect(previewValue(butterfly, body)).toBeGreaterThan(0)
    expect(previewValue(butterfly, body)).toBeLessThan(wing)
  })

  it('keeps the modelled premium convex so a long call condor costs a debit', () => {
    const condor = template('bullish_condor')
    const strikes = distinctStrikes(condor)

    expect(previewValue(condor, strikes[0])).toBeLessThan(0)
    expect(previewValue(condor, strikes[strikes.length - 1])).toBeLessThan(0)
    expect(previewValue(condor, strikes[1])).toBeGreaterThan(0)
  })

  it('satisfies put-call parity, so a synthetic long is free at the reference spot', () => {
    const synthetic = template('long_synthetic')

    expect(previewValue(synthetic, synthetic.referenceSpot)).toBeCloseTo(0, 9)
  })
})

describe('strategy template copy', () => {
  it('keeps downside claims physically bounded at an underlying price of zero', () => {
    const allTemplateCopy = STRATEGY_TEMPLATES.map((candidate) => candidate.description).join(' ')

    expect(allTemplateCopy).not.toMatch(/unlimited downside/i)
  })

  it('does not guarantee a credit or debit before live premiums are known', () => {
    const allTemplateCopy = STRATEGY_TEMPLATES.map((candidate) => candidate.description).join(' ')

    expect(allTemplateCopy).not.toMatch(/\bnet (?:credit|debit) trade\b/i)
    expect(allTemplateCopy).not.toMatch(/\bsmall (?:credit|debit)\b/i)
  })

  it('describes calendar previews as illustrative because the far leg retains time value', () => {
    for (const id of ['call_calendar', 'put_calendar', 'diagonal_calendar']) {
      const candidate = template(id)
      expect(candidate.description).toMatch(/residual time value/i)
      expect(candidate.illustrativePreview).toBe(true)
    }
  })
})
