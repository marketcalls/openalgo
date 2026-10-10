import { afterEach, describe, expect, it } from 'vitest'
import { parseQuickInterval, quickEntryKind } from './quickEntry'

const BROKER = ['1m', '3m', '5m', '15m', '30m', '1h', 'D', 'W', 'M']

function keyOn(target: EventTarget | null, key: string, init: Partial<KeyboardEvent> = {}) {
  return {
    key,
    target,
    defaultPrevented: false,
    isComposing: false,
    repeat: false,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    ...init,
  }
}

afterEach(() => {
  document.body.innerHTML = ''
})

describe('quickEntryKind', () => {
  it('reads a letter as a symbol and a digit from 1 to 9 as an interval', () => {
    expect(quickEntryKind(keyOn(document.body, 'r'))).toBe('symbol')
    expect(quickEntryKind(keyOn(document.body, 'R'))).toBe('symbol')
    expect(quickEntryKind(keyOn(document.body, '5'))).toBe('interval')
  })

  it('leaves 0 to the chart, which resets the view with it', () => {
    expect(quickEntryKind(keyOn(document.body, '0'))).toBeNull()
  })

  it('never takes a chord, a held key, a composed key or a claimed key', () => {
    expect(quickEntryKind(keyOn(document.body, 'r', { altKey: true }))).toBeNull()
    expect(quickEntryKind(keyOn(document.body, 'r', { ctrlKey: true }))).toBeNull()
    expect(quickEntryKind(keyOn(document.body, 'r', { metaKey: true }))).toBeNull()
    expect(quickEntryKind(keyOn(document.body, 'r', { repeat: true }))).toBeNull()
    expect(quickEntryKind(keyOn(document.body, 'r', { isComposing: true }))).toBeNull()
    expect(quickEntryKind(keyOn(document.body, 'r', { defaultPrevented: true }))).toBeNull()
  })

  it('ignores keys that are not letters or digits', () => {
    for (const key of ['Enter', 'Escape', ' ', '+', '-', 'ArrowLeft', 'Delete', '/'])
      expect(quickEntryKind(keyOn(document.body, key))).toBeNull()
  })

  it('never steals a key from a field, a dialog or the order ticket', () => {
    document.body.innerHTML =
      '<section data-chart-pane="p0"><input id="qty" /></section>' +
      '<div role="dialog"><button id="in-dialog">x</button></div>'
    expect(quickEntryKind(keyOn(document.getElementById('qty'), 'r'))).toBeNull()
    expect(quickEntryKind(keyOn(document.getElementById('in-dialog'), 'r'))).toBeNull()
    document.body.innerHTML = '<div data-trading-dialog-open="true"></div>'
    expect(quickEntryKind(keyOn(document.body, 'r'))).toBeNull()
  })

  it('takes keys on a chart or its toolbar, but not on the order book or a side panel', () => {
    document.body.innerHTML =
      '<div data-workspace-toolbar><button id="tool">Alerts</button></div>' +
      '<section data-chart-pane="p0"><button id="pane">x</button></section>' +
      '<div id="dock"><button id="row">Cancel</button></div>'
    expect(quickEntryKind(keyOn(document.getElementById('tool'), 'n'))).toBe('symbol')
    expect(quickEntryKind(keyOn(document.getElementById('pane'), '3'))).toBe('interval')
    expect(quickEntryKind(keyOn(document.getElementById('row'), 'n'))).toBeNull()
    expect(quickEntryKind(keyOn(document, 'n'))).toBe('symbol')
  })
})

describe('parseQuickInterval', () => {
  it('reads a bare number as minutes', () => {
    expect(parseQuickInterval('5', BROKER)).toEqual({ code: '5m' })
    expect(parseQuickInterval(' 15 ', BROKER)).toEqual({ code: '15m' })
  })

  it('reads hours, days, weeks and months the way the menu writes them', () => {
    expect(parseQuickInterval('1h', BROKER)).toEqual({ code: '1h' })
    expect(parseQuickInterval('1H', BROKER)).toEqual({ code: '1h' })
    expect(parseQuickInterval('D', BROKER)).toEqual({ code: 'D' })
    expect(parseQuickInterval('1d', BROKER)).toEqual({ code: 'D' })
    expect(parseQuickInterval('w', BROKER)).toEqual({ code: 'W' })
    expect(parseQuickInterval('1M', BROKER)).toEqual({ code: 'M' })
    expect(parseQuickInterval('30 min', BROKER)).toEqual({ code: '30m' })
  })

  it('keeps lower-case m as minutes and capital M as months', () => {
    expect(parseQuickInterval('3m', BROKER)).toEqual({ code: '3m' })
    expect(parseQuickInterval('3M', BROKER).error).toMatch(/does not offer 3M/)
  })

  it('accepts only what the broker serves, and says so', () => {
    const result = parseQuickInterval('7', BROKER)
    expect(result.code).toBeUndefined()
    expect(result.error).toBe('Your broker does not offer 7m. Choose one from the interval menu.')
    expect(parseQuickInterval('2h', BROKER).error).toMatch(/does not offer 2h/)
  })

  it('explains what to type when the text is not an interval', () => {
    expect(parseQuickInterval('', BROKER).error).toMatch(/Type an interval/)
    expect(parseQuickInterval('5x', BROKER).error).toMatch(/number of minutes/)
    expect(parseQuickInterval('0', BROKER).error).toMatch(/number of minutes/)
  })

  it('takes a broker code exactly as written', () => {
    expect(parseQuickInterval('10s', [...BROKER, '10s'])).toEqual({ code: '10s' })
  })
})
