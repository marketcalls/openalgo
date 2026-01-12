import { createContext, type ReactNode, useContext } from 'react'
import { useSocket } from '@/hooks/useSocket'
import { useAuthStore } from '@/stores/authStore'

interface SocketContextType {
  playAlertSound: () => void
}

const SocketContext = createContext<SocketContextType | null>(null)

export function useSocketContext() {
  const context = useContext(SocketContext)
  if (!context) {
    return { playAlertSound: () => {} }
  }
  return context
}

interface SocketProviderProps {
  children: ReactNode
}

export function SocketProvider({ children }: SocketProviderProps) {
  const { isAuthenticated } = useAuthStore()

  // Only initialize socket when authenticated
  const { playAlertSound } = useSocket()

  // Only provide socket context when authenticated
  if (!isAuthenticated) {
    return <>{children}</>
  }

  return <SocketContext.Provider value={{ playAlertSound }}>{children}</SocketContext.Provider>
}
