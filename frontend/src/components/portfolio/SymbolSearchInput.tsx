/**
 * Compact symbol search, the same pattern the scalping and websocket pages use.
 *
 * A plain text box makes the user remember exact tickers and offers no way to
 * find out they were wrong until the backtest fails with "no history". This
 * queries the instrument master as they type and returns a symbol that is
 * known to exist on the exchange they picked.
 */
import { useEffect, useId, useRef, useState } from 'react'
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
  // Index of the keyboard-highlighted suggestion; -1 = none, so Enter keeps
  // accepting the typed ticker.
  const [active, setActive] = useState(-1)
  const box = useRef<HTMLDivElement>(null)
  const listId = useId()

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

  const options = results.slice(0, 25)
  const listOpen = open && query.trim().length >= 2

  // Typing resets the highlight; a shorter result set can still leave it past the end.
  const current = active < options.length ? active : -1

  // Keep the highlighted option visible in the scrolling list.
  useEffect(() => {
    if (current >= 0)
      document.getElementById(`${listId}-${current}`)?.scrollIntoView?.({ block: 'nearest' })
  }, [current, listId])

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
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={listOpen}
        aria-controls={listId}
        aria-activedescendant={listOpen && current >= 0 ? `${listId}-${current}` : undefined}
        onChange={(e) => {
          setQuery(e.target.value.toUpperCase())
          setOpen(true)
          setActive(-1)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault()
            setOpen(true)
            if (options.length === 0) return
            const step = e.key === 'ArrowDown' ? 1 : -1
            setActive(
              current < 0 && step < 0
                ? options.length - 1
                : (current + step + options.length) % options.length
            )
          }
          // Typing an exact ticker and pressing Enter should just work, without
          // waiting for the list; a highlighted suggestion wins when there is one.
          if (e.key === 'Enter') {
            e.preventDefault()
            choose(listOpen && current >= 0 ? options[current].symbol : query.trim().toUpperCase())
          }
          if (e.key === 'Escape') {
            setOpen(false)
            setActive(-1)
          }
        }}
        onBlur={() => onSelect(query.trim().toUpperCase())}
      />
      {listOpen && (
        <div
          id={listId}
          role="listbox"
          className="absolute z-50 mt-1 max-h-64 w-full overflow-y-auto rounded-md border bg-popover shadow-lg"
        >
          {isFetching && results.length === 0 && (
            <div className="px-3 py-2 text-xs text-muted-foreground">Searching…</div>
          )}
          {!isFetching && results.length === 0 && (
            <div className="px-3 py-2 text-xs text-muted-foreground">
              Nothing on {exchange} matching “{query}”
            </div>
          )}
          {options.map((r, i) => (
            <button
              type="button"
              key={`${r.symbol}-${r.exchange}`}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === current}
              tabIndex={-1}
              onMouseDown={(e) => {
                // mousedown, not click: the input's blur would close the list
                // before a click could land.
                e.preventDefault()
                choose(r.symbol)
              }}
              className={cn(
                'flex w-full items-baseline gap-2 px-3 py-1.5 text-left text-sm hover:bg-accent',
                i === current && 'bg-accent'
              )}
            >
              <span className="font-medium">{r.symbol}</span>
              <span className="truncate text-xs text-muted-foreground">{r.name}</span>
              <span className="ml-auto text-[10px] text-muted-foreground">{r.exchange}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
