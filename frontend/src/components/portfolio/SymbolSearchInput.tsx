/**
 * Compact symbol search, the same pattern the scalping and websocket pages use.
 *
 * A plain text box makes the user remember exact tickers and offers no way to
 * find out they were wrong until the backtest fails with "no history". This
 * queries the instrument master as they type and returns a symbol that is
 * known to exist on the exchange they picked.
 */
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { chartinkApi } from '@/api/chartink'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

interface Props {
  value: string
  exchange: 'NSE' | 'BSE'
  onSelect(symbol: string): void
  placeholder?: string
  className?: string
}

export function SymbolSearchInput({
  value,
  exchange,
  onSelect,
  placeholder = 'Search symbol',
  className,
}: Props) {
  const [query, setQuery] = useState(value)
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  // Follow the value when the parent changes it (Distribute Equally, presets).
  useEffect(() => setQuery(value), [value])

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [open])

  // Two characters minimum: one letter matches most of the exchange and the
  // list is useless.
  const { data: results = [], isFetching } = useQuery({
    queryKey: ['portfolio', 'symsearch', exchange, query],
    queryFn: () => chartinkApi.searchSymbols(query.trim(), exchange),
    enabled: open && query.trim().length >= 2,
    staleTime: 60_000,
  })

  const choose = (symbol: string) => {
    setQuery(symbol)
    onSelect(symbol)
    setOpen(false)
  }

  return (
    <div ref={box} className={cn('relative', className)}>
      <Input
        value={query}
        placeholder={placeholder}
        onChange={(e) => {
          setQuery(e.target.value.toUpperCase())
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          // Typing an exact ticker and pressing Enter should just work, without
          // waiting for the list.
          if (e.key === 'Enter') {
            e.preventDefault()
            choose(query.trim().toUpperCase())
          }
          if (e.key === 'Escape') setOpen(false)
        }}
        onBlur={() => onSelect(query.trim().toUpperCase())}
      />
      {open && query.trim().length >= 2 && (
        <div className="absolute z-50 mt-1 max-h-64 w-full overflow-y-auto rounded-md border bg-popover shadow-lg">
          {isFetching && results.length === 0 && (
            <div className="px-3 py-2 text-xs text-muted-foreground">Searching…</div>
          )}
          {!isFetching && results.length === 0 && (
            <div className="px-3 py-2 text-xs text-muted-foreground">
              Nothing on {exchange} matching “{query}”
            </div>
          )}
          {results.slice(0, 25).map((r) => (
            <button
              type="button"
              key={`${r.symbol}-${r.exchange}`}
              onMouseDown={(e) => {
                // mousedown, not click: the input's blur would close the list
                // before a click could land.
                e.preventDefault()
                choose(r.symbol)
              }}
              className="flex w-full items-baseline gap-2 px-3 py-1.5 text-left text-sm hover:bg-accent"
            >
              <span className="font-medium">{r.symbol}</span>
              <span className="truncate text-xs text-muted-foreground">{r.name}</span>
              <span className="ml-auto text-[10px] text-muted-foreground">
                {r.exchange}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
