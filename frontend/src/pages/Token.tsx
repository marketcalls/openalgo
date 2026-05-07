import { Check, ChevronDown, History, Info, Search, Trash2, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useSupportedExchanges } from '@/hooks/useSupportedExchanges'

interface SearchResult {
  symbol: string
  name: string
  exchange: string
  token: string
  expiry?: string
  strike?: number
}

interface SearchHistoryEntry {
  symbol: string
  // Comma-joined for backwards compat with older entries that used a single string
  exchange: string
  underlying?: string
  expiry?: string
  // Comma-joined ("FUT", "FUT,CE")
  instrumentType?: string
  strikeMin?: string
  strikeMax?: string
  ts: number
}

const HISTORY_KEY = 'openalgo:search-history'
const HISTORY_MAX = 10

function loadHistory(): SearchHistoryEntry[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.slice(0, HISTORY_MAX)
  } catch {
    return []
  }
}

function saveHistory(entries: SearchHistoryEntry[]): void {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, HISTORY_MAX)))
  } catch {
    // ignore quota / privacy errors
  }
}

function historyKey(e: SearchHistoryEntry): string {
  return [
    e.symbol,
    e.exchange,
    e.underlying || '',
    e.expiry || '',
    e.instrumentType || '',
    e.strikeMin || '',
    e.strikeMax || '',
  ].join('|')
}

function formatHistoryLabel(e: SearchHistoryEntry): string {
  const parts: string[] = []
  if (e.symbol) parts.push(e.symbol)
  if (e.exchange) parts.push(e.exchange)
  const filters: string[] = []
  if (e.underlying) filters.push(e.underlying)
  if (e.instrumentType) filters.push(e.instrumentType)
  if (e.expiry) filters.push(e.expiry)
  if (e.strikeMin || e.strikeMax) filters.push(`${e.strikeMin || '*'}-${e.strikeMax || '*'}`)
  if (filters.length) parts.push(`[${filters.join(' ')}]`)
  return parts.join(' · ') || '(empty)'
}

// EXCHANGES and FNO_EXCHANGES are now dynamic — provided by useSupportedExchanges() hook

export default function Token() {
  const { allExchanges, fnoExchanges, isCrypto } = useSupportedExchanges()
  const navigate = useNavigate()
  const [symbol, setSymbol] = useState('')
  const [exchanges, setExchanges] = useState<string[]>([])
  const [underlying, setUnderlying] = useState('')
  const [instrumentTypes, setInstrumentTypes] = useState<string[]>([])
  const [expiry, setExpiry] = useState('')
  const [strikeMin, setStrikeMin] = useState('')
  const [strikeMax, setStrikeMax] = useState('')

  const [underlyings, setUnderlyings] = useState<string[]>([])
  const [expiries, setExpiries] = useState<string[]>([])
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [showResults, setShowResults] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [isFnoLoading, setIsFnoLoading] = useState(false)
  const [symbolError, setSymbolError] = useState('')
  const [history, setHistory] = useState<SearchHistoryEntry[]>(() => loadHistory())

  // Refs for click-outside handling and request tracking
  const inputWrapperRef = useRef<HTMLDivElement>(null)
  const fnoRequestIdRef = useRef(0)

  // FNO filter section is enabled only when a SINGLE exchange is selected and
  // it's an F&O exchange. Multi-exchange selections suppress these filters
  // because expiries/underlyings are exchange-specific.
  const exchange = exchanges.length === 1 ? exchanges[0] : ''
  const isFnoExchange = exchanges.length === 1 && fnoExchanges.some((ex) => ex.value === exchange)
  const exchangeCsv = exchanges.join(',')
  const instrumentTypeCsv = instrumentTypes.join(',')

  const toggleExchange = (value: string) => {
    setExchanges((prev) =>
      prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value]
    )
  }

  const toggleInstrumentType = (value: string) => {
    setInstrumentTypes((prev) =>
      prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value]
    )
  }

  const resetFnoFilters = useCallback(() => {
    setUnderlying('')
    setInstrumentTypes([])
    setExpiry('')
    setStrikeMin('')
    setStrikeMax('')
  }, [])

  // Fetch underlyings when exchange changes to FNO
  useEffect(() => {
    if (!isFnoExchange) {
      setUnderlyings([])
      setExpiries([])
      resetFnoFilters()
      return
    }

    // Increment request ID to invalidate stale responses
    const requestId = ++fnoRequestIdRef.current
    setIsFnoLoading(true)

    const fetchData = async () => {
      try {
        const [underlyingsRes, expiriesRes] = await Promise.all([
          // include_futures=true so MCX commodities with only live FUT contracts
          // (NATURALGASMINI, COPPER, LEADMINI, ...) appear in the dropdown.
          // Option-chain pages keep the default (options-only) behaviour.
          fetch(`/search/api/underlyings?exchange=${exchange}&include_futures=true`, {
            credentials: 'include',
          }),
          fetch(`/search/api/expiries?exchange=${exchange}`, { credentials: 'include' }),
        ])

        // Ignore if this is a stale request
        if (requestId !== fnoRequestIdRef.current) return

        if (underlyingsRes.ok) {
          const data = await underlyingsRes.json()
          if (data.status === 'success' && Array.isArray(data.underlyings)) {
            setUnderlyings(data.underlyings)
          }
        }

        if (expiriesRes.ok) {
          const data = await expiriesRes.json()
          if (data.status === 'success' && Array.isArray(data.expiries)) {
            setExpiries(data.expiries)
          }
        }
      } catch (error) {
      } finally {
        if (requestId === fnoRequestIdRef.current) {
          setIsFnoLoading(false)
        }
      }
    }

    fetchData()
  }, [exchange, isFnoExchange, resetFnoFilters])

  // Fetch expiries when underlying changes
  useEffect(() => {
    if (!isFnoExchange || !underlying) return

    const fetchExpiriesForUnderlying = async () => {
      try {
        const response = await fetch(
          `/search/api/expiries?exchange=${exchange}&underlying=${underlying}`,
          { credentials: 'include' }
        )
        if (response.ok) {
          const data = await response.json()
          if (data.status === 'success' && Array.isArray(data.expiries)) {
            setExpiries(data.expiries)
          }
        }
      } catch (error) {}
    }

    fetchExpiriesForUnderlying()
  }, [underlying, exchange, isFnoExchange])

  // Debounced search for autocomplete
  const performAutocompleteSearch = useCallback(
    async (query: string, exch: string) => {
      // Autocomplete is driven exclusively by the Symbol input. Selecting an
      // exchange or toggling F&O filters never fires the dropdown — that was
      // an annoying side-effect users complained about. The filters are still
      // sent along with the query so suggestions stay scoped, but they don't
      // trigger a fetch on their own.
      if (query.length < 2) {
        setSearchResults([])
        setShowResults(false)
        return
      }

      setIsLoading(true)
      try {
        const params = new URLSearchParams()
        params.append('q', query)
        if (exch) params.append('exchange', exch)
        if (underlying) params.append('underlying', underlying)
        if (expiry) params.append('expiry', expiry)
        if (instrumentTypeCsv) params.append('instrumenttype', instrumentTypeCsv)
        if (strikeMin) params.append('strike_min', strikeMin)
        if (strikeMax) params.append('strike_max', strikeMax)

        const response = await fetch(`/search/api/search?${params}`, {
          credentials: 'include',
        })
        const data = await response.json()
        setSearchResults((data.results || []).slice(0, 10))
        setShowResults(true)
      } catch (error) {
        setSearchResults([])
      } finally {
        setIsLoading(false)
      }
    },
    [underlying, expiry, instrumentTypeCsv, strikeMin, strikeMax]
  )

  // Debounced input handler — fires ONLY when the user types in the Symbol
  // box. Exchange and FNO filter changes do not trigger the dropdown.
  useEffect(() => {
    const timer = setTimeout(() => {
      if (symbol.length >= 2) {
        performAutocompleteSearch(symbol, exchange)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [symbol, exchange, performAutocompleteSearch])

  // Click-outside handler to close dropdown
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (inputWrapperRef.current && !inputWrapperRef.current.contains(e.target as Node)) {
        setShowResults(false)
      }
    }
    document.addEventListener('click', handleClickOutside)
    return () => document.removeEventListener('click', handleClickOutside)
  }, [])

  const persistToHistory = useCallback((entry: SearchHistoryEntry) => {
    setHistory((prev) => {
      const key = historyKey(entry)
      const filtered = prev.filter((e) => historyKey(e) !== key)
      const next = [entry, ...filtered].slice(0, HISTORY_MAX)
      saveHistory(next)
      return next
    })
  }, [])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setShowResults(false)
    setSymbolError('')

    // At least one exchange must be selected.
    if (exchanges.length === 0) {
      setSymbolError('Select at least one exchange')
      return
    }

    // Save to local history (exchange and instrumentType stored as comma-joined CSVs)
    persistToHistory({
      symbol,
      exchange: exchangeCsv,
      underlying: underlying || undefined,
      expiry: expiry || undefined,
      instrumentType: instrumentTypeCsv || undefined,
      strikeMin: strikeMin || undefined,
      strikeMax: strikeMax || undefined,
      ts: Date.now(),
    })

    const params = new URLSearchParams()
    if (symbol) params.append('symbol', symbol)
    if (exchangeCsv) params.append('exchange', exchangeCsv)
    if (underlying) params.append('underlying', underlying)
    if (expiry) params.append('expiry', expiry)
    if (instrumentTypeCsv) params.append('instrumenttype', instrumentTypeCsv)
    if (strikeMin) params.append('strike_min', strikeMin)
    if (strikeMax) params.append('strike_max', strikeMax)

    navigate(`/search?${params.toString()}`)
  }

  const applyHistoryEntry = (entry: SearchHistoryEntry) => {
    setSymbol(entry.symbol)
    setExchanges(
      (entry.exchange || '')
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
    )
    setUnderlying(entry.underlying || '')
    setExpiry(entry.expiry || '')
    setInstrumentTypes(
      (entry.instrumentType || '')
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
    )
    setStrikeMin(entry.strikeMin || '')
    setStrikeMax(entry.strikeMax || '')
    setSymbolError('')
    persistToHistory({ ...entry, ts: Date.now() })
    const params = new URLSearchParams()
    if (entry.symbol) params.append('symbol', entry.symbol)
    if (entry.exchange) params.append('exchange', entry.exchange)
    if (entry.underlying) params.append('underlying', entry.underlying)
    if (entry.expiry) params.append('expiry', entry.expiry)
    if (entry.instrumentType) params.append('instrumenttype', entry.instrumentType)
    if (entry.strikeMin) params.append('strike_min', entry.strikeMin)
    if (entry.strikeMax) params.append('strike_max', entry.strikeMax)
    navigate(`/search?${params.toString()}`)
  }

  const removeHistoryEntry = (key: string) => {
    setHistory((prev) => {
      const next = prev.filter((e) => historyKey(e) !== key)
      saveHistory(next)
      return next
    })
  }

  const clearHistory = () => {
    setHistory([])
    saveHistory([])
  }

  const handleResultClick = (result: SearchResult) => {
    setSymbol(result.symbol)
    setExchanges([result.exchange])
    setShowResults(false)
  }

  const showStrikeRange = instrumentTypes.includes('CE') || instrumentTypes.includes('PE')

  return (
    <div className="max-w-4xl mx-auto py-8 px-4">
      {/* Header */}
      <div className="text-center mb-8">
        <h1 className="text-4xl lg:text-5xl font-bold mb-4">Symbol Search</h1>
        <p className="text-lg text-muted-foreground">
          Search for symbols across different exchanges to get detailed information
        </p>
      </div>

      {/* Search Form */}
      <Card className="mb-6">
        <CardContent className="p-6 lg:p-8">
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Symbol Search */}
            <div className="space-y-2">
              <div className="flex justify-between">
                <Label htmlFor="symbol">Symbol, Name, or Token</Label>
                <span
                  className={`text-xs ${symbolError ? 'text-red-500' : exchanges.length > 0 ? 'text-green-600' : 'text-muted-foreground'}`}
                >
                  {symbolError ||
                    (exchanges.length > 0
                      ? '(Optional — browse selected exchange)'
                      : '(Or pick an exchange)')}
                </span>
              </div>
              <div className="relative" ref={inputWrapperRef}>
                <Input
                  id="symbol"
                  type="text"
                  placeholder={
                    isCrypto ? 'e.g., BTC, BTCUSDFUT, ETH' : 'e.g., nifty, RELIANCE, 2885'
                  }
                  value={symbol}
                  onChange={(e) => {
                    setSymbol(e.target.value)
                    setSymbolError('')
                  }}
                  onFocus={() => {
                    // Re-open the dropdown only if there's already a typed
                    // query and matching results — never on filter state alone.
                    if (symbol.length >= 2 && searchResults.length > 0) {
                      setShowResults(true)
                    }
                  }}
                  autoComplete="off"
                />
                {isLoading && (
                  <div className="absolute right-3 top-1/2 -translate-y-1/2">
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary"></div>
                  </div>
                )}

                {/* Autocomplete Results */}
                {showResults && searchResults.length > 0 && (
                  <div className="absolute z-50 w-full mt-1 bg-background border rounded-lg shadow-lg max-h-96 overflow-y-auto">
                    {searchResults.map((result, index) => (
                      <div
                        key={index}
                        className="p-3 border-b last:border-b-0 hover:bg-muted cursor-pointer"
                        onClick={() => handleResultClick(result)}
                      >
                        <div className="flex justify-between items-start gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="font-semibold truncate">{result.symbol}</div>
                            <div className="text-sm text-muted-foreground truncate">
                              {result.name}
                              {result.expiry && ` | ${result.expiry}`}
                              {result.strike && result.strike > 0 && ` | Strike: ${result.strike}`}
                            </div>
                            <div className="text-xs text-muted-foreground font-mono">
                              Token: {result.token}
                            </div>
                          </div>
                          <span className="shrink-0 bg-primary text-primary-foreground px-3 py-1 rounded-full text-xs font-semibold">
                            {result.exchange}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {showResults && searchResults.length === 0 && symbol.length >= 2 && !isLoading && (
                  <div className="absolute z-50 w-full mt-1 bg-background border rounded-lg shadow-lg p-8 text-center">
                    <Search className="h-12 w-12 mx-auto text-muted-foreground/50 mb-3" />
                    <div className="font-medium">No results found</div>
                    <div className="text-sm text-muted-foreground mt-1">
                      Try a different search term
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Exchange multi-select */}
            <div className="space-y-2">
              <Label>Exchange</Label>
              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full justify-between font-normal"
                  >
                    <span className="truncate text-left">
                      {exchanges.length === 0
                        ? 'Select Exchange(s)'
                        : exchanges.length === 1
                          ? (allExchanges.find((ex) => ex.value === exchanges[0])?.label ??
                            exchanges[0])
                          : `${exchanges.length} exchanges selected`}
                    </span>
                    <ChevronDown className="h-4 w-4 opacity-60 shrink-0" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-72 p-2 max-h-80 overflow-auto" align="start">
                  <div className="flex items-center justify-between px-2 py-1 text-xs text-muted-foreground">
                    <span>Pick one or more</span>
                    {exchanges.length > 0 ? (
                      <button
                        type="button"
                        onClick={() => setExchanges([])}
                        className="hover:text-foreground"
                      >
                        Clear
                      </button>
                    ) : null}
                  </div>
                  <div className="space-y-1">
                    {allExchanges.map((ex) => {
                      const checked = exchanges.includes(ex.value)
                      return (
                        <label
                          key={ex.value}
                          className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-muted cursor-pointer text-sm"
                        >
                          <Checkbox
                            checked={checked}
                            onCheckedChange={() => toggleExchange(ex.value)}
                          />
                          <span className="flex-1">{ex.label}</span>
                          {checked ? <Check className="h-3.5 w-3.5 text-primary" /> : null}
                        </label>
                      )
                    })}
                  </div>
                </PopoverContent>
              </Popover>
              {exchanges.length > 1 ? (
                <div className="flex flex-wrap gap-1 pt-1">
                  {exchanges.map((ex) => (
                    <span
                      key={ex}
                      className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs"
                    >
                      {ex}
                      <button
                        type="button"
                        onClick={() => toggleExchange(ex)}
                        className="text-muted-foreground hover:text-foreground"
                        aria-label={`Remove ${ex}`}
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  ))}
                </div>
              ) : null}
              {exchanges.length > 1 ? (
                <p className="text-xs text-muted-foreground">
                  F&O filters (underlying, expiry) are hidden when more than one exchange is
                  selected — pick one F&O exchange to use them.
                </p>
              ) : null}
            </div>

            {/* F&O Filters */}
            {isFnoExchange && (
              <div className="space-y-4">
                <div className="relative">
                  <div className="absolute inset-0 flex items-center">
                    <span className="w-full border-t" />
                  </div>
                  <div className="relative flex justify-center text-xs uppercase">
                    <span className="bg-background px-2 text-muted-foreground flex items-center gap-2">
                      F&O Filters
                      {isFnoLoading && (
                        <span className="animate-spin rounded-full h-3 w-3 border-b-2 border-primary"></span>
                      )}
                    </span>
                  </div>
                </div>

                {/* Row 1: Underlying and Instrument Type */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Underlying</Label>
                    <select
                      value={underlying}
                      onChange={(e) => setUnderlying(e.target.value)}
                      className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                    >
                      <option value="">All Underlyings</option>
                      {(underlyings || []).map((u) => (
                        <option key={u} value={u}>
                          {u}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="space-y-2">
                    <Label>Instrument Type</Label>
                    <div className="flex flex-wrap gap-3 h-10 items-center">
                      {[
                        { value: 'FUT', label: 'Futures' },
                        { value: 'CE', label: 'Calls' },
                        { value: 'PE', label: 'Puts' },
                      ].map((opt) => (
                        <label
                          key={opt.value}
                          className="flex items-center gap-1.5 text-sm cursor-pointer"
                        >
                          <Checkbox
                            checked={instrumentTypes.includes(opt.value)}
                            onCheckedChange={() => toggleInstrumentType(opt.value)}
                          />
                          {opt.label}
                        </label>
                      ))}
                      {instrumentTypes.length === 0 ? (
                        <span className="text-xs text-muted-foreground">(All)</span>
                      ) : null}
                    </div>
                  </div>
                </div>

                {/* Row 2: Expiry */}
                <div className="space-y-2">
                  <Label>Expiry Date</Label>
                  <select
                    value={expiry}
                    onChange={(e) => setExpiry(e.target.value)}
                    className="flex h-10 w-full items-center justify-between rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                  >
                    <option value="">All Expiries</option>
                    {(expiries || []).map((e) => (
                      <option key={e} value={e}>
                        {e}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Row 3: Strike Range (for options only) */}
                {showStrikeRange && (
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label>Min Strike</Label>
                      <Input
                        type="number"
                        placeholder="e.g., 24000"
                        value={strikeMin}
                        onChange={(e) => setStrikeMin(e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label>Max Strike</Label>
                      <Input
                        type="number"
                        placeholder="e.g., 26000"
                        value={strikeMax}
                        onChange={(e) => setStrikeMax(e.target.value)}
                      />
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Search Button */}
            <Button type="submit" className="w-full" size="lg">
              <Search className="mr-2 h-5 w-5" />
              Search Symbol
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Recent Searches */}
      {history.length > 0 ? (
        <Card className="mb-6">
          <CardContent className="p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2 text-sm font-medium">
                <History className="h-4 w-4" />
                Recent Searches
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={clearHistory}
                className="text-muted-foreground hover:text-foreground h-7 px-2"
              >
                <Trash2 className="h-3.5 w-3.5 mr-1" /> Clear
              </Button>
            </div>
            <div className="flex flex-wrap gap-2">
              {history.map((entry) => {
                const key = historyKey(entry)
                return (
                  <div
                    key={key}
                    className="inline-flex items-center gap-1 rounded-full bg-muted hover:bg-muted/70 transition-colors text-xs"
                  >
                    <button
                      type="button"
                      onClick={() => applyHistoryEntry(entry)}
                      className="px-3 py-1 font-mono"
                      title="Click to re-run this search"
                    >
                      {formatHistoryLabel(entry)}
                    </button>
                    <button
                      type="button"
                      onClick={() => removeHistoryEntry(key)}
                      className="pr-2 text-muted-foreground hover:text-foreground"
                      title="Remove from history"
                      aria-label="Remove from history"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {/* Search Tips */}
      <Alert>
        <Info className="h-4 w-4" />
        <AlertTitle>Search Tips</AlertTitle>
        <AlertDescription className="space-y-3 mt-2">
          {isCrypto ? (
            <>
              <div>
                <div className="font-semibold mb-1">Crypto Search:</div>
                <ul className="ml-2 space-y-0.5 text-sm">
                  <li>
                    Perpetual Futures:{' '}
                    <code className="bg-muted px-2 py-0.5 rounded">BTCUSDFUT</code>,{' '}
                    <code className="bg-muted px-2 py-0.5 rounded">ETHUSDFUT</code>
                  </li>
                  <li>
                    Spot: <code className="bg-muted px-2 py-0.5 rounded">BTCINR</code>,{' '}
                    <code className="bg-muted px-2 py-0.5 rounded">ETHINR</code>
                  </li>
                  <li>
                    Options: <code className="bg-muted px-2 py-0.5 rounded">BTC 80000 CE</code>,{' '}
                    <code className="bg-muted px-2 py-0.5 rounded">ETH 2000 PE</code>
                  </li>
                </ul>
              </div>
              <div className="text-xs text-muted-foreground mt-2">
                <strong>Tip:</strong> Use F&O filters to narrow by underlying, expiry, and strike
                price
              </div>
            </>
          ) : (
            <>
              <div>
                <div className="font-semibold mb-1">Stock Search:</div>
                <ul className="ml-2 space-y-0.5 text-sm">
                  <li>
                    By symbol: <code className="bg-muted px-2 py-0.5 rounded">RELIANCE</code>,{' '}
                    <code className="bg-muted px-2 py-0.5 rounded">INFY</code>
                  </li>
                  <li>
                    By company name:{' '}
                    <code className="bg-muted px-2 py-0.5 rounded">Reliance Industries</code>
                  </li>
                  <li>
                    By token number: <code className="bg-muted px-2 py-0.5 rounded">2885</code>
                  </li>
                </ul>
              </div>
              <div>
                <div className="font-semibold mb-1">Futures & Options:</div>
                <ul className="ml-2 space-y-0.5 text-sm">
                  <li>
                    Futures: <code className="bg-muted px-2 py-0.5 rounded">nifty oct fut</code>,{' '}
                    <code className="bg-muted px-2 py-0.5 rounded">banknifty dec fut</code>
                  </li>
                  <li>
                    Call Options:{' '}
                    <code className="bg-muted px-2 py-0.5 rounded">nifty 25000 ce</code>
                  </li>
                  <li>
                    Put Options:{' '}
                    <code className="bg-muted px-2 py-0.5 rounded">nifty 24000 pe</code>
                  </li>
                </ul>
              </div>
              <div className="text-xs text-muted-foreground mt-2">
                <strong>Tip:</strong> Select the appropriate exchange (NFO for F&O, NSE for stocks)
                for accurate results
              </div>
            </>
          )}
        </AlertDescription>
      </Alert>
    </div>
  )
}
