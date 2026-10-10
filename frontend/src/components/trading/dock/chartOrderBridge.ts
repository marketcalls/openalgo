/**
 * How the chart's right-click menu reaches the dock's books and the dock's
 * order actions.
 *
 * The dock owns the books (orders and positions, kept live by its own
 * socket subscription) and is rendered once under the grid; the charts are
 * its siblings. The page holds one ref, the dock fills it, and every chart
 * pane reads it at the moment its menu opens. Absent (no dock, a test), the
 * menu simply offers no order rows.
 */

import { createContext } from 'react'
import type { DockOrder, DockPosition } from './blotter'
import type { OrderActionContext } from './orderActions'

export interface ChartOrderBridge {
  /** The books as the dock holds them now. */
  book(): { orders: readonly DockOrder[]; positions: readonly DockPosition[] }
  /** The context the dock's own buttons act in: mode, replay lock, refresh. */
  actions: OrderActionContext
  /** Positions read fresh from the server, for an order sized from one. */
  freshPositions(): Promise<DockPosition[]>
}

export interface ChartOrderBridgeRef {
  current: ChartOrderBridge | null
}

export const ChartOrderBridgeContext = createContext<ChartOrderBridgeRef | null>(null)
