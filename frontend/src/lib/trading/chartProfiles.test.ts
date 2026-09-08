import type { Bar, PrimitiveRenderContext } from 'openalgo-charts'
import { describe, expect, it, vi } from 'vitest'
import { createChartProfile, MAX_PROFILE_ROWS, ProfileSessionStore } from './chartProfiles'
import { readProfileSettings } from './profileSettings'

const context = { tickSize: 1, exchange: 'NSE', timezone: 'America/New_York', intervalSeconds: 60 }
const time = (date: string) => Date.parse(date) / 1000
function bar(date: string, values: Partial<Bar> = {}): Bar {
  return { time: time(date), open: 100, high: 102, low: 100, close: 101, volume: 30, ...values }
}
const svp = () => readProfileSettings('session-volume-profile', {})
const tpo = () => readProfileSettings('tpo', {})

const splitFixture = () => [
  bar('2026-09-01T03:45:00Z', { high: 100, low: 100, close: 100 }),
  bar('2026-09-01T04:15:00Z', { high: 102, low: 102, open: 102, close: 102 }),
  bar('2026-09-02T03:45:00Z', { high: 100, low: 100, close: 100 }),
  bar('2026-09-02T04:15:00Z', { high: 102, low: 102, open: 102, close: 102 }),
]

function paintSplitFixture(profile: ReturnType<typeof createChartProfile>, bars: readonly Bar[]) {
  const c = canvas(bars, 50)
  c.rc.priceScale.priceToY = (price) => 150 - (price - 100) * 20
  profile.draw(c.ctx, c.rc)
  return {
    ...c,
    letterXs: [...new Set(c.textCalls.filter((call) => call.text === 'B').map((call) => call.x))],
    blockXs: c.fills.filter((fill) => fill.y < 130 && fill.height > 10).map((fill) => fill.x),
  }
}

function canvas(bars: readonly Bar[], spacing = 10) {
  const fills: {
    x: number
    y: number
    width: number
    height: number
    color: string
    alpha: number
  }[] = []
  const strokes: { color: string; points: number[][] }[] = []
  const texts: string[] = []
  const textCalls: { text: string; x: number; y: number; color: string; alpha: number }[] = []
  let points: number[][] = []
  const ctx = {
    fillStyle: '',
    strokeStyle: '',
    globalAlpha: 1,
    lineWidth: 1,
    save: vi.fn(),
    restore: vi.fn(),
    rect: vi.fn(),
    clip: vi.fn(),
    setLineDash: vi.fn(),
    beginPath: () => {
      points = []
    },
    moveTo: (x: number, y: number) => points.push([x, y]),
    lineTo: (x: number, y: number) => points.push([x, y]),
    stroke: () => strokes.push({ color: String(ctx.strokeStyle), points: [...points] }),
    fillRect: (x: number, y: number, width: number, height: number) =>
      fills.push({ x, y, width, height, color: String(ctx.fillStyle), alpha: ctx.globalAlpha }),
    fillText: (text: string, x: number, y: number) => {
      texts.push(text)
      textCalls.push({ text, x, y, color: String(ctx.fillStyle), alpha: ctx.globalAlpha })
    },
    measureText: (text: string) => ({ width: text.length * 5 }),
  }
  const rc = {
    dpr: 1,
    plotWidth: 300,
    plotHeight: 200,
    priceAxisWidth: 50,
    timeScale: { barSpacing: spacing, indexToX: (index: number) => index * spacing },
    priceScale: { priceToY: (price: number) => 150 - (price - 100) * 10, format: String },
    dataLayer: {
      timeToIndex: (stamp: number) => {
        const i = bars.findIndex((b) => b.time === stamp)
        return i < 0 ? undefined : i
      },
    },
    theme: {},
  } as unknown as PrimitiveRenderContext
  return { ctx: ctx as unknown as CanvasRenderingContext2D, rc, fills, strokes, texts, textCalls }
}

describe('per-session TPO context actions', () => {
  it.each([
    'tpo',
    'session-volume-profile',
  ] as const)('uses the primary-series price scale after an axis move (%s)', (kind) => {
    const data = [bar('2026-09-01T03:45:00Z')]
    const c = canvas(data, 80)
    const seriesScale = c.rc.priceScale
    c.rc.priceScale = Object.assign(Object.create(seriesScale), { priceToY: () => -10_000 })
    const profile = createChartProfile(kind, readProfileSettings(kind, {}), {
      ...context,
      priceScale: () => seriesScale,
    })
    profile.attached!({ requestUpdate: vi.fn() })
    profile.setBars(data)
    profile.draw(c.ctx, c.rc)
    expect(c.fills.some((fill) => fill.y >= 0 && fill.y < c.rc.plotHeight)).toBe(true)
    if (kind === 'tpo') expect(profile.contextMenuAt(4, 140)?.label).toBe('Split this session')
  })

  it('splits and unsplits only the clicked session in every native rendering pass', () => {
    const data = splitFixture()
    const profile = createChartProfile('tpo', { ...tpo(), display: 'both' }, context)
    const requestUpdate = vi.fn()
    profile.attached!({ requestUpdate })
    profile.setBars(data)
    expect(paintSplitFixture(profile, data).letterXs).toEqual([4, 104])
    const split = profile.contextMenuAt(4, 110)
    expect(split?.label).toBe('Split this session')
    expect(split?.sessionLabel).toMatch(/^1 Sep(?:t)? 2026$/)
    requestUpdate.mockClear()
    split!.run()
    expect(requestUpdate).toHaveBeenCalledOnce()
    const painted = paintSplitFixture(profile, data)
    expect(painted.letterXs).toEqual([12, 104])
    expect(painted.blockXs).toEqual([8, 100])
    const unsplit = profile.contextMenuAt(12, 110)
    expect(unsplit?.label).toBe('Unsplit this session')
    unsplit!.run()
    const restored = paintSplitFixture(profile, data)
    expect(restored.letterXs).toEqual([4, 104])
    expect(restored.blockXs).toEqual([0, 100])
  })

  it('retains the selected session override across native rebuild, backfill and replay removal', () => {
    const data = splitFixture()
    const profile = createChartProfile('tpo', tpo(), context)
    profile.attached!({ requestUpdate: vi.fn() })
    profile.setBars(data)
    paintSplitFixture(profile, data)
    profile.contextMenuAt(4, 110)!.run()
    const revised = data.map((bar, i) => (i === 1 ? { ...bar, volume: 60 } : bar))
    profile.setBars(revised)
    expect(paintSplitFixture(profile, revised).letterXs).toEqual([12, 104])
    const earlier = [bar('2026-08-31T03:45:00Z', { high: 100, low: 100, close: 100 })]
    const backfilled = [...earlier, ...revised]
    profile.setBars(backfilled)
    expect(paintSplitFixture(profile, backfilled).letterXs).toEqual([62, 154])
    profile.setBars(earlier)
    paintSplitFixture(profile, earlier)
    profile.setBars(backfilled)
    expect(paintSplitFixture(profile, backfilled).letterXs).toEqual([62, 154])
  })

  it('clears per-session overrides when the global split or grouping setting changes', () => {
    const data = splitFixture()
    const settings = tpo()
    const profile = createChartProfile('tpo', settings, context)
    profile.attached!({ requestUpdate: vi.fn() })
    profile.setBars(data)
    paintSplitFixture(profile, data)
    profile.contextMenuAt(4, 110)!.run()
    profile.setSettings({ ...settings, periodCount: 2 })
    paintSplitFixture(profile, data)
    expect(profile.contextMenuAt(4, 110)?.label).toBe('Split this session')
    profile.setSettings({ ...settings, split: true })
    paintSplitFixture(profile, data)
    profile.contextMenuAt(12, 110)!.run()
    expect(paintSplitFixture(profile, data).letterXs).toEqual([4, 112])
    profile.setSettings(settings)
    profile.setSettings({ ...settings, split: true })
    expect(paintSplitFixture(profile, data).letterXs).toEqual([12, 112])
  })

  it('rejects stale actions after removal, reappearance and detach', () => {
    const data = splitFixture()
    const profile = createChartProfile('tpo', tpo(), context)
    const requestUpdate = vi.fn()
    profile.attached!({ requestUpdate })
    profile.setBars(data)
    paintSplitFixture(profile, data)
    const removed = profile.contextMenuAt(104, 110)!
    profile.setBars(data.slice(0, 2))
    requestUpdate.mockClear()
    removed.run()
    expect(requestUpdate).not.toHaveBeenCalled()
    profile.setBars(data)
    paintSplitFixture(profile, data)
    requestUpdate.mockClear()
    removed.run()
    expect(requestUpdate).not.toHaveBeenCalled()
    expect(paintSplitFixture(profile, data).letterXs).toEqual([4, 104])
    const detached = profile.contextMenuAt(4, 110)!
    profile.detached!()
    detached.run()
    expect(requestUpdate).not.toHaveBeenCalled()
    expect(profile.contextMenuAt(4, 110)).toBeNull()
  })

  it('returns no action for SVP, outside the plot, missing rows or before the current paint', () => {
    const data = splitFixture()
    const profile = createChartProfile('tpo', tpo(), context)
    profile.attached!({ requestUpdate: vi.fn() })
    profile.setBars(data)
    expect(profile.contextMenuAt(4, 110)).toBeNull()
    paintSplitFixture(profile, data)
    for (const [x, y] of [
      [-1, 110],
      [301, 110],
      [4, -1],
      [4, 201],
      [4, 20],
      [250, 110],
    ]) {
      expect(profile.contextMenuAt(x, y)).toBeNull()
    }
    profile.setBars(data)
    expect(profile.contextMenuAt(4, 110)).toBeNull()
    const volume = createChartProfile('session-volume-profile', svp(), context)
    volume.attached!({ requestUpdate: vi.fn() })
    volume.setBars(data)
    paintSplitFixture(volume, data)
    expect(volume.contextMenuAt(4, 110)).toBeNull()
  })
})

describe('profile session calculations', () => {
  it('explains an SVP view whose supplied bars contain no volume', () => {
    const profile = createChartProfile('session-volume-profile', svp(), context)
    profile.setBars([bar('2026-09-01T03:45:00Z', { volume: 0 })])
    expect(profile.warning()).toContain('no volume')
    profile.setBars([bar('2026-09-01T03:45:00Z')])
    expect(profile.warning()).toBeNull()
  })

  it.each([
    'tpo',
    'session-volume-profile',
  ] as const)('explains an empty custom session without warning during initial loading (%s)', (kind) => {
    const settings = {
      ...readProfileSettings(kind, {}),
      sessionMode: 'custom' as const,
      sessionStart: '09:15',
      sessionEnd: '15:30',
    }
    const profile = createChartProfile(kind, settings, context)
    profile.setBars([])
    expect(profile.warning()).toBeNull()
    profile.setBars([bar('2026-09-01T02:00:00Z')])
    expect(profile.warning()).toContain('custom session')
  })

  it('anchors All-session composite blocks to the exchange clock after a partial first day', () => {
    const store = new ProfileSessionStore(
      { ...tpo(), periodCount: 2 },
      { ...context, intervalSeconds: 300 }
    )
    const data = [
      bar('2026-09-01T03:50:00Z', { high: 100, close: 100 }),
      bar('2026-09-02T03:45:00Z', { high: 100, close: 100 }),
      bar('2026-09-02T03:50:00Z', { high: 100, close: 100 }),
    ]
    store.setBars(data)
    const market = store.sessions[0].market!.sessions[0]
    expect(market.levels[0].count).toBe(2)
    expect(market.levels[0].letters).toBe('AB')
    expect(market.totalVolume).toBe(90)
    expect(market.startTime).toBe(data[0].time)
    expect(market.endTime).toBe(data[2].time)
    expect(market.periodDetail.map((period) => [period.startTime, period.endTime])).toEqual([
      [data[0].time, data[0].time],
      [data[1].time, data[2].time],
    ])
    expect(market.developing.map((point) => point.time)).toEqual([data[0].time, data[2].time])
  })

  it('aligns currency blocks to 09:00 and retains every supplied All-session bar', () => {
    const store = new ProfileSessionStore(tpo(), { ...context, exchange: 'CDS' })
    const data = [bar('2026-09-01T03:40:00Z'), bar('2026-09-01T03:50:00Z')]
    store.setBars(data)
    expect(store.sessions[0].market!.sessions[0].levels[0].count).toBe(1)
    const equity = new ProfileSessionStore(tpo(), context)
    equity.setBars(data)
    expect(equity.sessions[0].market!.sessions[0].totalVolume).toBe(60)
    expect(equity.sessions[0].market!.sessions[0].levels[0].count).toBe(2)
    expect(equity.sessions[0].startTime).toBe(data[0].time)
  })

  it('keeps midnight-aligned blocks stable over a daylight-saving change', () => {
    const store = new ProfileSessionStore(
      { ...tpo(), periodCount: 2, blockMinutes: 45 },
      { ...context, exchange: 'OTHER' }
    )
    store.setBars([
      bar('2026-03-08T05:00:00Z'),
      bar('2026-03-09T04:00:00Z'),
      bar('2026-03-09T04:30:00Z'),
    ])
    expect(store.sessions[0].market!.sessions[0].levels[0].count).toBe(2)
  })

  it.each([
    'all',
    'custom',
  ] as const)('marks the initial balance unavailable when its opening bars are absent (%s)', (sessionMode) => {
    const store = new ProfileSessionStore({ ...tpo(), sessionMode }, context)
    store.setBars([bar('2026-09-01T04:50:00Z', { low: 90, high: 120 })])
    expect(store.sessions[0].initialBalanceAvailable).toBe(false)
    expect(Number.isFinite(store.sessions[0].market!.sessions[0].initialBalance.high)).toBe(false)
  })

  it('limits a partial initial balance to observed bars inside the true opening window', () => {
    const store = new ProfileSessionStore(tpo(), context)
    store.setBars([
      bar('2026-09-01T04:20:00Z', { low: 99, high: 103 }),
      bar('2026-09-01T04:50:00Z', { low: 50, high: 150 }),
    ])
    expect(store.sessions[0].initialBalanceAvailable).toBe(true)
    expect(store.sessions[0].market!.sessions[0].initialBalance).toEqual({ low: 99, high: 103 })
  })

  it('does not fill a missing composite initial balance using the next day', () => {
    const store = new ProfileSessionStore({ ...tpo(), periodCount: 2 }, context)
    store.setBars([bar('2026-09-01T04:50:00Z'), bar('2026-09-02T03:45:00Z')])
    expect(store.sessions[0].initialBalanceAvailable).toBe(false)
  })

  it('uses the exchange day even when the display timezone differs', () => {
    const store = new ProfileSessionStore(svp(), context)
    store.setBars([bar('2026-09-01T03:45:00Z'), bar('2026-09-01T10:00:00Z')])
    expect(store.sessions).toHaveLength(1)
    expect(store.sessions[0].volume?.totalVolume).toBe(60)
  })

  it('filters custom hours and keeps an overnight session together', () => {
    const store = new ProfileSessionStore(
      { ...svp(), sessionMode: 'custom', sessionStart: '22:00', sessionEnd: '02:00' },
      context
    )
    store.setBars([
      bar('2026-09-01T16:00:00Z'),
      bar('2026-09-01T16:30:00Z'),
      bar('2026-09-01T19:30:00Z'),
      bar('2026-09-01T20:30:00Z'),
      bar('2026-09-02T16:30:00Z'),
    ])
    expect(store.sessions).toHaveLength(2)
    expect(store.sessions.map((s) => s.volume?.totalVolume)).toEqual([60, 30])
  })

  it('conserves volume and uses whole tick multiples for requested rows', () => {
    const store = new ProfileSessionStore({ ...svp(), rowCount: 5 }, { ...context, tickSize: 0.05 })
    store.setBars([bar('2026-09-01T03:45:00Z', { low: 100, high: 110, volume: 150 })])
    const session = store.sessions[0]
    expect(session.volume!.levels.length).toBeLessThanOrEqual(5)
    expect(session.rowSize / 0.05).toBeCloseTo(Math.round(session.rowSize / 0.05))
    expect(session.volume!.levels.reduce((sum, level) => sum + level.volume, 0)).toBeCloseTo(150)
  })

  it('bounds tiny manual rows before expanding a huge price range', () => {
    const store = new ProfileSessionStore(
      { ...svp(), rowsLayout: 'ticks-per-row', ticksPerRow: 1 },
      { ...context, tickSize: 0.000001 }
    )
    store.setBars([bar('2026-09-01T03:45:00Z', { low: 1, high: 1_000_000 })])
    expect(store.sessions[0].volume!.levels.length).toBeLessThanOrEqual(MAX_PROFILE_ROWS)
    expect(
      store.sessions[0].volume!.levels.reduce((sum, level) => sum + level.volume, 0)
    ).toBeCloseTo(30)
  })

  it('replaces forming volume and reuses unchanged historical session results', () => {
    const settings = svp()
    const store = new ProfileSessionStore(settings, context)
    const old = bar('2026-09-01T03:45:00Z')
    const live = bar('2026-09-02T03:45:00Z')
    store.setBars([old, live])
    const historical = store.sessions[0]
    live.volume = 45
    store.setBars([old, live])
    expect(store.sessions[0]).toBe(historical)
    expect(store.sessions[1].volume!.totalVolume).toBe(45)
    store.setBars([old, live, bar('2026-09-02T03:46:00Z', { volume: 15 })])
    expect(store.sessions[1].volume!.totalVolume).toBe(60)
  })

  it('drops future sessions and revised rows when replay supplies a shorter prefix', () => {
    const store = new ProfileSessionStore(svp(), context)
    const first = bar('2026-09-01T03:45:00Z')
    store.setBars([first, bar('2026-09-02T03:45:00Z', { high: 120 })])
    store.setBars([first])
    expect(store.sessions).toHaveLength(1)
    expect(store.sessions[0].volume!.levels[0].price).toBeLessThan(120)
    store.setBars([])
    expect(store.sessions).toEqual([])
  })

  it('retains TPO letters without inventing volume for an index', () => {
    const store = new ProfileSessionStore(tpo(), context)
    store.setBars([
      bar('2026-09-01T03:45:00Z', { volume: undefined }),
      bar('2026-09-01T04:15:00Z', { volume: 0 }),
    ])
    expect(store.sessions[0].market!.sessions[0].levels[0].letters).toBe('AB')
    expect(store.sessions[0].market!.sessions[0].totalVolume).toBe(0)
    expect(store.sessions[0].volume).toBeNull()
  })

  it('applies the configured TPO block and combines periods explicitly', () => {
    const store = new ProfileSessionStore({ ...tpo(), blockMinutes: 15, periodCount: 2 }, context)
    store.setBars([
      bar('2026-09-01T03:45:00Z'),
      bar('2026-09-01T04:00:00Z'),
      bar('2026-09-02T03:45:00Z'),
    ])
    expect(store.sessions).toHaveLength(1)
    expect(store.sessions[0].market!.sessions[0].levels[0].count).toBe(3)
    expect(store.sessions[0].market!.options.blockMinutes).toBe(15)
  })

  it('declines an oversized TPO composite with an actionable warning', () => {
    const store = new ProfileSessionStore(
      { ...tpo(), periodUnit: 'month', rowSizeMode: 'manual', ticksPerRow: 1 },
      context
    )
    const start = time('2026-09-01T03:45:00Z')
    store.setBars(
      Array.from({ length: 200 }, (_, index) => ({
        ...bar('2026-09-01T03:45:00Z'),
        time: start + index * 1800,
        high: 900,
      }))
    )
    expect(store.sessions).toHaveLength(0)
    expect(store.warning).toContain('Reduce period count')
  })

  it('recomputes settings against retained bars and clears a row-limit warning', () => {
    const settings = { ...svp(), rowsLayout: 'ticks-per-row' as const, ticksPerRow: 1 }
    const store = new ProfileSessionStore(settings, context)
    const data = [bar('2026-09-01T03:45:00Z', { high: 20_000 })]
    store.setBars(data)
    expect(store.warning).toContain('widened')
    store.setSettings({ ...settings, ticksPerRow: 100 })
    store.setBars(data)
    expect(store.warning).toBeNull()
    expect(store.sessions[0].rowSize).toBe(100)
  })

  it('does not assign fine TPO letters to a coarser source interval', () => {
    const store = new ProfileSessionStore(tpo(), { ...context, intervalSeconds: 3600 })
    store.setBars([bar('2026-09-01T03:45:00Z')])
    expect(store.sessions).toHaveLength(0)
    expect(store.warning).toContain('source interval')
  })

  it('anchors a late TPO bar to the custom session opening block', () => {
    const store = new ProfileSessionStore(
      { ...tpo(), sessionMode: 'custom', sessionStart: '09:15', sessionEnd: '15:30' },
      context
    )
    store.setBars([bar('2026-09-01T04:20:00Z')])
    expect(store.sessions[0].market!.sessions[0].levels[0].letters).toBe('B')
  })

  it('keeps an overnight TPO session in its opening month', () => {
    const store = new ProfileSessionStore(
      {
        ...tpo(),
        periodUnit: 'month',
        sessionMode: 'custom',
        sessionStart: '22:00',
        sessionEnd: '02:00',
      },
      context
    )
    store.setBars([bar('2026-09-30T16:30:00Z'), bar('2026-09-30T19:30:00Z')])
    expect(store.sessions).toHaveLength(1)
    expect(store.sessions[0].market!.sessions[0].totalVolume).toBe(60)
  })

  it('bounds developing snapshots including the final bar', () => {
    const store = new ProfileSessionStore({ ...svp(), showDevelopingPoc: true }, context)
    const first = bar('2026-09-01T03:45:00Z')
    const data = Array.from({ length: 128 }, (_, i) => ({ ...first, time: first.time + i * 60 }))
    store.setBars(data)
    expect(store.sessions[0].developing.length).toBeLessThanOrEqual(64)
    expect(store.sessions[0].developing.at(-1)!.time).toBe(data.at(-1)!.time)
  })

  it('reuses unchanged developing snapshots when a forming bar is replaced', () => {
    const store = new ProfileSessionStore({ ...svp(), showDevelopingPoc: true }, context)
    const first = bar('2026-09-01T03:45:00Z')
    const data = [first, { ...first, time: first.time + 60 }]
    store.setBars(data)
    const before = store.sessions[0].developing
    store.setBars([first, { ...data[1], volume: 45 }])
    expect(store.sessions[0].developing[0]).toBe(before[0])
    expect(store.sessions[0].developing[1]).not.toBe(before[1])
    expect(store.sessions[0].volume!.totalVolume).toBe(75)
  })

  it('uses consecutive active-day TPO letters while preserving missing intraday blocks', () => {
    const store = new ProfileSessionStore({ ...tpo(), periodCount: 2 }, context)
    const data = [
      bar('2026-09-01T03:45:00Z'),
      bar('2026-09-01T04:45:00Z'),
      bar('2026-09-02T03:45:00Z'),
    ]
    store.setBars(data)
    const market = store.sessions[0].market!.sessions[0]
    expect(market.levels[0].letters).toBe('ACD')
    expect(market.levels[0].periods).toEqual([0, 2, 3])
    expect(market.periods).toBe(4)
    expect(market.periodDetail.map((period) => period.index)).toEqual([0, 2, 3])
    expect(market.periodDetail.map((period) => period.startTime)).toEqual(
      data.map((item) => item.time)
    )
    expect(market.developing.map((point) => point.periodIndex)).toEqual([0, 2, 3])
    expect(market.totalVolume).toBe(90)
  })

  it('preserves unobserved custom opening and trailing blocks across composite sessions', () => {
    const store = new ProfileSessionStore(
      {
        ...tpo(),
        periodCount: 2,
        sessionMode: 'custom',
        sessionStart: '09:15',
        sessionEnd: '10:15',
      },
      context
    )
    store.setBars([bar('2026-09-01T03:45:00Z'), bar('2026-09-02T04:15:00Z')])
    expect(store.sessions[0].market!.sessions[0].levels[0].letters).toBe('AD')
  })

  it('keeps automatic TPO rows legible at the normal initial view', () => {
    const store = new ProfileSessionStore(tpo(), context)
    store.setBars([bar('2026-09-01T03:45:00Z', { low: 100, high: 200 })])
    expect(store.sessions[0].market!.sessions[0].levels.length).toBeLessThanOrEqual(24)
  })
})

describe('profile rendering', () => {
  const bars = [
    bar('2026-09-01T03:45:00Z'),
    bar('2026-09-01T03:46:00Z'),
    bar('2026-09-02T03:45:00Z'),
  ]

  it('draws each historical session close marker when Session close is enabled', () => {
    const profile = createChartProfile(
      'tpo',
      { ...tpo(), display: 'letters', showClose: true, closeColor: '#abcdef' },
      context
    )
    const data = [bars[0], bars[2]]
    profile.setBars(data)
    const c = canvas(data, 80)
    c.rc.priceScale.priceToY = (price) => 150 - (price - 100) * 20
    profile.draw(c.ctx, c.rc)
    const closes = c.textCalls.filter((call) => call.text === '#')
    expect(closes).toHaveLength(2)
    expect(closes[0].x).toBeLessThan(80)
    expect(closes[1].x).toBeGreaterThan(80)
    expect(closes.every((call) => call.color === '#abcdef')).toBe(true)
  })

  it('does not draw an initial-balance marker for a session with no opening-window bars', () => {
    const profile = createChartProfile(
      'tpo',
      { ...tpo(), showInitialBalance: true, initialBalanceColor: '#abcdef' },
      context
    )
    const data = [bar('2026-09-01T04:50:00Z')]
    profile.setBars(data)
    const c = canvas(data, 80)
    profile.draw(c.ctx, c.rc)
    expect(c.strokes.some((stroke) => stroke.color === '#abcdef')).toBe(false)
  })

  it('renders a later active day in a split composite without overnight column gaps', () => {
    const profile = createChartProfile(
      'tpo',
      { ...tpo(), display: 'letters', split: true, periodCount: 2 },
      context
    )
    const data = [bar('2026-09-01T03:45:00Z'), bar('2026-09-02T03:45:00Z')]
    profile.setBars(data)
    const c = canvas(data, 50)
    c.rc.priceScale.priceToY = (price) => 150 - (price - 100) * 20
    profile.draw(c.ctx, c.rc)
    expect(c.texts).toContain('A')
    expect(c.texts).toContain('B')
  })
  it.each([1, 10, 50])('sizes profiles to their full session slots at spacing %s', (spacing) => {
    const settings = {
      ...svp(),
      widthPercent: 100,
      volumeMode: 'total' as const,
      showPoc: false,
      showVah: false,
      showVal: false,
    }
    const profile = createChartProfile('session-volume-profile', settings, context)
    profile.setBars(bars)
    const c = canvas(bars, spacing)
    profile.draw(c.ctx, c.rc)
    expect(c.fills.length).toBeGreaterThan(0)
    expect(Math.max(...c.fills.filter((f) => f.x < spacing * 2).map((f) => f.width))).toBeCloseTo(
      spacing * 2
    )
    expect(c.fills.every((f) => f.x + f.width <= spacing * 3)).toBe(true)
  })

  it('right aligns a requested percentage without overlapping the next session', () => {
    const profile = createChartProfile(
      'session-volume-profile',
      { ...svp(), widthPercent: 50, placement: 'right', volumeMode: 'total' },
      context
    )
    profile.setBars(bars)
    const c = canvas(bars)
    profile.draw(c.ctx, c.rc)
    expect(c.fills.some((f) => f.x === 10 && f.width === 10)).toBe(true)
    expect(c.fills.some((f) => f.x === 25 && f.width === 5)).toBe(true)
  })

  it('uses independent value-area row colors and POC/VA line controls', () => {
    const settings = {
      ...svp(),
      rowsLayout: 'ticks-per-row' as const,
      ticksPerRow: 1,
      valueAreaPercent: 40,
      upColor: '#001111',
      downColor: '#110011',
      vaUpColor: '#00ffff',
      vaDownColor: '#ff00ff',
      showPoc: false,
      showVah: true,
      showVal: false,
      vahColor: '#abc123',
      extendVah: true,
    }
    const profile = createChartProfile('session-volume-profile', settings, context)
    profile.setBars(bars)
    const c = canvas(bars)
    profile.draw(c.ctx, c.rc)
    expect(new Set(c.fills.map((f) => f.color))).toEqual(new Set(['#001111', '#00ffff']))
    expect(c.strokes.every((s) => s.color === '#abc123')).toBe(true)
    expect(c.strokes[0].points.at(-1)![0]).toBe(c.rc.plotWidth)
  })

  it('draws no histogram or invented POC for missing volume', () => {
    const noVolume = bars.map((b) => ({ ...b, volume: 0 }))
    const profile = createChartProfile('session-volume-profile', svp(), context)
    profile.setBars(noVolume)
    const c = canvas(noVolume)
    profile.draw(c.ctx, c.rc)
    expect(c.fills).toEqual([])
    expect(c.strokes).toEqual([])
  })

  it('clears retained data and host notifications on detach', () => {
    const profile = createChartProfile('session-volume-profile', svp(), context)
    const requestUpdate = vi.fn()
    profile.attached!({ requestUpdate })
    profile.setBars(bars)
    profile.detached!()
    const c = canvas(bars)
    profile.draw(c.ctx, c.rc)
    expect(c.fills).toEqual([])
    requestUpdate.mockClear()
    profile.setSettings(svp())
    expect(requestUpdate).not.toHaveBeenCalled()
    expect(profile.autoscaleInfo!()).toBeNull()
  })

  it('renders native compact TPO glyphs and independent levels on a single bar session', () => {
    const settings = {
      ...tpo(),
      rowSizeMode: 'manual' as const,
      ticksPerRow: 1,
      showInitialBalance: false,
      showSinglePrints: false,
      showPoc: false,
      showVal: false,
      showVah: true,
      vahColor: '#abcdef',
      showMidpoint: true,
      midpointColor: '#123abc',
    }
    const profile = createChartProfile('tpo', settings, context)
    const data = bars.slice(0, 1)
    profile.setBars(data)
    const c = canvas(data, 30)
    profile.draw(c.ctx, c.rc)
    expect(c.fills.length + c.texts.length).toBeGreaterThan(0)
    expect(new Set(c.strokes.map((s) => s.color))).toEqual(new Set(['#abcdef', '#123abc']))
  })

  it('draws separately configured TPO volume rows and volume POC/VA levels', () => {
    const settings = {
      ...tpo(),
      display: 'blocks' as const,
      showVolumeProfile: true,
      volumeWidthPercent: 25,
      volumeColor: '#001122',
      volumeVaColor: '#334455',
      showInitialBalance: false,
      showSinglePrints: false,
      showPoc: false,
      showVah: false,
      showVal: false,
      showVolumePoc: true,
      volumePocColor: '#abcdef',
      showVolumeVah: true,
      volumeVahColor: '#fedcba',
      showVolumeVal: false,
    }
    const profile = createChartProfile('tpo', settings, context)
    profile.setBars(bars)
    const c = canvas(bars, 40)
    profile.draw(c.ctx, c.rc)
    const volumeFills = c.fills.filter((f) => ['#001122', '#334455'].includes(f.color))
    expect(volumeFills.length).toBeGreaterThan(0)
    expect(Math.max(...volumeFills.map((f) => f.width))).toBe(20)
    expect(new Set(c.strokes.map((s) => s.color))).toEqual(new Set(['#abcdef', '#fedcba']))
  })

  it('applies SVP display changes and computes developing tracks from cumulative volume', () => {
    const settings = {
      ...svp(),
      showPoc: false,
      showVah: false,
      showVal: false,
      showDevelopingPoc: true,
      pocColor: '#abcdef',
      rowsLayout: 'ticks-per-row' as const,
      ticksPerRow: 1,
    }
    const profile = createChartProfile('session-volume-profile', settings, context)
    const data = [bars[0], { ...bars[1], open: 102, close: 100, volume: 120 }]
    profile.setBars(data)
    const c = canvas(data, 40)
    profile.draw(c.ctx, c.rc)
    expect(c.strokes[0].color).toBe('#abcdef')
    expect(c.strokes[0].points).toHaveLength(3)
    profile.setSettings({
      ...settings,
      volumeMode: 'delta',
      showDevelopingPoc: false,
      downColor: '#998877',
      vaDownColor: '#998877',
    })
    const d = canvas(data, 40)
    profile.draw(d.ctx, d.rc)
    expect(d.strokes).toEqual([])
    expect(new Set(d.fills.map((f) => f.color))).toEqual(new Set(['#998877']))
  })

  it('keeps compact letters aligned when the opening marker reserves a column', () => {
    const profile = createChartProfile(
      'tpo',
      { ...tpo(), display: 'letters', showOpen: true },
      context
    )
    const data = bars.slice(0, 1)
    profile.setBars(data)
    const c = canvas(data, 50)
    c.rc.priceScale.priceToY = (price) => 150 - (price - 100) * 20
    profile.draw(c.ctx, c.rc)
    expect(c.textCalls.some((call) => call.text === 'o')).toBe(true)
    expect(
      new Set(c.textCalls.filter((call) => call.text === 'A').map((call) => call.x)).size
    ).toBe(1)
  })

  it('spreads the four configured gradient stops across a TPO session', () => {
    const settings = {
      ...tpo(),
      display: 'blocks' as const,
      gradientColor1: '#ff0000',
      gradientColor2: '#00ff00',
      gradientColor3: '#0000ff',
      gradientColor4: '#ffffff',
      showInitialBalance: false,
      showSinglePrints: false,
      showPoc: false,
      showVah: false,
      showVal: false,
    }
    const profile = createChartProfile('tpo', settings, context)
    const data = Array.from({ length: 5 }, (_, i) => ({
      ...bars[0],
      time: bars[0].time + i * 1800,
    }))
    profile.setBars(data)
    const c = canvas(data, 50)
    profile.draw(c.ctx, c.rc)
    expect(c.fills[0].color).toBe('#ff0000')
    expect(c.fills[4].color).toBe('#ffffff')
    expect(c.fills[1].color).not.toBe('#00ff00')
  })

  it('reserves the left volume overlay width before placing TPO letters', () => {
    const profile = createChartProfile(
      'tpo',
      {
        ...tpo(),
        display: 'letters',
        showVolumeProfile: true,
        volumePlacement: 'left',
        volumeWidthPercent: 50,
      },
      context
    )
    const data = bars.slice(0, 1)
    profile.setBars(data)
    const c = canvas(data, 200)
    c.rc.priceScale.priceToY = (price) => 150 - (price - 100) * 20
    profile.draw(c.ctx, c.rc)
    expect(c.textCalls.filter((call) => call.text === 'A').every((call) => call.x >= 100)).toBe(
      true
    )
  })
})
