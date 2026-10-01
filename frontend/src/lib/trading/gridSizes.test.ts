import { afterEach, describe, expect, it } from 'vitest'
import { LAYOUTS } from '@/lib/chart/layouts'
import {
  dividerSegments,
  parseAreas,
  parseTracks,
  readGridWeights,
  resizeTracks,
  sameWeights,
  tracksTemplate,
  writeGridWeights,
} from './gridSizes'

const preset = (id: string) => LAYOUTS.find((layout) => layout.id === id)!

afterEach(() => localStorage.clear())

describe('grid tracks', () => {
  it('reads and writes fr tracks', () => {
    expect(parseTracks('1.4fr 1fr')).toEqual([1.4, 1])
    expect(parseTracks('1fr nonsense 0fr')).toEqual([1, 1, 1])
    expect(tracksTemplate([1.23456789, 2])).toBe('1.2346fr 2fr')
  })

  it('places dividers only where two different charts meet', () => {
    expect(dividerSegments(parseAreas(preset('grid4').areas))).toEqual([
      { axis: 'column', index: 0, from: 0, to: 1 },
      { axis: 'row', index: 0, from: 0, to: 1 },
    ])
    // The large chart of 1 + 2 spans both rows, so the row divider runs beside the small ones only.
    expect(dividerSegments(parseAreas(preset('oneTwo').areas))).toEqual([
      { axis: 'column', index: 0, from: 0, to: 1 },
      { axis: 'row', index: 0, from: 1, to: 1 },
    ])
    expect(dividerSegments(parseAreas(preset('single').areas))).toEqual([])
    expect(dividerSegments(parseAreas(preset('grid8').areas))).toHaveLength(4)
  })
})

describe('dragging a divider', () => {
  it('moves only the two tracks either side and keeps the total', () => {
    const next = resizeTracks([1, 1, 1], 0, 100, 900, 120)
    expect(next[0]).toBeCloseTo(4 / 3, 3)
    expect(next[1]).toBeCloseTo(2 / 3, 3)
    expect(next[2]).toBe(1)
  })

  it('stops a chart at the smallest size rather than swapping the charts over', () => {
    const next = resizeTracks([1, 1], 0, 10_000, 600, 120)
    expect(next[1]).toBeCloseTo((120 / 600) * 2, 3)
    expect(next[0] + next[1]).toBeCloseTo(2, 3)
    const back = resizeTracks([1, 1], 0, -10_000, 600, 120)
    expect(back[0]).toBeCloseTo((120 / 600) * 2, 3)
  })

  it('ignores a boundary that does not exist', () => {
    expect(resizeTracks([1, 1], 1, 50, 600, 120)).toEqual([1, 1])
  })
})

describe('the unnamed grid split in this browser', () => {
  const defaults = { columns: [1, 1], rows: [1, 1] }

  it('opens a layout with nothing stored at the preset sizes, as before', () => {
    expect(readGridWeights(localStorage, 'grid4', defaults)).toEqual(defaults)
    expect(localStorage.getItem('oa-trading-layout-sizes')).toBeNull()
  })

  it('keeps a split per layout and forgets it when it is the preset again', () => {
    writeGridWeights(localStorage, 'grid4', { columns: [1.5, 0.5], rows: [1, 1] }, defaults)
    expect(readGridWeights(localStorage, 'grid4', defaults)).toEqual({
      columns: [1.5, 0.5],
      rows: [1, 1],
    })
    expect(readGridWeights(localStorage, 'cols2', { columns: [1, 1], rows: [1] })).toEqual({
      columns: [1, 1],
      rows: [1],
    })
    writeGridWeights(localStorage, 'grid4', defaults, defaults)
    expect(JSON.parse(localStorage.getItem('oa-trading-layout-sizes')!)).toEqual({})
  })

  it('falls back to the preset for anything stored that does not fit', () => {
    localStorage.setItem(
      'oa-trading-layout-sizes',
      JSON.stringify({ grid4: { columns: [1, 1, 1], rows: [-1, 'x'] } })
    )
    expect(readGridWeights(localStorage, 'grid4', defaults)).toEqual(defaults)
    localStorage.setItem('oa-trading-layout-sizes', '{not json')
    expect(readGridWeights(localStorage, 'grid4', defaults)).toEqual(defaults)
  })

  it('compares splits by proportion', () => {
    expect(sameWeights([2, 2], [1, 1])).toBe(true)
    expect(sameWeights([1.4, 1], [1, 1])).toBe(false)
  })
})
