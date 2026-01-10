import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type ThemeMode = 'light' | 'dark'
export type AppMode = 'live' | 'analyzer' | 'sandbox'
export type ThemeColor = 'zinc' | 'slate' | 'stone' | 'gray' | 'neutral' | 'red' | 'rose' | 'orange' | 'green' | 'blue' | 'yellow' | 'violet'

interface ThemeStore {
  mode: ThemeMode
  color: ThemeColor
  appMode: AppMode

  setMode: (mode: ThemeMode) => void
  setColor: (color: ThemeColor) => void
  setAppMode: (appMode: AppMode) => void
  toggleMode: () => void
}

export const useThemeStore = create<ThemeStore>()(
  persist(
    (set, get) => ({
      mode: 'light',
      color: 'zinc',
      appMode: 'live',

      setMode: (mode) => {
        set({ mode })
        if (typeof document !== 'undefined') {
          document.documentElement.classList.toggle('dark', mode === 'dark')
        }
      },

      setColor: (color) => {
        set({ color })
        if (typeof document !== 'undefined') {
          document.documentElement.setAttribute('data-theme', color)
        }
      },

      setAppMode: (appMode) => {
        set({ appMode })
        if (typeof document !== 'undefined') {
          document.documentElement.classList.remove('analyzer', 'sandbox')
          if (appMode !== 'live') {
            document.documentElement.classList.add(appMode)
          }
        }
      },

      toggleMode: () => {
        const newMode = get().mode === 'light' ? 'dark' : 'light'
        get().setMode(newMode)
      },
    }),
    {
      name: 'openalgo-theme',
      onRehydrateStorage: () => (state) => {
        // Apply theme on rehydration
        if (state && typeof document !== 'undefined') {
          document.documentElement.classList.toggle('dark', state.mode === 'dark')
          document.documentElement.setAttribute('data-theme', state.color)
          if (state.appMode !== 'live') {
            document.documentElement.classList.add(state.appMode)
          }
        }
      },
    }
  )
)
