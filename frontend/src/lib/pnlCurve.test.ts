import { describe, expect, it } from 'vitest'
import {
  type CurveLot,
  cumulative,
  currentDrawdown,
  curveSeries,
  dailySeries,
  drawdown,
  foldCurveStrategies,
  monthly,
  runningMaxDrawdown,
  stats,
  strategySummaries,
  UNTAGGED,
} from './pnlCurve'

const lot = (date: string, pnl: number, strategy: string | null): CurveLot => ({
  exit_timestamp: `${date}T10:00:00`,
  realized_pnl: pnl,
  strategy,
})

// Hand-worked: totals 80, -150, 30, 200 -> cumulative 80, -70, -40, 160.
const LOTS: CurveLot[] = [
  lot('2026-01-05', 100, 'A'),
  lot('2026-01-05', -20, 'B'),
  lot('2026-01-06', -150, 'A'),
  lot('2026-01-07', 30, 'B'),
  lot('2026-02-02', 200, 'A'),
]

describe('dailySeries and cumulative', () => {
  it('groups lots by exit date and strategy', () => {
    const series = dailySeries(LOTS)
    expect(series.dates).toEqual(['2026-01-05', '2026-01-06', '2026-01-07', '2026-02-02'])
    expect(series.total).toEqual([80, -150, 30, 200])
    expect(series.byStrategy.get('A')).toEqual([100, -150, 0, 200])
    expect(series.byStrategy.get('B')).toEqual([-20, 0, 30, 0])
    expect(cumulative(series.total)).toEqual([80, -70, -40, 160])
  })

  it('names a lot with no strategy Untagged', () => {
    const series = dailySeries([lot('2026-03-01', 5, null)])
    expect(series.byStrategy.get(UNTAGGED)).toEqual([5])
  })

  it('handles no lots', () => {
    const series = dailySeries([])
    expect(series.dates).toEqual([])
    expect(series.total).toEqual([])
  })
})

describe('drawdown', () => {
  it('finds the deepest fall, its peak and its recovery', () => {
    const series = dailySeries(LOTS)
    const result = drawdown(series.dates, cumulative(series.total))
    expect(result.series).toEqual([0, -150, -120, 0])
    expect(result.max).toEqual({
      depth: -150,
      peakDate: '2026-01-05',
      troughDate: '2026-01-06',
      recoveryDate: '2026-02-02',
      days: 28,
    })
  })

  it('treats the start as the first peak, at zero', () => {
    // -20 on day one is a fall from the zero the curve began at.
    const result = drawdown(['2026-01-05', '2026-01-07'], [-20, 10])
    expect(result.max.depth).toBe(-20)
    expect(result.max.peakDate).toBeNull()
    expect(result.max.recoveryDate).toBe('2026-01-07')
    expect(result.max.days).toBe(2)
  })

  it('reports no recovery while still under water', () => {
    const result = drawdown(['2026-01-05', '2026-01-09'], [50, 10])
    expect(result.max.depth).toBe(-40)
    expect(result.max.recoveryDate).toBeNull()
    expect(result.max.days).toBe(4)
  })

  it('is empty for a curve that never falls', () => {
    expect(drawdown(['2026-01-05'], [10]).max.depth).toBe(0)
    expect(drawdown([], []).max.depth).toBe(0)
  })
})

describe('stats', () => {
  it('summarises the days', () => {
    const series = dailySeries(LOTS)
    const result = stats(series.dates, series.total)
    expect(result.netPnl).toBe(160)
    expect(result.activeDays).toBe(4)
    expect(result.winDays).toBe(3)
    expect(result.lossDays).toBe(1)
    expect(result.winRate).toBe(0.75)
    expect(result.avgWinDay).toBeCloseTo(310 / 3)
    expect(result.avgLossDay).toBe(-150)
    expect(result.profitFactor).toBeCloseTo(310 / 150)
    expect(result.bestDay).toEqual({ date: '2026-02-02', value: 200 })
    expect(result.worstDay).toEqual({ date: '2026-01-06', value: -150 })
    expect(result.longestWinStreak).toBe(2)
    expect(result.longestLossStreak).toBe(1)
  })

  it('has no ratios without a decided day or a losing day', () => {
    const empty = stats([], [])
    expect(empty.winRate).toBeNull()
    expect(empty.bestDay).toBeNull()
    expect(empty.activeDays).toBe(0)
    expect(stats(['2026-01-05'], [10]).profitFactor).toBeNull()
  })
})

describe('monthly', () => {
  it('sums by month with a yearly total, leaving idle months empty', () => {
    const series = dailySeries(LOTS)
    const rows = monthly(series.dates, series.total)
    expect(rows).toHaveLength(1)
    expect(rows[0].year).toBe(2026)
    expect(rows[0].months[0]).toBe(-40)
    expect(rows[0].months[1]).toBe(200)
    expect(rows[0].months[2]).toBeNull()
    expect(rows[0].total).toBe(160)
  })
})

describe('strategySummaries', () => {
  it('judges each strategy on its own days, best first', () => {
    const rows = strategySummaries(dailySeries(LOTS))
    expect(rows.map((r) => r.strategy)).toEqual(['A', 'B'])
    const a = rows[0]
    expect(a.netPnl).toBe(150)
    expect(a.maxDrawdown).toBe(-150)
    expect(a.winRate).toBeCloseTo(2 / 3)
    expect(a.profitFactor).toBe(2)
    expect(a.activeDays).toBe(3)
    expect(rows[1].netPnl).toBe(10)
    expect(rows[1].maxDrawdown).toBe(-20)
  })
})

describe('a strategy selection', () => {
  // The page recomputes everything from the lots of the selected strategies,
  // so the total, drawdown and statistics are those of that subset alone.
  const only = (name: string) => LOTS.filter((l) => (l.strategy || UNTAGGED) === name)

  it('gives the total, drawdown and statistics of the selected strategy only', () => {
    const series = dailySeries(only('A'))
    expect(series.dates).toEqual(['2026-01-05', '2026-01-06', '2026-02-02'])
    expect(series.total).toEqual([100, -150, 200])
    expect(series.byStrategy.has('B')).toBe(false)

    const cum = cumulative(series.total)
    expect(cum).toEqual([100, -50, 150])
    expect(drawdown(series.dates, cum).max.depth).toBe(-150)
    expect(stats(series.dates, series.total).netPnl).toBe(150)
  })

  it('is empty when nothing is selected', () => {
    expect(dailySeries([]).dates).toEqual([])
  })
})

describe('equity curve (realized + unrealized)', () => {
  // A: held 5th-6th (level 50, 150), sold on the 7th for 200 realized.
  // B: untagged, 30 open throughout.
  const byStrategy = {
    A: { realized: [0, 0, 200, 0], unrealized: [50, 150, 0, 0] },
    [UNTAGGED]: { realized: [0, 0, 0, 0], unrealized: [30, 30, 30, 30] },
  }
  const dates = ['2026-05-05', '2026-05-06', '2026-05-07', '2026-05-08']
  const { byName } = foldCurveStrategies(byStrategy, 8)

  it('combined is realized plus the change in the open level', () => {
    const s = curveSeries(dates, byName, 'combined')
    // A: 50, +100, -150+200, 0. Untagged: 30, 0, 0, 0.
    expect(s.byStrategy.get('A')).toEqual([50, 100, 50, 0])
    expect(s.total).toEqual([80, 100, 50, 0])
    // Cumulative: total value = realized so far + open level (30 stays open).
    expect(cumulative(s.total)).toEqual([80, 180, 230, 230])
  })

  it('unrealized cumulates back to the level and realized to the running total', () => {
    expect(cumulative(curveSeries(dates, byName, 'unrealized').total)).toEqual([80, 180, 30, 30])
    expect(cumulative(curveSeries(dates, byName, 'realized').total)).toEqual([0, 0, 200, 200])
  })

  it('a selection drops the others from the total and from the series', () => {
    const s = curveSeries(dates, byName, 'combined', (n) => n === 'A')
    expect(Array.from(s.byStrategy.keys())).toEqual(['A'])
    expect(s.total).toEqual([50, 100, 50, 0])
    expect(drawdown(dates, cumulative(s.total)).max.depth).toBe(0)
  })

  it('folds strategies beyond the colour budget into Other', () => {
    const many = {
      A: { realized: [1, 0], unrealized: [0, 0] },
      B: { realized: [2, 0], unrealized: [0, 0] },
      C: { realized: [4, 0], unrealized: [0, 0] },
    }
    const folded = foldCurveStrategies(many, 2)
    expect(folded.names).toEqual(['A', 'B'])
    expect(folded.byName.get('Other')?.realized).toEqual([4, 0])
  })
})

describe('current and running drawdown', () => {
  const dates = ['2026-05-04', '2026-05-05', '2026-05-06', '2026-05-07', '2026-05-08']

  it('reports how far below the running peak the curve is on the last date', () => {
    const cum = [100, 160, 90, 60, 120]
    const now = currentDrawdown(dates, cum)
    expect(now.depth).toBe(-40)
    expect(now.peakValue).toBe(160)
    expect(now.peakDate).toBe('2026-05-05')
    expect(now.daysSincePeak).toBe(3)
    expect(now.atHigh).toBe(false)
  })

  it('is flat at a new high', () => {
    const now = currentDrawdown(dates, [10, 20, 15, 25, 30])
    expect(now.depth).toBe(0)
    expect(now.atHigh).toBe(true)
    expect(now.daysSincePeak).toBe(0)
  })

  it('the running maximum drawdown only ever deepens', () => {
    const series = drawdown(dates, [100, 160, 90, 60, 120]).series
    expect(runningMaxDrawdown(series)).toEqual([0, 0, -70, -100, -100])
  })
})
