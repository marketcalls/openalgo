import { describe, expect, it } from 'vitest'
import {
  foldedStudyIds,
  type PaneChart,
  type PaneStudy,
  panesToFold,
  readFoldedStudyIds,
  studyMenuAt,
} from './chartPaneActions'

const study = (id: string, paneIndex: number, policy = {}): PaneStudy => ({
  id,
  name: id.toUpperCase(),
  paneIndex,
  policy: () => policy,
})

function chart(studies: PaneStudy[], panes: number, folded: number[] = []): PaneChart {
  return {
    panes: () => Array.from({ length: panes }),
    primaryPaneIndex: () => 0,
    movablePrimaryPane: () => false,
    paneCollapsed: (i) => folded.includes(i),
    indicators: () => studies,
  }
}

describe('studyMenuAt', () => {
  it('offers settings and remove but no pane rows for a study over the price', () => {
    const c = chart([study('ema', 0)], 1)
    expect(studyMenuAt(c, 0, 'ema')).toEqual({
      study: { id: 'ema', name: 'EMA', configurable: true, removable: true },
      pane: null,
    })
    expect(studyMenuAt(c, 0)).toBeNull()
  })

  it('greys up below the pinned price pane and down at the bottom', () => {
    const c = chart([study('rsi', 1), study('macd', 2)], 3)
    const top = studyMenuAt(c, 1, 'rsi')
    expect(top?.pane?.up).toEqual({ disabled: true, reason: 'The price pane stays on top' })
    expect(top?.pane?.down).toEqual({ disabled: false })
    const bottom = studyMenuAt(c, 2, 'macd')
    expect(bottom?.pane?.up).toEqual({ disabled: false })
    expect(bottom?.pane?.down).toEqual({ disabled: true, reason: 'Already the bottom pane' })
  })

  it('names the only study of a pane clicked on its empty space, and none of several', () => {
    expect(studyMenuAt(chart([study('rsi', 1)], 2), 1)?.study?.id).toBe('rsi')
    const shared = studyMenuAt(chart([study('rsi', 1), study('stoch', 1)], 2), 1)
    expect(shared?.study).toBeNull()
    expect(shared?.pane?.index).toBe(1)
  })

  it('reports a folded pane and a protected study', () => {
    const c = chart([study('rsi', 1, { removable: false, configurable: false })], 2, [1])
    const m = studyMenuAt(c, 1, 'rsi')
    expect(m?.pane?.collapsed).toBe(true)
    expect(m?.study).toMatchObject({ removable: false, configurable: false })
  })
})

describe('folded panes in the save', () => {
  it('keeps the folded panes by their studies and folds them again', () => {
    const c = chart([study('ema', 0), study('rsi', 1), study('macd', 2)], 3, [2])
    const ids = foldedStudyIds(c)
    expect(ids).toEqual(['macd'])
    expect(readFoldedStudyIds(JSON.stringify(ids))).toEqual(['macd'])
    expect(panesToFold(c, ids)).toEqual([2])
  })

  it('reads an old save, or a damaged one, as nothing folded', () => {
    expect(readFoldedStudyIds(null)).toEqual([])
    expect(readFoldedStudyIds('not json')).toEqual([])
    expect(readFoldedStudyIds('{"a":1}')).toEqual([])
    expect(panesToFold(chart([study('rsi', 1)], 2), [])).toEqual([])
  })
})
