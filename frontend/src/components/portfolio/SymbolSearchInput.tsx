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
  const [activeIndex, setActiveIndex] = useState(-1)
  const [previousExchange, setPreviousExchange] = useState(exchange)

  if (previousExchange !== exchange) {
    setPreviousExchange(exchange)
    setActiveIndex(-1)
  }

  const optionRefs = useRef<(HTMLButtonElement | null)[]>([])
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (activeIndex < 0) return

    optionRefs.current[activeIndex]?.scrollIntoView({
      block: 'nearest',
    })
  }, [activeIndex])

  const listboxId = useId()

  // Follow the value when the parent changes it (Distribute Equally, presets).
  useEffect(() => {
    setQuery(value)
    setActiveIndex(-1)
  }, [value])

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
  const isListboxOpen = open && query.trim().length >= 2 && results.length > 0
  const suggestions = results.slice(0, 25)

  const choose = (symbol: string) => {
    setQuery(symbol)
    onSelect(symbol)
    setOpen(false)
    setActiveIndex(-1)
  }
  return (
    <div ref={box} className={cn('relative', className)}>
      <Input
        role="combobox"
        aria-autocomplete="list"
        aria-haspopup="listbox"
        aria-expanded={isListboxOpen}
        aria-controls={isListboxOpen ? listboxId : undefined}
        aria-activedescendant={
          open && activeIndex >= 0 ? `${listboxId}-option-${activeIndex}` : undefined
        }
        value={query}
        placeholder={placeholder}
        onChange={(e) => {
          setQuery(e.target.value.toUpperCase())
          setActiveIndex(-1)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            if (suggestions.length === 0) return

            setOpen(true)
            setActiveIndex((current) => (current >= suggestions.length - 1 ? 0 : current + 1))
          }

          if (e.key === 'ArrowUp') {
            e.preventDefault()
            if (suggestions.length === 0) return

            setOpen(true)
            setActiveIndex((current) => (current <= 0 ? suggestions.length - 1 : current - 1))
          }

          if (e.key === 'Enter') {
            e.preventDefault()

            if (activeIndex >= 0 && suggestions[activeIndex]) {
              choose(suggestions[activeIndex].symbol)
            } else {
              // Preserve the existing behaviour for an exact ticker typed manually.
              choose(query.trim().toUpperCase())
            }
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
      />
      {open &&
        query.trim().length >= 2 &&
        (results.length === 0 ? (
          <div
            aria-live="polite"
            className="absolute z-50 mt-1 w-full rounded-md border bg-popover px-3 py-2 text-xs text-muted-foreground shadow-lg"
          >
            {isFetching ? 'Searching…' : `Nothing on ${exchange} matching “${query}”`}
          </div>
        ) : (
          <div
            id={listboxId}
            role="listbox"
            className="absolute z-50 mt-1 max-h-64 w-full overflow-y-auto rounded-md border bg-popover shadow-lg"
          >
            {suggestions.map((r, index) => (
              <button
                ref={(element) => {
                  optionRefs.current[index] = element
                }}
                type="button"
                role="option"
                tabIndex={-1}
                id={`${listboxId}-option-${index}`}
                aria-selected={activeIndex === index}
                key={`${r.symbol}-${r.exchange}`}
                onMouseDown={(e) => {
                  e.preventDefault()
                  choose(r.symbol)
                }}
                className={cn(
                  'flex w-full items-baseline gap-2 px-3 py-1.5 text-left text-sm hover:bg-accent',
                  activeIndex === index && 'bg-accent'
                )}
              >
                <span className="font-medium">{r.symbol}</span>
                <span className="truncate text-xs text-muted-foreground">{r.name}</span>
                <span className="ml-auto text-[10px] text-muted-foreground">{r.exchange}</span>
              </button>
            ))}
          </div>
        ))}
    </div>
  )
}
