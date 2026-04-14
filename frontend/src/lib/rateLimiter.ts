/**
 * Rate Limiting Utilities
 *
 * Provides client-side rate limiting to prevent excessive API calls
 * and improve user experience by preventing accidental double-clicks.
 */

/**
 * Creates a debounced version of a function that delays execution
 * until after `wait` milliseconds have elapsed since the last call.
 *
 * @param fn - The function to debounce
 * @param wait - The number of milliseconds to delay
 * @returns A debounced version of the function
 */
export function debounce<T extends (...args: Parameters<T>) => ReturnType<T>>(
  fn: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeoutId: ReturnType<typeof setTimeout> | null = null

  return function debounced(...args: Parameters<T>): void {
    if (timeoutId !== null) {
      clearTimeout(timeoutId)
    }

    timeoutId = setTimeout(() => {
      fn(...args)
      timeoutId = null
    }, wait)
  }
}

/**
 * Creates a throttled version of a function that only executes
 * at most once per `wait` milliseconds.
 *
 * @param fn - The function to throttle
 * @param wait - The minimum time between function calls in milliseconds
 * @returns A throttled version of the function
 */
export function throttle<T extends (...args: Parameters<T>) => ReturnType<T>>(
  fn: T,
  wait: number
): (...args: Parameters<T>) => void {
  let lastCall = 0
  let timeoutId: ReturnType<typeof setTimeout> | null = null

  return function throttled(...args: Parameters<T>): void {
    const now = Date.now()
    const remaining = wait - (now - lastCall)

    if (remaining <= 0) {
      if (timeoutId !== null) {
        clearTimeout(timeoutId)
        timeoutId = null
      }
      lastCall = now
      fn(...args)
    } else if (timeoutId === null) {
      timeoutId = setTimeout(() => {
        lastCall = Date.now()
        timeoutId = null
        fn(...args)
      }, remaining)
    }
  }
}

/**
 * Creates a rate limiter that allows at most `maxCalls` calls
 * within a `windowMs` time window.
 *
 * @param maxCalls - Maximum number of calls allowed in the window
 * @param windowMs - Time window in milliseconds
 * @returns An object with `canCall()` to check limits and `call()` to execute
 */
export function createRateLimiter(maxCalls: number, windowMs: number) {
  const timestamps: number[] = []

  function cleanup() {
    const now = Date.now()
    while (timestamps.length > 0 && timestamps[0] < now - windowMs) {
      timestamps.shift()
    }
  }

  return {
    /**
     * Check if a call is allowed without consuming a slot
     */
    canCall(): boolean {
      cleanup()
      return timestamps.length < maxCalls
    },

    /**
     * Record a call and return whether it was allowed
     */
    call(): boolean {
      cleanup()
      if (timestamps.length < maxCalls) {
        timestamps.push(Date.now())
        return true
      }
      return false
    },

    /**
     * Get remaining calls available in current window
     */
    remaining(): number {
      cleanup()
      return Math.max(0, maxCalls - timestamps.length)
    },

    /**
     * Get time until next call is available (0 if available now)
     */
    timeUntilNext(): number {
      cleanup()
      if (timestamps.length < maxCalls) {
        return 0
      }
      return Math.max(0, timestamps[0] + windowMs - Date.now())
    },

    /**
     * Reset the rate limiter
     */
    reset(): void {
      timestamps.length = 0
    },
  }
}

/**
 * Creates a function wrapper that prevents duplicate calls while
 * a previous call is still pending.
 *
 * @param fn - An async function to wrap
 * @returns A wrapped function that prevents concurrent execution
 */
export function preventConcurrent<
  T extends (...args: Parameters<T>) => Promise<Awaited<ReturnType<T>>>,
>(fn: T): (...args: Parameters<T>) => Promise<Awaited<ReturnType<T>> | undefined> {
  let isPending = false

  return async (...args: Parameters<T>): Promise<Awaited<ReturnType<T>> | undefined> => {
    if (isPending) {
      return undefined
    }

    isPending = true
    try {
      return await fn(...args)
    } finally {
      isPending = false
    }
  }
}

// Pre-configured rate limiters for common use cases
export const orderRateLimiter = createRateLimiter(10, 1000) // 10 orders per second
export const apiRateLimiter = createRateLimiter(50, 1000) // 50 API calls per second
export const searchRateLimiter = createRateLimiter(5, 1000) // 5 searches per second
