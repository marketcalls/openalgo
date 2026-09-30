import { useEffect } from 'react'
import type { Socket } from 'socket.io-client'

/**
 * How long to wait, once a reconnection cycle has given up, before starting the
 * next one. Socket.IO's own ceiling between two attempts (`reconnectionDelayMax`
 * default), so a page that keeps retrying never retries faster than a socket
 * with unlimited attempts would.
 */
export const RECONNECT_CYCLE_PAUSE_MS = 5000

/**
 * Keep the shared Socket.IO connection retrying for as long as the caller is
 * mounted.
 *
 * The app-wide connection gives up after five reconnection attempts. A page
 * that used to own a connection with unlimited attempts (the Action Center,
 * which a trader leaves open to approve orders as they arrive) would otherwise
 * go quiet for good after a server restart longer than those five attempts.
 * This hook restores what that page had: when the connection gives up, it
 * starts another cycle, until the page unmounts.
 *
 * A connection its owner closed on purpose (logout, leaving the layout, the
 * server ending the session) is never reopened: `socket.active` is false for
 * those, and only true for one that is still meant to be connected.
 */
export function useKeepReconnecting(socket: Socket | null, enabled = true): void {
  useEffect(() => {
    if (!enabled || !socket) return

    const manager = socket.io
    let timer: ReturnType<typeof setTimeout> | null = null

    const startAnotherCycle = () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        timer = null
        if (socket.active && !socket.connected) socket.connect()
      }, RECONNECT_CYCLE_PAUSE_MS)
    }

    manager.on('reconnect_failed', startAnotherCycle)
    return () => {
      manager.off('reconnect_failed', startAnotherCycle)
      if (timer) clearTimeout(timer)
    }
  }, [socket, enabled])
}
