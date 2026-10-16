import {
  ArrowDown,
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  Download,
  Loader2,
  RefreshCw,
  Settings2,
  TrendingDown,
  TrendingUp,
  Upload,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { tradingApi } from '@/api/trading'
import { CalendarHeatmap, type CalendarHeatmapDay } from '@/components/reports/CalendarHeatmap'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useOrderEventRefresh } from '@/hooks/useOrderEventRefresh'
import { useSupportedExchanges } from '@/hooks/useSupportedExchanges'
import { groupTradesByOrder, ungrouped } from '@/lib/tradeGroups'
import { cn, makeFormatCurrency, sanitizeCSV } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { onModeChange } from '@/stores/themeStore'
import type { Segment, Trade } from '@/types/trading'
import { showToast } from '@/utils/toast'

interface FilterState {
  action: string[]
  exchange: string[]
  product: string[]
}

// Sort configuration types
type SortKey = 'timestamp' | 'symbol' | 'action'
interface SortConfig {
  key: SortKey
  direction: 'asc' | 'desc'
}

// Fork-only historical view (SKYSHIELD_PATCHES.md): mirrors
// database/pnl_db.py's derive_segment()/_EXCHANGE_SEGMENT_MAP exactly.
// Kept in sync by hand since the frontend has no import path into that
// Python module; if that mapping changes, update this one too. Live-today
// Trade objects have no `segment` field at all (the broker's own tradebook
// API doesn't have this concept), so this is the fallback used for those -
// historical rows from GET /api/v1/pnl/trades carry a real stored
// `segment` already and this is never called for them (see
// segmentOf below).
const EXCHANGE_SEGMENT_MAP: Record<string, Segment> = {
  NSE: 'equity',
  BSE: 'equity',
  NFO: 'fno',
  BFO: 'fno',
  CDS: 'currency',
  BCD: 'currency',
  MCX: 'commodity',
  NCDEX: 'commodity',
  NCO: 'commodity',
}

function segmentOf(trade: Trade): Segment | undefined {
  return (trade.segment as Segment | undefined) ?? EXCHANGE_SEGMENT_MAP[trade.exchange]
}

// Local calendar date (en-CA formats YYYY-MM-DD). toISOString() would be the
// UTC date, which is still yesterday before 05:30 IST.
function todayStr(): string {
  return new Date().toLocaleDateString('en-CA')
}

function sevenDaysAgoStr(): string {
  const d = new Date()
  d.setDate(d.getDate() - 7)
  return d.toLocaleDateString('en-CA')
}

/**
 * Helper to convert various broker timestamp formats into a sortable number.
 * Ensures chronological accuracy for non-ISO formats.
 */
function parseTimestamp(timestamp: string): number {
  if (!timestamp) return 0

  let date = new Date(timestamp)

  // If invalid, try "HH:MM:SS DD-MM-YYYY" (Flattrade/Shoonya/Zebu/Firstock norentm format)
  if (Number.isNaN(date.getTime())) {
    const norentm = timestamp.match(/^(\d{2}:\d{2}:\d{2})\s+(\d{2})-(\d{2})-(\d{4})$/)
    if (norentm) {
      date = new Date(`${norentm[4]}-${norentm[3]}-${norentm[2]}T${norentm[1]}`)
    }
  }

  // If invalid, try "DD-MM-YYYY HH:MM:SS"
  if (Number.isNaN(date.getTime())) {
    const ddmmyyyy = timestamp.match(/^(\d{2})-(\d{2})-(\d{4})\s+(\d{2}:\d{2}:\d{2})$/)
    if (ddmmyyyy) {
      date = new Date(`${ddmmyyyy[3]}-${ddmmyyyy[2]}-${ddmmyyyy[1]}T${ddmmyyyy[4]}`)
    }
  }

  return date.getTime() || 0
}

// Full date+time, always - a time-only display on the live (today-only)
// view read as "the date is missing" rather than "this is always today,"
// so both live and historical rows show date+time unconditionally now
// (previously live used a time-only formatTime() and historical showed
// the raw ISO string with no formatting at all). Routes through
// parseTimestamp for the same defensive multi-broker fallback the old
// formatTime had, though rows are always clean ISO in practice (live:
// broker/{zerodha,kotak}/mapping/order_data.py normalizes at the source;
// historical: database/pnl_db.py's parse_trade_timestamp normalizes at
// write time).
function formatDateTime(timestamp: string): string {
  if (!timestamp) return '-'

  const timeValue = parseTimestamp(timestamp)
  if (timeValue === 0) return timestamp

  const date = new Date(timeValue)
  return date.toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

// YYYY-MM-DD bucket key for a trade timestamp, for the heat map below. Most
// timestamps are already ISO-prefixed (historical rows from the ledger);
// non-ISO broker formats fall back through parseTimestamp then read the
// calendar date in the browser's local timezone, matching how Time is
// already displayed via toLocaleTimeString('en-IN', ...) elsewhere on this
// page - not a new timezone assumption, just the existing one applied here
// too.
function dateKeyOf(timestamp: string): string {
  const isoMatch = timestamp.match(/^(\d{4}-\d{2}-\d{2})/)
  if (isoMatch) return isoMatch[1]
  const ms = parseTimestamp(timestamp)
  if (!ms) return ''
  return new Date(ms).toLocaleDateString('en-CA')
}

// Blue-by-trade-count, matching Zerodha Console's own Tradebook heat map:
// lighter shades for fewer trades, darker for more.
function tradeCountHeatColor(value: number, maxAbs: number): string {
  if (value <= 0) return 'rgba(148, 163, 184, 0.12)'
  const intensity = Math.min(value / maxAbs, 1)
  const alpha = 0.2 + intensity * 0.7
  return `rgba(59, 130, 246, ${alpha})`
}

export default function TradeBook() {
  const { apiKey, user } = useAuthStore()
  const { isCrypto } = useSupportedExchanges()
  const formatCurrency = useMemo(() => makeFormatCurrency(user?.broker), [user?.broker])
  const [trades, setTrades] = useState<Trade[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Filter state
  const [filters, setFilters] = useState<FilterState>({
    action: [],
    exchange: [],
    product: [],
  })
  const [settingsOpen, setSettingsOpen] = useState(false)

  // P&L history CSV import (fork-only feature - SKYSHIELD_PATCHES.md)
  const [importDialogOpen, setImportDialogOpen] = useState(false)
  const [importFiles, setImportFiles] = useState<File[]>([])
  const [isImporting, setIsImporting] = useState(false)
  // Which file of the batch is currently uploading - null when idle, so the
  // dialog can show "Importing 2 of 3: <name>" during a multi-file run.
  const [importProgress, setImportProgress] = useState<{ index: number; total: number } | null>(
    null
  )

  // Historical view (fork-only - SKYSHIELD_PATCHES.md). Default date range
  // is the last 7 days, matching the Zerodha Console reference this filter
  // row is modeled on - end date defaults to today, so isHistorical is true
  // by default and fetchTrades starts on the ledger-backed
  // GET /api/v1/pnl/trades. Narrowing the range to today only switches back
  // to the existing live broker call, since today's trades aren't captured
  // into the ledger until the 16:00 IST daily job runs.
  const [segment, setSegment] = useState<'all' | Segment>('all')
  const [symbolFilter, setSymbolFilter] = useState('')
  // Strategy is only ever present on historical (GET /pnl/trades) rows -
  // live-today rows have no way to carry it (see the Trade type's own
  // comment), so filtering to one strategy naturally excludes every live
  // row, same as Segment's own exchange-derived fallback simply not
  // applying to strategy (there's no way to derive a strategy from
  // exchange). Options come from the account's own strategy book
  // (database/strategy_book_db.py, SKYSHIELD_PATCHES.md), same source and
  // pattern as PnlHistory.tsx's Strategy filter.
  // Multi-select: empty array means every strategy.
  const [strategyFilters, setStrategyFilters] = useState<string[]>([])
  const [strategyOptions, setStrategyOptions] = useState<string[]>([])
  // Manual strategy-tag fallback (SKYSHIELD_PATCHES.md) - which historical
  // row, if any, currently has its inline editor open.
  const [editingTradeId, setEditingTradeId] = useState<number | null>(null)
  const [editingValue, setEditingValue] = useState('')
  const [isSavingTag, setIsSavingTag] = useState(false)
  // Fold the fills of one order into a single row (fork-only). Off by
  // default so the table matches the broker's own tradebook until asked.
  const [groupByOrder, setGroupByOrder] = useState(false)
  const [expandedOrders, setExpandedOrders] = useState<Set<string>>(new Set())
  const [startDate, setStartDate] = useState(sevenDaysAgoStr())
  const [endDate, setEndDate] = useState(todayStr())
  const isHistorical = startDate !== todayStr() || endDate !== todayStr()

  // Sort state - Default: most recent first
  const [sortConfig, setSortConfig] = useState<SortConfig>({
    key: 'timestamp',
    direction: 'desc',
  })

  // Filter and Sort trades
  const sortedAndFilteredTrades = useMemo(() => {
    // 1. Filter Logic
    const filtered = trades.filter((trade) => {
      if (filters.action.length > 0 && !filters.action.includes(trade.action)) return false
      if (filters.exchange.length > 0 && !filters.exchange.includes(trade.exchange)) return false
      if (filters.product.length > 0 && !filters.product.includes(trade.product)) return false
      if (segment !== 'all' && segmentOf(trade) !== segment) return false
      if (
        strategyFilters.length > 0 &&
        !(trade.strategy && strategyFilters.includes(trade.strategy))
      )
        return false
      if (symbolFilter && !trade.symbol.toUpperCase().includes(symbolFilter.trim().toUpperCase()))
        return false
      return true
    })

    // 2. Sort Logic
    return [...filtered].sort((a, b) => {
      const aValue = a[sortConfig.key]
      const bValue = b[sortConfig.key]

      if (sortConfig.key === 'timestamp') {
        const aTime = parseTimestamp(aValue as string)
        const bTime = parseTimestamp(bValue as string)
        return sortConfig.direction === 'asc' ? aTime - bTime : bTime - aTime
      }

      // Standard alphabetical sort for Symbol and Action
      if (aValue < bValue) return sortConfig.direction === 'asc' ? -1 : 1
      if (aValue > bValue) return sortConfig.direction === 'asc' ? 1 : -1
      return 0
    })
  }, [trades, filters, segment, strategyFilters, symbolFilter, sortConfig])

  const displayGroups = useMemo(
    () =>
      groupByOrder
        ? groupTradesByOrder(sortedAndFilteredTrades)
        : ungrouped(sortedAndFilteredTrades),
    [groupByOrder, sortedAndFilteredTrades]
  )

  const toggleOrderExpanded = (key: string) => {
    setExpandedOrders((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // Heat map data, grouping the already-filtered trades by day. Scoped to
  // whatever Segment/Symbol/date range is currently applied, same as
  // Zerodha Console's own Tradebook heat map being scoped to its own
  // segment + duration picker.
  const tradeHeatmapDays: CalendarHeatmapDay[] = useMemo(() => {
    const counts = new Map<string, number>()
    for (const trade of sortedAndFilteredTrades) {
      const key = dateKeyOf(trade.timestamp)
      if (!key) continue
      counts.set(key, (counts.get(key) ?? 0) + 1)
    }
    return Array.from(counts.entries()).map(([date, count]) => ({
      date,
      value: count,
      tooltip: `${date}: ${count} trade${count === 1 ? '' : 's'}`,
    }))
  }, [sortedAndFilteredTrades])

  const requestSort = (key: SortKey) => {
    setSortConfig((prev) => ({
      key,
      direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc',
    }))
  }

  const hasActiveFilters =
    filters.action.length > 0 ||
    filters.exchange.length > 0 ||
    filters.product.length > 0 ||
    symbolFilter.trim() !== '' ||
    strategyFilters.length > 0

  const toggleFilter = (type: keyof FilterState, value: string) => {
    setFilters((prev) => {
      const arr = prev[type]
      const index = arr.indexOf(value)
      if (index > -1) {
        return { ...prev, [type]: arr.filter((v) => v !== value) }
      }
      return { ...prev, [type]: [...arr, value] }
    })
  }

  const clearFilters = () => {
    setFilters({ action: [], exchange: [], product: [] })
    setSymbolFilter('')
    setStrategyFilters([])
  }

  const fetchTrades = useCallback(
    async (showRefresh = false) => {
      if (!apiKey) {
        setIsLoading(false)
        return
      }

      if (showRefresh) setIsRefreshing(true)

      try {
        // A date range other than "today" switches to the ledger-backed
        // historical endpoint - see the isHistorical comment above. Segment/
        // Symbol/Strategy stay client-side filters applied uniformly to either
        // source in sortedAndFilteredTrades, rather than branching here too.
        const response = isHistorical
          ? await tradingApi.getPnlTrades(apiKey, startDate, endDate)
          : await tradingApi.getTrades(apiKey)
        if (response.status === 'success' && response.data) {
          setTrades(response.data)
          setError(null)
        } else {
          setError(response.message || 'Failed to fetch trades')
        }
      } catch {
        setError('Failed to fetch trades')
      } finally {
        setIsLoading(false)
        setIsRefreshing(false)
      }
    },
    [apiKey, isHistorical, startDate, endDate]
  )

  // Runs once on mount (and again if apiKey only becomes available after
  // mount) - deliberately not depending on fetchTrades itself, which also
  // changes identity on every Segment/Symbol/date edit. Re-fetching on
  // every such edit would fire a request per keystroke/date-picker
  // interaction; the explicit Fetch button below is the trigger for that
  // instead, matching PnlHistory.tsx's pattern.
  // biome-ignore lint/correctness/useExhaustiveDependencies: intentional - see comment above
  useEffect(() => {
    fetchTrades()
  }, [apiKey])

  // Populates the Strategy filter's options - same pattern as
  // PnlHistory.tsx, fetched once rather than derived from whatever trades
  // happen to be loaded right now.
  useEffect(() => {
    if (!apiKey) return
    tradingApi
      .getStrategyLegs(apiKey)
      .then((response) => {
        if (response.status === 'success' && response.data) {
          setStrategyOptions(Array.from(new Set(response.data.map((leg) => leg.strategy))).sort())
        }
      })
      .catch(() => {
        // Best-effort - see the identical comment in PnlHistory.tsx.
      })
  }, [apiKey])

  // Refresh on order events instead of polling
  useOrderEventRefresh(fetchTrades, {
    events: ['order_event', 'analyzer_update'],
  })

  // Listen for mode changes (live/analyze) and refresh data
  useEffect(() => {
    const unsubscribe = onModeChange(() => {
      fetchTrades()
    })
    return () => unsubscribe()
  }, [fetchTrades])

  const exportToCSV = () => {
    if (sortedAndFilteredTrades.length === 0) {
      showToast.error('No data to export', 'system')
      return
    }

    try {
      const headers = [
        'Symbol',
        'Exchange',
        ...(isCrypto ? [] : ['Product']),
        'Action',
        'Qty',
        'Price',
        'Trade Value',
        'Order ID',
        'Trade ID',
        'Time',
      ]
      const rows = sortedAndFilteredTrades.map((t) => [
        sanitizeCSV(t.symbol),
        sanitizeCSV(t.exchange),
        ...(isCrypto ? [] : [sanitizeCSV(t.product)]),
        sanitizeCSV(t.action),
        sanitizeCSV(t.quantity),
        sanitizeCSV(t.average_price),
        sanitizeCSV(t.trade_value),
        sanitizeCSV(t.orderid),
        sanitizeCSV(t.tradeid || ''),
        sanitizeCSV(t.timestamp),
      ])

      const csv = [headers, ...rows].map((row) => row.join(',')).join('\n')
      const blob = new Blob([csv], { type: 'text/csv' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const filename = `tradebook_${new Date().toISOString().split('T')[0]}.csv`
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
      showToast.success(`Downloaded ${filename}`, 'clipboard')
    } catch {
      showToast.error('Failed to export CSV', 'system')
    }
  }

  // P&L history CSV import (fork-only feature, backfills the consolidated
  // multi-day P&L ledger - see openalgo's SKYSHIELD_PATCHES.md). Distinct
  // from exportToCSV above: this uploads a broker-exported tradebook CSV
  // rather than downloading the currently-filtered view.
  //
  // Files are sent one request per file, sequentially - not batched into a
  // single request - because the backend commits an entire CSV as one
  // transaction (services/pnl_history_service.py::import_trades_csv): one
  // bad row anywhere in a combined upload would roll back every file, not
  // just the offending one. A broker typically exports equity and F&O as
  // two separate CSVs (see the tradebook page's own filter row), so this
  // also lets both go in as one action without either one's failure
  // silently discarding the other's rows.
  const importPnlHistory = async () => {
    if (!apiKey) {
      showToast.error('API key not available', 'system')
      return
    }
    if (importFiles.length === 0) {
      showToast.warning('Please select at least one CSV file', 'system')
      return
    }

    setIsImporting(true)
    let totalImported = 0
    let totalDuplicate = 0
    let totalInvalid = 0
    const failedFiles: string[] = []

    try {
      for (let i = 0; i < importFiles.length; i++) {
        const file = importFiles[i]
        setImportProgress({ index: i + 1, total: importFiles.length })
        try {
          const response = await tradingApi.importPnlHistoryCsv(apiKey, file)
          if (response.status === 'success' && response.data) {
            totalImported += response.data.imported
            totalDuplicate += response.data.skipped_duplicate
            totalInvalid += response.data.skipped_invalid
          } else {
            failedFiles.push(file.name)
          }
        } catch {
          // Isolated per file - one file's failure (a 500 from a bad row,
          // a network blip) must not abort the rest of the batch.
          failedFiles.push(file.name)
        }
      }

      if (totalImported || totalDuplicate || totalInvalid) {
        showToast.success(
          `Imported ${totalImported} trade(s)` +
            (totalDuplicate ? `, ${totalDuplicate} already had them` : '') +
            (totalInvalid ? `, ${totalInvalid} row(s) could not be read` : ''),
          'clipboard'
        )
      }
      if (failedFiles.length > 0) {
        showToast.error(`Failed to import: ${failedFiles.join(', ')}`, 'system')
      }

      if (failedFiles.length === 0) {
        setImportDialogOpen(false)
        setImportFiles([])
      } else {
        // Leave the successfully-imported files out, keep the failed ones
        // selected so the user can retry just those without reselecting.
        setImportFiles((prev) => prev.filter((f) => failedFiles.includes(f.name)))
      }
    } finally {
      setIsImporting(false)
      setImportProgress(null)
    }
  }

  // Manual strategy-tag fallback for one historical row (fork-only -
  // SKYSHIELD_PATCHES.md) - for CSV-imported history and anything placed
  // with no orderid to automatically join against the strategy book.
  // Updates local state in place rather than a full refetch, since the
  // PATCH already returns the saved value.
  const saveTradeStrategy = async (trade: Trade) => {
    if (!apiKey || trade.id === undefined) return
    const value = editingValue.trim()
    if (!value) {
      showToast.warning('Strategy cannot be empty', 'system')
      return
    }

    setIsSavingTag(true)
    try {
      const response = await tradingApi.setTradeStrategy(apiKey, trade.id, value)
      if (response.status === 'success' && response.data) {
        // The tag is set on every fill of the order, so mirror that here.
        const updated = new Set(response.data.updated_ids ?? [trade.id])
        setTrades((prev) =>
          prev.map((t) =>
            t.id !== undefined && updated.has(t.id)
              ? { ...t, strategy: response.data?.strategy }
              : t
          )
        )
        setEditingTradeId(null)
        showToast.success(`Tagged as ${response.data.strategy}`, 'clipboard')
      } else {
        showToast.error(response.message || 'Failed to save strategy tag', 'system')
      }
    } catch {
      showToast.error('Failed to save strategy tag', 'system')
    } finally {
      setIsSavingTag(false)
    }
  }

  const FilterChip = ({
    type,
    value,
    label,
  }: {
    type: keyof FilterState
    value: string
    label: string
  }) => (
    <Button
      variant={filters[type].includes(value) ? 'default' : 'outline'}
      size="sm"
      className={cn(
        'rounded-full',
        filters[type].includes(value) && 'bg-pink-500 hover:bg-pink-600'
      )}
      onClick={() => toggleFilter(type, value)}
    >
      {label}
    </Button>
  )

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Trade Book</h1>
          <p className="text-muted-foreground">
            {isHistorical
              ? 'Historical trades from the consolidated P&L ledger'
              : "View today's executed trades"}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* P&L history CSV import (fork-only) */}
          <Dialog
            open={importDialogOpen}
            onOpenChange={(open) => {
              setImportDialogOpen(open)
              if (!open) setImportFiles([])
            }}
          >
            <DialogTrigger asChild>
              <Button variant="outline" size="sm" aria-label="Import P&L history from CSV">
                <Upload className="h-4 w-4 mr-2" />
                Upload
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-md">
              <DialogHeader>
                <DialogTitle>Import P&L History</DialogTitle>
                <DialogDescription>
                  Upload exported tradebook CSVs (e.g. separate equity and F&O exports) to backfill
                  historical P&L for dates before automated capture started. Trades already recorded
                  are skipped automatically.
                </DialogDescription>
              </DialogHeader>
              <div className="py-2 space-y-3">
                <div>
                  <Label htmlFor="pnl-import-file">Tradebook CSV(s)</Label>
                  <Input
                    id="pnl-import-file"
                    type="file"
                    accept=".csv"
                    multiple
                    className="mt-2"
                    disabled={isImporting}
                    onChange={(e) => setImportFiles(Array.from(e.target.files ?? []))}
                  />
                </div>
                {importFiles.length > 0 && (
                  <ul className="space-y-1 max-h-32 overflow-y-auto">
                    {importFiles.map((file, index) => (
                      <li
                        key={`${file.name}-${index}`}
                        className="flex items-center justify-between text-sm text-muted-foreground bg-muted/50 rounded px-2 py-1"
                      >
                        <span className="truncate">{file.name}</span>
                        {!isImporting && (
                          <button
                            type="button"
                            aria-label={`Remove ${file.name}`}
                            onClick={() =>
                              setImportFiles((prev) => prev.filter((_, i) => i !== index))
                            }
                            className="ml-2 shrink-0 hover:text-foreground"
                          >
                            <X className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                {importProgress && (
                  <p className="text-sm text-muted-foreground">
                    Importing file {importProgress.index} of {importProgress.total}
                    {importFiles[importProgress.index - 1]
                      ? `: ${importFiles[importProgress.index - 1].name}`
                      : ''}
                  </p>
                )}
              </div>
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => setImportDialogOpen(false)}
                  disabled={isImporting}
                >
                  Cancel
                </Button>
                <Button
                  onClick={importPnlHistory}
                  disabled={isImporting || importFiles.length === 0}
                >
                  {isImporting ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <Upload className="h-4 w-4 mr-2" />
                  )}
                  Upload{importFiles.length > 1 ? ` (${importFiles.length})` : ''}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Segment / Date range (fork-only - SKYSHIELD_PATCHES.md). Same layout
          as PnlHistory.tsx's fetch row. Symbol and Strategy live in the Filters
          popup above the table, since they only narrow the rows already
          fetched. Leaving the date range at today keeps this page on the
          existing live broker view untouched - see isHistorical. */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex flex-col sm:flex-row sm:items-end gap-4">
            <div className="flex-1 space-y-1">
              <Label htmlFor="tb-segment">Segment</Label>
              <Select value={segment} onValueChange={(v) => setSegment(v as typeof segment)}>
                <SelectTrigger id="tb-segment">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All</SelectItem>
                  <SelectItem value="equity">Equity</SelectItem>
                  <SelectItem value="fno">Futures & Options</SelectItem>
                  <SelectItem value="currency">Currency</SelectItem>
                  <SelectItem value="commodity">Commodity</SelectItem>
                  <SelectItem value="mutual_fund">Mutual Funds</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1 space-y-1">
              <Label htmlFor="tb-start-date">Start date</Label>
              <Input
                id="tb-start-date"
                type="date"
                value={startDate}
                max={endDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div className="flex-1 space-y-1">
              <Label htmlFor="tb-end-date">End date</Label>
              <Input
                id="tb-end-date"
                type="date"
                value={endDate}
                min={startDate}
                max={todayStr()}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
            <Button
              onClick={() => fetchTrades(true)}
              disabled={isRefreshing}
              aria-label="Fetch trades for the selected filters"
            >
              {isRefreshing ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4 mr-2" />
              )}
              Fetch
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Heat Map, matching Zerodha Console's own Tradebook heat map - a
          calendar grid colored blue by that day's trade count, shade
          intensity scaled to volume. */}
      {tradeHeatmapDays.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Heat Map</CardTitle>
            <CardDescription>
              Trades per day - darker means more trades. Hover a day for details.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto pb-2">
              <CalendarHeatmap
                days={tradeHeatmapDays}
                startDate={startDate}
                endDate={endDate}
                colorFor={tradeCountHeatColor}
              />
            </div>
            <div className="flex items-center gap-2 mt-4 text-xs text-muted-foreground">
              <span>Fewer</span>
              <span
                className="w-4 h-4 rounded-sm"
                style={{ backgroundColor: 'rgba(59, 130, 246, 0.2)' }}
              />
              <span
                className="w-4 h-4 rounded-sm"
                style={{ backgroundColor: 'rgba(59, 130, 246, 0.45)' }}
              />
              <span
                className="w-4 h-4 rounded-sm"
                style={{ backgroundColor: 'rgba(59, 130, 246, 0.7)' }}
              />
              <span
                className="w-4 h-4 rounded-sm"
                style={{ backgroundColor: 'rgba(59, 130, 246, 0.9)' }}
              />
              <span>More</span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Table toolbar: Filters and Export act on the fetched rows below only,
          so they sit directly above the table, top right. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {groupByOrder
            ? `${displayGroups.length} order${displayGroups.length === 1 ? '' : 's'} (${sortedAndFilteredTrades.length} fills)`
            : `${sortedAndFilteredTrades.length} trade${sortedAndFilteredTrades.length === 1 ? '' : 's'}`}
        </p>
        <div className="flex items-center gap-2">
          <Label
            htmlFor="group-by-order"
            className="flex items-center gap-2 text-sm font-normal cursor-pointer"
          >
            <Switch
              id="group-by-order"
              checked={groupByOrder}
              onCheckedChange={setGroupByOrder}
              aria-label="Group fills by order"
            />
            Group by order
          </Label>
          <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
            <DialogTrigger asChild>
              <Button
                variant={hasActiveFilters ? 'default' : 'outline'}
                size="sm"
                className="relative"
                aria-label="Open trade filters"
              >
                <Settings2 className="h-4 w-4 mr-2" />
                Filters
                {hasActiveFilters && (
                  <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-red-500 rounded-full" />
                )}
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-md">
              <DialogHeader>
                <DialogTitle>Trade Filters</DialogTitle>
                <DialogDescription>
                  Filter trades by action, exchange, product, symbol or strategy
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-6 py-4">
                {/* Action */}
                <div className="space-y-3">
                  <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Action
                  </Label>
                  <div className="flex flex-wrap gap-2">
                    <FilterChip type="action" value="BUY" label="Buy" />
                    <FilterChip type="action" value="SELL" label="Sell" />
                  </div>
                </div>

                {/* Exchange */}
                <div className="space-y-3">
                  <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Exchange
                  </Label>
                  <div className="flex flex-wrap gap-2">
                    <FilterChip type="exchange" value="NSE" label="NSE" />
                    <FilterChip type="exchange" value="BSE" label="BSE" />
                    <FilterChip type="exchange" value="NFO" label="NFO" />
                    <FilterChip type="exchange" value="BFO" label="BFO" />
                    <FilterChip type="exchange" value="MCX" label="MCX" />
                    <FilterChip type="exchange" value="CDS" label="CDS" />
                  </div>
                </div>

                {/* Product */}
                {!isCrypto && (
                  <div className="space-y-3">
                    <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      Product
                    </Label>
                    <div className="flex flex-wrap gap-2">
                      <FilterChip type="product" value="CNC" label="CNC" />
                      <FilterChip type="product" value="MIS" label="MIS" />
                      <FilterChip type="product" value="NRML" label="NRML" />
                    </div>
                  </div>
                )}

                {/* Symbol */}
                <div className="space-y-3">
                  <Label
                    htmlFor="tb-filter-symbol"
                    className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
                  >
                    Symbol
                  </Label>
                  <Input
                    id="tb-filter-symbol"
                    placeholder="e.g. INFY"
                    value={symbolFilter}
                    onChange={(e) => setSymbolFilter(e.target.value)}
                  />
                </div>

                {/* Strategy (multi-select; none selected means all) */}
                <div className="space-y-3">
                  <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Strategy
                  </Label>
                  <div className="flex flex-wrap gap-2">
                    {strategyOptions.length === 0 && (
                      <span className="text-sm text-muted-foreground">No strategies tracked</span>
                    )}
                    {strategyOptions.map((name) => {
                      const selected = strategyFilters.includes(name)
                      return (
                        <Button
                          key={name}
                          type="button"
                          size="sm"
                          variant={selected ? 'default' : 'outline'}
                          className={cn(
                            'rounded-full',
                            selected && 'bg-pink-500 hover:bg-pink-600'
                          )}
                          onClick={() =>
                            setStrategyFilters((prev) =>
                              selected ? prev.filter((n) => n !== name) : [...prev, name]
                            )
                          }
                        >
                          {name}
                        </Button>
                      )
                    })}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Live (today-only) rows carry no strategy.
                  </p>
                </div>
              </div>

              <DialogFooter>
                <Button variant="ghost" onClick={clearFilters}>
                  Clear All
                </Button>
                <Button onClick={() => setSettingsOpen(false)}>Done</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Button
            variant="outline"
            size="sm"
            onClick={exportToCSV}
            aria-label="Export tradebook to CSV"
          >
            <Download className="h-4 w-4 mr-2" />
            Export
          </Button>
        </div>
      </div>

      {/* Active Filters Bar */}
      {hasActiveFilters && (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-muted-foreground">Active Filters:</span>
          {filters.action.map((v) => (
            <Badge
              key={v}
              variant="secondary"
              className="bg-pink-500/10 text-pink-600 border-pink-500/30"
            >
              {v}
            </Badge>
          ))}
          {filters.exchange.map((v) => (
            <Badge
              key={v}
              variant="secondary"
              className="bg-pink-500/10 text-pink-600 border-pink-500/30"
            >
              {v}
            </Badge>
          ))}
          {symbolFilter.trim() !== '' && (
            <Badge variant="secondary" className="bg-pink-500/10 text-pink-600 border-pink-500/30">
              {symbolFilter.trim().toUpperCase()}
            </Badge>
          )}
          {strategyFilters.map((v) => (
            <Badge
              key={v}
              variant="secondary"
              className="bg-pink-500/10 text-pink-600 border-pink-500/30"
            >
              {v}
            </Badge>
          ))}
          {!isCrypto &&
            filters.product.map((v) => (
              <Badge
                key={v}
                variant="secondary"
                className="bg-pink-500/10 text-pink-600 border-pink-500/30"
              >
                {v}
              </Badge>
            ))}
          <Button
            variant="outline"
            size="sm"
            className="text-red-500 border-red-500/50 hover:bg-red-500/10"
            onClick={clearFilters}
            aria-label="Clear active filters"
          >
            Clear All
          </Button>
        </div>
      )}

      {/* Trades Table */}
      <Card>
        <CardContent className="py-0">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin" />
            </div>
          ) : error ? (
            <div className="text-center py-12 text-muted-foreground">{error}</div>
          ) : sortedAndFilteredTrades.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              {hasActiveFilters ? (
                <div>
                  <p className="mb-4">No trades match your filters</p>
                  <Button variant="ghost" size="sm" onClick={clearFilters}>
                    Clear Filters
                  </Button>
                </div>
              ) : isHistorical ? (
                'No trades in this date range'
              ) : (
                'No trades today'
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead
                      onClick={() => requestSort('symbol')}
                      className="cursor-pointer hover:bg-muted/50 transition-colors"
                    >
                      <div className="flex items-center gap-1">
                        Symbol
                        {sortConfig.key === 'symbol' &&
                          (sortConfig.direction === 'asc' ? (
                            <ArrowUp className="h-3 w-3" />
                          ) : (
                            <ArrowDown className="h-3 w-3" />
                          ))}
                      </div>
                    </TableHead>
                    <TableHead>Exchange</TableHead>
                    {!isCrypto && <TableHead>Product</TableHead>}
                    <TableHead
                      onClick={() => requestSort('action')}
                      className="cursor-pointer hover:bg-muted/50 transition-colors"
                    >
                      <div className="flex items-center gap-1">
                        Action
                        {sortConfig.key === 'action' &&
                          (sortConfig.direction === 'asc' ? (
                            <ArrowUp className="h-3 w-3" />
                          ) : (
                            <ArrowDown className="h-3 w-3" />
                          ))}
                      </div>
                    </TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Price</TableHead>
                    <TableHead className="text-right">Trade Value</TableHead>
                    <TableHead>Order ID</TableHead>
                    <TableHead>Trade ID</TableHead>
                    {isHistorical && <TableHead>Strategy</TableHead>}
                    <TableHead
                      onClick={() => requestSort('timestamp')}
                      className="cursor-pointer hover:bg-muted/50 transition-colors"
                    >
                      <div className="flex items-center gap-1">
                        Time
                        {sortConfig.key === 'timestamp' &&
                          (sortConfig.direction === 'asc' ? (
                            <ArrowUp className="h-3 w-3" />
                          ) : (
                            <ArrowDown className="h-3 w-3" />
                          ))}
                      </div>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {displayGroups.flatMap((group) => {
                    const trade = group.trade
                    const isGroup = group.fills.length > 1
                    const isExpanded = isGroup && expandedOrders.has(group.key)
                    const rows = [
                      <TableRow key={group.key}>
                        <TableCell className="font-medium">{trade.symbol}</TableCell>
                        <TableCell>
                          <Badge variant="outline">{trade.exchange}</Badge>
                        </TableCell>
                        {!isCrypto && (
                          <TableCell>
                            <Badge variant="secondary">{trade.product}</Badge>
                          </TableCell>
                        )}
                        <TableCell>
                          <Badge
                            variant={trade.action === 'BUY' ? 'default' : 'destructive'}
                            className={cn('gap-1', trade.action === 'BUY' ? 'bg-green-500' : '')}
                          >
                            {trade.action === 'BUY' ? (
                              <TrendingUp className="h-3 w-3" />
                            ) : (
                              <TrendingDown className="h-3 w-3" />
                            )}
                            {trade.action}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right font-mono">{trade.quantity}</TableCell>
                        <TableCell className="text-right font-mono">
                          {formatCurrency(trade.average_price)}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {formatCurrency(trade.trade_value)}
                        </TableCell>
                        <TableCell className="font-mono text-xs">{trade.orderid}</TableCell>
                        <TableCell className="font-mono text-xs">
                          {isGroup ? (
                            <button
                              type="button"
                              className="flex items-center gap-1 hover:underline"
                              onClick={() => toggleOrderExpanded(group.key)}
                              aria-label={isExpanded ? 'Hide fills' : 'Show fills'}
                            >
                              {isExpanded ? (
                                <ChevronDown className="h-3 w-3" />
                              ) : (
                                <ChevronRight className="h-3 w-3" />
                              )}
                              {group.fills.length} fills
                            </button>
                          ) : (
                            trade.tradeid || '-'
                          )}
                        </TableCell>
                        {isHistorical && (
                          <TableCell>
                            {editingTradeId === trade.id ? (
                              <div className="flex items-center gap-1">
                                <Input
                                  autoFocus
                                  value={editingValue}
                                  onChange={(e) => setEditingValue(e.target.value)}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter') saveTradeStrategy(trade)
                                    if (e.key === 'Escape') setEditingTradeId(null)
                                  }}
                                  className="h-7 w-32 text-xs"
                                  placeholder="Strategy name"
                                />
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 w-7 p-0"
                                  disabled={isSavingTag}
                                  onClick={() => saveTradeStrategy(trade)}
                                  aria-label="Save strategy tag"
                                >
                                  <Check className="h-3.5 w-3.5" />
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-7 w-7 p-0"
                                  onClick={() => setEditingTradeId(null)}
                                  aria-label="Cancel"
                                >
                                  <X className="h-3.5 w-3.5" />
                                </Button>
                              </div>
                            ) : (
                              <button
                                type="button"
                                className="text-xs text-left hover:underline"
                                onClick={() => {
                                  setEditingTradeId(trade.id ?? null)
                                  setEditingValue(trade.strategy || '')
                                }}
                                aria-label={
                                  trade.strategy ? `Edit strategy tag` : 'Add strategy tag'
                                }
                              >
                                {trade.strategy ? (
                                  <>
                                    {trade.strategy}
                                    {group.partiallyTagged && (
                                      <span className="text-muted-foreground"> (some fills)</span>
                                    )}
                                  </>
                                ) : (
                                  <span className="text-muted-foreground">+ Tag</span>
                                )}
                              </button>
                            )}
                          </TableCell>
                        )}
                        <TableCell className="text-sm text-muted-foreground">
                          {formatDateTime(trade.timestamp)}
                        </TableCell>
                      </TableRow>,
                    ]
                    if (isExpanded) {
                      group.fills.forEach((fill, fillIndex) => {
                        rows.push(
                          <TableRow
                            key={`${group.key}-fill-${fill.tradeid ?? fill.id ?? fillIndex}`}
                            className="bg-muted/30 text-muted-foreground"
                          >
                            <TableCell colSpan={isCrypto ? 3 : 4} className="text-xs pl-8">
                              fill {fillIndex + 1}
                            </TableCell>
                            <TableCell className="text-right font-mono text-xs">
                              {fill.quantity}
                            </TableCell>
                            <TableCell className="text-right font-mono text-xs">
                              {formatCurrency(fill.average_price)}
                            </TableCell>
                            <TableCell className="text-right font-mono text-xs">
                              {formatCurrency(fill.trade_value)}
                            </TableCell>
                            <TableCell />
                            <TableCell className="font-mono text-xs">
                              {fill.tradeid || '-'}
                            </TableCell>
                            {isHistorical && <TableCell />}
                            <TableCell className="text-xs">
                              {formatDateTime(fill.timestamp)}
                            </TableCell>
                          </TableRow>
                        )
                      })
                    }
                    return rows
                  })}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
