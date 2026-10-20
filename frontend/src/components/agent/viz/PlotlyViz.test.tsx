import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PlotlyViz } from './PlotlyViz'

type Captured = {
  data: unknown[]
  layout: Record<string, unknown>
  config: Record<string, unknown>
}
const captured: { plot2d: Captured | null; plot3d: Captured | null } = {
  plot2d: null,
  plot3d: null,
}

vi.mock('@/lib/Plot2D', () => ({
  default: (props: Captured) => {
    captured.plot2d = props
    return <div data-testid="plot-2d" />
  },
}))
vi.mock('@/lib/Plot3D', () => ({
  default: (props: Captured) => {
    captured.plot3d = props
    return <div data-testid="plot-3d" />
  },
}))

const OI_SPEC = {
  engine: '2d',
  data: [
    { type: 'bar', name: 'Call OI', x: [23800, 23900], y: [10, 20], marker: { color: '#ef4444' } },
    { type: 'bar', name: 'Put OI', x: [23800, 23900], y: [30, null], marker: { color: '#22c55e' } },
  ],
  layout: {
    autosize: true,
    barmode: 'group',
    margin: { l: 56, r: 24, t: 32, b: 48 },
    xaxis: { title: { text: 'Strike' } },
    shapes: [
      { type: 'line', x0: 23850, x1: 23850, yref: 'paper', y0: 0, y1: 1, line: { dash: 'dot' } },
    ],
    annotations: [{ x: 23850, y: 1.02, yref: 'paper', text: 'ATM' }],
  },
  config: { displayModeBar: false, responsive: true },
}

const SURFACE_SPEC = {
  engine: '3d',
  data: [
    {
      type: 'surface',
      x: [23800, 23900],
      y: [5, 12],
      z: [
        [0.12, 0.13],
        [0.14, null],
      ],
      connectgaps: false,
    },
  ],
  layout: { autosize: true },
  config: { displayModeBar: false, responsive: true },
  expiry_labels: ['08SEP26', '15SEP26'],
}

beforeEach(() => {
  captured.plot2d = null
  captured.plot3d = null
})

describe('PlotlyViz', () => {
  it('renders a 2d bar spec through the 2D build and merges the theme underneath it', async () => {
    render(
      <PlotlyViz spec={OI_SPEC} title="NIFTY 08SEP26 open interest" source="option_chain_service" />
    )
    await screen.findByTestId('plot-2d')

    const { layout, config, data } = captured.plot2d as Captured
    // The producer's own keys survive.
    expect(layout.barmode).toBe('group')
    expect((layout.xaxis as Record<string, unknown>).title).toEqual({
      text: 'Strike',
      font: { color: expect.any(String), size: 11 },
    })
    // The theme fills in what the producer left out.
    expect(layout.paper_bgcolor).toBe('rgba(0,0,0,0)')
    expect((layout.font as Record<string, unknown>).color).toBeTruthy()
    expect((layout.yaxis as Record<string, unknown>).gridcolor).toBeTruthy()
    // Uncoloured overlays get a colour; the producer's dash survives.
    const shape = (layout.shapes as Record<string, unknown>[])[0]
    expect(shape.line).toEqual({ color: expect.any(String), width: 1, dash: 'dot' })
    const annotation = (layout.annotations as Record<string, unknown>[])[0]
    expect((annotation.font as Record<string, unknown>).color).toBeTruthy()
    // Meaning-bearing trace colour is untouched, nulls are not coerced.
    expect(data[0]).toEqual(OI_SPEC.data[0])
    expect((data[1] as Record<string, unknown>).y).toEqual([30, null])
    // The mode bar is the renderer's.
    expect(config.displayModeBar).toBe(true)
    expect(config.displaylogo).toBe(false)
    expect(screen.queryByTestId('plot-3d')).toBeNull()
  })

  it('renders a surface through the 3D build, labels the expiry axis and themes the colorscale', async () => {
    render(
      <PlotlyViz
        spec={SURFACE_SPEC}
        title="NIFTY implied volatility surface"
        source="vol_surface_service"
      />
    )
    await screen.findByTestId('plot-3d')

    const { layout, data } = captured.plot3d as Captured
    const scene = layout.scene as Record<string, unknown>
    expect((scene.yaxis as Record<string, unknown>).ticktext).toEqual(['08SEP26', '15SEP26'])
    expect((scene.yaxis as Record<string, unknown>).tickvals).toEqual([5, 12])
    const surface = data[0] as Record<string, unknown>
    expect(surface.colorscale).toBeTruthy()
    expect(surface.customdata).toEqual([
      ['08SEP26', '08SEP26'],
      ['15SEP26', '15SEP26'],
    ])
    expect(surface.z).toEqual(SURFACE_SPEC.data[0].z)
    expect(surface.connectgaps).toBe(false)
    expect(screen.queryByTestId('plot-2d')).toBeNull()
  })

  it('uses the 3D build when a spec declares 2d but carries a surface', async () => {
    render(<PlotlyViz spec={{ ...SURFACE_SPEC, engine: '2d' }} title="x" />)
    await screen.findByTestId('plot-3d')
  })

  it.each([
    [null, 'without a specification'],
    [{}, 'no data'],
    [{ engine: '2d', data: [] }, 'no data'],
    [{ engine: '2d', data: 'nope' }, 'no data'],
  ])('renders a plain message for a malformed spec (%#)', (spec, fragment) => {
    render(<PlotlyViz spec={spec} title="Broken" source="gex_service" />)
    expect(screen.getByText(new RegExp(fragment, 'i'))).toBeInTheDocument()
    expect(screen.queryByTestId('plot-2d')).toBeNull()
  })

  it('names the region and shows provenance', async () => {
    render(<PlotlyViz spec={OI_SPEC} title="NIFTY open interest" source="option_chain_service" />)
    await screen.findByTestId('plot-2d')
    expect(screen.getByRole('region', { name: 'NIFTY open interest' })).toBeInTheDocument()
    expect(screen.getByText('from option chain')).toBeInTheDocument()
  })

  it('keeps an accessible name with the header hidden', async () => {
    render(<PlotlyViz spec={OI_SPEC} title="Hidden header" showHeader={false} />)
    await screen.findByTestId('plot-2d')
    expect(screen.getByRole('region', { name: 'Hidden header' })).toBeInTheDocument()
    expect(screen.queryByText('from option chain')).toBeNull()
  })

  it('does not let a literal __proto__ key in a spec layout pollute Object.prototype', async () => {
    const hostile = { ...OI_SPEC, layout: JSON.parse('{"__proto__": {"polluted": true}}') }
    render(<PlotlyViz spec={hostile} title="x" />)
    await screen.findByTestId('plot-2d')
    expect(({} as Record<string, unknown>).polluted).toBeUndefined()
  })
})
