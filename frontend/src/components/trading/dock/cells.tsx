/**
 * What the three tables share: the cell metrics, the status badge, and the
 * symbol cell that charts its row.
 *
 * Written once so the books cannot drift: a quantity right-aligned in one
 * table and centred in the next is the kind of thing nobody files a bug
 * about and everybody notices.
 */

import type { MouseEvent, ReactNode } from 'react'
import type { SearchRow } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'
import { statusTone } from './blotter'
import { direction } from './format'

export const TH =
  'sticky top-0 z-10 h-7 bg-background px-2 text-left text-[11px] font-medium uppercase tracking-wide text-muted-foreground'
export const TH_NUM = cn(TH, 'text-right')
export const TD = 'px-2 py-1 align-middle text-[12px] whitespace-nowrap'
export const TD_NUM = cn(TD, 'text-right tabular-nums')
export const ROW =
  'group cursor-pointer border-b transition-colors hover:bg-accent/50 last:border-0'
/** The charted row, the watchlist's marker: a wash and a left rule. */
export const ROW_ACTIVE = '!bg-accent shadow-[inset_2px_0_0_0_var(--color-primary)]'

/** The emerald and rose the watchlist uses, on a signed figure. */
export function toneClass(value: number): string {
  const d = direction(value)
  if (d === 'up') return 'text-emerald-600 dark:text-emerald-400'
  if (d === 'down') return 'text-rose-600 dark:text-rose-400'
  return 'text-muted-foreground'
}

export function sideClass(action: string): string {
  if (action === 'BUY') return 'text-emerald-600 dark:text-emerald-400'
  if (action === 'SELL') return 'text-rose-600 dark:text-rose-400'
  return ''
}

/**
 * Whether a click on a row should chart it. A click that landed on a button
 * inside the row (Cancel, Modify, Close) is that button's, not the row's.
 */
export function isRowClick(e: MouseEvent<HTMLElement>): boolean {
  return !(e.target as HTMLElement).closest('button, a, input, [role="dialog"]')
}

export function isActiveRow(
  activeSymbol: string | null | undefined,
  row: { symbol: string; exchange: string }
): boolean {
  return activeSymbol === `${row.exchange}:${row.symbol}`
}

/**
 * The symbol, as a real button that loads the row into the focused pane.
 * Pointer users get the whole row through isRowClick; this is the same
 * action for the keyboard, and it is where the charted state is announced.
 */
export function SymbolCell({
  symbol,
  exchange,
  active,
  onPick,
  children,
}: {
  symbol: string
  exchange: string
  active: boolean
  onPick(row: SearchRow): void
  children?: ReactNode
}) {
  return (
    <td className={cn(TD, 'font-medium')}>
      <button
        type="button"
        onClick={() => onPick({ symbol, exchange })}
        aria-label={`Chart ${symbol} on ${exchange}`}
        aria-current={active ? true : undefined}
        className="rounded-sm text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        {symbol}
      </button>
      {children}
    </td>
  )
}

/**
 * A status in the broker's own words. Recognised ones take a tone; the rest
 * are printed as they came, in the neutral one, so a status this file has
 * never heard of is still a status on screen and not a blank cell.
 */
export function StatusBadge({ status }: { status: string }) {
  const tone = statusTone(status)
  return (
    <span
      className={cn(
        'inline-block rounded-full border px-1.5 py-px text-[10px] font-medium capitalize',
        // The primary token, not a fixed hue: it follows light, dark and the
        // analyzer accent the way the tab badge does.
        tone === 'working' && 'border-primary/40 bg-primary/10 text-primary',
        tone === 'done' &&
          'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
        tone === 'failed' && 'border-rose-500/40 bg-rose-500/10 text-rose-700 dark:text-rose-300',
        tone === 'off' && 'border-border bg-muted text-muted-foreground',
        tone === 'unknown' && 'border-border text-foreground'
      )}
    >
      {status || 'unknown'}
    </span>
  )
}

export function EmptyRows({ colSpan, children }: { colSpan: number; children: ReactNode }) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-2 py-6 text-center text-[12px] text-muted-foreground">
        {children}
      </td>
    </tr>
  )
}
