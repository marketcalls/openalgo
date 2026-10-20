import { afterEach, describe, expect, it, vi } from 'vitest'

import { createRateLimiter } from './rateLimiter'

describe('createRateLimiter', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('expires a call exactly at the window boundary', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-01T00:00:00.000Z'))

    const limiter = createRateLimiter(1, 1000)
    expect(limiter.call()).toBe(true)

    vi.advanceTimersByTime(1000)

    expect(limiter.canCall()).toBe(true)
  })

  it('retains a call that is still inside the window', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-01-01T00:00:00.000Z'))

    const limiter = createRateLimiter(1, 1000)
    expect(limiter.call()).toBe(true)

    vi.advanceTimersByTime(999)

    expect(limiter.canCall()).toBe(false)
  })
})
