/**
 * Sector Rotation page settings, kept across visits.
 *
 * Persisted because a trader who has built a watch list of stocks and indices
 * on the map expects to find it there tomorrow. Only the choices are stored,
 * never the result: positions are recomputed from fresh history on every
 * visit, so a stale map can never be shown as current.
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { PriceSource, RotationTimeframe } from '@/api/sector-rotation'

export interface MapInstrument {
  symbol: string
  exchange: string
  label: string
  color: string
}

export const instrumentKey = (i: { symbol: string; exchange: string }) =>
  `${i.exchange}:${i.symbol}`

interface SectorRotationState {
  benchmark: string
  timeframe: RotationTimeframe
  source: PriceSource
  tailStep: number
  zoomStep: number
  /** The symbols on the map. Null means the default sector set from the server. */
  instruments: MapInstrument[] | null
  /** Keys of instruments hidden from the map but kept in the list. */
  hidden: string[]

  setBenchmark: (benchmark: string) => void
  setTimeframe: (timeframe: RotationTimeframe) => void
  setSource: (source: PriceSource) => void
  setTailStep: (step: number) => void
  setZoomStep: (step: number) => void
  setInstruments: (instruments: MapInstrument[] | null) => void
  toggleHidden: (key: string) => void
  setHidden: (keys: string[]) => void
}

export const useSectorRotationStore = create<SectorRotationState>()(
  persist(
    (set) => ({
      benchmark: 'NIFTY',
      timeframe: 'daily',
      source: 'api',
      tailStep: 2,
      zoomStep: 0,
      instruments: null,
      hidden: [],

      setBenchmark: (benchmark) => set({ benchmark }),
      setTimeframe: (timeframe) => set({ timeframe }),
      setSource: (source) => set({ source }),
      setTailStep: (tailStep) => set({ tailStep }),
      setZoomStep: (zoomStep) => set({ zoomStep }),
      setInstruments: (instruments) => set({ instruments }),
      toggleHidden: (key) =>
        set((state) => ({
          hidden: state.hidden.includes(key)
            ? state.hidden.filter((k) => k !== key)
            : [...state.hidden, key],
        })),
      setHidden: (hidden) => set({ hidden }),
    }),
    { name: 'openalgo-sector-rotation', version: 1 }
  )
)
