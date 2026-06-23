import { createContext, type ReactNode, useContext } from 'react'
import type { Socket } from 'socket.io-client'
import { useSocket } from '@/hooks/useSocket'
import { useAuthStore } from '@/stores/authStore'

interface SocketContextType {
  playAlertSound: () => void
  // The single app-wide Socket.IO connection — shared so event hooks
  // (useOrderEventRefresh) reuse it instead of each opening a new one.
  socket: Socket | null
}

const SocketContext = createContext<SocketContextType | null>(null)

export function useSocketContext(): SocketContextType {
  const context = useContext(SocketContext)
  if (!context) {
    return { playAlertSound: () => {}, socket: null }
  }
  return context
}

interface SocketProviderProps {
  children: ReactNode
}

export function SocketProvider({ children }: SocketProviderProps) {
  const { isAuthenticated } = useAuthStore()

  // Only initialize socket when authenticated
  const { socket, playAlertSound } = useSocket()

  // Only provide socket context when authenticated
  if (!isAuthenticated) {
    return <>{children}</>
  }

  return (
    <SocketContext.Provider value={{ playAlertSound, socket }}>{children}</SocketContext.Provider>
  )
}
