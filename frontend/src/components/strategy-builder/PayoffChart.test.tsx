import { render, screen, within } from '@testing-library/react'
import type * as PlotlyTypes from 'plotly.js'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { computePayoff, type ScenarioState, type StrategyLeg } from '@/lib/strategyMath'
import { makeFormatCurrency } from '@/lib/utils'
import { PayoffChart } from './PayoffChart'

const plotCapture = vi.hoisted(() => ({
  props: null as {
    data: PlotlyTypes.Data[]
    layout: Partial<PlotlyTypes.Layout>
  } | null,
}))

vi.mock('@/lib/Plot2D', () => ({
  default: (props: { data: PlotlyTypes.Data[]; layout: Partial<PlotlyTypes.Layout> }) => {
    plotCapture.props = props
    return <div data-testid="payoff-plot" />
  },
}))

const NOW = new Date('2026-07-28T10:00:00.000Z')
const BASE_SCENARIO: ScenarioState = {
  spot: 100,
  iv: 20,
  daysElapsed: 0,
  valuationTime: NOW,
}
const formatCurrency = makeFormatCurrency(null)

function leg(
  id: string,
  side: 'BUY' | 'SELL',
  optionType: 'CE' | 'PE',
  strike: number,
  price: number
): StrategyLeg {
  return {
    id,
    segment: 'OPTION',
    side,
    lots: 1,
    lotSize: 1,
    expiry: '04AUG26',
    strike,
    optionType,
    price,
    iv: 20,
    active: true,
    symbol: id,
  }
}

describe('PayoffChart exact geometry', () => {
  beforeEach(() => {
    plotCapture.props = null
  })

  it('PG-08 joins profit and loss fills at the exact breakevens', () => {
    const payoff = computePayoff(
      [
        leg('lp', 'BUY', 'PE', 90, 0.5),
        leg('sp', 'SELL', 'PE', 95, 2),
        leg('sc', 'SELL', 'CE', 105, 2),
        leg('lc', 'BUY', 'CE', 110, 0.5),
      ],
      100,
      7,
      0,
      [90, 110],
      7,
      0,
      20,
      NOW
    )

    render(
      <PayoffChart
        title="Iron Condor"
        scenario={BASE_SCENARIO}
        remainingYears={7 / 365}
        payoff={payoff}
        formatCurrency={formatCurrency}
      />
    )

    const traces = plotCapture.props?.data ?? []
    const profit = traces.find((trace) => trace.name === 'Profit zone')
    const loss = traces.find((trace) => trace.name === 'Loss zone')
    const expiry = traces.find((trace) => trace.name === 'At Expiry')
    expect(profit).toBeDefined()
    expect(loss).toBeDefined()
    expect(expiry).toBeDefined()
    const expiryXs = expiry?.x as number[]
    const profitYs = profit?.y as number[]
    const lossYs = loss?.y as number[]

    expect(expiryXs).toEqual(expect.arrayContaining([90, 92, 95, 105, 108, 110]))
    for (const root of [92, 108]) {
      const index = expiryXs.indexOf(root)
      expect(index).toBeGreaterThanOrEqual(0)
      expect(profitYs[index]).toBe(0)
      expect(lossYs[index]).toBe(0)
    }
  })

  it('PG-06 keeps every sigma marker inside the autoranged curve domain', () => {
    const payoff = computePayoff(
      [leg('call', 'BUY', 'CE', 100, 2)],
      100,
      7,
      0,
      [40, 160],
      12,
      0,
      30,
      NOW
    )

    render(
      <PayoffChart
        title="Long Call"
        scenario={{ ...BASE_SCENARIO, iv: 30 }}
        remainingYears={1}
        payoff={payoff}
        formatCurrency={formatCurrency}
      />
    )

    // No explicit range: an axis pinned to the sample endpoints would be
    // re-supplied on every live tick and would discard the user's zoom. The
    // visible window is the sampled domain because every overlay is clipped
    // into it and the fill traces are unpadded.
    expect(plotCapture.props?.layout.xaxis?.autorange).toBe(true)
    expect(plotCapture.props?.layout.xaxis?.range).toBeUndefined()
    const curveXs = plotCapture.props?.data?.[0]?.x as number[]
    expect(curveXs[0]).toBe(40)
    expect(curveXs.at(-1)).toBe(160)
    const sigmaShapes = plotCapture.props?.layout.shapes?.filter(
      (shape) => shape.xref === 'x' && typeof shape.x0 === 'number'
    )
    expect(sigmaShapes?.every((shape) => Number(shape.x0) >= 40 && Number(shape.x0) <= 160)).toBe(
      true
    )
  })

  it('PG-06 omits physically invalid negative sigma markers', () => {
    const payoff = computePayoff(
      [leg('call', 'BUY', 'CE', 100, 2)],
      100,
      7,
      0,
      [0, 400],
      12,
      0,
      100,
      NOW
    )

    render(
      <PayoffChart
        title="High IV Call"
        scenario={{ ...BASE_SCENARIO, iv: 100 }}
        remainingYears={1}
        payoff={payoff}
        formatCurrency={formatCurrency}
      />
    )

    const xShapes = plotCapture.props?.layout.shapes?.filter((shape) => shape.xref === 'x') ?? []
    const xAnnotations =
      plotCapture.props?.layout.annotations?.filter((annotation) => annotation.xref === 'x') ?? []

    expect(
      xShapes.every(
        (shape) =>
          (typeof shape.x0 !== 'number' || shape.x0 >= 0) &&
          (typeof shape.x1 !== 'number' || shape.x1 >= 0)
      )
    ).toBe(true)
    expect(
      xAnnotations.every((annotation) => typeof annotation.x !== 'number' || annotation.x >= 0)
    ).toBe(true)
  })

  it('uses the shifted scenario for its marker and hand-derived lognormal bands', () => {
    const payoff = computePayoff(
      [leg('call', 'BUY', 'CE', 100, 2)],
      110,
      7,
      0.25,
      [70, 160],
      12,
      0,
      30,
      NOW
    )

    render(
      <PayoffChart
        title="Shifted Call"
        chartIdentity="NFO:NIFTY:04AUG26"
        scenario={{ ...BASE_SCENARIO, spot: 110, iv: 30, daysElapsed: 0.25 }}
        remainingYears={0.25}
        terminalLabel="At First Expiry"
        payoff={payoff}
        formatCurrency={formatCurrency}
      />
    )

    const layout = plotCapture.props?.layout
    expect(layout?.uirevision).toBe('NFO:NIFTY:04AUG26')
    expect(
      layout?.shapes?.some(
        (shape) =>
          shape.type === 'line' && shape.xref === 'x' && shape.x0 === 110 && shape.x1 === 110
      )
    ).toBe(true)

    const bands = layout?.shapes?.filter((shape) => shape.type === 'rect') ?? []
    expect(bands.some((shape) => Math.abs(Number(shape.x0) - 80.5783792325) < 1e-4)).toBe(true)
    expect(bands.some((shape) => Math.abs(Number(shape.x0) - 93.6187202159) < 1e-4)).toBe(true)
  })

  it('keeps zoom for live updates but resets it when the strategy identity changes', () => {
    const payoff = computePayoff(
      [leg('call', 'BUY', 'CE', 100, 2)],
      100,
      7,
      0,
      [80, 120],
      12,
      0,
      20,
      NOW
    )
    const view = render(
      <PayoffChart
        title="Long Call"
        chartIdentity="NFO:NIFTY:04AUG26"
        scenario={BASE_SCENARIO}
        remainingYears={7 / 365}
        payoff={payoff}
        formatCurrency={formatCurrency}
      />
    )

    expect(plotCapture.props?.layout.uirevision).toBe('NFO:NIFTY:04AUG26')
    const initialXaxis = plotCapture.props?.layout.xaxis
    expect(initialXaxis?.autorange).toBe(true)

    view.rerender(
      <PayoffChart
        title="Long Call"
        chartIdentity="NFO:NIFTY:04AUG26"
        scenario={{ ...BASE_SCENARIO, spot: 101 }}
        remainingYears={7 / 365}
        payoff={payoff}
        formatCurrency={formatCurrency}
      />
    )
    expect(plotCapture.props?.layout.uirevision).toBe('NFO:NIFTY:04AUG26')
    // A stable uirevision alone does not preserve zoom. Plotly discards the
    // interaction whenever the supplied axis-range value differs from the one
    // present when the user zoomed, so the range attribute must not drift with
    // spot either. This is the assertion the earlier version of this test was
    // missing, which is why the regression went unnoticed.
    expect(plotCapture.props?.layout.xaxis?.autorange).toBe(true)
    expect(plotCapture.props?.layout.xaxis?.range).toBeUndefined()

    view.rerender(
      <PayoffChart
        title="Long Call"
        chartIdentity="NFO:NIFTY:11AUG26"
        scenario={{ ...BASE_SCENARIO, spot: 101 }}
        remainingYears={14 / 365}
        payoff={payoff}
        formatCurrency={formatCurrency}
      />
    )
    expect(plotCapture.props?.layout.uirevision).toBe('NFO:NIFTY:11AUG26')
  })

  it('labels the selected horizon and gives both curves the same precise hover fields', () => {
    const payoff = computePayoff(
      [leg('call', 'BUY', 'CE', 100, 2)],
      100,
      7,
      0.25,
      [80, 120],
      12,
      0,
      20,
      NOW
    )

    render(
      <PayoffChart
        title="Calendar"
        scenario={{ ...BASE_SCENARIO, daysElapsed: 0.25 }}
        remainingYears={6.75 / 365}
        terminalLabel="At First Expiry"
        payoff={payoff}
        formatCurrency={formatCurrency}
      />
    )

    const curves = (plotCapture.props?.data ?? []).filter(
      (trace) => trace.name === 'At First Expiry' || trace.name === 'T+6h'
    )
    expect(curves).toHaveLength(2)
    for (const curve of curves) {
      expect(curve.hovertemplate).toContain('Underlying: %{customdata[0]}')
      expect(curve.hovertemplate).toContain('Chg. from Scenario: %{customdata[1]}')
      expect(curve.hovertemplate).toContain('P&L: %{customdata[2]}')
    }
  })

  it('formats Delta Exchange hover values in USD without a rupee chart label', () => {
    const payoff = computePayoff(
      [leg('call', 'BUY', 'CE', 100, 2)],
      100,
      7,
      0,
      [80, 120],
      12,
      0,
      20,
      NOW
    )

    render(
      <PayoffChart
        title="USD Call"
        scenario={BASE_SCENARIO}
        remainingYears={7 / 365}
        payoff={payoff}
        formatCurrency={makeFormatCurrency('deltaexchange')}
      />
    )

    const expiry = plotCapture.props?.data.find((trace) => trace.name === 'At Expiry')
    const customdata = expiry?.customdata as unknown as string[][]
    expect(customdata[0][0]).toBe('$80.00')
    expect(customdata[0][2]).toMatch(/^[-$]/)
    expect(plotCapture.props?.layout.yaxis?.title?.text).toBe('Profit / Loss')
    expect(expiry?.hovertemplate).not.toContain('₹')
  })

  it('SB-18 supplements the visual plot with a named summary and representative payoff table', () => {
    const payoff = computePayoff(
      [leg('call', 'BUY', 'CE', 100, 2)],
      100,
      7,
      0,
      [80, 120],
      12,
      0,
      20,
      NOW
    )

    render(
      <PayoffChart
        title="Long Call"
        scenario={BASE_SCENARIO}
        remainingYears={7 / 365}
        payoff={payoff}
        formatCurrency={formatCurrency}
      />
    )

    const region = screen.getByRole('region', { name: 'Long Call payoff analysis' })
    expect(within(region).getByText(/scenario spot/i)).toHaveTextContent('₹100.00')
    expect(within(region).getByRole('status')).toHaveTextContent(/at expiry/i)
    const table = within(region).getByRole('table', { name: /representative payoff values/i })
    expect(within(table).getAllByRole('row').length).toBeGreaterThanOrEqual(4)
    expect(within(table).getAllByRole('row').length).toBeLessThan(10)
  })

  it('SB-18 bounds many breakevens and discloses both summary and table omissions', () => {
    const basePayoff = computePayoff(
      [leg('call', 'BUY', 'CE', 100, 2)],
      100,
      7,
      0,
      [80, 120],
      12,
      0,
      20,
      NOW
    )
    const payoff = {
      ...basePayoff,
      breakevens: [82, 86, 90, 94, 98, 102, 106, 110, 114, 118],
    }

    render(
      <PayoffChart
        title="Many roots"
        scenario={BASE_SCENARIO}
        remainingYears={7 / 365}
        payoff={payoff}
        formatCurrency={formatCurrency}
      />
    )

    const region = screen.getByRole('region', { name: 'Many roots payoff analysis' })
    const breakevenSummary = within(region).getByTestId('breakeven-summary')
    expect(breakevenSummary).toHaveTextContent('4 of 10 shown')
    expect((breakevenSummary.textContent ?? '').split(' (')[0].split(', ')).toHaveLength(4)

    const table = within(region).getByRole('table', { name: /representative payoff values/i })
    expect(within(table).getAllByRole('row')).toHaveLength(8)
    expect(within(region).getByTestId('representative-payoff-disclosure')).toHaveTextContent(
      '7 of 13 representative points shown'
    )
  })
})
