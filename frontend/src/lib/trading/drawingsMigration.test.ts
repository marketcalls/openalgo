/**
 * A 1.9.x host saved `DrawingController.toJSON()` verbatim: a bare array, with
 * the text of a label on the style bag and Fibonacci levels as plain numbers.
 * 2.0.0 stores a document and moves the text onto the drawing. The terminal
 * keeps a stored array aside and migrates it the moment the lazily fetched
 * draw tier attaches (`terminal.ts`, `attachDrawing`), so every trader who
 * upgrades opens the chart with their levels where they left them.
 *
 * Pinned against the installed library, not a copy of its output: a release
 * that changes what the upgrade produces fails here rather than in a browser
 * with someone's drawings gone.
 */

import { migrateDrawings } from 'openalgo-charts/draw'
import { describe, expect, it } from 'vitest'

import { describeDrawings } from './chartContract'

/** What a 1.9.2 build wrote to localStorage for three drawings and a label. */
const LEGACY = [
  {
    id: 'd1',
    tool: 'trend-line',
    paneIndex: 0,
    points: [
      { time: 1775508803, price: 1420 },
      { time: 1787604803, price: 1290 },
    ],
    style: { color: '#2962ff', lineWidth: 2, lineStyle: 'solid' },
  },
  {
    id: 'd2',
    tool: 'text',
    paneIndex: 0,
    points: [{ time: 1780000000, price: 1380 }],
    style: {
      color: '#e4e8f4',
      text: 'Supply zone',
      fontSize: 14,
      fontWeight: 'bold',
      fontStyle: 'italic',
      background: true,
      backgroundColor: '#434651',
      border: false,
      borderColor: '#434651',
      wrap: false,
    },
  },
  {
    id: 'd3',
    tool: 'fib-retracement',
    paneIndex: 0,
    points: [
      { time: 1775508803, price: 1290 },
      { time: 1787604803, price: 1420 },
    ],
    style: { color: '#787b86', levels: [0, 0.236, 0.382, 0.5, 0.618, 1], showLabels: true },
    locked: true,
  },
  {
    id: 'd4',
    tool: 'price-label',
    paneIndex: 0,
    points: [{ time: 1786000000, price: 1402.5 }],
    style: { color: '#26a69a', text: '' },
  },
]

/** The fields a trader would notice missing, with the clock-dependent one left out. */
function shape(doc: ReturnType<typeof migrateDrawings>) {
  return doc.drawings.map(({ createdAt: _createdAt, ...rest }) => rest)
}

describe('a 1.9.x drawings array upgrades to a 2.0 document', () => {
  const doc = migrateDrawings(LEGACY)

  it('keeps every drawing, in order, with its anchors', () => {
    expect(doc.version).toBe(2)
    expect(doc.drawings.map((d) => d.id)).toEqual(['d1', 'd2', 'd3', 'd4'])
    expect(doc.drawings.map((d) => d.tool)).toEqual([
      'trend-line',
      'text',
      'fib-retracement',
      'price-label',
    ])
    expect(doc.drawings[0].points).toEqual(LEGACY[0].points)
    expect(doc.drawings[2].locked).toBe(true)
  })

  it('lifts a label off the style bag onto the drawing, with its weight and slant', () => {
    const label = doc.drawings[1]
    expect(label.text?.value).toBe('Supply zone')
    expect(label.text?.bold).toBe(true)
    expect(label.text?.italic).toBe(true)
    expect(label.text?.fontSize).toBe(14)
    expect(label.text?.background).toBe(true)
    expect(label.text?.backgroundColor).toBe('#434651')
    // The old keys do not survive as strays that a later save would carry around.
    expect('text' in label.style).toBe(false)
    expect('fontWeight' in label.style).toBe(false)
  })

  it('turns numeric fib levels into level objects that keep their ratios', () => {
    const levels = doc.drawings[2].style.levels
    expect(levels?.map((level) => level.ratio)).toEqual([0, 0.236, 0.382, 0.5, 0.618, 1])
  })

  it('gives every drawing a paint order, which 2.0 requires', () => {
    for (const drawing of doc.drawings) expect(typeof drawing.zIndex).toBe('number')
  })

  it('is stable: migrating the document again changes nothing', () => {
    expect(shape(migrateDrawings(doc))).toEqual(shape(doc))
  })

  it('is what the agent reads: the label reaches the chart context by value', () => {
    const described = describeDrawings(doc.drawings)
    const label = described.drawings.find((d) => d.tool === 'text')
    expect(label?.text).toBe('Supply zone')
    // An empty 1.9.x label is no label, not a label of nothing.
    const priceLabel = described.drawings.find((d) => d.tool === 'price-label')
    expect(priceLabel?.text).toBeUndefined()
  })
})
