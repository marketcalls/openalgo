/**
 * sandboxStore.ts
 *
 * Zustand store for sandbox / paper-trading settings that must survive
 * page navigation but do NOT need to survive browser refreshes (the
 * canonical source of truth is the backend DB).  We intentionally skip
 * `persist()` here so we always re-fetch from the server on mount.
 */

import { create } from 'zustand'

export type PaperPriceSource = 'LIVE' | 'REPLAY'

interface SandboxStore {
  paperPriceSource: PaperPriceSource
  isFetchingSource: boolean
  isSettingSource: boolean

  /** Load current setting from backend */
  fetchPaperPriceSource: () => Promise<void>

  /** Persist new setting to backend */
  setPaperPriceSource: (
    source: PaperPriceSource,
    csrfToken: string,
  ) => Promise<{ success: boolean; message?: string }>
}

export const useSandboxStore = create<SandboxStore>((set, get) => ({
  paperPriceSource: 'LIVE',
  isFetchingSource: false,
  isSettingSource: false,

  fetchPaperPriceSource: async () => {
    if (get().isFetchingSource) return
    set({ isFetchingSource: true })
    try {
      const response = await fetch('/settings/paper-price-source', {
        credentials: 'include',
      })
      if (response.ok) {
        const data = await response.json()
        if (data.paper_price_source) {
          set({ paperPriceSource: data.paper_price_source as PaperPriceSource })
        }
      }
    } catch {
      // Keep current value on network error
    } finally {
      set({ isFetchingSource: false })
    }
  },

  setPaperPriceSource: async (source, csrfToken) => {
    if (get().isSettingSource) return { success: false, message: 'Already updating' }
    set({ isSettingSource: true })
    try {
      const response = await fetch('/settings/paper-price-source', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({ source }),
      })
      const data = await response.json()
      if (response.ok && data.success) {
        set({ paperPriceSource: source })
        return { success: true, message: data.message }
      }
      return { success: false, message: data.error || 'Failed to update' }
    } catch {
      return { success: false, message: 'Network error' }
    } finally {
      set({ isSettingSource: false })
    }
  },
}))
