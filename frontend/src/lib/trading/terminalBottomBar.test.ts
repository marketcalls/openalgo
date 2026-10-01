import { afterEach, describe, expect, it, vi } from 'vitest'
import { type TerminalCallbacks, TradingTerminal } from './terminal'

const terminals: TradingTerminal[] = []
afterEach(() => {
  for (const terminal of terminals.splice(0)) terminal.destroy()
  vi.restoreAllMocks()
})

/** A pane's storage as an install written before the bottom bar existed would hold it. */
function legacyPrefs() {
  const values = new Map<string, string>([
    ['oa-trading-p0-symbol', JSON.stringify({ symbol: 'SBIN', exchange: 'NSE' })],
    ['oa-trading-p0-interval', '15m'],
    ['oa-trading-p0-ctype', 'heikin-ashi'],
    ['oa-trading-p0-grid', '10'],
    ['oa-trading-p0-chartsettings', JSON.stringify({ 'scales.mode': 'logarithmic' })],
  ])
  const storage = {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      values.set(key, value)
    }),
  }
  return { values, storage }
}

function mount(storage: Pick<Storage, 'getItem' | 'setItem'>) {
  const callbacks: TerminalCallbacks = {
    onReady: vi.fn(),
    onToast: vi.fn(),
    onWsState: vi.fn(),
    onSymbolLoaded: vi.fn(),
    onLtp: vi.fn(),
  }
  const terminal = new TradingTerminal({
    apiKey: 'test',
    wsUrl: 'ws://test',
    container: document.createElement('div'),
    legendEl: document.createElement('div'),
    storageKey: 'oa-trading-p0',
    getTheme: () => ({ mode: 'dark', appMode: 'live' }),
    callbacks,
    preferences: storage,
  })
  terminals.push(terminal)
  return { terminal, callbacks }
}

describe('bottom bar preferences on a pane', () => {
  it('opens a pane saved before the bottom bar exactly as before', () => {
    const { values, storage } = legacyPrefs()
    const before = new Map(values)
    const { terminal, callbacks } = mount(storage)
    expect(terminal.currentInterval()).toBe('15m')
    expect(terminal.activeRange()).toBeNull()
    expect(terminal.gridState()).toEqual({ vertical: true, horizontal: false })
    // Reading old state writes nothing back and reports nothing.
    expect(storage.setItem).not.toHaveBeenCalled()
    expect(values).toEqual(before)
    expect(callbacks.onToast).not.toHaveBeenCalled()
  })

  it('keeps a chosen range as a versioned record, only while its interval holds', () => {
    const { values, storage } = legacyPrefs()
    const { terminal } = mount(storage)
    terminal.setActiveRange('1M')
    expect(JSON.parse(values.get('oa-trading-p0-range') ?? '')).toEqual({
      v: 1,
      id: '1M',
      interval: '15m',
    })
    expect(terminal.activeRange()).toBe('1M')
    // Any other interval change ends the range.
    terminal.setInterval('5m')
    expect(terminal.activeRange()).toBeNull()
    expect(values.get('oa-trading-p0-range')).toBe('')
  })

  it('restores a saved range, and ignores one it cannot read', () => {
    const saved = legacyPrefs()
    saved.values.set('oa-trading-p0-range', JSON.stringify({ v: 1, id: '1M', interval: '15m' }))
    expect(mount(saved.storage).terminal.activeRange()).toBe('1M')
    const future = legacyPrefs()
    future.values.set('oa-trading-p0-range', JSON.stringify({ v: 9, id: '1M', interval: '15m' }))
    expect(mount(future.storage).terminal.activeRange()).toBeNull()
  })
})
