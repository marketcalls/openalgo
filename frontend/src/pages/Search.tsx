import {
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  Search as SearchIcon,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
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
import { showToast } from '@/utils/toast'

type CopyFormat = 'exchange_symbol' | 'symbol' | 'token' | 'broker_symbol'

const COPY_FORMAT_OPTIONS: { value: CopyFormat; label: string; example: string }[] = [
  { value: 'exchange_symbol', label: 'EXCHANGE:SYMBOL', example: 'NSE:RELIANCE' },
  { value: 'symbol', label: 'SYMBOL only', example: 'RELIANCE' },
  { value: 'broker_symbol', label: 'Broker symbol', example: 'RELIANCE-EQ' },
  { value: 'token', label: 'Token', example: '2885' },
]

function rowKey(r: { symbol: string; exchange: string; token: string }): string {
  return `${r.exchange}:${r.symbol}:${r.token}`
}

function escapeCsvField(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return ''
  const str = String(value)
  if (/[",\n\r]/.test(str)) {
    return `"${str.replace(/"/g, '""')}"`
  }
  return str
}

interface SearchResult {
  symbol: string
  brsymbol: string
  name: string
  exchange: string
  brexchange: string
  token: string
  lotsize: number | null
  contract_value: number | null
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
  const [total, setTotal] = useState<number | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey | null>(null)
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState<number | 'all'>(25)
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [copyFormat, setCopyFormat] = useState<CopyFormat>('exchange_symbol')

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
        const rows = data.results || []
        setResults(rows)
        setTotal(typeof data.total === 'number' ? data.total : rows.length)
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

  const allOnPageSelected =
    paginatedResults.length > 0 && paginatedResults.every((r) => selected.has(rowKey(r)))
  const someOnPageSelected =
    paginatedResults.some((r) => selected.has(rowKey(r))) && !allOnPageSelected

  const toggleRow = (r: SearchResult) => {
    const key = rowKey(r)
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  const togglePageSelection = () => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (allOnPageSelected) {
        for (const r of paginatedResults) next.delete(rowKey(r))
      } else {
        for (const r of paginatedResults) next.add(rowKey(r))
      }
      return next
    })
  }

  const formatRow = (r: SearchResult, format: CopyFormat): string => {
    switch (format) {
      case 'exchange_symbol':
        return `${r.exchange}:${r.symbol}`
      case 'symbol':
        return r.symbol
      case 'broker_symbol':
        return r.brsymbol
      case 'token':
        return r.token
      default:
        return r.symbol
    }
  }

  const copyRows = (rows: SearchResult[], format: CopyFormat) => {
    if (rows.length === 0) {
      showToast.error('Nothing to copy', 'clipboard')
      return
    }
    const text = rows.map((r) => formatRow(r, format)).join('\n')
    navigator.clipboard
      .writeText(text)
      .then(() => {
        showToast.success(
          `Copied ${rows.length} ${rows.length === 1 ? 'row' : 'rows'}`,
          'clipboard'
        )
      })
      .catch(() => {
        showToast.error('Failed to copy', 'clipboard')
      })
  }

  const copySelected = () => {
    const rows = sortedResults.filter((r) => selected.has(rowKey(r)))
    copyRows(rows, copyFormat)
  }

  const copyAllVisible = () => {
    copyRows(sortedResults, copyFormat)
  }

  const clearSelection = () => setSelected(new Set())

  const downloadCSV = () => {
    const rows =
      selected.size > 0 ? sortedResults.filter((r) => selected.has(rowKey(r))) : sortedResults
    if (rows.length === 0) {
      showToast.error('Nothing to download', 'system')
      return
    }
    const headers = [
      'symbol',
      'brsymbol',
      'name',
      'exchange',
      'brexchange',
      'token',
      'lotsize',
      'contract_value',
      'freeze_qty',
    ]
    const lines = [headers.join(',')]
    for (const r of rows) {
      lines.push(
        [
          r.symbol,
          r.brsymbol,
          r.name,
          r.exchange,
          r.brexchange,
          r.token,
          r.lotsize,
          r.contract_value,
          r.freeze_qty,
        ]
          .map(escapeCsvField)
          .join(',')
      )
    }
    const csv = lines.join('\n')
    // BOM so Excel detects UTF-8 correctly when the user opens the file
    const blob = new Blob(['﻿', csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
    const a = document.createElement('a')
    a.href = url
    a.download = `openalgo-search-${ts}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    showToast.success(`Downloaded ${rows.length} ${rows.length === 1 ? 'row' : 'rows'}`, 'system')
  }

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
            <div className="text-3xl font-bold text-primary">
              {total !== null ? total.toLocaleString() : results.length.toLocaleString()}
            </div>
            <div className="text-sm text-muted-foreground">matching symbols</div>
          </div>
        </CardContent>
      </Card>

      {/* Toolbar: copy + CSV */}
      <Card>
        <CardContent className="p-4 flex flex-wrap items-center gap-3">
          <div className="text-sm">
            <span className="font-semibold">{selected.size}</span>
            <span className="text-muted-foreground"> selected</span>
            {selected.size > 0 ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={clearSelection}
                className="ml-2 h-7 px-2 text-xs"
              >
                Clear
              </Button>
            ) : null}
          </div>

          <div className="flex items-center gap-2">
            <Select value={copyFormat} onValueChange={(v) => setCopyFormat(v as CopyFormat)}>
              <SelectTrigger className="w-56 h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {COPY_FORMAT_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label} <span className="text-muted-foreground">({opt.example})</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="outline"
              size="sm"
              onClick={copySelected}
              disabled={selected.size === 0}
              title="Copy selected rows to clipboard"
            >
              <Copy className="h-4 w-4 mr-1" />
              Copy selected
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={copyAllVisible}
              disabled={sortedResults.length === 0}
              title="Copy all rows currently displayed (after filters/sort)"
            >
              <Copy className="h-4 w-4 mr-1" />
              Copy all
            </Button>
          </div>

          <div className="ml-auto">
            <Button
              variant="outline"
              size="sm"
              onClick={downloadCSV}
              disabled={sortedResults.length === 0}
              title={
                selected.size > 0
                  ? `Download ${selected.size} selected rows as CSV`
                  : 'Download all rows as CSV'
              }
            >
              <Download className="h-4 w-4 mr-1" />
              Download CSV{selected.size > 0 ? ` (${selected.size})` : ''}
            </Button>
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
                  <TableHead className="w-12">
                    <Checkbox
                      checked={
                        allOnPageSelected ? true : someOnPageSelected ? 'indeterminate' : false
                      }
                      onCheckedChange={togglePageSelection}
                      aria-label="Select all rows on this page"
                    />
                  </TableHead>
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
                    <TableCell colSpan={9} className="text-center py-8 text-muted-foreground">
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
                      <TableCell className="w-12">
                        <Checkbox
                          checked={selected.has(rowKey(row))}
                          onCheckedChange={() => toggleRow(row)}
                          aria-label={`Select ${row.symbol}`}
                        />
                      </TableCell>
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
                      <TableCell>
                        {row.contract_value != null && row.contract_value !== 1
                          ? row.contract_value
                          : (row.lotsize ?? '-')}
                      </TableCell>
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
