import { useCallback, useEffect, useState } from 'react'

interface MarketTiming {
  exchange: string
  start_time: number
  end_time: number
}

interface HolidayOpenExchange {
  exchange: string
  start_time: number
  end_time: number
}

interface Holiday {
  date: string
  description: string
  holiday_type: string
  closed_exchanges: string[]
  open_exchanges: HolidayOpenExchange[]
}

interface MarketStatusState {
  timings: MarketTiming[]
  holidays: Holiday[]
  isLoading: boolean
  error: string | null
}

// Fetch CSRF token for authenticated requests
async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', { credentials: 'include' })
  const data = await response.json()
  return data.csrf_token
}

export function useMarketStatus() {
  const [state, setState] = useState<MarketStatusState>({
    timings: [],
    holidays: [],
    isLoading: true,
    error: null,
  })

  useEffect(() => {
    const fetchMarketData = async () => {
      try {
        const csrfToken = await fetchCSRFToken()
        const headers = {
          'X-CSRFToken': csrfToken,
          'Content-Type': 'application/json',
        }

        // Fetch market timings and holidays in parallel
        // Note: These endpoints are under the admin blueprint (/admin prefix)
        const [timingsRes, holidaysRes] = await Promise.all([
          fetch('/admin/api/timings', { headers, credentials: 'include' }),
          fetch('/admin/api/holidays', { headers, credentials: 'include' }),
        ])

        const timingsData = await timingsRes.json()
        const holidaysData = await holidaysRes.json()

        setState({
          // Use market_status field which contains epoch timestamps for market open checks
          timings: timingsData.status === 'success' ? timingsData.market_status || [] : [],
          holidays: holidaysData.status === 'success' ? holidaysData.data || [] : [],
          isLoading: false,
          error: null,
        })
      } catch (err) {
        setState((prev) => ({
          ...prev,
          isLoading: false,
          error: `Failed to fetch market status: ${err}`,
        }))
      }
    }

    fetchMarketData()
  }, [])

  // Check if today is a holiday for a specific exchange
  const isHolidayForExchange = useCallback(
    (exchange: string): boolean => {
      const today = new Date().toISOString().split('T')[0] // YYYY-MM-DD format
      const todayHoliday = state.holidays.find((h) => h.date === today)

      if (!todayHoliday) return false

      // Check if exchange is in closed_exchanges
      if (todayHoliday.closed_exchanges.includes(exchange)) {
        // Check if there's a special session for this exchange
        const specialSession = todayHoliday.open_exchanges.find((e) => e.exchange === exchange)
        if (specialSession) {
          // There's a special session - check if we're within it
          const now = Date.now()
          return !(now >= specialSession.start_time && now <= specialSession.end_time)
        }
        return true // Closed with no special session
      }

      return false
    },
    [state.holidays]
  )

  // Check if market is currently open for a specific exchange
  const isMarketOpen = useCallback(
    (exchange: string): boolean => {
      // First check if it's a holiday
      if (isHolidayForExchange(exchange)) {
        return false
      }

      // Check regular market timing
      const timing = state.timings.find((t) => t.exchange === exchange)
      if (!timing) {
        // If no timing found, assume market is closed (conservative approach)
        return false
      }

      const now = Date.now()
      return now >= timing.start_time && now <= timing.end_time
    },
    [state.timings, isHolidayForExchange]
  )

  // Check if any market is open (useful for deciding whether to connect WebSocket)
  const isAnyMarketOpen = useCallback((): boolean => {
    return state.timings.some((timing) => {
      const now = Date.now()
      const isWithinHours = now >= timing.start_time && now <= timing.end_time
      return isWithinHours && !isHolidayForExchange(timing.exchange)
    })
  }, [state.timings, isHolidayForExchange])

  // Get market status for display
  const getMarketStatus = useCallback(
    (exchange: string): 'open' | 'closed' | 'pre-market' | 'post-market' => {
      if (isHolidayForExchange(exchange)) {
        return 'closed'
      }

      const timing = state.timings.find((t) => t.exchange === exchange)
      if (!timing) {
        return 'closed'
      }

      const now = Date.now()
      const preMarketBuffer = 15 * 60 * 1000 // 15 minutes before market open

      if (now < timing.start_time - preMarketBuffer) {
        return 'closed'
      } else if (now < timing.start_time) {
        return 'pre-market'
      } else if (now <= timing.end_time) {
        return 'open'
      } else {
        return 'post-market'
      }
    },
    [state.timings, isHolidayForExchange]
  )

  return {
    isMarketOpen,
    isAnyMarketOpen,
    isHolidayForExchange,
    getMarketStatus,
    timings: state.timings,
    holidays: state.holidays,
    isLoading: state.isLoading,
    error: state.error,
  }
}
