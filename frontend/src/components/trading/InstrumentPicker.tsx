/**
 * The instrument, the exchange, the bar and the product, picked rather than typed.
 *
 * **Every one of these typed by hand is a run that fails later, or worse.** A
 * symbol is the one string a broker mapping matches on, so a character wrong is
 * a start refused a minute later in a log, and a character wrong in a way that
 * happens to name another instrument is a strategy trading something nobody
 * chose. An interval the broker does not serve is a run that fetches no history
 * at all. A product the exchange does not take is an order rejected at the
 * broker, after a signal has already been acted on.
 *
 * So each one offers what this platform already knows: the broker's own
 * exchanges, its instrument master, its own interval list, and the products that
 * exchange actually takes.
 *
 * **The box still accepts typing**, because a trader who knows the exact symbol
 * is faster than any list, and because a list that has not loaded must never be
 * a form that cannot be filled in. What it does not do is leave them with no
 * idea whether what they typed exists.
 */

import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { instrumentsOn, intervalsAvailable } from '@/api/openscriptRunner'
import { useSupportedExchanges } from '@/hooks/useSupportedExchanges'
import { DERIVATIVE_EXCHANGES } from '@/lib/flow/constants'
import { cn } from '@/lib/utils'

const FIELD = 'h-7 w-full rounded border border-border bg-background px-1.5 text-[11px]'

/**
 * The products an exchange takes.
 *
 * A cash venue settles in shares and takes delivery or intraday; a derivative
 * venue carries a contract on margin and takes normal or intraday. The same
 * split the rest of this platform makes, read from the same set, so a product
 * offered here is one an order can actually be sent as.
 */
export function productsOn(exchange: string): string[] {
  return DERIVATIVE_EXCHANGES.has((exchange || '').trim().toUpperCase())
    ? ['MIS', 'NRML']
    : ['MIS', 'CNC']
}

/** The product to move to when the exchange changes under a chosen one. */
export function productFor(exchange: string, current: string): string {
  const offered = productsOn(exchange)
  return offered.includes((current || '').toUpperCase()) ? current.toUpperCase() : offered[0]
}

interface Props {
  symbol: string
  exchange: string
  interval: string
  product: string
  onChange(next: { symbol?: string; exchange?: string; interval?: string; product?: string }): void
}

export function InstrumentPicker({ symbol, exchange, interval, product, onChange }: Props) {
  // The venues that can be traded, never the index ones. A strategy deployed on
  // an index is a strategy whose every order the broker refuses: an index has no
  // contract to buy. The same list the chart and the search box offer.
  const { tradingExchanges } = useSupportedExchanges()
  const [query, setQuery] = useState(symbol)
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  // Follow the parent when it fills the form from the chart.
  useEffect(() => setQuery(symbol), [symbol])

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false)
    }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [open])

  // Two characters minimum: one matches most of an exchange, which is a list
  // nobody can read and a request nobody benefits from.
  const { data: found = [], isFetching } = useQuery({
    queryKey: ['openscript', 'instruments', exchange, query],
    queryFn: () => instrumentsOn(query.trim(), exchange),
    enabled: open && query.trim().length >= 2,
    staleTime: 60_000,
  })

  const { data: bars = [] } = useQuery({
    queryKey: ['openscript', 'intervals'],
    queryFn: () => intervalsAvailable(),
    // The broker's answer changes when the broker does, which is a login and
    // not a minute, so this is asked once and kept.
    staleTime: 30 * 60_000,
  })

  const choose = (picked: string) => {
    setQuery(picked)
    onChange({ symbol: picked })
    setOpen(false)
  }

  const venues =
    tradingExchanges.length > 0 ? tradingExchanges : [{ value: exchange, label: exchange }]
  // An interval the broker does not serve is still shown while it is the one
  // saved: a deployment that already runs on it should not have its own bar
  // silently changed by a list that has not loaded, or by a broker swap.
  const offered = bars.includes(interval) || !interval ? bars : [interval, ...bars]

  return (
    <div className="grid grid-cols-2 gap-1.5">
      <div ref={box} className="relative col-span-2">
        <input
          className={FIELD}
          placeholder="Instrument"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value.toUpperCase())
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(event) => {
            // A trader who knows the exact symbol should not have to wait for a
            // list to agree with them.
            if (event.key === 'Enter') {
              event.preventDefault()
              choose(query.trim().toUpperCase())
            }
            if (event.key === 'Escape') setOpen(false)
          }}
          onBlur={() => onChange({ symbol: query.trim().toUpperCase() })}
        />
        {open && query.trim().length >= 2 && (
          <div className="absolute z-50 mt-1 max-h-56 w-full overflow-y-auto rounded border border-border bg-popover shadow-lg">
            {isFetching && found.length === 0 && (
              <div className="px-2 py-1.5 text-[11px] text-muted-foreground">Searching</div>
            )}
            {!isFetching && found.length === 0 && (
              <div className="px-2 py-1.5 text-[11px] text-muted-foreground">
                Nothing on {exchange || 'any exchange'} matching {query}
              </div>
            )}
            {found.slice(0, 25).map((row) => (
              <button
                type="button"
                key={`${row.symbol}-${row.exchange}`}
                // mousedown, not click: the input's blur would close the list
                // before a click could land on it.
                onMouseDown={(event) => {
                  event.preventDefault()
                  choose(row.symbol)
                  if (row.exchange && row.exchange !== exchange) {
                    onChange({
                      symbol: row.symbol,
                      exchange: row.exchange,
                      product: productFor(row.exchange, product),
                    })
                  }
                }}
                className="flex w-full items-baseline gap-2 px-2 py-1 text-left text-[11px] hover:bg-accent"
              >
                <span className="font-medium">{row.symbol}</span>
                <span className="truncate text-[10px] text-muted-foreground">{row.name}</span>
                <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                  {row.exchange}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      <select
        className={cn(FIELD, 'font-mono')}
        aria-label="Exchange"
        value={exchange}
        onChange={(event) =>
          onChange({
            exchange: event.target.value,
            // A product the new venue does not take would be a form that looks
            // complete and an order the broker refuses.
            product: productFor(event.target.value, product),
          })
        }
      >
        {venues.map((one) => (
          <option key={one.value} value={one.value}>
            {one.label}
          </option>
        ))}
      </select>

      <select
        className={cn(FIELD, 'font-mono')}
        aria-label="Interval"
        value={interval}
        onChange={(event) => onChange({ interval: event.target.value })}
      >
        {offered.length === 0 && <option value={interval}>{interval || 'Interval'}</option>}
        {offered.map((one) => (
          <option key={one} value={one}>
            {one}
          </option>
        ))}
      </select>

      <select
        className={cn(FIELD, 'col-span-2 font-mono')}
        aria-label="Product"
        value={product}
        onChange={(event) => onChange({ product: event.target.value })}
      >
        {productsOn(exchange).map((one) => (
          <option key={one} value={one}>
            {one}
          </option>
        ))}
      </select>
    </div>
  )
}
