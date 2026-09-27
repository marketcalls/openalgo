import type { Bar, ReplayGroupChartHost, ReplayState, SeriesApi } from 'openalgo-charts'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { replayTiming } from './replayTiming'
import {
  type PreparedReplayMember,
  WorkspaceReplayCoordinator,
  type WorkspaceReplayTerminal,
} from './workspaceReplay'

const T = 1700000000
const bars = (step = 60, count = 8): Bar[] =>
  Array.from({ length: count }, (_, index) => ({
    time: T + index * step,
    open: 10,
    high: 12,
    low: 8,
    close: 10 + index,
  }))

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}

async function flush() {
  for (let index = 0; index < 10; index++) await Promise.resolve()
}

class Terminal implements WorkspaceReplayTerminal {
  data: Bar[]
  active = false
  locked = false
  current = true
  token = 0
  pick: ((time: number) => void) | null = null
  cancelPick: (() => void) | null = null
  preview: ((time: number) => void) | null = null
  previewTime: number | null = null
  invalidate: (() => void) | null = null
  pending: Promise<PreparedReplayMember> | null = null
  signal: AbortSignal | null = null
  writtenWhileActive: boolean[] = []
  destroyListeners = new Set<() => void>()
  readonly chart: ReplayGroupChartHost
  readonly series: SeriesApi

  constructor(
    readonly id: string,
    readonly interval = '1m',
    step = 60
  ) {
    this.data = bars(step)
    this.series = {
      getData: () => this.data,
      setData: (next: readonly Bar[]) => {
        this.writtenWhileActive.push(this.active)
        this.data = [...next]
      },
    } as unknown as SeriesApi
    const scale = {
      barSpacing: 8,
      rightOffset: 3,
      setBarSpacing: (value: number) => {
        scale.barSpacing = value
      },
      setRightOffset: (value: number) => {
        scale.rightOffset = value
      },
    }
    this.chart = {
      timeScale: scale,
      primarySeries: () => this.series,
      emit: () => {},
      on: (_event, callback) => {
        this.destroyListeners.add(callback)
        return () => {
          this.destroyListeners.delete(callback)
        }
      },
    }
  }

  prepared(): PreparedReplayMember {
    return {
      member: {
        id: this.id,
        chart: this.chart,
        options: { series: this.series, timing: replayTiming(this.interval, 'UTC') },
      },
      isCurrent: () => this.current,
    }
  }

  beginWorkspaceReplayPick = vi.fn(
    (onPick: (time: number) => void, onCancel: () => void, onPreview?: (time: number) => void) => {
      this.pick = onPick
      this.cancelPick = onCancel
      this.preview = onPreview ?? null
      onPreview?.(T + 60)
      return true
    }
  )
  setWorkspaceReplayPreview = vi.fn((time: number | null) => {
    this.previewTime = time
  })
  cancelReplayPick = vi.fn(() => {
    this.pick = null
    this.cancelPick = null
  })
  prepareReplayMember = vi.fn((args: { id: string; sessionId: number; signal: AbortSignal }) => {
    this.token = args.sessionId
    this.signal = args.signal
    return this.pending ?? Promise.resolve(this.prepared())
  })
  setReplayParticipation = vi.fn((sessionId: number, active: boolean, _state?: ReplayState) => {
    if (sessionId === this.token) this.active = active
  })
  restoreReplayMember = vi.fn((sessionId: number) => {
    if (sessionId === this.token) this.active = false
  })
  setWorkspaceReplayLocked = vi.fn((locked: boolean) => {
    this.locked = locked
  })
  setReplayInvalidationHandler = vi.fn((handler: (() => void) | null) => {
    this.invalidate = handler
  })
}

const liveOwners = new Set<WorkspaceReplayCoordinator>()
function setup(...members: Terminal[]) {
  const changed = vi.fn(),
    errors = vi.fn()
  const owner = new WorkspaceReplayCoordinator({ onChange: changed, onError: errors })
  liveOwners.add(owner)
  owner.setMembers(members.map((terminal) => ({ id: terminal.id, terminal })))
  return { owner, changed, errors }
}

afterEach(() => {
  for (const owner of liveOwners) owner.destroy()
  liveOwners.clear()
  vi.useRealTimers()
})

describe('workspace replay coordination with the published engine', () => {
  it('locks every visible pane while picking and captures the selected owner', async () => {
    const a = new Terminal('a'),
      b = new Terminal('b')
    const { owner } = setup(a, b)
    owner.start('b')
    expect(owner.state()).toMatchObject({ phase: 'picking', ownerId: 'b', scope: 'focused' })
    expect(a.locked && b.locked).toBe(true)
    owner.start('a')
    expect(a.beginWorkspaceReplayPick).not.toHaveBeenCalled()
    b.pick?.(T + 180)
    await flush()
    expect(owner.state()).toMatchObject({
      phase: 'active',
      ownerId: 'b',
      state: { focusedId: 'b', time: T + 180 },
    })
    expect(a.data).toHaveLength(8)
    expect(b.data).toHaveLength(3)
    expect(b.writtenWhileActive.every(Boolean)).toBe(true)
    owner.stop()
    expect(b.data).toHaveLength(8)
    expect(a.locked || b.locked).toBe(false)
  })

  it('waits for all preparations, then aligns unlike intervals without future bars', async () => {
    const a = new Terminal('a'),
      b = new Terminal('b', '5m', 300)
    const loading = deferred<PreparedReplayMember>()
    b.pending = loading.promise
    const { owner } = setup(a, b)
    owner.start('a')
    owner.setScope('all')
    a.pick?.(T + 120)
    await flush()
    expect(owner.state().phase).toBe('loading')
    expect(a.data).toHaveLength(8)
    loading.resolve(b.prepared())
    await flush()
    expect(a.data).toHaveLength(2)
    expect(b.data).toHaveLength(0)
    owner.step()
    expect(owner.state().state?.time).toBe(T + 180)
    expect(b.data).toHaveLength(0)
    owner.seek(4)
    expect(owner.state().state?.time).toBe(T + 300)
    expect(b.data).toHaveLength(1)
  })

  it('delegates playback to one engine timer and clears it on exit', async () => {
    vi.useFakeTimers()
    const a = new Terminal('a'),
      b = new Terminal('b')
    const { owner } = setup(a, b)
    owner.start('a')
    owner.setScope('all')
    a.pick?.(T + 60)
    await flush()
    owner.play()
    expect(vi.getTimerCount()).toBe(1)
    vi.advanceTimersByTime(1000)
    expect(owner.state().state?.time).toBe(T + 120)
    owner.play(2)
    expect(vi.getTimerCount()).toBe(1)
    vi.advanceTimersByTime(500)
    expect(owner.state().state?.time).toBe(T + 180)
    owner.pause()
    expect(vi.getTimerCount()).toBe(0)
    owner.stepBack()
    expect(owner.state().state?.time).toBe(T + 120)
    owner.play()
    owner.stop()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('recaptures current inactive data on scope entry and restores after engine writes', async () => {
    const a = new Terminal('a'),
      b = new Terminal('b')
    const { owner, changed } = setup(a, b)
    owner.start('a')
    a.pick?.(T + 180)
    await flush()
    b.data = bars(60, 10)
    owner.setScope('all')
    expect(owner.state().state?.time).toBe(T + 180)
    expect(b.data).toHaveLength(3)
    expect(b.active).toBe(true)
    owner.setScope('focused')
    expect(b.data).toHaveLength(10)
    expect(b.active).toBe(false)
    expect(b.locked).toBe(true)
    expect(changed.mock.calls.at(-1)?.[0]).toMatchObject({ phase: 'active', scope: 'focused' })
  })

  it('restores every started member when any preparation fails, retaining the original error', async () => {
    const a = new Terminal('a'),
      b = new Terminal('b'),
      c = new Terminal('c')
    const failure = new Error('History unavailable')
    b.pending = Promise.reject(failure)
    c.pending = new Promise(() => {})
    a.restoreReplayMember.mockImplementation(() => {
      throw new Error('Restoration failed')
    })
    const { owner, errors } = setup(a, b, c)
    owner.start('a')
    a.pick?.(T + 60)
    await flush()
    expect(owner.state().phase).toBe('idle')
    for (const terminal of [a, b, c]) {
      expect(terminal.restoreReplayMember).toHaveBeenCalled()
      expect(terminal.signal?.aborted).toBe(true)
      expect(terminal.locked).toBe(false)
    }
    expect(errors).toHaveBeenCalledWith(failure)
  })

  it('ignores a cancelled late preparation without unpausing a newer session', async () => {
    const a = new Terminal('a'),
      late = deferred<PreparedReplayMember>()
    a.pending = late.promise
    const { owner } = setup(a)
    owner.start('a')
    a.pick?.(T + 60)
    await flush()
    const oldToken = a.token,
      oldSignal = a.signal
    owner.stop()
    expect(oldSignal?.aborted).toBe(true)
    a.pending = null
    owner.start('a')
    a.pick?.(T + 180)
    await flush()
    expect(a.token).not.toBe(oldToken)
    late.resolve(a.prepared())
    await flush()
    expect(owner.state()).toMatchObject({ phase: 'active', state: { time: T + 180 } })
    expect(a.active && a.locked).toBe(true)
  })

  it('rejects stale captures before a chart is projected', async () => {
    const a = new Terminal('a'),
      b = new Terminal('b')
    b.current = false
    const { owner, errors } = setup(a, b)
    owner.start('a')
    a.pick?.(T + 60)
    await flush()
    expect(owner.state().phase).toBe('idle')
    expect(a.data).toHaveLength(8)
    expect(errors).toHaveBeenCalledOnce()
    expect(a.locked || b.locked).toBe(false)
  })

  it('stops every member on source invalidation or membership replacement', async () => {
    const a = new Terminal('a'),
      b = new Terminal('b')
    const { owner } = setup(a, b)
    owner.start('a')
    owner.setScope('all')
    a.pick?.(T + 60)
    await flush()
    b.invalidate?.()
    expect(owner.state().phase).toBe('idle')
    expect(a.data).toHaveLength(8)
    expect(b.data).toHaveLength(8)
    owner.start('a')
    a.pick?.(T + 120)
    await flush()
    owner.setMembers([{ id: 'b', terminal: b }])
    expect(owner.state().phase).toBe('idle')
    expect(a.invalidate).toBeNull()
    expect(a.locked || b.locked).toBe(false)
  })

  it('retains an active session on invalid transport input and failed scope preparation', async () => {
    const a = new Terminal('a'),
      b = new Terminal('b')
    const { owner, errors } = setup(a, b)
    owner.start('a')
    a.pick?.(T + 120)
    await flush()
    const state = owner.state().state
    owner.play(0)
    expect(owner.state().state).toEqual(state)
    b.data = [{ ...b.data[0] }, { ...b.data[0] }]
    owner.setScope('all')
    expect(owner.state()).toMatchObject({
      phase: 'active',
      scope: 'focused',
      state: { time: T + 120 },
    })
    expect(a.active).toBe(true)
    expect(b.active).toBe(false)
    expect(errors).toHaveBeenCalledTimes(2)
  })

  it('cleans up on chart destruction and attempts all terminal restorations after a failure', async () => {
    const a = new Terminal('a'),
      b = new Terminal('b')
    const { owner, errors } = setup(a, b)
    owner.start('a')
    owner.setScope('all')
    a.pick?.(T + 120)
    await flush()
    a.restoreReplayMember.mockImplementation(() => {
      throw new Error('Restore failed')
    })
    for (const destroy of a.destroyListeners) destroy()
    expect(owner.state().phase).toBe('idle')
    expect(b.restoreReplayMember).toHaveBeenCalled()
    expect(a.locked || b.locked).toBe(false)
    expect(errors).toHaveBeenCalled()
    owner.destroy()
    expect(a.invalidate).toBeNull()
    expect(b.invalidate).toBeNull()
  })

  it('unlocks a refused picker and supports cancel before any preparation', () => {
    const a = new Terminal('a'),
      b = new Terminal('b')
    const { owner } = setup(a, b)
    a.beginWorkspaceReplayPick.mockReturnValueOnce(false)
    owner.start('a')
    expect(owner.state().phase).toBe('idle')
    expect(a.locked || b.locked).toBe(false)
    owner.start('a')
    a.cancelPick?.()
    expect(owner.state().phase).toBe('idle')
    expect(a.prepareReplayMember).not.toHaveBeenCalled()
  })

  it('restores the engine snapshot before abort listeners publish newer live data', async () => {
    const a = new Terminal('a')
    const latest = bars(60, 10)
    const prepare = a.prepareReplayMember.getMockImplementation()!
    a.prepareReplayMember.mockImplementation((args) => {
      args.signal.addEventListener('abort', () => {
        a.data = latest
      })
      return prepare(args)
    })
    const { owner } = setup(a)
    owner.start('a')
    a.pick?.(T + 120)
    await flush()
    owner.stop()
    expect(a.data).toEqual(latest)
  })

  it('stops a stale session before transport can expose the old captured source', async () => {
    const a = new Terminal('a')
    const { owner, errors } = setup(a)
    owner.start('a')
    a.pick?.(T + 120)
    await flush()
    a.current = false
    owner.step()
    expect(owner.state()).toMatchObject({ phase: 'idle', state: null })
    expect(a.data).toHaveLength(8)
    expect(a.locked).toBe(false)
    expect(errors).toHaveBeenCalledOnce()
  })

  it('does not publish a stale frame when terminal notification reentrantly stops replay', async () => {
    const a = new Terminal('a'),
      b = new Terminal('b')
    const { owner, changed } = setup(a, b)
    const participate = a.setReplayParticipation.getMockImplementation()!
    a.setReplayParticipation.mockImplementation((id, active, state) => {
      participate(id, active, state)
      if (active && state) owner.stop()
    })
    owner.start('a')
    owner.setScope('all')
    a.pick?.(T + 120)
    await flush()
    expect(owner.state()).toEqual({ phase: 'idle', scope: 'all', ownerId: null, state: null })
    expect(changed.mock.calls.at(-1)?.[0].state).toBeNull()
    expect(a.active || b.active || a.locked || b.locked).toBe(false)
  })

  it('does not start later preparations after synchronous cancellation', async () => {
    const a = new Terminal('a'),
      b = new Terminal('b')
    const { owner } = setup(a, b)
    const prepare = a.prepareReplayMember.getMockImplementation()!
    a.prepareReplayMember.mockImplementation((args) => {
      const result = prepare(args)
      owner.stop()
      return result
    })
    owner.start('a')
    a.pick?.(T + 120)
    await flush()
    expect(owner.state().phase).toBe('idle')
    expect(b.prepareReplayMember).not.toHaveBeenCalled()
    expect(a.locked || b.locked).toBe(false)
  })

  it('supports onChange stopping and starting a replacement without stale publication', async () => {
    const a = new Terminal('a'),
      b = new Terminal('b')
    const { owner, changed } = setup(a, b)
    let replaced = false
    changed.mockImplementation((snapshot) => {
      if (snapshot.phase === 'active' && !replaced) {
        replaced = true
        owner.stop()
        owner.start('b')
      }
    })
    owner.start('a')
    a.pick?.(T + 120)
    await flush()
    expect(owner.state()).toEqual({ phase: 'picking', scope: 'focused', ownerId: 'b', state: null })
    expect(a.data).toHaveLength(8)
    expect(a.locked && b.locked).toBe(true)
    b.pick?.(T + 180)
    await flush()
    expect(owner.state()).toMatchObject({ phase: 'active', ownerId: 'b', state: { time: T + 180 } })
  })

  it('attempts every registration cleanup if a removed terminal throws', async () => {
    const a = new Terminal('a'),
      b = new Terminal('b'),
      c = new Terminal('c')
    const { owner, errors } = setup(a, b)
    a.setReplayInvalidationHandler.mockImplementation((handler) => {
      if (handler === null) throw new Error('Listener cleanup failed')
      a.invalidate = handler
    })
    owner.start('a')
    a.pick?.(T + 120)
    await flush()
    expect(() => owner.setMembers([{ id: 'c', terminal: c }])).not.toThrow()
    expect(b.invalidate).toBeNull()
    expect(c.invalidate).not.toBeNull()
    expect(a.locked || b.locked).toBe(false)
    expect(errors).toHaveBeenCalledOnce()
    owner.start('c')
    expect(owner.state().ownerId).toBe('c')
  })

  it('shares picker preview time only with followers in all scope and clears before preparation', async () => {
    const a = new Terminal('a'),
      b = new Terminal('b', '5m', 300),
      c = new Terminal('c')
    const { owner } = setup(a, b, c)
    owner.start('a')
    expect(b.previewTime).toBeNull()
    owner.setScope('all')
    expect(b.previewTime).toBe(T + 60)
    expect(c.previewTime).toBe(T + 60)
    a.preview?.(T + 180)
    expect(b.previewTime).toBe(T + 180)
    expect(a.setWorkspaceReplayPreview).not.toHaveBeenCalled()
    owner.setScope('focused')
    expect(b.previewTime).toBeNull()
    owner.setScope('all')
    const prepare = b.prepareReplayMember.getMockImplementation()!
    b.prepareReplayMember.mockImplementation((args) => {
      expect(b.previewTime).toBeNull()
      return prepare(args)
    })
    a.pick?.(T + 180)
    await flush()
    expect(owner.state().phase).toBe('active')
    expect(b.previewTime).toBeNull()
    owner.stop()
    expect(c.previewTime).toBeNull()
  })

  it('clears every follower shade on cancellation and ignores stale preview callbacks', () => {
    const a = new Terminal('a'),
      b = new Terminal('b')
    const { owner } = setup(a, b)
    owner.start('a')
    owner.setScope('all')
    const preview = a.preview
    owner.stop()
    expect(b.previewTime).toBeNull()
    preview?.(T + 300)
    expect(b.previewTime).toBeNull()
  })
})
