import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Hook to detect page visibility state using the Page Visibility API.
 *
 * This hook helps optimize resource usage by detecting when the browser tab
 * is hidden (user switched tabs, minimized window, etc.) so that WebSocket
 * connections and polling can be paused.
 *
 * @example
 * ```tsx
 * const { isVisible, wasHidden, timeSinceVisible } = usePageVisibility()
 *
 * // Pause WebSocket when hidden
 * const { data } = useLivePrice(items, {
 *   enabled: items.length > 0 && isVisible,
 * })
 *
 * // Refresh data when tab becomes visible after being hidden
 * useEffect(() => {
 *   if (isVisible && wasHidden && timeSinceVisible > 30000) {
 *     refreshData()
 *   }
 * }, [isVisible, wasHidden, timeSinceVisible])
 * ```
 */
export interface UsePageVisibilityReturn {
  /** Whether the page is currently visible */
  isVisible: boolean
  /** Whether the page was previously hidden (useful for detecting tab return) */
  wasHidden: boolean
  /** Time in ms since the page became visible (0 if currently hidden) */
  timeSinceVisible: number
  /** Time in ms since the page became hidden (0 if currently visible) */
  timeSinceHidden: number
  /** Timestamp when visibility last changed */
  lastVisibilityChange: number
}

export function usePageVisibility(): UsePageVisibilityReturn {
  // Initialize based on current document state (SSR-safe)
  const [isVisible, setIsVisible] = useState<boolean>(() =>
    typeof document !== 'undefined' ? document.visibilityState === 'visible' : true
  )

  const [wasHidden, setWasHidden] = useState<boolean>(false)
  const [lastVisibilityChange, setLastVisibilityChange] = useState<number>(Date.now())
  const [timeSinceVisible, setTimeSinceVisible] = useState<number>(0)
  const [timeSinceHidden, setTimeSinceHidden] = useState<number>(0)

  // Track previous visibility state
  const previousVisibleRef = useRef<boolean>(isVisible)
  const hiddenTimestampRef = useRef<number | null>(null)
  const visibleTimestampRef = useRef<number>(Date.now())
  // Use ref to track visibility for timer updates (avoids callback recreation)
  const isVisibleRef = useRef<boolean>(isVisible)

  // Keep ref in sync with state
  useEffect(() => {
    isVisibleRef.current = isVisible
  }, [isVisible])

  // Update time counters - uses ref to avoid effect re-runs on visibility change
  const updateTimers = useCallback(() => {
    const now = Date.now()
    if (isVisibleRef.current) {
      setTimeSinceVisible(now - visibleTimestampRef.current)
      setTimeSinceHidden(0)
    } else {
      setTimeSinceHidden(hiddenTimestampRef.current ? now - hiddenTimestampRef.current : 0)
      setTimeSinceVisible(0)
    }
  }, []) // No dependencies - uses refs instead

  useEffect(() => {
    // SSR guard
    if (typeof document === 'undefined') return

    const handleVisibilityChange = () => {
      const nowVisible = document.visibilityState === 'visible'
      const now = Date.now()

      // Detect if returning from hidden state
      if (nowVisible && !previousVisibleRef.current) {
        setWasHidden(true)
        visibleTimestampRef.current = now

        // Calculate how long the tab was hidden
        if (hiddenTimestampRef.current) {
          setTimeSinceHidden(now - hiddenTimestampRef.current)
        }
      } else if (!nowVisible) {
        hiddenTimestampRef.current = now
        setWasHidden(false)
      }

      previousVisibleRef.current = nowVisible
      setIsVisible(nowVisible)
      setLastVisibilityChange(now)
      updateTimers()
    }

    // Listen for visibility changes
    document.addEventListener('visibilitychange', handleVisibilityChange)

    // Also listen for focus/blur as backup (some browsers)
    const handleFocus = () => {
      if (!previousVisibleRef.current) {
        handleVisibilityChange()
      }
    }

    const handleBlur = () => {
      // Only update if we haven't already detected hidden via visibilitychange
      if (previousVisibleRef.current && document.visibilityState === 'hidden') {
        handleVisibilityChange()
      }
    }

    window.addEventListener('focus', handleFocus)
    window.addEventListener('blur', handleBlur)

    // Update timers periodically when visible (for timeSinceVisible accuracy)
    const timerInterval = setInterval(updateTimers, 1000)

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      window.removeEventListener('focus', handleFocus)
      window.removeEventListener('blur', handleBlur)
      clearInterval(timerInterval)
    }
  }, [updateTimers])

  // Reset wasHidden after a short delay (so consumers can react to it)
  useEffect(() => {
    if (wasHidden) {
      const timeout = setTimeout(() => setWasHidden(false), 100)
      return () => clearTimeout(timeout)
    }
  }, [wasHidden])

  return {
    isVisible,
    wasHidden,
    timeSinceVisible,
    timeSinceHidden,
    lastVisibilityChange,
  }
}

/**
 * Simplified hook that just returns visibility boolean.
 * Use this when you don't need the additional metadata.
 *
 * @example
 * ```tsx
 * const isVisible = useIsPageVisible()
 *
 * useEffect(() => {
 *   if (!isVisible) return // Skip when hidden
 *   // ... your effect
 * }, [isVisible])
 * ```
 */
export function useIsPageVisible(): boolean {
  const { isVisible } = usePageVisibility()
  return isVisible
}
