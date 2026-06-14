import { useEffect, useRef } from 'react'
import { io, type Socket } from 'socket.io-client'
import { useSocketContext } from '@/components/socket/SocketProvider'

/**
 * Supported Socket.IO event types for order-related updates
 */
export type OrderEventType =
  | 'order_event'
  | 'analyzer_update'
  | 'close_position_event'
  | 'cancel_order_event'
  | 'modify_order_event'
  // Pushed by the server-side scalping risk monitor when it trails/clears an SL.
  | 'scalping_sl_update'

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
  const { events = ['order_event', 'analyzer_update'], delay = 500, enabled = true } = options

  const refreshFnRef = useRef(refreshFn)
  const eventsRef = useRef(events)
  eventsRef.current = events

  // Reuse the ONE app-wide Socket.IO connection (SocketProvider) instead of opening
  // our own. Each Socket.IO long-poll holds an HTTP connection, and the browser's
  // ~6-per-host limit is shared across all tabs — so a per-hook connection (×pages
  // ×tabs) exhausts the pool and the app hangs. Sharing one connection fixes that.
  const { socket } = useSocketContext()

  // Keep refresh function reference up to date
  useEffect(() => {
    refreshFnRef.current = refreshFn
  }, [refreshFn])

  // Key the effect on the event CONTENTS (callers pass inline arrays), and on the
  // shared socket — re-attach listeners only when the socket or the set changes.
  const eventsKey = events.join('|')

  // biome-ignore lint/correctness/useExhaustiveDependencies: events read via ref; eventsKey tracks content
  useEffect(() => {
    if (!enabled || !socket) return

    const handleEvent = () => {
      // Delay slightly to allow server to process the event
      setTimeout(() => refreshFnRef.current(), delay)
    }

    const subscribed = eventsRef.current
    subscribed.forEach((event) => {
      socket.on(event, handleEvent)
    })

    // Only remove OUR listeners — never disconnect the shared connection.
    return () => {
      subscribed.forEach((event) => {
        socket.off(event, handleEvent)
      })
    }
  }, [socket, eventsKey, delay, enabled])
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
