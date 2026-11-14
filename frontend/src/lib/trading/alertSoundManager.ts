/**
 * Persistent Alert Sound Manager & Procedural Web Audio Synthesizer.
 *
 * Provides distinctive synthesised alert sounds (chime, siren, radar, beep, synth),
 * per-alert volume and duration controls, non-overlapping loop scheduling,
 * and immediate STOP/DISMISS controls for persistent alerts.
 */

export type AlertSoundName = 'chime' | 'siren' | 'radar' | 'beep' | 'synth'

export type AlertSoundDuration =
  | 'once'
  | '3s'
  | '5s'
  | '10s'
  | '30s'
  | '1m'
  | '5m'
  | 'untilDismissed'

export interface RingingAlertInfo {
  readonly id: string
  readonly title: string
  readonly soundName: AlertSoundName
  readonly volume: number
  readonly duration: AlertSoundDuration
  readonly startedAt: number
  readonly timeoutId?: ReturnType<typeof setTimeout> | null
}

export const ALERT_SOUND_OPTIONS: readonly {
  value: AlertSoundName
  label: string
  description: string
}[] = [
  { value: 'chime', label: 'Chime', description: 'Harmonic ascending chime' },
  { value: 'siren', label: 'Siren', description: 'Alternating alarm siren' },
  { value: 'radar', label: 'Radar Ping', description: 'Sonar sweep ping' },
  { value: 'beep', label: 'Electronic Beep', description: 'Crisp triple pulse beep' },
  { value: 'synth', label: 'Modern Synth', description: 'Stacked polyphonic synth chord' },
]

export const ALERT_DURATION_OPTIONS: readonly { value: AlertSoundDuration; label: string }[] = [
  { value: 'once', label: 'Once' },
  { value: '3s', label: '3 seconds' },
  { value: '5s', label: '5 seconds' },
  { value: '10s', label: '10 seconds' },
  { value: '30s', label: '30 seconds' },
  { value: '1m', label: '1 minute' },
  { value: '5m', label: '5 minutes' },
  { value: 'untilDismissed', label: 'Until Manually Dismissed' },
]

export function durationToMilliseconds(duration: AlertSoundDuration): number | null {
  switch (duration) {
    case 'once':
      return 0
    case '3s':
      return 3000
    case '5s':
      return 5000
    case '10s':
      return 10000
    case '30s':
      return 30000
    case '1m':
      return 60000
    case '5m':
      return 300000
    case 'untilDismissed':
      return null
  }
}

let sharedContext: AudioContext | null = null

function getAudioContext(): AudioContext | null {
  if (typeof window === 'undefined') return null
  const Ctor =
    window.AudioContext ??
    (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (typeof Ctor !== 'function') return null
  try {
    sharedContext ??= new Ctor()
    return sharedContext
  } catch {
    return null
  }
}

/** Synchronizes persistent ringing with local Windows-native audio service. */
function postNativeSoundStart(options: {
  alertId: string
  title: string
  soundName: AlertSoundName
  duration: AlertSoundDuration
  volume: number
}): void {
  if (typeof fetch === 'undefined') return
  void fetch('/alerts/sound/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options),
  }).catch(() => {})
}

/** Immediately silences local Windows-native audio service. */
function postNativeSoundStop(alertId?: string): void {
  if (typeof fetch === 'undefined') return
  void fetch('/alerts/sound/stop', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(alertId ? { alertId } : {}),
  }).catch(() => {})
}

/** Pre-warms or resumes AudioContext from a user interaction gesture. */
export function readyAudioContext(): void {
  const ctx = getAudioContext()
  if (ctx && ctx.state === 'suspended') {
    void ctx.resume().catch(() => {})
  }
}

/**
 * Procedurally synthesize one iteration of a sound pattern.
 * Uses Web Audio API oscillator nodes and envelope gain curves.
 */
function playPattern(
  ctx: AudioContext,
  sound: AlertSoundName,
  volume: number
): { duration: number } {
  const masterGain = ctx.createGain()
  const clampedVol = Math.max(0, Math.min(1, volume))
  masterGain.gain.setValueAtTime(clampedVol, ctx.currentTime)
  masterGain.connect(ctx.destination)

  const at = ctx.currentTime

  switch (sound) {
    case 'siren': {
      // Alternating two-tone siren
      const tones = [
        { freq: 880, start: 0, dur: 0.22 },
        { freq: 660, start: 0.24, dur: 0.22 },
        { freq: 880, start: 0.48, dur: 0.22 },
      ]
      for (const t of tones) {
        const osc = ctx.createOscillator()
        const g = ctx.createGain()
        osc.type = 'sawtooth'
        osc.frequency.setValueAtTime(t.freq, at + t.start)
        g.gain.setValueAtTime(0.0001, at + t.start)
        g.gain.exponentialRampToValueAtTime(0.25, at + t.start + 0.02)
        g.gain.exponentialRampToValueAtTime(0.0001, at + t.start + t.dur)
        osc.connect(g).connect(masterGain)
        osc.start(at + t.start)
        osc.stop(at + t.start + t.dur + 0.02)
      }
      return { duration: 0.75 }
    }

    case 'radar': {
      // Resonant sonar ping with descending pitch
      const osc1 = ctx.createOscillator()
      const osc2 = ctx.createOscillator()
      const g = ctx.createGain()
      osc1.type = 'sine'
      osc2.type = 'triangle'
      osc1.frequency.setValueAtTime(1400, at)
      osc1.frequency.exponentialRampToValueAtTime(700, at + 0.5)
      osc2.frequency.setValueAtTime(2800, at)
      osc2.frequency.exponentialRampToValueAtTime(1400, at + 0.3)

      g.gain.setValueAtTime(0.0001, at)
      g.gain.exponentialRampToValueAtTime(0.35, at + 0.01)
      g.gain.exponentialRampToValueAtTime(0.0001, at + 0.6)

      osc1.connect(g)
      osc2.connect(g)
      g.connect(masterGain)
      osc1.start(at)
      osc2.start(at)
      osc1.stop(at + 0.65)
      osc2.stop(at + 0.65)
      return { duration: 0.7 }
    }

    case 'beep': {
      // Crisp triple staccato electronic beep
      const pulses = [
        { freq: 960, start: 0, dur: 0.07 },
        { freq: 960, start: 0.12, dur: 0.07 },
        { freq: 1200, start: 0.24, dur: 0.14 },
      ]
      for (const p of pulses) {
        const osc = ctx.createOscillator()
        const g = ctx.createGain()
        osc.type = 'sine'
        osc.frequency.setValueAtTime(p.freq, at + p.start)
        g.gain.setValueAtTime(0.0001, at + p.start)
        g.gain.exponentialRampToValueAtTime(0.3, at + p.start + 0.008)
        g.gain.exponentialRampToValueAtTime(0.0001, at + p.start + p.dur)
        osc.connect(g).connect(masterGain)
        osc.start(at + p.start)
        osc.stop(at + p.start + p.dur + 0.01)
      }
      return { duration: 0.45 }
    }

    case 'synth': {
      // Modern polyphonic synth chord (A minor / C major triad)
      const notes = [523.25, 659.25, 783.99, 1046.5]
      for (const [idx, freq] of notes.entries()) {
        const osc = ctx.createOscillator()
        const g = ctx.createGain()
        osc.type = 'triangle'
        osc.frequency.setValueAtTime(freq, at + idx * 0.06)
        const noteStart = at + idx * 0.06
        g.gain.setValueAtTime(0.0001, noteStart)
        g.gain.exponentialRampToValueAtTime(0.18, noteStart + 0.02)
        g.gain.exponentialRampToValueAtTime(0.0001, noteStart + 0.5)
        osc.connect(g).connect(masterGain)
        osc.start(noteStart)
        osc.stop(noteStart + 0.52)
      }
      return { duration: 0.8 }
    }

    default: {
      // Classic ascending melodic chime (C5 -> E5 -> G5 -> C6)
      const freqs = [523.25, 659.25, 783.99, 1046.5]
      for (const [idx, freq] of freqs.entries()) {
        const osc = ctx.createOscillator()
        const g = ctx.createGain()
        osc.type = 'sine'
        const noteStart = at + idx * 0.12
        osc.frequency.setValueAtTime(freq, noteStart)
        g.gain.setValueAtTime(0.0001, noteStart)
        g.gain.exponentialRampToValueAtTime(0.25, noteStart + 0.01)
        g.gain.exponentialRampToValueAtTime(0.0001, noteStart + 0.28)
        osc.connect(g).connect(masterGain)
        osc.start(noteStart)
        osc.stop(noteStart + 0.3)
      }
      return { duration: 0.75 }
    }
  }
}

type RingingListener = (ringing: RingingAlertInfo[]) => void

class AlertSoundManager {
  private activeAlerts = new Map<string, RingingAlertInfo>()
  private loopTimer: ReturnType<typeof setInterval> | null = null
  private listeners = new Set<RingingListener>()
  private previewTimer: ReturnType<typeof setTimeout> | null = null

  /** Play a one-shot preview of a sound at the given volume. */
  public preview(soundName: AlertSoundName = 'chime', volume: number = 0.8): boolean {
    this.stopPreview()
    const ctx = getAudioContext()
    if (!ctx) return false
    try {
      if (ctx.state === 'suspended') void ctx.resume().catch(() => {})
      playPattern(ctx, soundName, volume)
      return true
    } catch {
      return false
    }
  }

  public stopPreview(): void {
    if (this.previewTimer !== null) {
      clearTimeout(this.previewTimer)
      this.previewTimer = null
    }
  }

  /**
   * Trigger an alert sound.
   * If duration is 'once', plays once immediately.
   * If duration is persistent (timed or until dismissed), adds to active ringing set
   * and schedules non-overlapping looping playback.
   */
  public trigger(options: {
    readonly id: string
    readonly title: string
    readonly soundName?: AlertSoundName
    readonly volume?: number
    readonly duration?: AlertSoundDuration
  }): boolean {
    const soundName = options.soundName ?? 'chime'
    const volume = typeof options.volume === 'number' ? options.volume : 0.8
    const duration = options.duration ?? 'once'
    const id = options.id || options.title || 'default-alert'

    const ctx = getAudioContext()
    if (ctx) {
      try {
        if (ctx.state === 'suspended') void ctx.resume().catch(() => {})
      } catch {
        // AudioContext resume failed
      }
    }

    if (duration === 'once') {
      if (ctx) {
        try {
          playPattern(ctx, soundName, volume)
        } catch {
          return false
        }
      }
      return true
    }

    // Persistent ringing:
    const now = Date.now()
    const maxMs = durationToMilliseconds(duration)
    const timeoutId =
      maxMs !== null
        ? setTimeout(() => {
            this.dismiss(id)
          }, maxMs)
        : null

    const info: RingingAlertInfo = {
      id,
      title: options.title || 'Alert',
      soundName,
      volume,
      duration,
      startedAt: now,
      timeoutId,
    }

    // If this alert is already ringing, keep it ringing without duplicating the loop
    if (!this.activeAlerts.has(id)) {
      this.activeAlerts.set(id, info)
      this.notifyListeners()
    } else {
      const existing = this.activeAlerts.get(id)
      if (existing?.timeoutId) {
        clearTimeout(existing.timeoutId)
      }
      this.activeAlerts.set(id, info)
    }

    // Play immediate first iteration
    if (ctx) {
      try {
        playPattern(ctx, soundName, volume)
      } catch {
        // ignore
      }
    }

    // Ensure loop is running
    this.ensureLoopRunning()

    // Sync with Windows native background sound
    postNativeSoundStart({
      alertId: id,
      title: options.title || 'Alert',
      soundName,
      duration,
      volume,
    })

    return true
  }

  private ensureLoopRunning(): void {
    if (this.loopTimer !== null) return

    // Loop interval: 1.25 seconds between pattern pulses
    this.loopTimer = setInterval(() => {
      this.checkTimeoutsAndTick()
    }, 1250)
  }

  private checkTimeoutsAndTick(): void {
    const now = Date.now()
    let changed = false

    for (const [id, info] of Array.from(this.activeAlerts.entries())) {
      const maxMs = durationToMilliseconds(info.duration)
      if (maxMs !== null && now - info.startedAt >= maxMs) {
        this.activeAlerts.delete(id)
        changed = true
      }
    }

    if (changed) {
      this.notifyListeners()
    }

    if (this.activeAlerts.size === 0) {
      this.stopLoop()
      return
    }

    // Play next pulse from the most recently triggered active alert
    const activeList = Array.from(this.activeAlerts.values())
    const current = activeList[activeList.length - 1]
    if (current) {
      const ctx = getAudioContext()
      if (ctx) {
        try {
          if (ctx.state === 'suspended') void ctx.resume().catch(() => {})
          playPattern(ctx, current.soundName, current.volume)
        } catch {
          // ignore
        }
      }
    }
  }

  private stopLoop(): void {
    if (this.loopTimer !== null) {
      clearInterval(this.loopTimer)
      this.loopTimer = null
    }
  }

  /** Stop and dismiss a specific active ringing alert. */
  public dismiss(id: string): void {
    if (this.activeAlerts.has(id)) {
      const existing = this.activeAlerts.get(id)
      if (existing?.timeoutId) {
        clearTimeout(existing.timeoutId)
      }
      this.activeAlerts.delete(id)
      postNativeSoundStop(id)
      this.notifyListeners()
      if (this.activeAlerts.size === 0) {
        this.stopLoop()
      }
    }
  }

  /** Stop and dismiss all active ringing alerts immediately. */
  public dismissAll(): void {
    if (this.activeAlerts.size > 0) {
      for (const info of this.activeAlerts.values()) {
        if (info.timeoutId) {
          clearTimeout(info.timeoutId)
        }
      }
      this.activeAlerts.clear()
      postNativeSoundStop()
      this.stopLoop()
      this.notifyListeners()
    }
  }

  /** Check whether any alert is actively ringing. */
  public isRinging(): boolean {
    return this.activeAlerts.size > 0
  }

  /** List of currently ringing alerts. */
  public getRingingAlerts(): readonly RingingAlertInfo[] {
    return Array.from(this.activeAlerts.values())
  }

  /** Subscribe to changes in active ringing alerts. */
  public subscribe(listener: RingingListener): () => void {
    this.listeners.add(listener)
    listener(this.getRingingAlerts() as RingingAlertInfo[])
    return () => {
      this.listeners.delete(listener)
    }
  }

  private notifyListeners(): void {
    const ringing = Array.from(this.activeAlerts.values())
    for (const listener of Array.from(this.listeners)) {
      try {
        listener(ringing)
      } catch {
        // Listener error ignored
      }
    }
  }
}

export const alertSoundManager = new AlertSoundManager()
