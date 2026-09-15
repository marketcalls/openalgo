import { Search } from 'lucide-react'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { useSupportedExchanges } from '@/hooks/useSupportedExchanges'
import type { SearchRow } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'
import { isPlainSymbol, parseExpression } from 'openalgo-charts/transform'

/**
 * The operator keypad, in the order it is drawn. `1/` wraps the whole box
 * rather than splicing at the caret, because a reciprocal of part of an
 * expression is almost never what was meant.
 */
const OPERATORS = [
  { label: '÷', insert: '/', title: 'Divide' },
  { label: '−', insert: '-', title: 'Subtract' },
  { label: '+', insert: '+', title: 'Add' },
  { label: '×', insert: '*', title: 'Multiply' },
  { label: '^', insert: '^', title: 'Exponentiation' },
  { label: '1/', insert: '1/', title: 'Reciprocal' },
] as const

/**
 * Is the box holding arithmetic over instruments rather than one symbol?
 *
 * A parse failure answers no. A half-typed `NIFTY/` arrives on every keystroke,
 * and the ordinary search below already says when a symbol is unknown.
 */
/** Characters that end one leg and begin the next. */
const OPERATOR = /[+\-*/^(),÷×−]/

/**
 * The leg the caret is in, and everything before it.
 *
 * The result list has to search THIS, not the whole box. Searching the whole
 * string meant that the moment an operator was typed the query stopped matching
 * any instrument, the list went empty, and there was no way to look up the
 * second leg: you had to know its exact name already.
 */
function splitLeg(query: string): { prefix: string; leg: string } {
  for (let i = query.length - 1; i >= 0; i--) {
    if (OPERATOR.test(query[i])) {
      return { prefix: query.slice(0, i + 1), leg: query.slice(i + 1) }
    }
  }
  return { prefix: '', leg: query }
}

function isExpression(text: string): boolean {
  const q = text.trim()
  if (q === '' || isPlainSymbol(q)) return false
  try {
    parseExpression(q)
    return true
  } catch {
    return false
  }
}

/**
 * Symbol search modal for the /trading page.
 *
 * Searches broker-supported symbols (the master-contract cache is already
 * broker-scoped), groups them into segment chips derived from the broker's
 * supported exchanges, and returns the picked row to the caller. One instance
 * per chart pane, so it works unchanged in every grid layout.
 */

type Category = 'Index' | 'Cash' | 'F&O' | 'Currency' | 'Commodity' | 'Crypto'
type Chip = 'ALL' | Category

/** Map an OpenAlgo exchange code to its trading segment (chip). Any exchange
 * ending in _INDEX (NSE_INDEX, BSE_INDEX, GLOBAL_INDEX, MCX_INDEX, CDS_INDEX)
 * is routed to 'Index' below, not listed here. */
const EXCHANGE_CATEGORY: Record<string, Category> = {
  NSE: 'Cash',
  BSE: 'Cash',
  NFO: 'F&O',
  BFO: 'F&O',
  CDS: 'Currency',
  BCD: 'Currency',
  MCX: 'Commodity',
  NCDEX: 'Commodity',
  NCO: 'Commodity',
  CRYPTO: 'Crypto',
}

const CHIP_ORDER: Category[] = ['Index', 'Cash', 'F&O', 'Currency', 'Commodity', 'Crypto']

function categoryOf(exchange: string): Category {
  if (exchange.endsWith('_INDEX')) return 'Index'
  return EXCHANGE_CATEGORY[exchange] ?? 'Cash'
}

/**
 * Segment display and ALL-view priority order. Index ranks first: a benchmark
 * index (NIFTY, BANKNIFTY, SENSEX, ...) is almost always what someone charting
 * "NIFTY" wants, not an ETF or scheme that happens to share the prefix.
 */
const CATEGORY_RANK: Record<Category, number> = {
  Index: 0,
  Cash: 1,
  'F&O': 2,
  Currency: 3,
  Commodity: 4,
  Crypto: 5,
}

/**
 * Within-segment exchange order. Equity indices (NSE_INDEX, BSE_INDEX) rank
 * above global and sector indices, and each derivatives segment lists its
 * primary exchange first. The backend (BrokerSymbolCache.search_symbols)
 * already ranks matches by relevance before this component ever sees them —
 * this is a finer-grained tiebreaker on top of that for rows the backend
 * scored equally.
 */
const EXCHANGE_RANK: Record<string, number> = {
  NSE_INDEX: 0,
  BSE_INDEX: 1,
  GLOBAL_INDEX: 2,
  MCX_INDEX: 3,
  CDS_INDEX: 4,
  NSE: 0,
  BSE: 1,
  NFO: 0,
  BFO: 1,
  CDS: 0,
  BCD: 1,
  MCX: 0,
  NCDEX: 1,
  NCO: 2,
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

/** Rank rows so Index surfaces above Cash, which surfaces above F&O/Currency/Commodity. */
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
  /**
   * Where the caret belongs after the next render.
   *
   * Writing the box also changes the leg being searched, which re-renders, and
   * a `requestAnimationFrame` restore raced that: typing could resume before
   * the caret moved and lose its first character. A layout effect runs after
   * every render and before paint, so there is no window to race.
   */
  const caretRef = useRef<number | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Chips = ALL + only the segments the broker actually supports.
  const chips = useMemo<Chip[]>(() => {
    const present = new Set<Category>()
    for (const e of allExchanges) present.add(categoryOf(e.value))
    return ['ALL', ...CHIP_ORDER.filter((c) => present.has(c))]
  }, [allExchanges])

  const expression = useMemo(() => isExpression(query), [query])
  const { prefix, leg } = useMemo(() => splitLeg(query), [query])

  const filtered = useMemo(() => {
    const q = leg.trim().toUpperCase()
    const base = chip === 'ALL' ? rows : rows.filter((r) => categoryOf(String(r.exchange)) === chip)
    return [...base].sort((a, b) => compareRows(a, b, q)).slice(0, MAX_ROWS)
  }, [rows, chip, leg])

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
    // The leg being typed, not the whole box: mid-expression the box is not a
    // symbol and would match nothing.
    const q = leg.trim()
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
  }, [leg, open, search])

  useLayoutEffect(() => {
    if (caretRef.current === null) return
    const node = inputRef.current
    if (node) {
      node.focus()
      node.setSelectionRange(caretRef.current, caretRef.current)
    }
    caretRef.current = null
  })

  // Keep the keyboard selection within bounds and scrolled into view.
  useEffect(() => {
    if (sel >= filtered.length) setSel(filtered.length ? filtered.length - 1 : 0)
  }, [filtered, sel])
  useEffect(() => {
    listRef.current?.querySelector(`[data-idx="${sel}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [sel])

  /** Load this and close. The only path that leaves the dialog. */
  const pick = (row: SearchRow) => {
    onPick(row)
    onOpenChange(false)
  }

  /**
   * What clicking a result row does.
   *
   * Mid-expression it completes the leg and stays open, because the user is
   * still building; otherwise it loads that instrument. The exchange is written
   * in so a leg is never ambiguous: `NFO:NIFTY...CE` and `NSE:RELIANCE` resolve
   * without inheriting whatever the pane happens to be showing.
   */
  const chooseRow = (row: SearchRow) => {
    if (prefix === '') {
      pick(row)
      return
    }
    const next = `${prefix}${row.exchange}:${row.symbol}`
    setQuery(next)
    caretRef.current = next.length
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
      // Arithmetic wins over the result list: the rows below are matches for
      // the last leg the user typed, and loading one of those would silently
      // discard the expression they built.
      if (expression) {
        pick({ symbol: query.trim(), exchange: '', name: 'Computed chart', expression: true })
        return
      }
      const row = filtered[sel]
      if (row) chooseRow(row)
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
            placeholder="Search symbol, or build an expression…"
            className="w-full bg-transparent text-base outline-none placeholder:text-muted-foreground"
            aria-label="Search symbol"
          />
          {/* Each key carries its own label, so the row needs no group role of its
              own: a wrapper role here would only add a landmark with nothing to say. */}
          <div className="flex shrink-0 items-center gap-0.5">
            {OPERATORS.map((op) => (
              <button
                type="button"
                key={op.insert}
                title={op.title}
                aria-label={op.title}
                // `mousedown`, not `click`: the field must not lose focus first,
                // or the caret position being written to is already gone.
                onMouseDown={(e) => {
                  e.preventDefault()
                  const node = inputRef.current
                  if (!node) return
                  const start = node.selectionStart ?? query.length
                  const end = node.selectionEnd ?? start
                  const next =
                    op.insert === '1/'
                      ? `1/(${query.trim()})`
                      : query.slice(0, start) + op.insert + query.slice(end)
                  setQuery(next)
                  caretRef.current = op.insert === '1/' ? next.length : start + op.insert.length
                }}
                className="flex h-6 w-6 items-center justify-center rounded text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                {op.label}
              </button>
            ))}
          </div>
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
                onClick={() => chooseRow(r)}
                onMouseEnter={() => setSel(i)}
                className={cn(
                  'grid w-full grid-cols-[1fr_1fr_auto] items-center gap-3 px-5 py-2.5 text-left',
                  i === sel ? 'bg-accent' : 'hover:bg-accent/50'
                )}
              >
                <span className="truncate text-sm font-medium">{r.symbol}</span>
                <span className="truncate text-sm text-muted-foreground">
                  <Highlight text={r.name || ''} q={leg.trim()} />
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
          {expression ? (
            <>
              Press Enter to chart{' '}
              <span className="font-medium text-foreground">{query.trim()}</span>. A computed
              chart cannot be traded.
            </>
          ) : (
            'Start typing to search, then press Enter to load the highlighted symbol. Operators build an expression.'
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
