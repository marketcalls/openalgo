import { create } from 'zustand'

interface SessionStore {
  activeSessionCount: number
  setActiveSessionCount: (count: number) => void
}

export const useSessionStore = create<SessionStore>((set) => ({
  activeSessionCount: 0,
  setActiveSessionCount: (count) => set({ activeSessionCount: count }),
}))
