import type { Alert, AlertsDocument } from 'openalgo-charts'
import { beforeEach, describe, expect, it } from 'vitest'
import { alertRuntimeKey, mergeAlertRuntime, removeWorkspaceAlertRuntime } from './alertRuntime'

const saved = (patch: Partial<Alert> = {}): Alert => ({
  id: 'breakout',
  source: { kind: 'price', price: 105 },
  condition: 'crossingUp',
  policy: 'onBarClose',
  repeat: 'once',
  state: 'armed',
  title: 'Breakout',
  cooldownSeconds: 0,
  scope: { symbol: 'ONE', exchange: 'NSE', interval: '5m' },
  ...patch,
})
const doc = (...alerts: Alert[]): AlertsDocument => ({ version: 1, alerts })
beforeEach(() => localStorage.clear())

describe('alert runtime snapshots', () => {
  it('merges lifecycle and guards without replacing saved presentation or routing', () => {
    const definition = saved({
      title: 'Renamed',
      message: 'Current message',
      payload: { route: 'new' },
    })
    const runtime = saved({
      state: 'triggered',
      title: 'Old title',
      payload: { route: 'old' },
      lastClosedTime: 240,
      lastTriggeredAt: 1000,
      lastTriggeredTime: 240,
    })
    expect(mergeAlertRuntime(doc(definition), doc(runtime))).toEqual(
      doc({
        ...definition,
        state: 'triggered',
        lastClosedTime: 240,
        lastTriggeredAt: 1000,
        lastTriggeredTime: 240,
      })
    )
    expect(definition.state).toBe('armed')
  })

  it.each<Partial<Alert>>([
    { source: { kind: 'price', price: 106 } },
    { condition: 'crossingDown' },
    { policy: 'onTouch' },
    { repeat: 'everyTime' },
    { cooldownSeconds: 60 },
    { expiresAt: 2000 },
    { scope: { symbol: 'OTHER', exchange: 'NSE', interval: '5m' } },
    { state: 'disabled' },
    { id: 'different' },
  ])('does not apply old execution state to a changed definition: %j', (patch) => {
    const definition = saved(patch)
    expect(
      mergeAlertRuntime(doc(definition), doc(saved({ state: 'triggered', lastTriggeredAt: 1000 })))
    ).toEqual(doc(definition))
  })

  it('does not resurrect absent definitions and clears old guards on explicit rearming', () => {
    expect(mergeAlertRuntime(doc(), doc(saved({ state: 'triggered' })))).toEqual(doc())
    expect(
      mergeAlertRuntime(doc(saved({ state: 'triggered', lastTriggeredAt: 1000 })), doc(saved()))
    ).toEqual(doc(saved()))
  })

  it('rejects a malformed snapshot before touching the saved definition', () => {
    const definition = doc(saved())
    expect(() => mergeAlertRuntime(definition, { version: 2, alerts: [] })).toThrow()
    expect(definition).toEqual(doc(saved()))
  })

  it('isolates accounts, workspaces and panes and removes only the deleted workspace', () => {
    const keys = [
      alertRuntimeKey('user:one', 'research', 'p0'),
      alertRuntimeKey('user', 'one:research', 'p0'),
      alertRuntimeKey('user:one', 'research', 'p1'),
      alertRuntimeKey('user:one', 'other', 'p0'),
    ]
    expect(new Set(keys).size).toBe(4)
    for (const key of keys) localStorage.setItem(key, '{}')
    localStorage.setItem('unrelated', 'preserve')
    removeWorkspaceAlertRuntime(localStorage, 'user:one', 'research')
    expect(localStorage.getItem(keys[0])).toBeNull()
    expect(localStorage.getItem(keys[2])).toBeNull()
    expect(localStorage.getItem(keys[1])).toBe('{}')
    expect(localStorage.getItem(keys[3])).toBe('{}')
    expect(localStorage.getItem('unrelated')).toBe('preserve')
  })
})
