/**
 * The three books behind the dock, kept the way Scalping keeps its own:
 * TanStack Query with the app mode in the key, refetched on the broker's
 * order events through the one shared socket, never polled.
 *
 * On top of that, the order book takes the SocketIO `order_update` frames
 * nothing else in the app consumes: a fill or a rejection lands on its row
 * the moment the broker pushes it, and the refetch that follows confirms it.
 */

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef } from 'react'
import { tradingApi } from '@/api/trading'
import { useSocketContext } from '@/components/socket/SocketProvider'
import { type OrderEventType, useOrderEventRefresh } from '@/hooks/useOrderEventRefresh'
import type { AppMode } from '@/stores/themeStore'
import {
  type DockOrder,
  type DockPosition,
  type DockTrade,
  parseOrder,
  parsePosition,
  parseTrade,
} from './blotter'
import {
  applyOrderUpdate,
  frameMode,
  holdPushedStatus,
  type OrderUpdateFrame,
  type PushedStatus,
  RecentKeys,
  rememberPushed,
  updateKey,
} from './orderUpdates'

/** The events each book page refreshes on today, in one list. */
const BOOK_EVENTS: OrderEventType[] = [
  'order_event',
  'analyzer_update',
  'close_position_event',
  'cancel_order_event',
  'modify_order_event',
]

/**
 * A burst of events (a basket, a close-all) collapses into one refetch at
 * the front and one at the back, the way Scalping's refreshBooks does.
 */
const REFRESH_THROTTLE_MS = 400

/**
 * The gap between a live frame and the refetch that confirms it, the same
 * settle the event path gives the server. Fired in the same tick, the refetch
 * read a broker book that had not caught up with its own postback and put
 * the old status back on the row.
 */
const FRAME_SETTLE_MS = 150

const ROOT = 'trading-dock'

export function ordersKey(appMode: AppMode) {
  return [ROOT, 'orders', appMode] as const
}

interface Options {
  apiKey: string | null
  appMode: AppMode
  /** False while the dock is closed: nothing is fetched for a strip of counts alone. */
  enabled?: boolean
}

export interface Blotter {
  orders: DockOrder[]
  positions: DockPosition[]
  trades: DockTrade[]
  isLoading: boolean
  error: string | null
  refresh(): void
}

export function useBlotter({ apiKey, appMode, enabled = true }: Options): Blotter {
  const queryClient = useQueryClient()
  const { socket } = useSocketContext()
  const active = enabled && !!apiKey

  // What the last frame per order said, so a refetch that reaches a lagging
  // broker book cannot put 'open' back on a row the broker already filled.
  const pushedRef = useRef(new Map<string, PushedStatus>())

  const ordersQuery = useQuery({
    queryKey: ordersKey(appMode),
    queryFn: async () => {
      const res = await tradingApi.getOrders(apiKey ?? '')
      if (res.status === 'error') throw new Error(res.message || 'Order book unavailable')
      const rows = (res.data?.orders ?? []).map(parseOrder)
      return holdPushedStatus(rows, pushedRef.current, Date.now())
    },
    enabled: active,
    refetchOnWindowFocus: true,
  })
  const positionsQuery = useQuery({
    queryKey: [ROOT, 'positions', appMode],
    queryFn: async () => {
      const res = await tradingApi.getPositions(apiKey ?? '')
      if (res.status === 'error') throw new Error(res.message || 'Position book unavailable')
      return (res.data ?? []).map(parsePosition)
    },
    enabled: active,
    refetchOnWindowFocus: true,
  })
  const tradesQuery = useQuery({
    queryKey: [ROOT, 'trades', appMode],
    queryFn: async () => {
      const res = await tradingApi.getTrades(apiKey ?? '')
      if (res.status === 'error') throw new Error(res.message || 'Trade book unavailable')
      return (res.data ?? []).map(parseTrade)
    },
    enabled: active,
    refetchOnWindowFocus: true,
  })

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastRef = useRef(0)
  const refresh = useCallback(() => {
    const run = () => {
      lastRef.current = Date.now()
      void queryClient.invalidateQueries({ queryKey: [ROOT] })
    }
    const since = Date.now() - lastRef.current
    if (since >= REFRESH_THROTTLE_MS) run()
    else if (timerRef.current == null) {
      timerRef.current = setTimeout(() => {
        timerRef.current = null
        run()
      }, REFRESH_THROTTLE_MS - since)
    }
  }, [queryClient])

  // One settle timer for a burst of frames; the throttle above spaces the
  // refetches behind it.
  const settleRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const refreshSettled = useCallback(() => {
    if (settleRef.current != null) return
    settleRef.current = setTimeout(() => {
      settleRef.current = null
      refresh()
    }, FRAME_SETTLE_MS)
  }, [refresh])

  useEffect(
    () => () => {
      if (timerRef.current != null) clearTimeout(timerRef.current)
      if (settleRef.current != null) clearTimeout(settleRef.current)
    },
    []
  )

  useOrderEventRefresh(refresh, { events: BOOK_EVENTS, delay: 150, enabled: active })

  /**
   * Live rows. The frame is folded into the cached book straight away and a
   * throttled refetch follows, so the positions and trades it implies catch
   * up without the order book waiting for them. The refetch is scheduled for
   * every frame, a repeat included: a repeat still says the broker's book
   * moved, and the confirming fetch must not be lost with the fold.
   */
  const seenRef = useRef(new RecentKeys())
  useEffect(() => {
    if (!socket || !active) return
    const onUpdate = (frame: OrderUpdateFrame) => {
      if (!frame || typeof frame !== 'object') return
      const mode = frameMode(frame.mode)
      if (mode !== null && mode !== appMode) return
      if (seenRef.current.add(updateKey(frame))) {
        rememberPushed(pushedRef.current, frame, Date.now())
        queryClient.setQueryData<DockOrder[]>(ordersKey(appMode), (orders) =>
          applyOrderUpdate(orders ?? [], frame)
        )
      }
      refreshSettled()
    }
    socket.on('order_update', onUpdate)
    return () => {
      socket.off('order_update', onUpdate)
    }
  }, [socket, active, appMode, queryClient, refreshSettled])

  /**
   * A full refetch after the socket comes back. Whatever the broker pushed
   * while the connection was down never arrived, and the events that would
   * have refreshed the books went with it. The first connect after mount is
   * not a reconnect and the queries are fetching anyway.
   */
  useEffect(() => {
    if (!socket || !active) return
    let seen = socket.connected
    const onConnect = () => {
      if (seen) refresh()
      seen = true
    }
    socket.on('connect', onConnect)
    return () => {
      socket.off('connect', onConnect)
    }
  }, [socket, active, refresh])

  const error =
    (ordersQuery.error as Error | null)?.message ??
    (positionsQuery.error as Error | null)?.message ??
    (tradesQuery.error as Error | null)?.message ??
    null

  const orders = ordersQuery.data
  const positions = positionsQuery.data
  const trades = tradesQuery.data
  return useMemo(
    () => ({
      orders: orders ?? [],
      positions: positions ?? [],
      trades: trades ?? [],
      isLoading: ordersQuery.isPending || positionsQuery.isPending || tradesQuery.isPending,
      error,
      refresh,
    }),
    [
      orders,
      positions,
      trades,
      ordersQuery.isPending,
      positionsQuery.isPending,
      tradesQuery.isPending,
      error,
      refresh,
    ]
  )
}
