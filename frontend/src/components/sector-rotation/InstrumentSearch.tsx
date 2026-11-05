/**
 * Find a stock or index in the master contract and add it to the rotation map.
 *
 * Same search the TradingView configuration page uses (`/search/api/search`),
 * narrowed to the exchanges the map can place: cash equity and indices.
 */

import { Plus } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

export interface SearchHit {
  symbol: string
  name: string
  exchange: string
}

const EXCHANGE_LABELS: Record<string, string> = {
  NSE: 'NSE Equity',
  BSE: 'BSE Equity',
  NSE_INDEX: 'NSE Index',
  BSE_INDEX: 'BSE Index',
  MCX_INDEX: 'MCX Index',
  GLOBAL_INDEX: 'Global Index',
}

export function InstrumentSearch({
  exchanges,
  isOnMap,
  onAdd,
  disabled,
}: {
  exchanges: string[]
  isOnMap: (hit: SearchHit) => boolean
  onAdd: (hit: SearchHit) => void
  disabled?: boolean
}) {
  const [query, setQuery] = useState('')
  const [exchange, setExchange] = useState('NSE')
  const [results, setResults] = useState<SearchHit[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)
  // Only the newest search may write results: a slow answer for "REL" must not
  // replace the one for "RELI" that came back first.
  const latestSearch = useRef(0)

  const search = useCallback(
    async (q: string) => {
      const ticket = ++latestSearch.current
      setLoading(true)
      try {
        const params = new URLSearchParams({ q, exchange })
        const response = await fetch(`/search/api/search?${params}`, {
          credentials: 'include',
        })
        const data = await response.json()
        if (ticket !== latestSearch.current) return
        const hits: SearchHit[] = (data.results || []).filter((r: SearchHit) =>
          exchanges.includes(r.exchange)
        )
        setResults(hits.slice(0, 10))
        setOpen(true)
      } catch {
        if (ticket === latestSearch.current) setResults([])
      } finally {
        if (ticket === latestSearch.current) setLoading(false)
      }
    },
    [exchange, exchanges]
  )

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults([])
      setOpen(false)
      return
    }
    const timer = setTimeout(() => search(query.trim()), 300)
    return () => clearTimeout(timer)
  }, [query, search])

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('click', onClick)
    return () => document.removeEventListener('click', onClick)
  }, [])

  const pick = (hit: SearchHit) => {
    if (isOnMap(hit)) return
    onAdd(hit)
    setQuery('')
    setOpen(false)
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select value={exchange} onValueChange={setExchange}>
        <SelectTrigger className="w-36" aria-label="Search exchange">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {exchanges.map((ex) => (
            <SelectItem key={ex} value={ex}>
              {EXCHANGE_LABELS[ex] ?? ex}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <div className="relative min-w-56 flex-1" ref={wrapperRef}>
        <Input
          type="text"
          placeholder={disabled ? 'The map is full' : 'Search a stock or index to add...'}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results.length > 0 && setOpen(true)}
          autoComplete="off"
          disabled={disabled}
          aria-label="Search symbol"
        />
        {loading && (
          <div className="absolute top-1/2 right-3 -translate-y-1/2">
            <div className="h-4 w-4 animate-spin rounded-full border-b-2 border-primary" />
          </div>
        )}
        {open && (
          <div className="absolute z-50 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border bg-background shadow-lg">
            {results.length === 0 ? (
              <div className="p-3 text-sm text-muted-foreground">
                No match on {EXCHANGE_LABELS[exchange] ?? exchange}.
              </div>
            ) : (
              results.map((hit) => {
                const added = isOnMap(hit)
                return (
                  <button
                    type="button"
                    key={`${hit.exchange}:${hit.symbol}`}
                    disabled={added}
                    onClick={() => pick(hit)}
                    className="flex w-full items-center justify-between gap-3 border-b p-3 text-left last:border-b-0 hover:bg-muted disabled:cursor-default disabled:opacity-50"
                  >
                    <div className="min-w-0">
                      <div className="font-medium">{hit.symbol}</div>
                      <div className="truncate text-xs text-muted-foreground">{hit.name}</div>
                    </div>
                    <span className="flex shrink-0 items-center gap-2">
                      <span className="rounded bg-primary px-2 py-1 text-xs text-primary-foreground">
                        {hit.exchange}
                      </span>
                      {added ? (
                        <span className="text-xs text-muted-foreground">On map</span>
                      ) : (
                        <Plus className="size-4 text-muted-foreground" />
                      )}
                    </span>
                  </button>
                )
              })
            )}
          </div>
        )}
      </div>
    </div>
  )
}
