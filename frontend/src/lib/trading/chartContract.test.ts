import { describe, expect, it } from 'vitest'
import type { AgentChartCommand } from '@/lib/agent/stream'
import {
  type AgentDrawingSurface,
  agentGroupOf,
  applyChartCommands,
  describeDrawings,
  isAgentDrawingId,
} from './chartContract'

/** A drawing as the controller stores it, with only what these tests read. */
interface Stored {
  id: string
  tool: string
  points: { time: number; price: number }[]
  style: Record<string, unknown>
}

/**
 * A stand-in for `DrawingController`.
 *
 * The three methods the contract is allowed to reach, backed by an array, so a
 * command's effect on the chart is a list that can be asserted on. `remove`
 * splices, which is what makes the "removing while walking the live array"
 * hazard real here rather than only in production.
 */
function surface(initial: Partial<Stored>[] = []) {
  const items: Stored[] = initial.map((item) => ({
    id: item.id ?? 'd0',
    tool: item.tool ?? 'trend-line',
    points: item.points ?? [],
    style: item.style ?? {},
  }))
  const api: AgentDrawingSurface & { items: Stored[] } = {
    items,
    drawings: () => items,
    add: (drawing) => {
      const stored = drawing as unknown as Stored
      items.push(stored)
      return stored
    },
    remove: (id) => {
      const index = items.findIndex((item) => item.id === id)
      if (index < 0) return false
      items.splice(index, 1)
      return true
    },
  }
  return api
}

/** An operator drawing: a terminal-generated id, which never starts with "ai:". */
const OPERATOR: Partial<Stored> = {
  id: 'd7',
  tool: 'trend-line',
  points: [
    { time: 1775508803, price: 1420 },
    { time: 1787604803, price: 1290 },
  ],
  style: { text: 'watch this breakout' },
}

function drawLevels(): AgentChartCommand {
  return {
    op: 'draw',
    group: 'levels',
    shapes: [
      { kind: 'level', price: 1271, tone: 'bullish', time: 1783468800, ray: true },
      { kind: 'level', price: 1328.6, tone: 'bearish' },
    ],
  }
}

describe('applyChartCommands', () => {
  it('draws each shape under its own namespaced id', () => {
    const chart = surface()
    expect(applyChartCommands(chart, [drawLevels()])).toBe(true)

    expect(chart.items.map((item) => item.id)).toEqual(['ai:levels:0', 'ai:levels:1'])
    expect(chart.items.map((item) => item.tool)).toEqual(['horizontal-ray', 'horizontal-line'])
    expect(chart.items[0].points).toEqual([{ time: 1783468800, price: 1271 }])
    // Tone resolves to a colour here, not on the wire.
    expect(chart.items[0].style.color).toBe('#26a69a')
    expect(chart.items[1].style.color).toBe('#ef5350')
  })

  it('maps every shape kind onto a drawing tool', () => {
    const chart = surface()
    applyChartCommands(chart, [
      {
        op: 'draw',
        group: 'zone',
        shapes: [
          {
            kind: 'trendline',
            from: { time: 1, price: 10 },
            to: { time: 2, price: 20 },
            extend_right: true,
          },
          { kind: 'zone', from: { time: 1, price: 10 }, to: { time: 2, price: 20 } },
          { kind: 'marker', at: { time: 3, price: 30 }, text: 'doji' },
        ],
      },
    ])

    expect(chart.items.map((item) => item.tool)).toEqual(['trend-line', 'rectangle', 'price-label'])
    expect(chart.items[0].style.extendRight).toBe(true)
    expect(chart.items[1].style.fill).toBe(true)
    expect(chart.items[2].style.text).toBe('doji')
  })

  it('anchors a level with no time of its own to the terminal last bar', () => {
    const chart = surface()
    applyChartCommands(
      chart,
      [{ op: 'draw', group: 'levels', shapes: [{ kind: 'level', price: 5 }] }],
      {
        anchorTime: 1788393600,
      }
    )
    expect(chart.items[0].points).toEqual([{ time: 1788393600, price: 5 }])
  })

  it('replaces a group rather than stacking on it', () => {
    const chart = surface()
    applyChartCommands(chart, [drawLevels()])
    applyChartCommands(chart, [drawLevels()])
    expect(chart.items).toHaveLength(2)
  })

  it('treats an empty shape list as clearing that group', () => {
    const chart = surface()
    applyChartCommands(chart, [drawLevels()])
    applyChartCommands(chart, [{ op: 'draw', group: 'levels', shapes: [] }])
    expect(chart.items).toHaveLength(0)
  })

  it('ignores an unknown op instead of throwing', () => {
    const chart = surface([OPERATOR])
    expect(() =>
      applyChartCommands(chart, [
        { op: 'set_symbol', symbol: 'INFY' },
        { op: '', group: 'levels' },
      ])
    ).not.toThrow()
    expect(applyChartCommands(chart, [{ op: 'set_symbol', symbol: 'INFY' }])).toBe(false)
    expect(chart.items.map((item) => item.id)).toEqual(['d7'])
  })

  it('skips an unknown shape kind and still draws its siblings', () => {
    const chart = surface()
    applyChartCommands(chart, [
      {
        op: 'draw',
        group: 'patterns',
        shapes: [
          { kind: 'hologram', at: { time: 1, price: 2 } },
          { kind: 'marker', at: { time: 3, price: 4 }, text: 'inside bar' },
        ],
      },
    ])
    // The second shape keeps index 1: ids come from the wire position, so a
    // skipped shape must not silently renumber the ones after it.
    expect(chart.items.map((item) => item.id)).toEqual(['ai:patterns:1'])
  })

  it('drops a shape whose anchor is unusable', () => {
    const chart = surface()
    applyChartCommands(chart, [
      {
        op: 'draw',
        group: 'trendline',
        shapes: [
          { kind: 'trendline', from: { time: 1, price: null }, to: { time: 2, price: 20 } },
          { kind: 'level', price: Number.NaN },
        ],
      },
    ])
    expect(chart.items).toHaveLength(0)
  })

  it('refuses a group name that could forge an id', () => {
    const chart = surface()
    applyChartCommands(chart, [
      { op: 'draw', group: 'levels:0', shapes: [{ kind: 'level', price: 1 }] },
    ])
    expect(chart.items).toHaveLength(0)
  })
})

describe('clearing agent markup', () => {
  it('leaves a drawing the operator made by hand untouched', () => {
    const chart = surface([OPERATOR])
    applyChartCommands(chart, [drawLevels()])
    expect(chart.items).toHaveLength(3)

    expect(applyChartCommands(chart, [{ op: 'clear', group: 'levels' }])).toBe(true)

    // The whole point of the namespace. Losing this is losing real work.
    expect(chart.items).toHaveLength(1)
    expect(chart.items[0].id).toBe('d7')
    expect(chart.items[0].style.text).toBe('watch this breakout')
  })

  it('removes every agent group, and nothing else, when the group is null', () => {
    const chart = surface([OPERATOR])
    applyChartCommands(chart, [
      drawLevels(),
      { op: 'draw', group: 'patterns', shapes: [{ kind: 'marker', at: { time: 1, price: 2 } }] },
    ])
    expect(chart.items).toHaveLength(4)

    applyChartCommands(chart, [{ op: 'clear', group: null }])
    expect(chart.items.map((item) => item.id)).toEqual(['d7'])
  })

  it('removes every agent drawing of a group, not just the first', () => {
    const chart = surface()
    applyChartCommands(chart, [
      {
        op: 'draw',
        group: 'levels',
        shapes: [
          { kind: 'level', price: 1 },
          { kind: 'level', price: 2 },
          { kind: 'level', price: 3 },
        ],
      },
    ])
    applyChartCommands(chart, [{ op: 'clear', group: 'levels' }])
    expect(chart.items).toHaveLength(0)
  })

  it('removes nothing for a group name that is not one', () => {
    const chart = surface([OPERATOR])
    applyChartCommands(chart, [drawLevels()])
    expect(applyChartCommands(chart, [{ op: 'clear', group: 'not a group' }])).toBe(false)
    expect(chart.items).toHaveLength(3)
  })
})

describe('id helpers', () => {
  it('tells an agent drawing from an operator one', () => {
    expect(isAgentDrawingId('ai:levels:0')).toBe(true)
    expect(isAgentDrawingId('d7')).toBe(false)
    expect(agentGroupOf('ai:levels:0')).toBe('levels')
    expect(agentGroupOf('d7')).toBeNull()
    expect(agentGroupOf('ai:')).toBeNull()
  })
})

describe('describeDrawings', () => {
  it('reports the operator drawings and the agent groups separately', () => {
    const chart = surface([OPERATOR])
    applyChartCommands(chart, [
      drawLevels(),
      {
        op: 'draw',
        group: 'zone',
        shapes: [{ kind: 'zone', from: { time: 1, price: 2 }, to: { time: 3, price: 4 } }],
      },
    ])

    const described = describeDrawings(chart.items)
    expect(described.drawings).toEqual([
      {
        tool: 'trend-line',
        points: [
          { time: 1775508803, price: 1420 },
          { time: 1787604803, price: 1290 },
        ],
        text: 'watch this breakout',
      },
    ])
    expect(described.agentGroups.sort()).toEqual(['levels', 'zone'])
  })

  it('caps the anchors it reports per drawing', () => {
    const points = Array.from({ length: 50 }, (_, index) => ({ time: index, price: index }))
    const described = describeDrawings([{ id: 'd1', tool: 'path', points, style: {} }])
    expect(described.drawings[0].points).toHaveLength(4)
  })
})
