import { getDrawingTool, type Drawing, type DrawContext } from 'openalgo-charts/draw'
import { TradingTerminal } from './terminal'

const theme = { background: 'rgb(19,23,34)', lineColor: '#2962ff' }
const textTools = [
  'text',
  'callout',
  'price-label',
  'note',
  'balloon',
  'comment',
  'signpost',
  'price-note',
  'table',
]

function setup(tool: string) {
  const descriptor = getDrawingTool(tool)
  const drawing: Drawing = {
    id: 'sample',
    tool,
    points: [
      { time: 1, price: 23800 },
      { time: 2, price: 23810 },
    ],
    style: {},
    text: { ...descriptor.defaultText, value: descriptor.defaultText?.value ?? 'Saved caption' },
    paneIndex: 0,
    zIndex: 0,
  }
  const terminal = Object.assign(Object.create(TradingTerminal.prototype), {
    chart: { theme: () => theme },
    toolOf: getDrawingTool,
    draw: {
      get: () => drawing,
      update: (_id: string, patch: Partial<Drawing>) => {
        drawing.style = { ...drawing.style, ...patch.style }
        drawing.text = { ...drawing.text, ...patch.text }
      },
    },
    afterDrawChange: () => {},
  }) as TradingTerminal
  return { drawing, terminal }
}

/** Record actual renderer output; the canvas only supplies font widths and state. */
function paint(drawing: Drawing) {
  const result = { strokes: 0, fills: [] as string[], text: [] as string[] }
  const state: Record<string, unknown> = {}
  const stack: Record<string, unknown>[] = []
  const ctx = new Proxy(state, {
    get(target, key: string) {
      if (key === 'save') return () => stack.push({ ...target })
      if (key === 'restore') return () => Object.assign(target, stack.pop())
      if (key === 'measureText') return (value: string) => ({ width: value.length * 7 })
      if (key === 'stroke') return () => result.strokes++
      if (key === 'fill') return () => result.fills.push(String(target.fillStyle))
      if (key === 'fillText') return () => result.text.push(String(target.fillStyle))
      return target[key] ?? (() => {})
    },
  })
  getDrawingTool(drawing.tool).draw({
    ctx,
    drawing,
    pts: [
      { x: 100, y: 120 },
      { x: 200, y: 160 },
    ],
    rc: { dpr: 1, theme },
    rect: { x: 0, y: 0, width: 500, height: 400 },
    style: { color: theme.lineColor, lineWidth: 1, ...drawing.style },
    formatPrice: String,
  } as unknown as DrawContext)
  return result
}

describe('drawing content editor appearance', () => {
  it.each(['callout', 'price-label'])('ignores obsolete background overrides when editing saved %s', (tool) => {
    const { drawing, terminal } = setup(tool)
    drawing.style.color = '#ffff00'
    drawing.text = { ...drawing.text, backgroundColor: '#434651' }
    const initial = terminal.drawTextStyle('sample')!
    expect(initial.color).toBe(paint(drawing).text[0])
    terminal.applyDrawText('sample', { ...initial, color: '#ffffff' })
    expect(paint(drawing).text.every((color) => color === '#ffffff')).toBe(true)
  })

  it('seeds the price label font from its rendered default', () => {
    expect(setup('price-label').terminal.drawTextStyle('sample')?.fontSize).toBe(12)
  })

  it('shows the actual table background in a native colour input', () => {
    const { terminal } = setup('table')
    expect(terminal.drawTextStyle('sample')?.backgroundColor).toBe('#131722')
    expect(terminal.drawTextStyle('sample')?.border).toBe(true)
  })

  it.each([
    '#fff',
    '#10131a',
    'rgb(230,240,250)',
    'rgba(16,19,26,0.8)',
  ])('seeds the note font from the renderer contrast for %s', (backgroundColor) => {
    const { drawing, terminal } = setup('note')
    drawing.text = { ...drawing.text, backgroundColor }
    expect(terminal.drawTextStyle('sample')?.color).toBe(paint(drawing).text[0])
  })

  it.each(textTools)('preserves %s appearance and unset defaults on an untouched save', (tool) => {
    const { drawing, terminal } = setup(tool)
    const before = paint(drawing)
    const originalText = { ...drawing.text }
    terminal.applyDrawText(drawing.id, terminal.drawTextStyle(drawing.id)!)
    expect(paint(drawing)).toEqual(before)
    expect(drawing.text).toEqual(originalText)
  })

  it.each(textTools)('changes the actual %s letters when font colour is edited', (tool) => {
    const { drawing, terminal } = setup(tool)
    terminal.applyDrawText(drawing.id, { ...terminal.drawTextStyle(drawing.id)!, color: '#ff0000' })
    const result = paint(drawing)
    expect(result.text.length).toBeGreaterThan(0)
    expect(result.text.every((color) => color === '#ff0000')).toBe(true)
  })
})
