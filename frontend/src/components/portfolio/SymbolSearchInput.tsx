/**
 * Compact symbol search, the same pattern the scalping and websocket pages use.
 *
 * A plain text box makes the user remember exact tickers and offers no way to
 * find out they were wrong until the backtest fails with "no history". This
 * queries the instrument master as they type and returns a symbol that is
 * known to exist on the exchange they picked.
 */

import { useQuery } from '@tanstack/react-query'
import { useEffect, useId, useRef, useState } from 'react'
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
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([])
  const [activeIndex, setActiveIndex] = useState(-1)
  const listBoxId = useId()

  // Follow the value when the parent changes it (Distribute Equally, presets).
  useEffect(() => setQuery(value), [value])

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) {
        setOpen(false)
        setActiveIndex(-1)
      }
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
  const popupVisible = open && query.trim().length >= 2
  const visibleResults = results.slice(0, 25)
  const maxIndex = visibleResults.length - 1
  const listBoxVisible = popupVisible && visibleResults.length > 0
  const activeResult = activeIndex >= 0 ? visibleResults[activeIndex] : undefined

  // The list is capped and scrolls, so keyboard users must see the option that
  // Enter will pick.
  useEffect(() => {
    if (activeIndex < 0) return
    optionRefs.current[activeIndex]?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  const choose = (symbol: string) => {
    setQuery(symbol)
    onSelect(symbol)
    setOpen(false)
    setActiveIndex(-1)
  }

  return (
    <div ref={box} className={cn('relative', className)}>
      <Input
        value={query}
        placeholder={placeholder}
        onChange={(e) => {
          setQuery(e.target.value.toUpperCase())
          setOpen(true)
          setActiveIndex(-1)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          // Typing an exact ticker and pressing Enter should just work, without
          // waiting for the list.
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            setOpen(true)
            if (maxIndex < 0) return
            setActiveIndex((prev) => (prev >= maxIndex ? 0 : prev + 1))
          }
          if (e.key === 'ArrowUp') {
            e.preventDefault()
            setOpen(true)
            if (maxIndex < 0) return
            setActiveIndex((prev) => (prev <= 0 ? maxIndex : prev - 1))
          }
          if (e.key === 'Enter') {
            e.preventDefault()
            choose(activeResult?.symbol ?? query.trim().toUpperCase())
          }
          if (e.key === 'Escape') {
            setOpen(false)
            setActiveIndex(-1)
          }
        }}
        onBlur={() => {
          setOpen(false)
          setActiveIndex(-1)
          onSelect(query.trim().toUpperCase())
        }}
        role="combobox"
        aria-label={placeholder}
        aria-expanded={popupVisible}
        aria-controls={listBoxVisible ? listBoxId : undefined}
        aria-autocomplete="list"
        aria-haspopup="listbox"
        aria-activedescendant={
          listBoxVisible && activeIndex >= 0 ? `${listBoxId}-option-${activeIndex}` : undefined
        }
      />
      {popupVisible && (
        <div className="absolute z-50 mt-1 max-h-64 w-full overflow-y-auto rounded-md border bg-popover shadow-lg">
          {isFetching && results.length === 0 && (
            <div className="px-3 py-2 text-xs text-muted-foreground">Searching…</div>
          )}
          {!isFetching && results.length === 0 && (
            <output className="block px-3 py-2 text-xs text-muted-foreground">
              Nothing on {exchange} matching “{query}”
            </output>
          )}
          {listBoxVisible && (
            <div role="listbox" id={listBoxId}>
              {visibleResults.map((r, index) => (
                <button
                  type="button"
                  key={`${r.symbol}-${r.exchange}`}
                  ref={(el) => {
                    optionRefs.current[index] = el
                  }}
                  tabIndex={-1}
                  onMouseDown={(e) => {
                    // mousedown, not click: the input's blur would close the list
                    // before a click could land.
                    e.preventDefault()
                    choose(r.symbol)
                  }}
                  className={cn(
                    'flex w-full items-baseline gap-2 px-3 py-1.5 text-left text-sm hover:bg-accent',
                    activeIndex === index && 'bg-accent'
                  )}
                  role="option"
                  aria-selected={activeIndex === index}
                  id={`${listBoxId}-option-${index}`}
                >
                  <span className="font-medium">{r.symbol}</span>
                  <span className="truncate text-xs text-muted-foreground">{r.name}</span>
                  <span className="ml-auto text-[10px] text-muted-foreground">{r.exchange}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
