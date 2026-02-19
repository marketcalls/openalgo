import { ArrowUpDown, ChevronLeft, ChevronRight, Copy, Search as SearchIcon } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

interface SearchResult {
  symbol: string
  brsymbol: string
  name: string
  exchange: string
  brexchange: string
  token: string
  lotsize: number | null
  freeze_qty: number | null
}

type SortKey =
  | 'symbol'
  | 'brsymbol'
  | 'name'
  | 'exchange'
  | 'brexchange'
  | 'token'
  | 'lotsize'
  | 'freeze_qty'
type SortDirection = 'asc' | 'desc'

const PAGE_SIZE_OPTIONS = [25, 50, 100, 250, 500, 'all'] as const

export default function Search() {
  const [searchParams] = useSearchParams()
  const [results, setResults] = useState<SearchResult[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey | null>(null)
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState<number | 'all'>(25)

  useEffect(() => {
    fetchResults()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchResults = async () => {
    setIsLoading(true)
    setError(null)
    try {
      // Build URL with all search params - use the API endpoint
      const params = new URLSearchParams()
      const symbol = searchParams.get('symbol')
      const exchange = searchParams.get('exchange')
      const underlying = searchParams.get('underlying')
      const expiry = searchParams.get('expiry')
      const instrumenttype = searchParams.get('instrumenttype')
      const strike_min = searchParams.get('strike_min')
      const strike_max = searchParams.get('strike_max')

      // Use 'q' parameter for the API endpoint
      if (symbol) params.append('q', symbol)
      if (exchange) params.append('exchange', exchange)
      if (underlying) params.append('underlying', underlying)
      if (expiry) params.append('expiry', expiry)
      if (instrumenttype) params.append('instrumenttype', instrumenttype)
      if (strike_min) params.append('strike_min', strike_min)
      if (strike_max) params.append('strike_max', strike_max)

      // Use the API search endpoint which returns JSON
      const response = await fetch(`/search/api/search?${params.toString()}`, {
        credentials: 'include',
      })

      if (response.ok) {
        const data = await response.json()
        setResults(data.results || [])
      } else if (response.status === 401 || response.status === 403) {
        setError('Session expired. Please log in again.')
        showToast.error('Session expired. Please log in again.', 'system')
        setResults([])
      } else {
        setError('Search failed. Please try again.')
        showToast.error('Failed to search symbols', 'system')
        setResults([])
      }
    } catch (err) {
      setError('Failed to search symbols. Please check your connection.')
      showToast.error('Failed to search symbols', 'system')
      setResults([])
    } finally {
      setIsLoading(false)
    }
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard
      .writeText(text)
      .then(() => {
        showToast.success('Symbol copied to clipboard', 'clipboard')
      })
      .catch(() => {
        showToast.error('Failed to copy symbol', 'clipboard')
      })
  }

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDirection('asc')
    }
  }

  const sortedResults = useMemo(() => {
    if (!sortKey) return results

    return [...results].sort((a, b) => {
      const aVal = a[sortKey]
      const bVal = b[sortKey]

      // Handle numeric sorting
      if (['lotsize', 'token', 'freeze_qty'].includes(sortKey)) {
        const aNum = parseFloat(String(aVal ?? 0).replace(/[^0-9.-]/g, '')) || 0
        const bNum = parseFloat(String(bVal ?? 0).replace(/[^0-9.-]/g, '')) || 0
        return sortDirection === 'asc' ? aNum - bNum : bNum - aNum
      }

      // Handle string sorting
      const aStr = String(aVal ?? '')
      const bStr = String(bVal ?? '')
      return sortDirection === 'asc' ? aStr.localeCompare(bStr) : bStr.localeCompare(aStr)
    })
  }, [results, sortKey, sortDirection])

  const paginatedResults = useMemo(() => {
    if (pageSize === 'all') return sortedResults
    const start = (currentPage - 1) * pageSize
    return sortedResults.slice(start, start + pageSize)
  }, [sortedResults, currentPage, pageSize])

  const totalPages = useMemo(() => {
    if (pageSize === 'all') return 1
    return Math.ceil(sortedResults.length / pageSize)
  }, [sortedResults.length, pageSize])

  const showingStart = pageSize === 'all' ? 1 : (currentPage - 1) * pageSize + 1
  const showingEnd =
    pageSize === 'all'
      ? sortedResults.length
      : Math.min(currentPage * (pageSize as number), sortedResults.length)

  const SortableHeader = ({ column, label }: { column: SortKey; label: string }) => (
    <TableHead
      className="cursor-pointer hover:bg-muted/50 select-none"
      onClick={() => handleSort(column)}
    >
      <div className="flex items-center gap-1">
        {label}
        <ArrowUpDown className="h-4 w-4 opacity-50" />
      </div>
    </TableHead>
  )

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <Card>
        <CardContent className="p-6">
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-4">
            <h1 className="text-3xl font-bold">Search Results</h1>
            <Button asChild>
              <Link to="/search/token">
                <SearchIcon className="h-5 w-5 mr-2" />
                New Search
              </Link>
            </Button>
          </div>
          <div className="inline-flex flex-col items-center bg-muted p-4 rounded-lg">
            <div className="text-sm text-muted-foreground">Found</div>
            <div className="text-3xl font-bold text-primary">{results.length}</div>
            <div className="text-sm text-muted-foreground">matching symbols</div>
          </div>
        </CardContent>
      </Card>

      {/* Results Table */}
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHeader column="symbol" label="Symbol" />
                  <SortableHeader column="brsymbol" label="Broker Symbol" />
                  <SortableHeader column="name" label="Name" />
                  <SortableHeader column="exchange" label="Exchange" />
                  <SortableHeader column="brexchange" label="Broker Exch" />
                  <SortableHeader column="token" label="Token" />
                  <SortableHeader column="lotsize" label="Lot Size" />
                  <SortableHeader column="freeze_qty" label="Freeze Qty" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {paginatedResults.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="text-center py-8 text-muted-foreground">
                      {error ? (
                        <span className="text-destructive">{error}</span>
                      ) : (
                        'No results found'
                      )}
                    </TableCell>
                  </TableRow>
                ) : (
                  paginatedResults.map((row, index) => (
                    <TableRow key={index} className="hover:bg-muted/50">
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <span className="font-semibold">{row.symbol}</span>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6 opacity-60 hover:opacity-100"
                            onClick={() => copyToClipboard(row.symbol)}
                            title="Copy symbol"
                          >
                            <Copy className="h-3 w-3" />
                          </Button>
                        </div>
                      </TableCell>
                      <TableCell>{row.brsymbol}</TableCell>
                      <TableCell className="text-muted-foreground max-w-[200px] truncate">
                        {row.name}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{row.exchange}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">{row.brexchange}</Badge>
                      </TableCell>
                      <TableCell className="font-mono text-sm">{row.token}</TableCell>
                      <TableCell>{row.lotsize ?? '-'}</TableCell>
                      <TableCell>{row.freeze_qty ?? '-'}</TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Pagination */}
      {results.length > 25 && (
        <div className="flex flex-col sm:flex-row justify-between items-center gap-4">
          <div className="text-sm text-muted-foreground">
            Showing {showingStart} to {showingEnd} of {sortedResults.length} results
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage === 1}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="text-sm px-2">
              Page {currentPage} of {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              disabled={currentPage >= totalPages}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
          <Select
            value={String(pageSize)}
            onValueChange={(v) => {
              setPageSize(v === 'all' ? 'all' : Number(v))
              setCurrentPage(1)
            }}
          >
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZE_OPTIONS.map((opt) => (
                <SelectItem key={opt} value={String(opt)}>
                  {opt === 'all' ? 'Show All' : `${opt} per page`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
    </div>
  )
}
