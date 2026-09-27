import { create } from 'zustand'
import type { BacktestRequest, BacktestResponse } from '@/api/portfolio'

/**
 * Holds the most recent backtest result so the results sub-page can render it
 * without re-running the backtest. Not persisted: a stale result surviving a
 * reload would look current when the holdings behind it may have changed.
 */
interface PortfolioBacktestStore {
  result: BacktestResponse | null
  request: BacktestRequest | null
  setResult: (result: BacktestResponse, request: BacktestRequest) => void
  clear: () => void
}

export const usePortfolioBacktestStore = create<PortfolioBacktestStore>((set) => ({
  result: null,
  request: null,
  setResult: (result, request) => set({ result, request }),
  clear: () => set({ result: null, request: null }),
}))
