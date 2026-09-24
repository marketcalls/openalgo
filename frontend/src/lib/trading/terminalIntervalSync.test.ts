import { createLinkGroup, type Chart, type LinkGroup } from 'openalgo-charts'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TradingTerminal } from './terminal'

const groups: LinkGroup[] = []
afterEach(() => {
  for (const group of groups.splice(0)) group.destroy()
})

function mount(interval = '5m', availableIntervals = ['1m', '5m', '15m', 'D']) {
  const listeners = new Map<string, Set<(value: unknown) => void>>()
  const chart = {
    on(event: string, callback: (value: unknown) => void) {
      const set = listeners.get(event) ?? new Set()
      set.add(callback)
      listeners.set(event, set)
      return () => {
        set.delete(callback)
      }
    },
    panes: () => [{ series: () => [] }],
    addPrimitive() {},
    removePrimitive() {},
  } as unknown as Chart
  const terminal = Object.assign(Object.create(TradingTerminal.prototype), {
    interval,
    availableIntervals,
    chart,
    link: null,
    ctype: 'candlestick',
    sym: { symbol: 'TEST', exchange: 'NSE' },
    stopReplay: vi.fn(),
    reloadCurrent: vi.fn(),
    lsSet: vi.fn(),
    toast: vi.fn(),
    profileBlockMinutes: () => 30,
    cb: { onIntervalChange: vi.fn() },
  }) as Pick<TradingTerminal, 'setInterval' | 'setLinkGroup'> & {
    interval: string
    ctype: string
    availableIntervals: string[]
    stopReplay: ReturnType<typeof vi.fn>
    reloadCurrent: ReturnType<typeof vi.fn>
    toast: ReturnType<typeof vi.fn>
  }
  return terminal
}

function link(...terminals: ReturnType<typeof mount>[]) {
  const group = createLinkGroup({ interval: true, crosshair: false, viewport: false })
  groups.push(group)
  for (const terminal of terminals) terminal.setLinkGroup(group)
  return group
}

describe('terminal interval synchronization', () => {
  it('rejects unsupported intervals before stopping replay or requesting history', () => {
    const terminal = mount()
    expect(terminal.setInterval('7m')).toBe('5m')
    expect(terminal.stopReplay).not.toHaveBeenCalled()
    expect(terminal.reloadCurrent).not.toHaveBeenCalled()
    expect(terminal.toast).toHaveBeenCalled()
  })

  it('leaves the current interval and viewport alone on a repeated selection', () => {
    const terminal = mount()
    expect(terminal.setInterval('5m')).toBe('5m')
    expect(terminal.stopReplay).not.toHaveBeenCalled()
    expect(terminal.reloadCurrent).not.toHaveBeenCalled()
  })

  it('changes every accepting pane through the same terminal path exactly once', () => {
    const leader = mount()
    const follower = mount()
    link(leader, follower)
    leader.setInterval('15m')
    expect(follower.interval).toBe('15m')
    expect(leader.reloadCurrent).toHaveBeenCalledOnce()
    expect(follower.reloadCurrent).toHaveBeenCalledOnce()
    expect(follower.stopReplay).toHaveBeenCalledOnce()
  })

  it('keeps unsupported followers on their current interval and can retry later', () => {
    const leader = mount()
    const follower = mount('5m', ['5m'])
    const group = link(leader, follower)
    leader.setInterval('15m')
    expect(group.interval()).toBe('15m')
    expect(follower.interval).toBe('5m')
    expect(follower.reloadCurrent).not.toHaveBeenCalled()
    follower.availableIntervals.push('15m')
    group.setOptions({ interval: false })
    group.setOptions({ interval: true })
    expect(follower.interval).toBe('15m')
  })

  it('converges to the last selected interval when sync is enabled again', () => {
    const first = mount()
    const second = mount()
    const group = link(first, second)
    group.setOptions({ interval: false })
    first.setInterval('1m')
    second.setInterval('15m')
    expect(first.interval).toBe('1m')
    group.setOptions({ interval: true })
    expect(first.interval).toBe('15m')
    expect(second.interval).toBe('15m')
  })

  it('lets session profiles refuse calendar intervals without changing the leader', () => {
    const leader = mount()
    const profile = mount()
    profile.ctype = 'tpo'
    link(leader, profile)
    leader.setInterval('D')
    expect(leader.interval).toBe('D')
    expect(profile.interval).toBe('5m')
    expect(profile.stopReplay).not.toHaveBeenCalled()
    expect(profile.toast).toHaveBeenCalled()
  })
})
