import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface User {
  username: string
  broker: string | null
  isLoggedIn: boolean
  loginTime: string | null
}

interface AuthStore {
  user: User | null
  apiKey: string | null
  isAuthenticated: boolean

  setUser: (user: User) => void
  setApiKey: (apiKey: string | null) => void
  login: (username: string, broker: string) => void
  logout: () => void
  checkSession: () => boolean
}

export const useAuthStore = create<AuthStore>()(
  persist(
    (set, get) => ({
      user: null,
      apiKey: null,
      isAuthenticated: false,

      setUser: (user) => set({ user, isAuthenticated: user.isLoggedIn }),

      setApiKey: (apiKey) => set({ apiKey }),

      login: (username, broker) => {
        const user: User = {
          username,
          broker,
          isLoggedIn: true,
          loginTime: new Date().toISOString(),
        }
        set({ user, isAuthenticated: true })
      },

      logout: () => {
        set({ user: null, isAuthenticated: false, apiKey: null })
      },

      checkSession: () => {
        const { user } = get()
        if (!user || !user.loginTime) return false

        // Session expiry check (3 AM IST daily)
        const now = new Date()
        const loginTime = new Date(user.loginTime)

        // Get IST time
        const istOffset = 5.5 * 60 * 60 * 1000
        const nowIST = new Date(now.getTime() + istOffset)
        const todayExpiry = new Date(nowIST)
        todayExpiry.setHours(3, 0, 0, 0)

        // If login was before today's 3 AM and now is after 3 AM, session expired
        if (nowIST > todayExpiry && loginTime < todayExpiry) {
          get().logout()
          return false
        }

        return true
      },
    }),
    {
      name: 'openalgo-auth',
    }
  )
)
