import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ALERT_DURATION_OPTIONS,
  ALERT_SOUND_OPTIONS,
  alertSoundManager,
  durationToMilliseconds,
  readyAudioContext,
} from './alertSoundManager'

describe('alert sound configuration options', () => {
  it('provides the 5 distinctive sound options', () => {
    const keys = ALERT_SOUND_OPTIONS.map((one) => one.value)
    expect(keys).toEqual(['chime', 'siren', 'radar', 'beep', 'synth'])
  })

  it('provides all required duration choices including until dismissed', () => {
    const durations = ALERT_DURATION_OPTIONS.map((one) => one.value)
    expect(durations).toEqual(['once', '3s', '5s', '10s', '30s', '1m', '5m', 'untilDismissed'])
  })

  it('converts duration keys to accurate millisecond timeouts', () => {
    expect(durationToMilliseconds('once')).toBe(0)
    expect(durationToMilliseconds('3s')).toBe(3000)
    expect(durationToMilliseconds('5s')).toBe(5000)
    expect(durationToMilliseconds('10s')).toBe(10000)
    expect(durationToMilliseconds('30s')).toBe(30000)
    expect(durationToMilliseconds('1m')).toBe(60000)
    expect(durationToMilliseconds('5m')).toBe(300000)
    expect(durationToMilliseconds('untilDismissed')).toBeNull()
  })
})

describe('alert sound manager audio execution', () => {
  let createdNodes: string[] = []

  beforeEach(() => {
    vi.useFakeTimers()
    createdNodes = []

    class FakeGain {
      gain = {
        value: 1,
        setValueAtTime: vi.fn(),
        exponentialRampToValueAtTime: vi.fn(),
      }
      connect = vi.fn().mockReturnThis()
    }

    class FakeOscillator {
      type = 'sine'
      frequency = {
        value: 440,
        setValueAtTime: vi.fn(),
        exponentialRampToValueAtTime: vi.fn(),
      }
      connect = vi.fn().mockReturnThis()
      start = vi.fn()
      stop = vi.fn()
    }

    class FakeAudioContext {
      currentTime = 0
      state = 'running'
      destination = {}
      createGain() {
        createdNodes.push('gain')
        return new FakeGain()
      }
      createOscillator() {
        createdNodes.push('oscillator')
        return new FakeOscillator()
      }
      resume = vi.fn().mockResolvedValue(undefined)
    }

    vi.stubGlobal('AudioContext', FakeAudioContext)
    alertSoundManager.dismissAll()
  })

  afterEach(() => {
    alertSoundManager.dismissAll()
    vi.clearAllTimers()
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('plays one-shot sound without keeping it in ringing state', () => {
    const ok = alertSoundManager.trigger({
      id: 'a1',
      title: 'TCS above 3500',
      soundName: 'chime',
      duration: 'once',
    })
    expect(ok).toBe(true)
    expect(createdNodes.length).toBeGreaterThan(0)
    expect(alertSoundManager.isRinging()).toBe(false)
    expect(alertSoundManager.getRingingAlerts()).toHaveLength(0)
  })

  it('manages persistent ringing until dismissed', () => {
    let notifiedCount = 0
    const unsub = alertSoundManager.subscribe((ringing) => {
      notifiedCount = ringing.length
    })

    const ok = alertSoundManager.trigger({
      id: 'persistent-1',
      title: 'INFY below 1400',
      soundName: 'siren',
      duration: 'untilDismissed',
      volume: 0.9,
    })

    expect(ok).toBe(true)
    expect(alertSoundManager.isRinging()).toBe(true)
    expect(notifiedCount).toBe(1)
    expect(alertSoundManager.getRingingAlerts()[0]?.id).toBe('persistent-1')

    // Advance time - should continue ringing
    vi.advanceTimersByTime(3000)
    expect(alertSoundManager.isRinging()).toBe(true)

    // Manual dismissal stops ringing immediately
    alertSoundManager.dismiss('persistent-1')
    expect(alertSoundManager.isRinging()).toBe(false)
    expect(notifiedCount).toBe(0)

    unsub()
  })

  it('automatically stops timed persistent ringing after duration expires', () => {
    alertSoundManager.trigger({
      id: 'timed-alert',
      title: 'NIFTY Breakout',
      soundName: 'beep',
      duration: '3s',
    })

    expect(alertSoundManager.isRinging()).toBe(true)

    // Advance time past 3s
    vi.advanceTimersByTime(3500)
    expect(alertSoundManager.isRinging()).toBe(false)
  })

  it('prevents duplicate ringing loop for same alert id', () => {
    alertSoundManager.trigger({
      id: 'dup-1',
      title: 'CRUDEOIL Cross',
      soundName: 'radar',
      duration: 'untilDismissed',
    })

    // Trigger again with same ID
    alertSoundManager.trigger({
      id: 'dup-1',
      title: 'CRUDEOIL Cross',
      soundName: 'radar',
      duration: 'untilDismissed',
    })

    expect(alertSoundManager.getRingingAlerts()).toHaveLength(1)
  })

  it('supports previewing different sound types', () => {
    expect(alertSoundManager.preview('siren', 0.5)).toBe(true)
    expect(alertSoundManager.preview('synth', 0.7)).toBe(true)
    expect(alertSoundManager.preview('radar', 0.8)).toBe(true)
    expect(alertSoundManager.preview('beep', 0.6)).toBe(true)
    expect(alertSoundManager.preview('chime', 0.8)).toBe(true)
  })

  it('dismissAll clears multiple active alerts immediately', () => {
    alertSoundManager.trigger({
      id: 'a1',
      title: 'Alert 1',
      soundName: 'chime',
      duration: 'untilDismissed',
    })
    alertSoundManager.trigger({
      id: 'a2',
      title: 'Alert 2',
      soundName: 'synth',
      duration: 'untilDismissed',
    })

    expect(alertSoundManager.getRingingAlerts()).toHaveLength(2)
    alertSoundManager.dismissAll()
    expect(alertSoundManager.isRinging()).toBe(false)
    expect(alertSoundManager.getRingingAlerts()).toHaveLength(0)
  })

  it('readies audio context without throwing', () => {
    expect(() => readyAudioContext()).not.toThrow()
  })
})
