import { Search } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { useSupportedExchanges } from '@/hooks/useSupportedExchanges'
import type { SearchRow } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'

/**
 * TradingView / Upstox-style symbol search modal for the /trading page.
 *
 * Searches broker-supported symbols (the master-contract cache is already
 * broker-scoped), groups them into segment chips derived from the broker's
 * supported exchanges, and returns the picked row to the caller. One instance
 * per chart pane, so it works unchanged in every grid layout.
 */

type Category = 'Cash' | 'F&O' | 'Currency' | 'Commodity' | 'Crypto'
type Chip = 'ALL' | Category

/** Map an OpenAlgo exchange code to its trading segment (chip). */
const EXCHANGE_CATEGORY: Record<string, Category> = {
  NSE: 'Cash',
  BSE: 'Cash',
  NSE_INDEX: 'Cash',
  BSE_INDEX: 'Cash',
  GLOBAL_INDEX: 'Cash',
  NFO: 'F&O',
  BFO: 'F&O',
  CDS: 'Currency',
  BCD: 'Currency',
  CDS_INDEX: 'Currency',
  MCX: 'Commodity',
  NCDEX: 'Commodity',
  NCO: 'Commodity',
  MCX_INDEX: 'Commodity',
  CRYPTO: 'Crypto',
}

const CHIP_ORDER: Category[] = ['Cash', 'F&O', 'Currency', 'Commodity', 'Crypto']

function categoryOf(exchange: string): Category {
  return EXCHANGE_CATEGORY[exchange] ?? 'Cash'
}

/** Segment display order — Cash (equity + index) first, then F&O, etc. */
const CATEGORY_RANK: Record<Category, number> = {
  Cash: 0,
  'F&O': 1,
  Currency: 2,
  Commodity: 3,
  Crypto: 4,
}

/**
 * Within-segment exchange order: cash equities (NSE, BSE) rank above their
 * indices (NSE_INDEX, BSE_INDEX), and each derivatives segment lists its primary
 * exchange first. The backend returns matches in cache-insertion order with no
 * relevance ranking, so this ordering happens entirely client-side.
 */
const EXCHANGE_RANK: Record<string, number> = {
  NSE: 0,
  BSE: 1,
  NSE_INDEX: 2,
  BSE_INDEX: 3,
  GLOBAL_INDEX: 4,
  NFO: 0,
  BFO: 1,
  CDS: 0,
  BCD: 1,
  CDS_INDEX: 2,
  MCX: 0,
  NCDEX: 1,
  NCO: 2,
  MCX_INDEX: 3,
  CRYPTO: 0,
}

/** 0 = exact symbol match, 1 = prefix, 2 = substring, 3 = matched on name only. */
function matchScore(symbol: string, q: string): number {
  if (!q) return 3
  const s = symbol.toUpperCase()
  if (s === q) return 0
  if (s.startsWith(q)) return 1
  if (s.includes(q)) return 2
  return 3
}

/** Rank rows so Cash (NSE/BSE, then indices) surfaces above F&O/Currency/Commodity. */
function compareRows(a: SearchRow, b: SearchRow, q: string): number {
  const exA = String(a.exchange)
  const exB = String(b.exchange)
  const catDiff = CATEGORY_RANK[categoryOf(exA)] - CATEGORY_RANK[categoryOf(exB)]
  if (catDiff) return catDiff
  const scoreDiff = matchScore(String(a.symbol), q) - matchScore(String(b.symbol), q)
  if (scoreDiff) return scoreDiff
  const exDiff = (EXCHANGE_RANK[exA] ?? 9) - (EXCHANGE_RANK[exB] ?? 9)
  if (exDiff) return exDiff
  const lenDiff = String(a.symbol).length - String(b.symbol).length
  if (lenDiff) return lenDiff
  return String(a.symbol).localeCompare(String(b.symbol))
}

/** Cap on rendered rows after ranking (the most relevant are already on top). */
const MAX_ROWS = 150

/** Short instrument-type badge (INDEX / FUT / CE / PE / EQ). */
function typeBadge(row: SearchRow): string {
  const ex = String(row.exchange)
  if (ex.endsWith('_INDEX')) return 'INDEX'
  const s = String(row.symbol).toUpperCase()
  if (s.endsWith('CE')) return 'CE'
  if (s.endsWith('PE')) return 'PE'
  if (s.endsWith('FUT')) return 'FUT'
  const it = String(row.instrumenttype ?? '').toUpperCase()
  return it && it !== 'EQ' ? it : 'EQ'
}

/** Highlight the matched query substring inside a description. */
function Highlight({ text, q }: { text: string; q: string }) {
  if (!q) return <>{text}</>
  const i = text.toLowerCase().indexOf(q.toLowerCase())
  if (i < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, i)}
      <span className="font-semibold text-primary">{text.slice(i, i + q.length)}</span>
      {text.slice(i + q.length)}
    </>
  )
}

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Bound to the pane terminal's search; returns broker-supported symbols. */
  search: (query: string, exchange?: string, limit?: number) => Promise<SearchRow[]>
  onPick: (row: SearchRow) => void
  /** Seeds the input (usually the pane's current symbol) and is text-selected on open. */
  initialQuery?: string
}

export function SymbolSearchDialog({ open, onOpenChange, search, onPick, initialQuery }: Props) {
  const { allExchanges } = useSupportedExchanges()
  const [query, setQuery] = useState('')
  const [rows, setRows] = useState<SearchRow[]>([])
  const [chip, setChip] = useState<Chip>('ALL')
  const [sel, setSel] = useState(0)
  const [loading, setLoading] = useState(false)

  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const reqIdRef = useRef(0)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Chips = ALL + only the segments the broker actually supports.
  const chips = useMemo<Chip[]>(() => {
    const present = new Set<Category>()
    for (const e of allExchanges) present.add(categoryOf(e.value))
    return ['ALL', ...CHIP_ORDER.filter((c) => present.has(c))]
  }, [allExchanges])

  const filtered = useMemo(() => {
    const q = query.trim().toUpperCase()
    const base = chip === 'ALL' ? rows : rows.filter((r) => categoryOf(String(r.exchange)) === chip)
    return [...base].sort((a, b) => compareRows(a, b, q)).slice(0, MAX_ROWS)
  }, [rows, chip, query])

  // On open: seed query with the current symbol, select it, focus, reset chip.
  useEffect(() => {
    if (!open) return
    setChip('ALL')
    setSel(0)
    setQuery(initialQuery ?? '')
    const t = setTimeout(() => {
      inputRef.current?.focus()
      inputRef.current?.select()
    }, 30)
    return () => clearTimeout(t)
  }, [open, initialQuery])

  // Debounced search; a request id guards against out-of-order responses.
  useEffect(() => {
    if (!open) return
    const q = query.trim()
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (q.length < 1) {
      setRows([])
      setLoading(false)
      return
    }
    setLoading(true)
    const id = ++reqIdRef.current
    debounceRef.current = setTimeout(async () => {
      // Fetch the full match set (the backend caps at 500) so Cash/index rows are
      // present before client-side ranking floats them to the top.
      const res = await search(q, undefined, 500)
      if (id !== reqIdRef.current) return // a newer keystroke won
      setRows(res)
      setSel(0)
      setLoading(false)
    }, 180)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query, open, search])

  // Keep the keyboard selection within bounds and scrolled into view.
  useEffect(() => {
    if (sel >= filtered.length) setSel(filtered.length ? filtered.length - 1 : 0)
  }, [filtered, sel])
  useEffect(() => {
    listRef.current?.querySelector(`[data-idx="${sel}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [sel])

  const pick = (row: SearchRow) => {
    onPick(row)
    onOpenChange(false)
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSel((s) => Math.min(s + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSel((s) => Math.max(s - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const row = filtered[sel]
      if (row) pick(row)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="flex max-h-[80vh] w-full flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl"
        onOpenAutoFocus={(e) => e.preventDefault()}
      >
        <DialogTitle className="px-5 pt-5 pb-3 text-xl">Symbol Search</DialogTitle>

        {/* Search input */}
        <div className="flex items-center gap-2 border-y px-5 py-3">
          <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search symbol…"
            className="w-full bg-transparent text-base outline-none placeholder:text-muted-foreground"
            aria-label="Search symbol"
          />
        </div>

        {/* Segment chips (broker-supported only) */}
        <div className="flex flex-wrap gap-2 px-5 py-3">
          {chips.map((c) => (
            <button
              type="button"
              key={c}
              onClick={() => setChip(c)}
              className={cn(
                'rounded-full px-3 py-1 text-xs font-medium transition-colors',
                c === chip
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:bg-muted/70'
              )}
            >
              {c}
            </button>
          ))}
        </div>

        {/* Column headers */}
        <div className="grid grid-cols-[1fr_1fr_auto] gap-3 border-b px-5 py-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          <span>Symbol</span>
          <span>Description</span>
          <span className="text-right">Exchange</span>
        </div>

        {/* Results */}
        <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto">
          {filtered.length === 0 ? (
            <div className="px-5 py-10 text-center text-sm text-muted-foreground">
              {loading
                ? 'Searching…'
                : query.trim().length < 1
                  ? 'Type to search symbols'
                  : 'No matching symbols'}
            </div>
          ) : (
            filtered.map((r, i) => (
              <button
                type="button"
                key={`${r.symbol}:${r.exchange}`}
                data-idx={i}
                onClick={() => pick(r)}
                onMouseEnter={() => setSel(i)}
                className={cn(
                  'grid w-full grid-cols-[1fr_1fr_auto] items-center gap-3 px-5 py-2.5 text-left',
                  i === sel ? 'bg-accent' : 'hover:bg-accent/50'
                )}
              >
                <span className="truncate text-sm font-medium">{r.symbol}</span>
                <span className="truncate text-sm text-muted-foreground">
                  <Highlight text={r.name || ''} q={query.trim()} />
                </span>
                <span className="flex items-center justify-end gap-2 text-xs">
                  <span className="text-[10px] font-medium uppercase text-muted-foreground">
                    {typeBadge(r)}
                  </span>
                  <span className="font-medium text-foreground">{String(r.exchange)}</span>
                </span>
              </button>
            ))
          )}
        </div>

        <div className="border-t px-5 py-2.5 text-center text-xs text-muted-foreground">
          Start typing to search, then press Enter to load the highlighted symbol.
        </div>
      </DialogContent>
    </Dialog>
  )
}
