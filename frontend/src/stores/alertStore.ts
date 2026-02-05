import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type ToastPosition = 'top-right' | 'top-center' | 'top-left' | 'bottom-right' | 'bottom-center' | 'bottom-left'

export interface AlertCategories {
  // Real-time Socket.IO events (High-frequency)
  orders: boolean // Order placement notifications (BUY/SELL) - Socket: order_event, order_notification
  analyzer: boolean // Analyzer/sandbox mode operations - Socket: analyzer_update
  system: boolean // Password change, master contract download - Socket: password_change, master_contract_download
  actionCenter: boolean // Pending order notifications - Socket: pending_order_created

  // User-initiated operations (Tier 1 - High Impact)
  historify: boolean // Historify job operations, file uploads, schedules (67 toasts)
  strategy: boolean // Strategy management, symbol configuration (39 toasts)
  positions: boolean // Position close/update operations

  // User-initiated operations (Tier 2 - Medium Impact)
  chartink: boolean // Chartink strategy operations (26 toasts)
  pythonStrategy: boolean // Python strategy operations (34 toasts)
  telegram: boolean // Telegram bot operations (19 toasts)
  flow: boolean // Workflow management (15 toasts)

  // User-initiated operations (Tier 3 - Low Impact)
  admin: boolean // Admin panel operations (27 toasts)
  monitoring: boolean // Health, latency, security dashboards (10 toasts)
  clipboard: boolean // Copy to clipboard feedback (11 toasts)
}

interface AlertStore {
  // Master controls
  toastsEnabled: boolean
  soundEnabled: boolean

  // Toast display settings
  position: ToastPosition
  maxVisibleToasts: number
  duration: number // in milliseconds

  // Category toggles
  categories: AlertCategories

  // Actions
  setToastsEnabled: (enabled: boolean) => void
  setSoundEnabled: (enabled: boolean) => void
  setPosition: (position: ToastPosition) => void
  setMaxVisibleToasts: (max: number) => void
  setDuration: (duration: number) => void
  setCategoryEnabled: (category: keyof AlertCategories, enabled: boolean) => void
  resetToDefaults: () => void

  // Helper to check if a category toast should be shown
  shouldShowToast: (category?: keyof AlertCategories) => boolean
  shouldPlaySound: () => boolean
}

const DEFAULT_STATE = {
  toastsEnabled: true,
  soundEnabled: true,
  position: 'top-right' as ToastPosition,
  maxVisibleToasts: 3,
  duration: 3000, // 3 seconds
  categories: {
    // Real-time (Socket.IO)
    orders: true,
    analyzer: true,
    system: true,
    actionCenter: true,
    // Tier 1
    historify: true,
    strategy: true,
    positions: true,
    // Tier 2
    chartink: true,
    pythonStrategy: true,
    telegram: true,
    flow: true,
    // Tier 3
    admin: true,
    monitoring: true,
    clipboard: true,
  },
}

export const useAlertStore = create<AlertStore>()(
  persist(
    (set, get) => ({
      ...DEFAULT_STATE,

      setToastsEnabled: (enabled) => set({ toastsEnabled: enabled }),

      setSoundEnabled: (enabled) => set({ soundEnabled: enabled }),

      setPosition: (position) => set({ position }),

      setMaxVisibleToasts: (max) => set({ maxVisibleToasts: Math.min(Math.max(max, 1), 10) }),

      setDuration: (duration) => set({ duration: Math.min(Math.max(duration, 1000), 15000) }),

      setCategoryEnabled: (category, enabled) =>
        set((state) => ({
          categories: {
            ...state.categories,
            [category]: enabled,
          },
        })),

      resetToDefaults: () => set(DEFAULT_STATE),

      shouldShowToast: (category) => {
        const state = get()
        if (!state.toastsEnabled) return false
        if (category && !state.categories[category]) return false
        return true
      },

      shouldPlaySound: () => {
        const state = get()
        return state.toastsEnabled && state.soundEnabled
      },
    }),
    {
      name: 'openalgo-alerts',
      partialize: (state) => ({
        toastsEnabled: state.toastsEnabled,
        soundEnabled: state.soundEnabled,
        position: state.position,
        maxVisibleToasts: state.maxVisibleToasts,
        duration: state.duration,
        categories: state.categories,
      }),
    }
  )
)
