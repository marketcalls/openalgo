import { create } from 'zustand'
import type {
  AlertItem,
  Candle,
  DepthLevel,
  Timeframe,
  TickData,
} from '@/types/dashboard'

// ─────────────────────────────────────────────────────────────────────────────
// AAUM Institutional Dashboard — Zustand Store
// ─────────────────────────────────────────────────────────────────────────────

export type DashboardMode = 'execution' | 'research'

interface DashboardState {
  // Selection
  selectedSymbol: string
  selectedTimeframe: Timeframe

  // Dashboard mode
  mode: DashboardMode

  // WebSocket connection
  connection: 'connecting' | 'open' | 'closed'

  // Real-time market data (keyed by symbol)
  ticks: Record<string, TickData>
  candles: Record<string, Record<string, Candle[]>> // symbol -> timeframe -> candles
  depth: Record<string, { bids: DepthLevel[]; asks: DepthLevel[] }>

  // Alerts
  alerts: AlertItem[]

  // Scanner state
  scannerSort: { key: string; dir: 'asc' | 'desc' }

  // ── Actions ────────────────────────────────────────────────────────────────

  setSymbol: (symbol: string) => void
  setTimeframe: (tf: Timeframe) => void
  setMode: (mode: DashboardMode) => void
  setConnection: (state: 'connecting' | 'open' | 'closed') => void

  // Market data
  upsertTick: (symbol: string, tick: TickData) => void
  upsertCandles: (symbol: string, tf: string, candles: Candle[]) => void
  appendCandle: (symbol: string, tf: string, candle: Candle) => void
  upsertDepth: (symbol: string, bids: DepthLevel[], asks: DepthLevel[]) => void

  // Alerts
  pushAlert: (alert: AlertItem) => void
  dismissAlert: (id: string) => void
  dismissAllAlerts: () => void

  // Scanner
  setScannerSort: (key: string) => void
}

const MAX_CANDLES = 500
const MAX_ALERTS = 100

export const useDashboardStore = create<DashboardState>()((set) => ({
  // ── Initial State ──────────────────────────────────────────────────────────

  selectedSymbol: 'NIFTY',
  selectedTimeframe: '5m',
  mode: 'execution',
  connection: 'closed',
  ticks: {},
  candles: {},
  depth: {},
  alerts: [],
  scannerSort: { key: 'institutionalScore', dir: 'desc' },

  // ── Actions ────────────────────────────────────────────────────────────────

  setSymbol: (symbol) => set({ selectedSymbol: symbol }),

  setTimeframe: (tf) => set({ selectedTimeframe: tf }),

  setMode: (mode) => set({ mode }),

  setConnection: (connection) => set({ connection }),

  upsertTick: (symbol, tick) =>
    set((state) => ({
      ticks: { ...state.ticks, [symbol]: tick },
    })),

  upsertCandles: (symbol, tf, newCandles) =>
    set((state) => ({
      candles: {
        ...state.candles,
        [symbol]: {
          ...state.candles[symbol],
          [tf]: newCandles.slice(-MAX_CANDLES),
        },
      },
    })),

  appendCandle: (symbol, tf, candle) =>
    set((state) => {
      const existing = state.candles[symbol]?.[tf] ?? []
      // Replace last candle if same timestamp, else append
      const last = existing[existing.length - 1]
      const updated =
        last && last.time === candle.time
          ? [...existing.slice(0, -1), candle]
          : [...existing, candle].slice(-MAX_CANDLES)
      return {
        candles: {
          ...state.candles,
          [symbol]: {
            ...state.candles[symbol],
            [tf]: updated,
          },
        },
      }
    }),

  upsertDepth: (symbol, bids, asks) =>
    set((state) => ({
      depth: { ...state.depth, [symbol]: { bids, asks } },
    })),

  pushAlert: (alert) =>
    set((state) => ({
      alerts: [alert, ...state.alerts].slice(0, MAX_ALERTS),
    })),

  dismissAlert: (id) =>
    set((state) => ({
      alerts: state.alerts.map((a) => (a.id === id ? { ...a, dismissed: true } : a)),
    })),

  dismissAllAlerts: () =>
    set((state) => ({
      alerts: state.alerts.map((a) => ({ ...a, dismissed: true })),
    })),

  setScannerSort: (key) =>
    set((state) => ({
      scannerSort: {
        key,
        dir: state.scannerSort.key === key && state.scannerSort.dir === 'desc' ? 'asc' : 'desc',
      },
    })),
}))
