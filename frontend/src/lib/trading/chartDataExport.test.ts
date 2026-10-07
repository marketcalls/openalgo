import { describe, expect, it } from 'vitest'
import { csvOptions, visibleTimes } from './chartDataExport'

function chart(from: number, to: number, times: number[]) {
  return {
    getVisibleLogicalRange: () => ({ from, to }),
    primaryBars: () => times.map((time) => ({ time, open: 1, high: 1, low: 1, close: 1 })),
    dataLayer: {
      length: times.length + 2,
      indexToTime: (index: number) => (index < times.length ? times[index] : times.at(-1)! + 60),
    },
  } as unknown as Parameters<typeof csvOptions>[0]
}

describe('chart data export options', () => {
  it('asks for nothing extra by default, which is every bar, study and comparison', () => {
    expect(csvOptions(chart(0, 3, [60, 120, 180, 240]), {})).toEqual({})
    expect(
      csvOptions(chart(0, 3, [60, 120, 180, 240]), { range: 'all', comparisons: true })
    ).toEqual({})
  })

  it('names the studies chosen, or none', () => {
    const target = chart(0, 3, [60, 120])
    expect(csvOptions(target, { studies: ['rsi', 'ema'] }).indicators).toEqual(['rsi', 'ema'])
    expect(csvOptions(target, { studies: [] }).indicators).toBe(false)
  })

  it('leaves comparison closes out on request', () => {
    expect(csvOptions(chart(0, 3, [60]), { comparisons: false }).comparisons).toEqual([])
  })

  it('limits the rows to the bars on screen, never past the last real bar', () => {
    expect(visibleTimes(chart(0.6, 7.5, [60, 120, 180, 240]))).toEqual({ from: 120, to: 240 })
    expect(csvOptions(chart(0.2, 2.9, [60, 120, 180, 240]), { range: 'visible' }).range).toEqual({
      from: 120,
      to: 180,
    })
  })

  it('says so when no bar is on screen', () => {
    expect(() => csvOptions(chart(8, 9, [60, 120]), { range: 'visible' })).toThrow(
      'No bars are on screen to export'
    )
  })
})
