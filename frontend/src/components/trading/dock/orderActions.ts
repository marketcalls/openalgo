/**
 * The dock's order actions, as plain functions: cancel one order, close one
 * position, cancel every order, close every position.
 *
 * They lived inside the dock component. The chart's right-click menu offers
 * the same cancel and close for the symbol on the chart, and it must not grow
 * a second order path beside this one, so both call these. Each goes through
 * the session web routes the dock always used, which read the platform's
 * analyzer switch on the server: in analyzer mode the order goes to the
 * sandbox, in live mode to the broker, and nothing here decides which.
 *
 * Toasts follow the scalping terminal's split. In analyzer mode the
 * analyzer_update event toasts every outcome globally, so these only speak
 * when that handler will not: live mode, or a transport error.
 */

import { tradingApi } from '@/api/trading'
import type { AppMode } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'
import type { DockOrder, DockPosition } from './blotter'

export interface OrderActionContext {
  appMode: AppMode
  /**
   * True when trading is locked (a replay on screen, a workspace switching),
   * having already told the trader why. Asked first, every time.
   */
  refuse(): boolean
  /** Refetch the books once the action has been sent. */
  refresh(): void
}

/**
 * The trader-facing reason out of an API error, falling back to the
 * transport's message.
 */
export function apiErrorMessage(e: unknown): string {
  const err = e as { response?: { data?: { message?: string } }; message?: string }
  return err.response?.data?.message || err.message || 'Request failed'
}

/** Whether the analyzer_update handler already toasts this failure. */
function handledGlobally(ctx: OrderActionContext, e: unknown): boolean {
  return ctx.appMode === 'analyzer' && !!(e as { response?: unknown }).response
}

/** Cancel one working order. True when the server accepted the cancel. */
export async function cancelDockOrder(order: DockOrder, ctx: OrderActionContext): Promise<boolean> {
  if (ctx.refuse()) return false
  let ok = false
  try {
    const res = await tradingApi.cancelOrder(order.orderid)
    ok = res.status === 'success'
    if (ok) {
      // cancel_order_event only plays the sound in live mode.
      if (ctx.appMode === 'live') showToast.success(`Order cancelled: ${order.orderid}`, 'orders')
    } else if (ctx.appMode === 'live') {
      showToast.error(res.message || 'Cancel failed', 'orders')
    }
  } catch (e) {
    if (!handledGlobally(ctx, e)) showToast.error(apiErrorMessage(e), 'orders')
  }
  ctx.refresh()
  return ok
}

/**
 * Square off one position through the per-position web route. Success is
 * toasted by the close_position_event it raises, in both modes. True when
 * the server accepted the square-off.
 */
export async function closeDockPosition(
  p: DockPosition,
  ctx: OrderActionContext
): Promise<boolean> {
  if (ctx.refuse()) return false
  let ok = false
  try {
    const res = await tradingApi.closePosition(p.symbol, p.exchange, p.product)
    ok = res.status === 'success'
    if (!ok && ctx.appMode === 'live') {
      showToast.error(res.message || 'Close failed', 'orders')
    }
  } catch (e) {
    if (!handledGlobally(ctx, e)) showToast.error(apiErrorMessage(e), 'orders')
  }
  ctx.refresh()
  return ok
}

export async function cancelAllDockOrders(ctx: OrderActionContext): Promise<void> {
  if (ctx.refuse()) return
  try {
    const res = await tradingApi.cancelAllOrders()
    if (res.status !== 'success' && ctx.appMode === 'live') {
      showToast.error(res.message || 'Cancel all failed', 'orders')
    }
  } catch (e) {
    if (!handledGlobally(ctx, e)) showToast.error(apiErrorMessage(e), 'orders')
  }
  ctx.refresh()
}

export async function closeAllDockPositions(ctx: OrderActionContext): Promise<void> {
  if (ctx.refuse()) return
  try {
    const res = await tradingApi.closeAllPositions()
    if (res.status !== 'success' && ctx.appMode === 'live') {
      showToast.error(res.message || 'Close all failed', 'orders')
    }
  } catch (e) {
    if (!handledGlobally(ctx, e)) showToast.error(apiErrorMessage(e), 'orders')
  }
  ctx.refresh()
}
