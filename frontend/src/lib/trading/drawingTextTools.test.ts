import { TradingTerminal } from './terminal'

describe('drawing text editing', () => {
  it.each([
    'text',
    'callout',
    'price-label',
    'note',
    'balloon',
    'comment',
    'signpost',
    'price-note',
    'table',
  ])('opens the existing content editor for %s', (tool) => {
    const onDrawTextEdit = vi.fn()
    const terminal = Object.assign(Object.create(TradingTerminal.prototype), {
      draw: {
        selected: () => 'saved-drawing',
        get: () => ({ id: 'saved-drawing', tool, text: { value: 'Saved content' } }),
      },
      cb: { onDrawTextEdit },
    }) as TradingTerminal
    expect(terminal.isTextDrawing('saved-drawing')).toBe(true)
    expect(terminal.editSelectedText()).toBe(true)
    expect(onDrawTextEdit).toHaveBeenCalledWith({
      id: 'saved-drawing',
      tool,
      text: 'Saved content',
    })
  })

  it('keeps measured pattern labels out of the text editor', () => {
    const onDrawTextEdit = vi.fn()
    const terminal = Object.assign(Object.create(TradingTerminal.prototype), {
      draw: { selected: () => 'pattern', get: () => ({ id: 'pattern', tool: 'gartley' }) },
      cb: { onDrawTextEdit },
    }) as TradingTerminal
    expect(terminal.editSelectedText()).toBe(false)
    expect(onDrawTextEdit).not.toHaveBeenCalled()
  })
})
