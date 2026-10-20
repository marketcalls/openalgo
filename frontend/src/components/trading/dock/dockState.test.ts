import { beforeEach, describe, expect, it } from 'vitest'
import {
  clampDockHeight,
  DOCK_HEIGHT_KEY,
  DOCK_KEY,
  dockMaxHeight,
  escapeTarget,
  isDockTab,
  readDockHeight,
  readDockTab,
  writeDockTab,
} from './dockState'

describe('dockState', () => {
  beforeEach(() => localStorage.clear())

  it('recognises only the tabs the dock renders', () => {
    expect(isDockTab('orders')).toBe(true)
    expect(isDockTab('gtt')).toBe(true)
    expect(isDockTab('holdings')).toBe(false)
    expect(isDockTab('closed')).toBe(false)
    expect(isDockTab(null)).toBe(false)
  })

  it('reads a remembered tab and treats anything else as closed', () => {
    localStorage.setItem(DOCK_KEY, 'positions')
    expect(readDockTab()).toBe('positions')
    localStorage.setItem(DOCK_KEY, 'closed')
    expect(readDockTab()).toBeNull()
    localStorage.setItem(DOCK_KEY, 'depth')
    expect(readDockTab()).toBeNull()
  })

  it('writes closed as a word rather than removing the key', () => {
    writeDockTab('trades')
    expect(localStorage.getItem(DOCK_KEY)).toBe('trades')
    writeDockTab(null)
    expect(localStorage.getItem(DOCK_KEY)).toBe('closed')
  })

  it('clamps the height between the minimum and 60 percent of the viewport', () => {
    expect(dockMaxHeight(1000)).toBe(600)
    expect(clampDockHeight(50, 1000)).toBe(120)
    expect(clampDockHeight(900, 1000)).toBe(600)
    expect(clampDockHeight(300.4, 1000)).toBe(300)
    expect(clampDockHeight(Number.NaN, 1000)).toBe(240)
    // A tiny viewport still leaves the minimum standing.
    expect(dockMaxHeight(100)).toBe(120)
  })

  it('reads a remembered height through the clamp', () => {
    expect(readDockHeight(1000)).toBe(240)
    localStorage.setItem(DOCK_HEIGHT_KEY, '333')
    expect(readDockHeight(1000)).toBe(333)
    localStorage.setItem(DOCK_HEIGHT_KEY, '5000')
    expect(readDockHeight(1000)).toBe(600)
    localStorage.setItem(DOCK_HEIGHT_KEY, 'tall')
    expect(readDockHeight(1000)).toBe(240)
  })

  it('lets Escape take the dock only while it is topmost with focus', () => {
    expect(escapeTarget({ dock: true, panel: false, focusInDock: false })).toBe('dock')
    expect(escapeTarget({ dock: true, panel: true, focusInDock: true })).toBe('dock')
    expect(escapeTarget({ dock: true, panel: true, focusInDock: false })).toBe('panel')
    expect(escapeTarget({ dock: false, panel: true, focusInDock: false })).toBe('panel')
    expect(escapeTarget({ dock: false, panel: false, focusInDock: false })).toBeNull()
  })
})
