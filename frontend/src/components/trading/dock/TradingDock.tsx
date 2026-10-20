/**
 * The dock, assembled: the books from useBlotter, live prices over the
 * position rows, the shell around them, and every action the rows offer.
 *
 * Page-level, like the side panels. It acts on whichever pane is focused
 * when a row is clicked and on the broker for everything else, so it is
 * rendered once under the grid rather than once per pane.
 */

import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { tradingApi } from '@/api/trading'
import { useLivePrice } from '@/hooks/useLivePrice'
import type { SearchRow } from '@/lib/trading/terminal'
import { makeFormatCurrency } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'
import {
  type DockOrder,
  type DockPosition,
  isWorking,
  realisedFromTrades,
  parsePosition,
  sumOpenPnl,
} from './blotter'
import type { ChartOrderBridgeRef } from './chartOrderBridge'
import { DockShell } from './DockShell'
import type { DockTab } from './dockState'
import { ModifyOrderDialog, type ModifyValues, sendsPrice, sendsTrigger } from './ModifyOrderDialog'
import {
  apiErrorMessage,
  cancelAllDockOrders,
  cancelDockOrder,
  closeAllDockPositions,
  closeDockPosition,
  type OrderActionContext,
} from './orderActions'
import { OrdersTable } from './OrdersTable'
import { PnlStrip } from './PnlStrip'
import { PositionsTable } from './PositionsTable'
import { TradesTable } from './TradesTable'
import { useBlotter } from './useBlotter'

// The GTT tab carries its own fetch, dialogs and CSV export; nobody pays
// for it until the tab is opened.
const GttTab = lazy(() => import('../GttTab'))

/** The chart's words, so the dock and the chart refuse in one voice. */
export const REPLAY_REFUSAL = 'Replay is a simulation. Leave replay to trade.'

interface Props {
  tab: DockTab | null
  onTabChange(tab: DockTab | null): void
  apiKey: string
  /** Charts a row in the focused pane, the way a watchlist row does. */
  onPick(row: SearchRow): void
  activeSymbol: string | null
  /** True while any pane is replaying or picking a replay start. */
  tradingLocked(): boolean
  /** Filled with the books and the actions, for the chart's right-click menu. */
  bridge?: ChartOrderBridgeRef
}

export function TradingDock({
  tab,
  onTabChange,
  apiKey,
  onPick,
  activeSymbol,
  tradingLocked,
  bridge,
}: Props) {
  const appMode = useThemeStore((s) => s.appMode)
  const broker = useAuthStore((s) => s.user?.broker)
  const formatCurrency = useMemo(() => makeFormatCurrency(broker), [broker])
  const { orders, positions, trades, isLoading, error, refresh } = useBlotter({ apiKey, appMode })
  const [modifying, setModifying] = useState<DockOrder | null>(null)

  // Live LTP and P&L over the position rows, only while the dock is open:
  // the collapsed strip shows counts, which do not move with the feed.
  const { data: livePositions, isLive } = useLivePrice(positions, {
    enabled: tab !== null && positions.length > 0,
  })
  const openPnl = useMemo(() => sumOpenPnl(livePositions), [livePositions])
  const realised = useMemo(() => realisedFromTrades(trades), [trades])
  const workingOrders = useMemo(
    () => orders.filter((o) => isWorking(o.order_status)).length,
    [orders]
  )
  /**
   * A tab's badge is the number of rows behind it, nothing cleverer. Counting
   * working orders instead read as a defect: four completed orders on screen
   * under a tab saying 0. The figures that are about live risk have their own
   * places, the working count beside Cancel all and the open count beside the
   * P&L, where they are labelled.
   */
  const counts = useMemo(
    () => ({ orders: orders.length, positions: positions.length, trades: trades.length }),
    [orders.length, positions.length, trades.length]
  )

  const refuse = useCallback(() => {
    if (!tradingLocked()) return false
    showToast.error(REPLAY_REFUSAL)
    return true
  }, [tradingLocked])

  /** The context every dock action runs in; the chart's menu builds the same. */
  const actions = useMemo<OrderActionContext>(
    () => ({ appMode, refuse, refresh }),
    [appMode, refuse, refresh]
  )
  /** Analyzer mode toasts outcomes globally; see orderActions.ts. */
  const handledGlobally = useCallback(
    (e: unknown) => appMode === 'analyzer' && !!(e as { response?: unknown }).response,
    [appMode]
  )

  // The chart menus read the books at the moment they open, never a copy
  // taken when the bridge was filled.
  const bookRef = useRef({ orders, positions })
  bookRef.current = { orders, positions }
  useEffect(() => {
    if (!bridge) return
    bridge.current = {
      book: () => bookRef.current,
      actions,
      freshPositions: async () => {
        const res = await tradingApi.getPositions(apiKey)
        if (res.status === 'error') throw new Error(res.message || 'Position book unavailable')
        return (res.data ?? []).map(parsePosition)
      },
    }
    return () => {
      if (bridge.current?.actions === actions) bridge.current = null
    }
  }, [bridge, actions, apiKey])

  const cancelOrder = useCallback((order: DockOrder) => cancelDockOrder(order, actions), [actions])

  const modifyOrder = useCallback(
    async (order: DockOrder, values: ModifyValues): Promise<boolean> => {
      if (refuse()) return false
      let ok = false
      try {
        const res = await tradingApi.modifyOrder(order.orderid, {
          symbol: order.symbol,
          exchange: order.exchange,
          action: order.action,
          product: order.product,
          pricetype: order.pricetype,
          quantity: values.quantity,
          ...(sendsPrice(order.pricetype) && { price: values.price }),
          ...(sendsTrigger(order.pricetype) && { trigger_price: values.trigger_price }),
        })
        ok = res.status === 'success'
        if (ok) {
          if (appMode === 'live') showToast.success(`Order modified: ${order.orderid}`, 'orders')
        } else if (appMode === 'live') {
          showToast.error(res.message || 'Modify failed', 'orders')
        }
      } catch (e) {
        if (!handledGlobally(e)) showToast.error(apiErrorMessage(e), 'orders')
      }
      refresh()
      return ok
    },
    [refuse, appMode, handledGlobally, refresh]
  )

  const closePosition = useCallback((p: DockPosition) => closeDockPosition(p, actions), [actions])
  const cancelAll = useCallback(() => cancelAllDockOrders(actions), [actions])
  const closeAll = useCallback(() => closeAllDockPositions(actions), [actions])

  const openModify = useCallback(
    (order: DockOrder) => {
      if (refuse()) return
      setModifying(order)
    },
    [refuse]
  )

  return (
    <DockShell
      tab={tab}
      onTabChange={onTabChange}
      counts={counts}
      header={
        <PnlStrip
          openPnl={openPnl.pnl}
          openCount={openPnl.open}
          realised={realised}
          live={isLive}
          workingOrders={workingOrders}
          onCancelAll={() => void cancelAll()}
          onCloseAll={() => void closeAll()}
          formatCurrency={formatCurrency}
        />
      }
    >
      {error && (
        <div className="flex items-center gap-2 border-b bg-destructive/10 px-2 py-1 text-[12px] text-destructive">
          <span className="min-w-0 flex-1 truncate">{error}</span>
          <button type="button" className="underline" onClick={refresh}>
            Retry
          </button>
        </div>
      )}
      {tab === 'orders' && (
        <OrdersTable
          orders={orders}
          activeSymbol={activeSymbol}
          onPick={onPick}
          onCancel={(o) => void cancelOrder(o)}
          onModify={openModify}
          isLoading={isLoading}
        />
      )}
      {tab === 'positions' && (
        <PositionsTable
          positions={livePositions}
          activeSymbol={activeSymbol}
          onPick={onPick}
          onClose={(p) => void closePosition(p)}
          isLoading={isLoading}
        />
      )}
      {tab === 'trades' && (
        <TradesTable
          trades={trades}
          activeSymbol={activeSymbol}
          onPick={onPick}
          isLoading={isLoading}
        />
      )}
      {tab === 'gtt' && (
        <Suspense
          fallback={<div className="p-3 text-[12px] text-muted-foreground">Loading GTT</div>}
        >
          <div className="p-2">
            {/* Its own fetch and dialogs, but the dock's replay lock. */}
            <GttTab refuse={refuse} />
          </div>
        </Suspense>
      )}
      <ModifyOrderDialog
        order={modifying}
        onOpenChange={(open) => !open && setModifying(null)}
        onSubmit={modifyOrder}
      />
    </DockShell>
  )
}
