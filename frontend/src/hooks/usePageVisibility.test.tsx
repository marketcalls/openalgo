import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePageVisibility } from './usePageVisibility'

const originalVisibility = Object.getOwnPropertyDescriptor(document, 'visibilityState')

function visibility(value: DocumentVisibilityState) {
  Object.defineProperty(document, 'visibilityState', { configurable: true, value })
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
  if (originalVisibility) Object.defineProperty(document, 'visibilityState', originalVisibility)
  else Reflect.deleteProperty(document, 'visibilityState')
  vi.restoreAllMocks()
  vi.useRealTimers()
})

function Observer() {
  const state = usePageVisibility()
  return <output data-testid="visibility">{JSON.stringify(state)}</output>
}

function state() {
  return JSON.parse(screen.getByTestId('visibility').textContent!)
}

describe('page visibility notifications', () => {
  it('commits visibility in a later browser task, after microtask checkpoints', async () => {
    visibility('visible')
    render(<Observer />)
    await act(async () => {
      visibility('hidden')
      document.dispatchEvent(new Event('visibilitychange'))
      await Promise.resolve()
    })
    expect(state().isVisible).toBe(true)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(state().isVisible).toBe(false)
  })
  it('defers a browser visibility event until an interrupted render has finished', async () => {
    visibility('visible')
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {})
    let sent = false
    function BrowserTransition({ fire }: { fire: boolean }) {
      if (fire && !sent) {
        sent = true
        visibility('hidden')
        // Firefox can deliver this while an outgoing page is still rendering.
        document.dispatchEvent(new Event('visibilitychange'))
      }
      return null
    }
    const view = render(
      <>
        <Observer />
        <BrowserTransition fire={false} />
      </>
    )
    await act(async () => {
      view.rerender(
        <>
          <Observer />
          <BrowserTransition fire />
        </>
      )
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(state().isVisible).toBe(false)
    expect(errors).not.toHaveBeenCalled()
  })

  it('keeps the timestamp of each transition even when events arrive in one turn', async () => {
    visibility('visible')
    let now = 1000
    vi.spyOn(Date, 'now').mockImplementation(() => now)
    render(<Observer />)
    await act(async () => {
      now = 2000
      visibility('hidden')
      document.dispatchEvent(new Event('visibilitychange'))
      now = 6000
      visibility('visible')
      document.dispatchEvent(new Event('visibilitychange'))
      now = 9000
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(state()).toMatchObject({ isVisible: true, wasHidden: true, lastVisibilityChange: 6000 })
  })

  it('ignores a pending notification after the observer unmounts', async () => {
    visibility('visible')
    const view = render(<Observer />)
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {})
    await act(async () => {
      visibility('hidden')
      document.dispatchEvent(new Event('visibilitychange'))
      view.unmount()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(errors).not.toHaveBeenCalled()
  })
})
