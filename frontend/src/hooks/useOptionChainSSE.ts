import { useCallback, useEffect, useRef, useState } from 'react'
import type { OptionChainResponse } from '@/types/option-chain'

interface UseOptionChainSSEOptions {
  enabled: boolean
  refreshInterval?: number
}

interface UseOptionChainSSEState {
  data: OptionChainResponse | null
  isLoading: boolean
  isConnected: boolean
  error: string | null
  lastUpdate: Date | null
}

export function useOptionChainSSE(
  apiKey: string | null,
  underlying: string,
  exchange: string,
  expiryDate: string,
  strikeCount: number,
  options: UseOptionChainSSEOptions = { enabled: true, refreshInterval: 3000 }
) {
  const { enabled, refreshInterval = 3000 } = options
  const [state, setState] = useState<UseOptionChainSSEState>({
    data: null,
    isLoading: false,
    isConnected: false,
    error: null,
    lastUpdate: null,
  })

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  const fetchData = useCallback(async () => {
    if (!apiKey || !underlying || !exchange || !expiryDate) {
      return
    }

    setState((prev) => ({ ...prev, isLoading: true }))

    try {
      // Abort any existing request before starting a new one
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }

      const controller = new AbortController()
      abortControllerRef.current = controller

      const response = await fetch('/api/v1/optionchain', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          apikey: apiKey,
          underlying,
          exchange,
          expiry_date: expiryDate,
          strike_count: strikeCount,
        }),
        signal: controller.signal,
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const data: OptionChainResponse = await response.json()

      if (data.status === 'success') {
        setState((prev) => ({
          ...prev,
          data,
          isLoading: false,
          isConnected: true,
          error: null,
          lastUpdate: new Date(),
        }))
      } else {
        setState((prev) => ({
          ...prev,
          isLoading: false,
          error: data.message || 'Failed to fetch option chain',
        }))
      }
    } catch (error) {
      if (error instanceof Error) {
        if (error.name === 'AbortError') {
          if (abortControllerRef.current === null) {
            setState((prev) => ({ ...prev, isLoading: false }))
          }
        } else {
          setState((prev) => ({
            ...prev,
            isLoading: false,
            error: error.message || 'Connection error',
            isConnected: false,
          }))
        }
      }
    }
  }, [apiKey, underlying, exchange, expiryDate, strikeCount])

  useEffect(() => {
    if (!enabled) {
      return
    }

    setState((prev) => ({ ...prev, isConnected: true }))

    fetchData()

    intervalRef.current = setInterval(fetchData, refreshInterval)

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
        abortControllerRef.current = null
      }
    }
  }, [enabled, fetchData, refreshInterval])

  const refetch = useCallback(() => {
    fetchData()
  }, [fetchData])

  return {
    ...state,
    refetch,
  }
}
