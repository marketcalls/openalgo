import { useQuery } from '@tanstack/react-query'
import { useCallback } from 'react'
import { pythonStrategyApi } from '@/api/python-strategy'
import type { StrategyExchange } from '@/types/python-strategy'
import { CRYPTO_EXCHANGE_VALUE, FALLBACK_STRATEGY_EXCHANGES } from '@/types/python-strategy'

/**
 * Exchange options for the /python strategy host, with their live session
 * windows read from the market calendar DB.
 *
 * Nothing here hardcodes a trading window. When an exchange timing changes
 * (SEBI's Closing Auction Session moved the NFO/BFO close to 15:40, or an
 * admin edits one under /admin/timings), the dropdown labels and the schedule
 * defaults follow it without a frontend change.
 */
export function useStrategyExchanges() {
  const { data, isLoading } = useQuery({
    queryKey: ['python-strategy', 'exchanges'],
    queryFn: pythonStrategyApi.getExchanges,
    // Timings change on the order of years, so refetching per mount is waste.
    staleTime: 30 * 60 * 1000,
  })

  const exchanges: StrategyExchange[] = data && data.length > 0 ? data : FALLBACK_STRATEGY_EXCHANGES

  /** The session window for an exchange, or null while the list is loading. */
  const getWindow = useCallback(
    (value: string): { start: string; stop: string } | null => {
      if (value === CRYPTO_EXCHANGE_VALUE) {
        return { start: '00:00', stop: '23:59' }
      }
      const match = exchanges.find((e) => e.value === value)
      if (!match?.start_time || !match?.end_time) return null
      return { start: match.start_time, stop: match.end_time }
    },
    [exchanges]
  )

  return { exchanges, getWindow, isLoading }
}
