import { useCallback, useEffect, useRef, useState } from 'react'
import type { WebSocketMessage, LatencySample } from '@/types/websocket'

// Fetch CSRF token for authenticated requests
async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', { credentials: 'include' })
  const data = await response.json()
  return data.csrf_token
}

const MAX_MESSAGES = 1000
const MAX_LATENCY_SAMPLES = 100

interface UseWebSocketTesterReturn {
  // Connection state
  isConnected: boolean
  isConnecting: boolean
  isAuthenticated: boolean
  wsUrl: string | null
  error: string | null
  connect: () => Promise<void>
  disconnect: () => void

  // Messages
  sendMessage: (message: string | object) => boolean
  messages: WebSocketMessage[]
  clearMessages: () => void
  exportMessages: () => void

  // Latency testing
  ping: () => string
  lastLatency: number | null
  averageLatency: number | null

  // Config
  autoReconnect: boolean
  setAutoReconnect: (value: boolean) => void
}

export function useWebSocketTester(_apiKey?: string): UseWebSocketTesterReturn {
  const [isConnected, setIsConnected] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [wsUrl, setWsUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [messages, setMessages] = useState<WebSocketMessage[]>([])
  const [autoReconnect, setAutoReconnect] = useState(true)
  const [lastLatency, setLastLatency] = useState<number | null>(null)
  const [averageLatency, setAverageLatency] = useState<number | null>(null)

  const socketRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pingIdRef = useRef<string | null>(null)
  const pingStartTimeRef = useRef<number>(0)
  const latencySamplesRef = useRef<LatencySample[]>([])
  const isReconnectingRef = useRef(false)
  const userInitiatedCloseRef = useRef(false)

  const getCsrfToken = useCallback(async () => fetchCSRFToken(), [])

  // Add message to log
  const addMessage = useCallback(
    (direction: WebSocketMessage['direction'], data: unknown, rawData?: string) => {
      const message: WebSocketMessage = {
        id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
        direction,
        timestamp: Date.now(),
        data,
        rawData,
      }
      setMessages((prev) => {
        const updated = [message, ...prev]
        return updated.slice(0, MAX_MESSAGES)
      })
    },
    []
  )

  // Handle incoming WebSocket messages
  const handleMessage = useCallback(
    (event: MessageEvent) => {
      try {
        const data = JSON.parse(event.data)
        const type = (data.type || data.status) as string

        switch (type) {
          case 'auth':
            if (data.status === 'success') {
              setIsAuthenticated(true)
              setError(null)
              addMessage('system', { message: 'Authentication successful' })
            } else {
              setError(`Authentication failed: ${data.message}`)
              addMessage('error', { message: `Authentication failed: ${data.message}` })
            }
            break

          case 'pong':
            // Calculate latency from ping response
            if (data._pingId === pingIdRef.current) {
              const latency = Date.now() - pingStartTimeRef.current
              setLastLatency(latency)
              latencySamplesRef.current.push({ timestamp: Date.now(), latency })
              if (latencySamplesRef.current.length > MAX_LATENCY_SAMPLES) {
                latencySamplesRef.current.shift()
              }
              // Calculate average
              const avg =
                latencySamplesRef.current.reduce((sum, s) => sum + s.latency, 0) /
                latencySamplesRef.current.length
              setAverageLatency(Math.round(avg))
              pingIdRef.current = null
              addMessage('system', { message: `Pong received (${latency}ms)` })
            } else {
              // Show pong for manual ping messages (without _pingId)
              addMessage('received', data, event.data)
            }
            break

          case 'error':
            setError(`WebSocket error: ${data.message}`)
            addMessage('error', data)
            break

          default:
            // Log all other messages
            addMessage('received', data, event.data)
        }
      } catch {
        // Add raw message for non-JSON
        addMessage('received', event.data, event.data)
      }
    },
    [addMessage]
  )

  // Connect to WebSocket
  const connect = useCallback(async () => {
    if (socketRef.current?.readyState === WebSocket.OPEN || isReconnectingRef.current) {
      return
    }

    isReconnectingRef.current = true
    setIsConnecting(true)
    setError(null)

    try {
      const csrfToken = await getCsrfToken()

      // Get WebSocket config (URL from .env)
      const configResponse = await fetch('/api/websocket/config', {
        headers: { 'X-CSRFToken': csrfToken },
        credentials: 'include',
      })
      const configData = await configResponse.json()

      if (configData.status !== 'success') {
        throw new Error('Failed to get WebSocket configuration')
      }

      const url = configData.websocket_url
      setWsUrl(url)

      const socket = new WebSocket(url)

      socket.onopen = async () => {
        setIsConnected(true)
        setIsConnecting(false)
        addMessage('system', { message: 'Connected to WebSocket server' })

        try {
          // Get API key for authentication
          const authCsrfToken = await getCsrfToken()
          const apiKeyResponse = await fetch('/api/websocket/apikey', {
            headers: { 'X-CSRFToken': authCsrfToken },
            credentials: 'include',
          })
          const apiKeyData = await apiKeyResponse.json()

          if (apiKeyData.status === 'success' && apiKeyData.api_key) {
            const authMessage = { action: 'authenticate', api_key: apiKeyData.api_key }
            socket.send(JSON.stringify(authMessage))
            addMessage('sent', authMessage)
          } else {
            setError('No API key found - please generate one at /apikey')
            addMessage('error', { message: 'No API key found' })
          }
        } catch (err) {
          setError(`Authentication error: ${err}`)
          addMessage('error', { message: `Authentication error: ${err}` })
        }
      }

      socket.onclose = (event) => {
        setIsConnected(false)
        setIsConnecting(false)
        setIsAuthenticated(false)
        isReconnectingRef.current = false

        if (!event.wasClean) {
          addMessage('system', { message: `Connection closed unexpectedly: ${event.code}` })
        } else {
          addMessage('system', { message: `Connection closed: ${event.code}` })
        }

        // Only reconnect if NOT user-initiated AND autoReconnect is enabled
        if (autoReconnect && !userInitiatedCloseRef.current) {
          reconnectTimeoutRef.current = setTimeout(() => {
            userInitiatedCloseRef.current = false // Reset for next attempt
            connect()
          }, 3000)
        }
        userInitiatedCloseRef.current = false
      }

      socket.onerror = () => {
        setError('WebSocket connection error')
        setIsConnecting(false)
        addMessage('error', { message: 'WebSocket connection error' })
      }

      socket.onmessage = handleMessage

      socketRef.current = socket
    } catch (err) {
      setError(`Connection failed: ${err}`)
      setIsConnecting(false)
      addMessage('error', { message: `Connection failed: ${err}` })
    }
  }, [getCsrfToken, handleMessage, autoReconnect, addMessage])

  // Disconnect from WebSocket
  const disconnect = useCallback(() => {
    userInitiatedCloseRef.current = true

    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    if (socketRef.current) {
      socketRef.current.close(1000, 'User disconnect')
      socketRef.current = null
    }
    setIsConnected(false)
    setIsAuthenticated(false)
    addMessage('system', { message: 'Disconnected by user' })
  }, [addMessage])

  // Send message
  const sendMessage = useCallback(
    (message: string | object): boolean => {
      if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
        setError('Cannot send message: not connected')
        return false
      }

      try {
        const messageObj = typeof message === 'string' ? JSON.parse(message) : message
        const messageStr = JSON.stringify(messageObj)
        socketRef.current.send(messageStr)
        addMessage('sent', messageObj, messageStr)
        return true
      } catch (err) {
        setError(`Failed to send message: ${err}`)
        addMessage('error', { message: `Failed to send: ${err}` })
        return false
      }
    },
    [addMessage]
  )

  // Ping for latency testing
  const ping = useCallback((): string => {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
      setError('Cannot ping: not connected')
      return 'error'
    }

    const pingId = `ping-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
    pingIdRef.current = pingId
    pingStartTimeRef.current = Date.now()

    const pingMessage = { _pingId: pingId, action: 'ping', timestamp: Date.now() }
    socketRef.current.send(JSON.stringify(pingMessage))
    addMessage('sent', pingMessage)

    return pingId
  }, [addMessage])

  // Clear messages
  const clearMessages = useCallback(() => {
    setMessages([])
    latencySamplesRef.current = []
    setLastLatency(null)
    setAverageLatency(null)
  }, [])

  // Export messages
  const exportMessages = useCallback(() => {
    const exportData = {
      exportedAt: new Date().toISOString(),
      totalMessages: messages.length,
      messages: messages.map((m) => ({
        ...m,
        timestamp: new Date(m.timestamp).toISOString(),
      })),
    }
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `websocket-messages-${Date.now()}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }, [messages])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (socketRef.current) {
        socketRef.current.close()
      }
    }
  }, [])

  return {
    isConnected,
    isConnecting,
    isAuthenticated,
    wsUrl,
    error,
    connect,
    disconnect,
    sendMessage,
    messages,
    clearMessages,
    exportMessages,
    ping,
    lastLatency,
    averageLatency,
    autoReconnect,
    setAutoReconnect,
  }
}
