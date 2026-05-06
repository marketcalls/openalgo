/**
 * Debounced symbol-search input with a dropdown of suggestions.
 *
 * Backend: GET /search/api/search?q=<query>&exchange=<exchange>
 *   returns { results: [{ symbol, brsymbol, name, exchange, token, lotsize }], total }
 *
 * Used by the strategy v2 leg builder so users don't have to memorise
 * exact OpenAlgo symbol formats — same search experience as /tradingview
 * and the global Search page.
 *
 * Behaviour:
 *   - debounces 250ms after typing pauses
 *   - filters by exchange if `exchange` prop is set (limits noise on NSE+BSE
 *     vs full master contract DB)
 *   - selecting a row commits the OpenAlgo symbol back via onChange and hides
 *     the dropdown
 *   - clears the dropdown on outside click + on Escape
 *   - keyboard arrows (↑/↓) + Enter to commit highlighted row
 */
import { useEffect, useRef, useState } from 'react'

import { Input } from '@/components/ui/input'
import type { SymbolSearchResult } from '@/types/symbol'

interface Props {
  value: string
  onChange: (symbol: string) => void
  // Optional exchange filter (e.g. 'NSE'). When omitted, searches all exchanges.
  exchange?: string
  placeholder?: string
  disabled?: boolean
  // Optional callback invoked with the full row when a suggestion is picked.
  // Lets the parent capture the broker-specific lotsize, etc.
  onSelect?: (row: SymbolSearchResult) => void
}

export function SymbolSearchInput({
  value,
  onChange,
  exchange,
  placeholder = 'Search symbol…',
  disabled = false,
  onSelect,
}: Props) {
  const [results, setResults] = useState<SymbolSearchResult[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [highlight, setHighlight] = useState(0)
  const containerRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<number | null>(null)

  // Debounced search whenever `value` changes (and the input is focused).
  useEffect(() => {
    if (!open) return
    if (debounceRef.current) window.clearTimeout(debounceRef.current)
    if (!value || value.length < 1) {
      setResults([])
      return
    }
    debounceRef.current = window.setTimeout(async () => {
      setLoading(true)
      try {
        const params = new URLSearchParams({ q: value })
        if (exchange) params.append('exchange', exchange)
        const res = await fetch(`/search/api/search?${params.toString()}`, {
          credentials: 'include',
        })
        if (res.ok) {
          const data = await res.json()
          setResults(data.results ?? [])
          setHighlight(0)
        } else {
          setResults([])
        }
      } catch {
        setResults([])
      } finally {
        setLoading(false)
      }
    }, 250)
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current)
    }
  }, [value, exchange, open])

  // Close on outside click.
  useEffect(() => {
    const onDoc = (ev: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(ev.target as Node)
      ) {
        setOpen(false)
      }
    }
    if (open) document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const commit = (row: SymbolSearchResult) => {
    onChange(row.symbol)
    onSelect?.(row)
    setOpen(false)
  }

  return (
    <div ref={containerRef} className="relative">
      <Input
        value={value}
        onChange={(e) => {
          onChange(e.target.value.toUpperCase())
          if (!open) setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (!open) return
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            setHighlight((h) => Math.min(h + 1, results.length - 1))
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setHighlight((h) => Math.max(h - 1, 0))
          } else if (e.key === 'Enter' && results[highlight]) {
            e.preventDefault()
            commit(results[highlight])
          } else if (e.key === 'Escape') {
            setOpen(false)
          }
        }}
        placeholder={placeholder}
        disabled={disabled}
        autoComplete="off"
      />
      {open && (results.length > 0 || loading) && (
        <div className="absolute z-50 left-0 right-0 mt-1 max-h-72 overflow-y-auto rounded-md border bg-popover text-popover-foreground shadow-md">
          {loading && (
            <div className="px-3 py-2 text-xs text-muted-foreground">
              Searching…
            </div>
          )}
          {!loading &&
            results.map((row, idx) => (
              <button
                key={`${row.exchange}:${row.symbol}:${row.token}`}
                type="button"
                className={`w-full text-left px-3 py-2 text-sm border-b last:border-b-0 ${
                  idx === highlight
                    ? 'bg-accent text-accent-foreground'
                    : 'hover:bg-accent/50'
                }`}
                onMouseEnter={() => setHighlight(idx)}
                onMouseDown={(e) => {
                  // Use mousedown so the click fires before the input blurs
                  // and re-renders the dropdown closed.
                  e.preventDefault()
                  commit(row)
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono">{row.symbol}</span>
                  <span className="text-xs text-muted-foreground">
                    {row.exchange}
                  </span>
                </div>
                <div className="text-xs text-muted-foreground truncate">
                  {row.name}
                </div>
              </button>
            ))}
        </div>
      )}
    </div>
  )
}
