import { useEffect, useRef } from 'react'
import { io, type Socket } from 'socket.io-client'

/**
 * Supported Socket.IO event types for order-related updates
 */
export type OrderEventType =
  | 'order_event'
  | 'analyzer_update'
  | 'close_position_event'
  | 'cancel_order_event'
  | 'modify_order_event'

/**
 * Configuration options for useOrderEventRefresh hook
 */
export interface UseOrderEventRefreshOptions {
  /** Events to listen for (default: ['order_event', 'analyzer_update']) */
  events?: OrderEventType[]
  /** Delay in ms before calling refresh function (default: 500) */
  delay?: number
  /** Whether the hook is enabled (default: true) */
  enabled?: boolean
}

/**
 * Centralized hook for Socket.IO order event listeners.
 *
 * Automatically sets up Socket.IO connection and listens for specified events,
 * calling the refresh function with an optional delay when events occur.
 *
 * @example
 * ```tsx
 * // Basic usage - listens to order_event and analyzer_update
 * useOrderEventRefresh(fetchPositions);
 *
 * // With additional events
 * useOrderEventRefresh(fetchPositions, {
 *   events: ['order_event', 'analyzer_update', 'close_position_event'],
 *   delay: 500,
 * });
 *
 * // Conditional enablement
 * useOrderEventRefresh(fetchPositions, {
 *   enabled: isAuthenticated,
 * });
 * ```
 *
 * @param refreshFn - Function to call when an event is received
 * @param options - Configuration options
 */
export function useOrderEventRefresh(
  refreshFn: () => void,
  options: UseOrderEventRefreshOptions = {}
): void {
  const {
    events = ['order_event', 'analyzer_update'],
    delay = 500,
    enabled = true,
  } = options

  const socketRef = useRef<Socket | null>(null)
  const refreshFnRef = useRef(refreshFn)

  // Keep refresh function reference up to date
  useEffect(() => {
    refreshFnRef.current = refreshFn
  }, [refreshFn])

  useEffect(() => {
    if (!enabled) return

    // Build Socket.IO URL from current location
    const protocol = window.location.protocol
    const host = window.location.hostname
    const port = window.location.port

    socketRef.current = io(`${protocol}//${host}:${port}`, {
      transports: ['polling'],
      upgrade: false,
    })

    const socket = socketRef.current

    // Create handler for each event type
    const handleEvent = () => {
      // Delay slightly to allow server to process the event
      setTimeout(() => refreshFnRef.current(), delay)
    }

    // Register listeners for all specified events
    events.forEach((event) => {
      socket.on(event, handleEvent)
    })

    // Cleanup on unmount
    return () => {
      events.forEach((event) => {
        socket.off(event, handleEvent)
      })
      socket.disconnect()
    }
  }, [events, delay, enabled])
}

/**
 * Hook to get direct access to Socket.IO connection for custom event handling.
 *
 * @example
 * ```tsx
 * const { socket, isConnected } = useSocketConnection();
 *
 * useEffect(() => {
 *   if (!socket) return;
 *   socket.on('custom_event', handleCustomEvent);
 *   return () => socket.off('custom_event', handleCustomEvent);
 * }, [socket]);
 * ```
 */
export function useSocketConnection(enabled = true): {
  socket: Socket | null
  isConnected: boolean
} {
  const socketRef = useRef<Socket | null>(null)

  useEffect(() => {
    if (!enabled) return

    const protocol = window.location.protocol
    const host = window.location.hostname
    const port = window.location.port

    socketRef.current = io(`${protocol}//${host}:${port}`, {
      transports: ['polling'],
      upgrade: false,
    })

    return () => {
      socketRef.current?.disconnect()
      socketRef.current = null
    }
  }, [enabled])

  return {
    socket: socketRef.current,
    isConnected: socketRef.current?.connected ?? false,
  }
}
