import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@/test/test-utils'
import MasterContract from './MasterContract'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('Master Contract polling lifetime', () => {
  it('stops polling after an initial download becomes terminal across 101 timer ticks', async () => {
    vi.useFakeTimers()
    let statusCalls = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => ({
        ok: true,
        json: async () =>
          url.includes('smart-status')
            ? { status: ++statusCalls === 1 ? 'downloading' : 'complete' }
            : {},
      }))
    )

    const page = render(<MasterContract />)
    await act(async () => {
      await Promise.resolve()
    })
    expect(statusCalls).toBe(1)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(202_000)
    })
    expect(statusCalls).toBe(2)
    page.unmount()
  })

  it('keeps only one status request pending through 101 slow-server ticks and aborts on unmount', async () => {
    vi.useFakeTimers()
    let statusCalls = 0
    let finishSlow: ((value: object) => void) | undefined
    const slow = new Promise<object>((resolve) => {
      finishSlow = resolve
    })
    let slowSignal: AbortSignal | undefined
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, options?: RequestInit) => {
        if (!url.includes('smart-status')) {
          return Promise.resolve({ ok: true, json: async () => ({}) })
        }
        statusCalls++
        if (statusCalls === 1) {
          return Promise.resolve({ ok: true, json: async () => ({ status: 'downloading' }) })
        }
        slowSignal = options?.signal ?? undefined
        return slow
      })
    )

    const page = render(<MasterContract />)
    await act(async () => {
      await Promise.resolve()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(202_000)
    })
    expect(statusCalls).toBe(2)

    page.unmount()
    expect(slowSignal?.aborted).toBe(true)
    finishSlow?.({ ok: true, json: async () => ({ status: 'downloading' }) })
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(202_000)
    expect(statusCalls).toBe(2)
  })

  it('rechecks a force download when the immediate status still shows the previous result', async () => {
    vi.useFakeTimers()
    let statusCalls = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => ({
        ok: true,
        json: async () => {
          if (url.includes('csrf-token')) return { csrf_token: 'test' }
          if (url.includes('/download')) return { status: 'success', started: true }
          if (url.includes('smart-status')) {
            statusCalls++
            return { status: statusCalls === 3 ? 'downloading' : 'complete' }
          }
          return {}
        },
      }))
    )

    const page = render(<MasterContract />)
    await act(async () => {
      await Promise.resolve()
    })
    fireEvent.click(screen.getByRole('button', { name: 'Force Download' }))
    await act(async () => {
      await Promise.resolve()
    })
    expect(statusCalls).toBe(2)

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_000)
    })
    expect(statusCalls).toBe(4)
    page.unmount()
  })
})
