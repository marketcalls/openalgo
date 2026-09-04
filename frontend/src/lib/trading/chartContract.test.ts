import { describe, expect, it } from 'vitest'
import type { AgentChartCommand } from '@/lib/agent/stream'
import {
  type AgentDrawingSurface,
  agentGroupOf,
  applyChartCommands,
  applyIndicatorCommands,
  describeDrawings,
  isAgentDrawingId,
} from './chartContract'

/** A drawing as the controller stores it, with only what these tests read. */
interface Stored {
  id: string
  tool: string
  points: { time: number; price: number }[]
  style: Record<string, unknown>
  text?: { value: string; fontSize?: number }
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
    ...(item.text ? { text: item.text } : {}),
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
  text: { value: 'watch this breakout' },
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
    expect(chart.items[2].text?.value).toBe('doji')
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
    expect(chart.items[0].text?.value).toBe('watch this breakout')
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

/**
 * The indicator half of the vocabulary.
 *
 * Written after the tools that emit these commands shipped unexercised. Three
 * of the four assertions below failed against the first implementation, all for
 * one reason: it compared the agent's descriptor id (`ema`) to a live
 * indicator's INSTANCE id (`ema-1`), which never matches. Remove removed
 * nothing and the duplicate guard never fired, so asking for AlphaTrend twice
 * drew two identical lines.
 */
describe('applyIndicatorCommands', () => {
  /** A stand-in for the chart's indicator tier, backed by an array. */
  function tier(known: string[], live: string[] = []) {
    let seq = 0
    const items = live.map((indicatorId) => ({ id: `${indicatorId}-${seq++}`, indicatorId }))
    const added: { id: string; settings: Record<string, unknown> }[] = []
    return {
      items,
      added,
      indicators: () => items.map((item) => ({ ...item })),
      addIndicator: (id: string, settings: Record<string, unknown>) => {
        added.push({ id, settings })
        items.push({ id: `${id}-${seq++}`, indicatorId: id })
      },
      // The chart's own removal, which is what actually drops the instance.
      // The instance's own `remove()` is deliberately NOT modelled here: it
      // clears the drawn series and leaves the instance in `indicators()`,
      // and a double that spliced on it hid exactly that difference.
      removeIndicator: (instanceId: string) => {
        const at = items.findIndex((item) => item.id === instanceId)
        if (at >= 0) items.splice(at, 1)
      },
      hasIndicator: (id: string) => known.includes(id),
    }
  }

  it('adds an indicator the chart knows, with the settings it was given', () => {
    const chart = tier(['alphatrend'])
    const changed = applyIndicatorCommands(chart, [
      { op: 'indicator', action: 'add', id: 'alphatrend', settings: { period: 14 } },
    ])
    expect(changed).toBe(true)
    expect(chart.added).toEqual([{ id: 'alphatrend', settings: { period: 14 } }])
  })

  it('ignores an id the chart does not know rather than throwing', () => {
    const chart = tier(['alphatrend'])
    expect(() =>
      applyIndicatorCommands(chart, [
        { op: 'indicator', action: 'add', id: 'no-such-indicator' },
        { op: 'indicator', action: 'add', id: 'alphatrend' },
      ])
    ).not.toThrow()
    expect(chart.added.map((a) => a.id)).toEqual(['alphatrend'])
  })

  it('adds a custom module the backend catalogue has never heard of', () => {
    // The chart's registry is the authority, because the operator's own
    // modules load in the browser and no list on the server can see them.
    const chart = tier(['my-own-study'])
    applyIndicatorCommands(chart, [{ op: 'indicator', action: 'add', id: 'my-own-study' }])
    expect(chart.added.map((a) => a.id)).toEqual(['my-own-study'])
  })

  it('does not draw a second identical line when asked twice', () => {
    const chart = tier(['alphatrend'])
    applyIndicatorCommands(chart, [{ op: 'indicator', action: 'add', id: 'alphatrend' }])
    const changed = applyIndicatorCommands(chart, [
      { op: 'indicator', action: 'add', id: 'alphatrend' },
    ])
    expect(changed).toBe(false)
    expect(chart.items).toHaveLength(1)
  })

  it('can add the same indicator again after removing it', () => {
    // The removal has to leave `indicators()` empty, not merely blank the
    // chart. When it did not, the duplicate guard read the leftover instance
    // as "already there" and skipped the add, so the turn reported success and
    // drew nothing, while the toolbar went on counting an indicator that was
    // not visible anywhere.
    const chart = tier(['alphatrend'], ['alphatrend'])
    applyIndicatorCommands(chart, [{ op: 'indicator', action: 'remove', id: 'alphatrend' }])
    expect(chart.items).toHaveLength(0)

    const changed = applyIndicatorCommands(chart, [
      { op: 'indicator', action: 'add', id: 'alphatrend' },
    ])
    expect(changed).toBe(true)
    expect(chart.items).toHaveLength(1)
  })

  it('removes by the descriptor id, not the instance id it is stored under', () => {
    const chart = tier(['ema', 'rsi'], ['ema', 'ema', 'rsi'])
    expect(chart.items.map((i) => i.id)).toEqual(['ema-0', 'ema-1', 'rsi-2'])
    const changed = applyIndicatorCommands(chart, [
      { op: 'indicator', action: 'remove', id: 'ema' },
    ])
    expect(changed).toBe(true)
    expect(chart.items.map((i) => i.indicatorId)).toEqual(['rsi'])
  })

  it('leaves an unknown action alone by treating it as an add', () => {
    const chart = tier(['ema'])
    applyIndicatorCommands(chart, [{ op: 'indicator', action: 'wobble', id: 'ema' }])
    expect(chart.added.map((a) => a.id)).toEqual(['ema'])
  })

  it('ignores drawing ops, as the drawing surface ignores indicator ops', () => {
    const chart = tier(['ema'])
    expect(applyIndicatorCommands(chart, [drawLevels(), { op: 'clear', group: null }])).toBe(false)
    const drawings = surface()
    applyChartCommands(drawings, [{ op: 'indicator', action: 'add', id: 'ema' }])
    expect(drawings.items).toEqual([])
  })
})
