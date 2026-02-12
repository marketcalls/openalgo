import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type ThemeMode = 'light' | 'dark'
export type AppMode = 'live' | 'analyzer'
export type ThemeColor =
  | 'zinc'
  | 'slate'
  | 'stone'
  | 'gray'
  | 'neutral'
  | 'red'
  | 'rose'
  | 'orange'
  | 'green'
  | 'blue'
  | 'yellow'
  | 'violet'

// Event emitter for mode changes
type ModeChangeCallback = (newMode: AppMode) => void
const modeChangeListeners: Set<ModeChangeCallback> = new Set()

export const onModeChange = (callback: ModeChangeCallback): (() => void) => {
  modeChangeListeners.add(callback)
  return () => {
    modeChangeListeners.delete(callback)
  }
}

const notifyModeChange = (newMode: AppMode) => {
  modeChangeListeners.forEach((cb) => cb(newMode))
}

interface ThemeStore {
  mode: ThemeMode
  color: ThemeColor
  appMode: AppMode
  isTogglingMode: boolean

  setMode: (mode: ThemeMode) => void
  setColor: (color: ThemeColor) => void
  setAppMode: (appMode: AppMode) => void
  toggleMode: () => void
  toggleAppMode: () => Promise<{ success: boolean; message?: string }>
  syncAppMode: () => Promise<void>
}

export const useThemeStore = create<ThemeStore>()(
  persist(
    (set, get) => ({
      mode: 'light',
      color: 'zinc',
      appMode: 'live',
      isTogglingMode: false,

      setMode: (mode) => {
        // Only allow theme change in live mode
        if (get().appMode !== 'live') return

        set({ mode })
        if (typeof document !== 'undefined') {
          document.documentElement.classList.toggle('dark', mode === 'dark')
        }
      },

      setColor: (color) => {
        // Only allow color change in live mode
        if (get().appMode !== 'live') return

        set({ color })
        if (typeof document !== 'undefined') {
          document.documentElement.setAttribute('data-theme', color)
        }
      },

      setAppMode: (appMode) => {
        const previousMode = get().appMode
        set({ appMode })
        if (typeof document !== 'undefined') {
          // Remove all mode classes first
          document.documentElement.classList.remove('analyzer', 'sandbox', 'dark')

          if (appMode === 'live') {
            // Restore the saved light/dark mode when returning to live
            const savedMode = get().mode
            document.documentElement.classList.toggle('dark', savedMode === 'dark')
          } else {
            // Analyzer mode uses its own dark purple theme (like dracula)
            document.documentElement.classList.add('analyzer')
          }
        }
        // Notify listeners if mode changed
        if (previousMode !== appMode) {
          notifyModeChange(appMode)
        }
      },

      toggleMode: () => {
        // Only allow toggle in live mode
        if (get().appMode !== 'live') return

        const newMode = get().mode === 'light' ? 'dark' : 'light'
        set({ mode: newMode })
        if (typeof document !== 'undefined') {
          document.documentElement.classList.toggle('dark', newMode === 'dark')
        }
      },

      // Toggle app mode via backend API
      toggleAppMode: async (): Promise<{ success: boolean; message?: string }> => {
        if (get().isTogglingMode) return { success: false, message: 'Already toggling' }

        set({ isTogglingMode: true })
        try {
          // First fetch CSRF token
          const csrfResponse = await fetch('/auth/csrf-token', {
            credentials: 'include',
          })
          const csrfData = await csrfResponse.json()

          const response = await fetch('/auth/analyzer-toggle', {
            method: 'POST',
            credentials: 'include',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': csrfData.csrf_token,
            },
          })

          const data = await response.json()

          if (response.ok && data.status === 'success') {
            const newMode: AppMode = data.data.analyze_mode ? 'analyzer' : 'live'
            get().setAppMode(newMode)
            return { success: true, message: data.data.message }
          } else {
            return { success: false, message: data.message || 'Failed to toggle mode' }
          }
        } catch (error) {
          return { success: false, message: 'Network error' }
        } finally {
          set({ isTogglingMode: false })
        }
      },

      // Sync app mode from backend
      syncAppMode: async () => {
        try {
          const response = await fetch('/auth/analyzer-mode', {
            credentials: 'include',
          })

          if (response.ok) {
            const data = await response.json()
            if (data.status === 'success') {
              const backendMode: AppMode = data.data.analyze_mode ? 'analyzer' : 'live'
              const currentMode = get().appMode
              if (currentMode !== backendMode) {
                get().setAppMode(backendMode)
              }
            }
            // If backend returns error status but response.ok, keep current appMode
          }
          // If request fails (401, etc.) - user is logged out, keep current appMode
          // This preserves the theme across logout for visual continuity
        } catch (error) {
          // On error, keep current appMode - preserves theme across logout
        }
      },
    }),
    {
      name: 'openalgo-theme',
      partialize: (state) => ({
        mode: state.mode,
        color: state.color,
        appMode: state.appMode, // Persist appMode for visual continuity across logout
      }),
      onRehydrateStorage: () => (state) => {
        // Apply theme on rehydration
        if (state && typeof document !== 'undefined') {
          document.documentElement.classList.remove('analyzer', 'sandbox', 'dark')

          // Apply persisted appMode for visual continuity
          if (state.appMode === 'analyzer') {
            document.documentElement.classList.add('analyzer')
          } else {
            // Live mode - apply light/dark preference
            document.documentElement.classList.toggle('dark', state.mode === 'dark')
          }
          document.documentElement.setAttribute('data-theme', state.color)
        }
      },
    }
  )
)
