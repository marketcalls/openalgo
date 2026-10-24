import { describe, expect, it } from 'vitest'
import { bucketize, weekStart } from './pnlBuckets'

// 2026-05-04 is a Monday.
const DATES = ['2026-05-04', '2026-05-05', '2026-05-08', '2026-05-11', '2026-06-01']
const VALUES = [100, -40, 25, 10, -5]

describe('weekStart', () => {
  it('returns the Monday of the week, including for a Sunday', () => {
    expect(weekStart('2026-05-04')).toBe('2026-05-04')
    expect(weekStart('2026-05-08')).toBe('2026-05-04')
    expect(weekStart('2026-05-10')).toBe('2026-05-04')
    expect(weekStart('2026-05-11')).toBe('2026-05-11')
  })

  it('crosses a month and a year boundary', () => {
    expect(weekStart('2026-06-01')).toBe('2026-06-01')
    expect(weekStart('2027-01-01')).toBe('2026-12-28')
  })
})

describe('bucketize', () => {
  it('keeps one bucket per day with a running total', () => {
    const days = bucketize(DATES, VALUES, 'day')
    expect(days.map((b) => b.value)).toEqual(VALUES)
    expect(days.map((b) => b.cumulative)).toEqual([100, 60, 85, 95, 90])
  })

  it('sums a week, Monday to Sunday', () => {
    const weeks = bucketize(DATES, VALUES, 'week')
    expect(weeks.map((b) => b.start)).toEqual(['2026-05-04', '2026-05-11', '2026-06-01'])
    expect(weeks.map((b) => b.value)).toEqual([85, 10, -5])
    expect(weeks[0].days).toBe(3)
    expect(weeks[0].label).toBe('Week of 04 May')
  })

  it('sums a calendar month', () => {
    const months = bucketize(DATES, VALUES, 'month')
    expect(months.map((b) => b.key)).toEqual(['2026-05', '2026-06'])
    expect(months.map((b) => b.value)).toEqual([95, -5])
    expect(months[0].label).toBe('May 2026')
    expect(months[1].cumulative).toBe(90)
  })

  it('is empty for an empty series', () => {
    expect(bucketize([], [], 'week')).toEqual([])
  })
})
