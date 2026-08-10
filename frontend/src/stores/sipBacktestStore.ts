import { create } from 'zustand'
import type { SipBacktestRequest, SipBacktestResponse } from '@/api/sip'

/**
 * Holds the most recent SIP result so the results sub-page can render it
 * without re-running the backtest. Not persisted: a stale result surviving a
 * reload would look current when the inputs behind it may have changed.
 */
interface SipBacktestStore {
  result: SipBacktestResponse | null
  request: SipBacktestRequest | null
  setResult: (result: SipBacktestResponse, request: SipBacktestRequest) => void
  clear: () => void
}

export const useSipBacktestStore = create<SipBacktestStore>((set) => ({
  result: null,
  request: null,
  setResult: (result, request) => set({ result, request }),
  clear: () => set({ result: null, request: null }),
}))
