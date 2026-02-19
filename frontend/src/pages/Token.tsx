import { Info, Search } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

interface SearchResult {
  symbol: string
  name: string
  exchange: string
  token: string
  expiry?: string
  strike?: number
}

const EXCHANGES = [
  { value: 'NSE', label: 'NSE - National Stock Exchange' },
  { value: 'NFO', label: 'NFO - NSE Futures & Options' },
  { value: 'BSE', label: 'BSE - Bombay Stock Exchange' },
  { value: 'BFO', label: 'BFO - BSE Futures & Options' },
  { value: 'CDS', label: 'CDS - Currency Derivatives' },
  { value: 'MCX', label: 'MCX - Multi Commodity Exchange' },
  { value: 'NSE_INDEX', label: 'NSE_INDEX - National Stock Exchange Index' },
  { value: 'BSE_INDEX', label: 'BSE_INDEX - Bombay Stock Exchange Index' },
]

const FNO_EXCHANGES = ['NFO', 'BFO', 'MCX', 'CDS']

export default function Token() {
  const navigate = useNavigate()
  const [symbol, setSymbol] = useState('')
  const [exchange, setExchange] = useState('')
  const [underlying, setUnderlying] = useState('')
  const [instrumentType, setInstrumentType] = useState('')
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

  // Refs for click-outside handling and request tracking
  const inputWrapperRef = useRef<HTMLDivElement>(null)
  const fnoRequestIdRef = useRef(0)

  const isFnoExchange = FNO_EXCHANGES.includes(exchange)

  const hasFnoFilters = underlying || expiry || instrumentType || strikeMin || strikeMax

  const resetFnoFilters = useCallback(() => {
    setUnderlying('')
    setInstrumentType('')
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
          fetch(`/search/api/underlyings?exchange=${exchange}`, { credentials: 'include' }),
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
      } catch (error) {
      }
    }

    fetchExpiriesForUnderlying()
  }, [underlying, exchange, isFnoExchange])

  // Debounced search for autocomplete
  const performAutocompleteSearch = useCallback(
    async (query: string, exch: string) => {
      if (query.length < 2 && !(isFnoExchange && hasFnoFilters)) {
        setSearchResults([])
        setShowResults(false)
        return
      }

      setIsLoading(true)
      try {
        const params = new URLSearchParams()
        if (query) params.append('q', query)
        if (exch) params.append('exchange', exch)
        if (underlying) params.append('underlying', underlying)
        if (expiry) params.append('expiry', expiry)
        if (instrumentType) params.append('instrumenttype', instrumentType)
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
    [underlying, expiry, instrumentType, strikeMin, strikeMax, isFnoExchange, hasFnoFilters]
  )

  // Debounced input handler
  useEffect(() => {
    const timer = setTimeout(() => {
      if (symbol.length >= 2 || (isFnoExchange && hasFnoFilters)) {
        performAutocompleteSearch(symbol, exchange)
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [symbol, exchange, performAutocompleteSearch, hasFnoFilters, isFnoExchange])

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

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setShowResults(false)
    setSymbolError('')

    // Validate: symbol is required unless FNO filters are applied
    if (!symbol && !(isFnoExchange && hasFnoFilters)) {
      setSymbolError('Required - enter a search term')
      return
    }

    // Exchange is required
    if (!exchange) {
      return
    }

    // Navigate to search results page with query params
    const params = new URLSearchParams()
    if (symbol) params.append('symbol', symbol)
    if (exchange) params.append('exchange', exchange)
    if (underlying) params.append('underlying', underlying)
    if (expiry) params.append('expiry', expiry)
    if (instrumentType) params.append('instrumenttype', instrumentType)
    if (strikeMin) params.append('strike_min', strikeMin)
    if (strikeMax) params.append('strike_max', strikeMax)

    navigate(`/search?${params.toString()}`)
  }

  const handleResultClick = (result: SearchResult) => {
    setSymbol(result.symbol)
    setExchange(result.exchange)
    setShowResults(false)
  }

  const showStrikeRange = instrumentType === 'CE' || instrumentType === 'PE'

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
                  className={`text-xs ${symbolError ? 'text-red-500' : isFnoExchange && hasFnoFilters ? 'text-green-600' : 'text-muted-foreground'}`}
                >
                  {symbolError ||
                    (isFnoExchange && hasFnoFilters ? '(Optional with filters)' : '(Required)')}
                </span>
              </div>
              <div className="relative" ref={inputWrapperRef}>
                <Input
                  id="symbol"
                  type="text"
                  placeholder="e.g., nifty, RELIANCE, 2885"
                  value={symbol}
                  onChange={(e) => {
                    setSymbol(e.target.value)
                    setSymbolError('')
                  }}
                  onFocus={() => {
                    if (symbol.length >= 2 || (isFnoExchange && hasFnoFilters)) {
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

            {/* Exchange Select */}
            <div className="space-y-2">
              <Label htmlFor="exchange">Exchange</Label>
              <Select value={exchange} onValueChange={setExchange}>
                <SelectTrigger>
                  <SelectValue placeholder="Select Exchange" />
                </SelectTrigger>
                <SelectContent>
                  {EXCHANGES.map((ex) => (
                    <SelectItem key={ex.value} value={ex.value}>
                      {ex.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
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
                    <Select
                      value={instrumentType || '_all'}
                      onValueChange={(v) => setInstrumentType(v === '_all' ? '' : v)}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="All Types" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="_all">All Types</SelectItem>
                        <SelectItem value="FUT">Futures</SelectItem>
                        <SelectItem value="CE">Call Options (CE)</SelectItem>
                        <SelectItem value="PE">Put Options (PE)</SelectItem>
                      </SelectContent>
                    </Select>
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

      {/* Search Tips */}
      <Alert>
        <Info className="h-4 w-4" />
        <AlertTitle>Search Tips</AlertTitle>
        <AlertDescription className="space-y-3 mt-2">
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
                Call Options: <code className="bg-muted px-2 py-0.5 rounded">nifty 25000 ce</code>
              </li>
              <li>
                Put Options: <code className="bg-muted px-2 py-0.5 rounded">nifty 24000 pe</code>
              </li>
            </ul>
          </div>
          <div className="text-xs text-muted-foreground mt-2">
            <strong>Tip:</strong> Select the appropriate exchange (NFO for F&O, NSE for stocks) for
            accurate results
          </div>
        </AlertDescription>
      </Alert>
    </div>
  )
}
