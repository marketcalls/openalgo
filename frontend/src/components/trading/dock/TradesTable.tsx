/**
 * The trade book as a dock table: every fill today, across every symbol.
 * Read-only; a fill is a fact.
 */

import type { SearchRow } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'
import type { DockTrade } from './blotter'
import {
  EmptyRows,
  isActiveRow,
  isRowClick,
  ROW,
  ROW_ACTIVE,
  SymbolCell,
  sideClass,
  TD,
  TD_NUM,
  TH,
  TH_NUM,
} from './cells'
import { fmt2, formatTime } from './format'

interface Props {
  trades: DockTrade[]
  activeSymbol?: string | null
  onPick(row: SearchRow): void
  isLoading?: boolean
}

export function TradesTable({ trades, activeSymbol, onPick, isLoading }: Props) {
  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr>
          <th scope="col" className={TH}>
            Time
          </th>
          <th scope="col" className={TH}>
            Symbol
          </th>
          <th scope="col" className={TH}>
            Exch
          </th>
          <th scope="col" className={TH}>
            Side
          </th>
          <th scope="col" className={TH}>
            Product
          </th>
          <th scope="col" className={TH_NUM}>
            Qty
          </th>
          <th scope="col" className={TH_NUM}>
            Avg price
          </th>
          <th scope="col" className={TH_NUM}>
            Value
          </th>
        </tr>
      </thead>
      <tbody>
        {trades.length === 0 && (
          <EmptyRows colSpan={8}>{isLoading ? 'Loading trades' : 'No trades today.'}</EmptyRows>
        )}
        {trades.map((t, i) => {
          const active = isActiveRow(activeSymbol, t)
          return (
            <tr
              // A partial fill reports the same order id twice, so the key
              // needs the time and the position in the list as well.
              key={`${t.orderid}-${t.timestamp}-${i}`}
              className={cn(ROW, active && ROW_ACTIVE)}
              onClick={(e) => {
                if (isRowClick(e)) onPick({ symbol: t.symbol, exchange: t.exchange })
              }}
            >
              <td className={cn(TD, 'tabular-nums text-muted-foreground')}>
                {formatTime(t.timestamp)}
              </td>
              <SymbolCell symbol={t.symbol} exchange={t.exchange} active={active} onPick={onPick} />
              <td className={cn(TD, 'text-muted-foreground')}>{t.exchange}</td>
              <td className={cn(TD, 'font-medium', sideClass(t.action))}>{t.action}</td>
              <td className={cn(TD, 'text-muted-foreground')}>{t.product}</td>
              <td className={TD_NUM}>{t.quantity}</td>
              <td className={TD_NUM}>{fmt2(t.average_price)}</td>
              <td className={TD_NUM}>{fmt2(t.trade_value)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
