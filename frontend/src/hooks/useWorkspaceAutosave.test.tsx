import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useWorkspaceAutosave } from './useWorkspaceAutosave'

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})
describe('workspace autosave ownership', () => {
  it('checks replay ownership again when a queued timer fires before React commits', async () => {
    let replaying = false
    const capture = vi.fn(() => ({ symbol: 'BHEL' })),
      save = vi.fn(async () => {})
    const { result } = renderHook(() =>
      useWorkspaceAutosave({
        identity: 'one',
        enabled: true,
        paused: false,
        isPaused: () => replaying,
        capture,
        save,
      })
    )
    act(() => result.current.changed())
    replaying = true
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    expect(capture).not.toHaveBeenCalled()
    expect(save).not.toHaveBeenCalled()
    expect(result.current.error).toBeNull()
    replaying = false
    await act(async () => result.current.flush())
    expect(save).toHaveBeenCalledExactlyOnceWith({ symbol: 'BHEL' })
  })

  it('retains dirty configuration through replay selection, loading and cancellation', async () => {
    let value = { source: 'live', color: 'blue' }
    const capture = vi.fn(() => value),
      save = vi.fn(async () => {})
    const { result, rerender } = renderHook(
      ({ phase }: { phase: 'idle' | 'picking' | 'loading' | 'active' }) =>
        useWorkspaceAutosave({
          identity: 'one',
          enabled: true,
          paused: phase !== 'idle',
          capture,
          save,
        }),
      { initialProps: { phase: 'idle' as 'idle' | 'picking' | 'loading' | 'active' } }
    )
    act(() => result.current.markSaved())
    value = { source: 'live', color: 'red' }
    act(() => result.current.changed())
    capture.mockClear()
    for (const phase of ['picking', 'loading', 'active'] as const) {
      rerender({ phase })
      value = { source: 'replay', color: 'red' }
      act(() => result.current.changed())
      await act(async () => vi.advanceTimersByTimeAsync(1000))
      expect(capture).not.toHaveBeenCalled()
      expect(save).not.toHaveBeenCalled()
    }
    value = { source: 'live', color: 'red' }
    rerender({ phase: 'idle' })
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    expect(save).toHaveBeenCalledExactlyOnceWith({ source: 'live', color: 'red' })
    expect(result.current.status).toBe('Saved')
  })

  it('keeps unchanged gestures saved while autosave is disabled', async () => {
    const save = vi.fn(async () => {})
    const { result } = renderHook(() =>
      useWorkspaceAutosave({
        identity: 'one',
        enabled: false,
        capture: () => ({ volume: true }),
        save,
      })
    )
    act(() => result.current.markSaved())
    act(() => result.current.changed())
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    expect(result.current.status).toBe('Saved')
    expect(save).not.toHaveBeenCalled()
  })

  it('keeps edits made during Save as dirty against the snapshot that actually reached storage', async () => {
    const save = vi.fn(async () => {})
    const { result } = renderHook(() =>
      useWorkspaceAutosave({ identity: 'one', enabled: true, capture: () => ({ layout: 2 }), save })
    )
    act(() => result.current.markSaved({ layout: 1 }))
    expect(result.current.status).toBe('Unsaved')
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    expect(save).toHaveBeenCalledExactlyOnceWith({ layout: 2 })
    expect(result.current.status).toBe('Saved')
  })

  it('debounces configuration changes and never polls or writes an unchanged snapshot', async () => {
    let value = { layout: 1 }
    const capture = vi.fn(() => value),
      save = vi.fn(async () => {})
    const { result } = renderHook(() =>
      useWorkspaceAutosave({ identity: 'account:one', enabled: true, capture, save })
    )
    act(() => result.current.markSaved())
    await act(async () => vi.advanceTimersByTimeAsync(5000))
    expect(save).not.toHaveBeenCalled()
    expect(capture).toHaveBeenCalledOnce()
    act(() => {
      value = { layout: 2 }
      result.current.changed()
      result.current.changed()
    })
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    expect(save).toHaveBeenCalledExactlyOnceWith({ layout: 2 })
    act(() => result.current.changed())
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    expect(save).toHaveBeenCalledOnce()
    expect(result.current.status).toBe('Saved')
  })

  it('serializes writes and coalesces changes made during an outstanding write', async () => {
    let value = 1,
      release!: () => void
    const save = vi
      .fn()
      .mockImplementationOnce(
        () =>
          new Promise<void>((resolve) => {
            release = resolve
          })
      )
      .mockResolvedValue(undefined)
    const { result } = renderHook(() =>
      useWorkspaceAutosave({ identity: 'one', enabled: true, capture: () => value, save })
    )
    act(() => result.current.changed())
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    act(() => {
      value = 2
      result.current.changed()
      value = 3
      result.current.changed()
    })
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    expect(save).toHaveBeenCalledExactlyOnceWith(1)
    await act(async () => release())
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    expect(save.mock.calls).toEqual([[1], [3]])
  })

  it('cancels queued work on identity change and ignores an outgoing save completion', async () => {
    let release!: () => void
    const oldSave = vi.fn(
        () =>
          new Promise<void>((resolve) => {
            release = resolve
          })
      ),
      newSave = vi.fn(async () => {})
    const { result, rerender } = renderHook(
      ({ identity }) =>
        useWorkspaceAutosave({
          identity,
          enabled: true,
          capture: () => identity,
          save: identity === 'one' ? oldSave : newSave,
        }),
      { initialProps: { identity: 'one' } }
    )
    act(() => result.current.changed())
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    act(() => result.current.changed())
    rerender({ identity: 'two' })
    await act(async () => {
      release()
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(oldSave).toHaveBeenCalledExactlyOnceWith('one')
    expect(newSave).not.toHaveBeenCalled()
    expect(result.current.status).toBe('Saved')
  })

  it('keeps a failed save unsaved without retrying endlessly and lets an explicit retry recover', async () => {
    const save = vi
      .fn()
      .mockRejectedValueOnce(new Error('Quota exceeded'))
      .mockResolvedValue(undefined)
    const { result } = renderHook(() =>
      useWorkspaceAutosave({ identity: 'one', enabled: true, capture: () => 1, save })
    )
    act(() => result.current.changed())
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    expect(result.current.error).toBe('Quota exceeded')
    expect(result.current.status).toBe('Unsaved')
    await act(async () => vi.advanceTimersByTimeAsync(5000))
    expect(save).toHaveBeenCalledOnce()
    await act(async () => result.current.flush())
    expect(result.current.status).toBe('Saved')
    expect(result.current.error).toBeNull()
  })

  it('keeps edits while autosave is off or loading and saves them when enabled and resumed', async () => {
    const save = vi.fn(async () => {})
    const { result, rerender } = renderHook(
      ({ enabled, paused }) =>
        useWorkspaceAutosave({ identity: 'one', enabled, paused, capture: () => 2, save }),
      { initialProps: { enabled: false, paused: false } }
    )
    act(() => result.current.changed())
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    expect(save).not.toHaveBeenCalled()
    rerender({ enabled: true, paused: true })
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    expect(save).not.toHaveBeenCalled()
    rerender({ enabled: true, paused: false })
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    expect(save).toHaveBeenCalledExactlyOnceWith(2)
  })
})
