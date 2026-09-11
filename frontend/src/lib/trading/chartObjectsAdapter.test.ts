import type { ChartObjectDrawing, ChartObjectDrawingSource } from 'openalgo-charts'
import { describe, expect, it, vi } from 'vitest'
import { CurrentDrawingSource, profileObjectProvider } from './chartObjectsAdapter'

function drawing(id: string): ChartObjectDrawing {
  return {
    id,
    tool: 'trend-line',
    paneIndex: 0,
    points: [
      { time: 1, price: 100 },
      { time: 2, price: 110 },
    ],
  }
}

function source(item: ChartObjectDrawing): ChartObjectDrawingSource {
  return {
    drawings: vi.fn(() => [item]),
    get: vi.fn((id) => (id === item.id ? item : undefined)),
    selection: vi.fn(() => [item.id]),
    select: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(() => true),
  }
}

describe('CurrentDrawingSource', () => {
  it('is an inert structural source before the lazy drawing tier attaches', () => {
    const current = new CurrentDrawingSource()

    expect(current.drawings()).toEqual([])
    expect(current.get('old')).toBeUndefined()
    expect(current.selection()).toEqual([])
    expect(current.remove('old')).toBe(false)
    expect(() => current.select('old')).not.toThrow()
    expect(() => current.update('old', { locked: true })).not.toThrow()
  })

  it('forwards operations only to the current chart generation', () => {
    const first = source(drawing('first'))
    const second = source(drawing('second'))
    const current = new CurrentDrawingSource()

    current.attach(first)
    expect(current.drawings()).toEqual([expect.objectContaining({ id: 'first' })])

    current.attach(second)
    current.select('second', true)
    current.update('second', { visible: false })
    expect(current.remove('second')).toBe(true)

    expect(first.select).not.toHaveBeenCalled()
    expect(first.update).not.toHaveBeenCalled()
    expect(first.remove).not.toHaveBeenCalled()
    expect(second.select).toHaveBeenCalledWith('second', true)
    expect(second.update).toHaveBeenCalledWith('second', { visible: false })
    expect(second.remove).toHaveBeenCalledWith('second')
  })

  it('does not clear a newer generation through a stale detach', () => {
    const first = source(drawing('first'))
    const second = source(drawing('second'))
    const current = new CurrentDrawingSource()

    current.attach(first)
    current.attach(second)
    current.detach(first)

    expect(current.get('second')).toEqual(expect.objectContaining({ id: 'second' }))
    current.detach(second)
    expect(current.drawings()).toEqual([])
  })
})

describe('profileObjectProvider', () => {
  it('registers TPO with settings as its only operation', () => {
    const openSettings = vi.fn()
    const provider = profileObjectProvider('tpo', openSettings)

    expect(provider.id).toBe('profile:tpo')
    expect(provider.get()).toEqual({
      kind: 'profile',
      name: 'Time Price Opportunity',
      paneIndex: 0,
      visible: true,
    })
    provider.openSettings?.()
    expect(openSettings).toHaveBeenCalledOnce()
    expect(provider).not.toHaveProperty('remove')
    expect(provider).not.toHaveProperty('setVisible')
    expect(provider).not.toHaveProperty('setLocked')
    expect(provider).not.toHaveProperty('select')
    expect(provider).not.toHaveProperty('focus')
  })

  it('names the session volume profile explicitly', () => {
    expect(profileObjectProvider('session-volume-profile', vi.fn()).get()?.name).toBe(
      'Session Volume Profile'
    )
  })
})
