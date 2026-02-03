import { useEffect, useMemo, useState } from 'react'
import { RefreshCw, TrendingUp } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { useOptionChainSSE } from '@/hooks/useOptionChainSSE'
import { useOptionChainPreferences } from '@/hooks/useOptionChainPreferences'
import { optionChainApi } from '@/api/option-chain'
import type { BarDataSource, BarStyle, ColumnKey, OptionStrike } from '@/types/option-chain'
import { COLUMN_DEFINITIONS } from '@/types/option-chain'
import { BarSettingsDropdown, ColumnConfigDropdown, ColumnReorderPanel } from '@/components/option-chain'
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
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

const UNDERLYINGS = [
  { value: 'NIFTY', label: 'NIFTY', exchange: 'NFO', brokerExchange: 'NSE_INDEX' },
  { value: 'BANKNIFTY', label: 'BANKNIFTY', exchange: 'NFO', brokerExchange: 'NSE_INDEX' },
  { value: 'SENSEX', label: 'SENSEX', exchange: 'BFO', brokerExchange: 'BSE_INDEX' },
  { value: 'FINNIFTY', label: 'FINNIFTY', exchange: 'NFO', brokerExchange: 'NSE_INDEX' },
  { value: 'MIDCPNIFTY', label: 'MIDCPNIFTY', exchange: 'NFO', brokerExchange: 'NSE_INDEX' },
]

const STRIKE_COUNTS = [
  { value: 5, label: '5 strikes' },
  { value: 10, label: '10 strikes' },
  { value: 15, label: '15 strikes' },
  { value: 20, label: '20 strikes' },
  { value: 25, label: '25 strikes' },
]

// Column widths in pixels for proper alignment
const COLUMN_WIDTHS: Record<ColumnKey, number> = {
  ce_oi: 80,
  ce_volume: 80,
  ce_bid_qty: 60,
  ce_bid: 70,
  ce_ltp: 80,
  ce_ask: 70,
  ce_ask_qty: 60,
  ce_spread: 60,
  strike: 80,
  pe_spread: 60,
  pe_ask_qty: 60,
  pe_ask: 70,
  pe_ltp: 80,
  pe_bid: 70,
  pe_bid_qty: 60,
  pe_volume: 80,
  pe_oi: 80,
}

// Format number in lakhs (divide by 100000)
function formatInLakhs(num: number | undefined | null): string {
  if (num === undefined || num === null || num === 0) return '0'
  const lakhs = num / 100000
  if (lakhs >= 100) {
    return lakhs.toFixed(0) + 'L'
  } else if (lakhs >= 10) {
    return lakhs.toFixed(1) + 'L'
  } else if (lakhs >= 1) {
    return lakhs.toFixed(2) + 'L'
  } else {
    // Less than 1 lakh, show in thousands
    const thousands = num / 1000
    if (thousands >= 1) {
      return thousands.toFixed(1) + 'K'
    }
    return num.toLocaleString()
  }
}

function formatPrice(num: number | undefined | null): string {
  if (num === undefined || num === null) return '0.00'
  return num.toFixed(2)
}

function convertExpiryForAPI(expiry: string): string {
  if (!expiry) return ''
  const parts = expiry.split('-')
  if (parts.length === 3) {
    return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
  }
  return expiry.replace(/-/g, '').toUpperCase()
}

function calculatePCR(chain: OptionStrike[]): number {
  let totalCeOi = 0
  let totalPeOi = 0

  chain.forEach((strike) => {
    if (strike.ce?.oi) totalCeOi += strike.ce.oi
    if (strike.pe?.oi) totalPeOi += strike.pe?.oi ?? 0
  })

  if (totalCeOi === 0) return 0
  return totalPeOi / totalCeOi
}

function calculateTotals(chain: OptionStrike[]): { ceVolume: number; peVolume: number; ceOi: number; peOi: number } {
  let ceVolume = 0
  let peVolume = 0
  let ceOi = 0
  let peOi = 0

  chain.forEach((strike) => {
    if (strike.ce) {
      ceVolume += strike.ce.volume ?? 0
      ceOi += strike.ce.oi ?? 0
    }
    if (strike.pe) {
      peVolume += strike.pe.volume ?? 0
      peOi += strike.pe.oi ?? 0
    }
  })

  return { ceVolume, peVolume, ceOi, peOi }
}

function getMaxValue(chain: OptionStrike[], dataSource: BarDataSource): number {
  let maxVal = 0
  chain.forEach((strike) => {
    const ceVal = dataSource === 'oi' ? strike.ce?.oi : strike.ce?.volume
    const peVal = dataSource === 'oi' ? strike.pe?.oi : strike.pe?.volume
    if (ceVal && ceVal > maxVal) maxVal = ceVal
    if (peVal && peVal > maxVal) maxVal = peVal
  })
  return maxVal || 1
}

interface OptionChainRowProps {
  strike: OptionStrike
  previousData: Map<number, OptionStrike>
  maxBarValue: number
  visibleCeColumns: ColumnKey[]
  visiblePeColumns: ColumnKey[]
  barDataSource: BarDataSource
  barStyle: BarStyle
}

function OptionChainRow({
  strike,
  previousData,
  maxBarValue,
  visibleCeColumns,
  visiblePeColumns,
  barDataSource,
  barStyle,
}: OptionChainRowProps) {
  const previous = previousData.get(strike.strike)
  const ce = strike.ce
  const pe = strike.pe
  const label = ce?.label ?? pe?.label ?? ''
  const isATM = label === 'ATM'

  // For CE: OTM means strike > ATM (label starts with OTM)
  // For PE: OTM means strike < ATM (which is ITM for CE)
  const isCeOTM = label.startsWith('OTM')
  const isPeOTM = label.startsWith('ITM')

  const ceLtpChanged = previous?.ce?.ltp !== ce?.ltp
  const peLtpChanged = previous?.pe?.ltp !== pe?.ltp

  const ceFlashClass = ceLtpChanged ? (ce && previous?.ce && ce.ltp > previous.ce.ltp ? 'bg-green-500/30' : 'bg-red-500/30') : ''
  const peFlashClass = peLtpChanged ? (pe && previous?.pe && pe.ltp > previous.pe.ltp ? 'bg-green-500/30' : 'bg-red-500/30') : ''

  const ceSpread = ce && ce.bid > 0 && ce.ask > 0 ? ce.ask - ce.bid : 0
  const peSpread = pe && pe.bid > 0 && pe.ask > 0 ? pe.ask - pe.bid : 0

  const ceSpreadClass = ceSpread <= 1 ? 'text-green-500' : ceSpread <= 2 ? 'text-yellow-500' : 'text-red-500'
  const peSpreadClass = peSpread <= 1 ? 'text-green-500' : peSpread <= 2 ? 'text-yellow-500' : 'text-red-500'

  // Bar values based on data source
  const ceBarValue = barDataSource === 'oi' ? ce?.oi : ce?.volume
  const peBarValue = barDataSource === 'oi' ? pe?.oi : pe?.volume
  const ceBarPercent = ceBarValue ? Math.min((ceBarValue / maxBarValue) * 100, 100) : 0
  const peBarPercent = peBarValue ? Math.min((peBarValue / maxBarValue) * 100, 100) : 0

  // Bar styles
  const ceBarClass = barStyle === 'gradient'
    ? 'bg-gradient-to-r from-green-500/25 to-transparent'
    : 'bg-green-500/20'
  const peBarClass = barStyle === 'gradient'
    ? 'bg-gradient-to-l from-red-500/25 to-transparent'
    : 'bg-red-500/20'

  const getCeColumnValue = (key: ColumnKey) => {
    switch (key) {
      case 'ce_oi':
        return <span className="font-mono text-xs">{formatInLakhs(ce?.oi)}</span>
      case 'ce_volume':
        return <span className="font-mono text-xs">{formatInLakhs(ce?.volume)}</span>
      case 'ce_bid_qty':
        return <span className="text-xs">{ce?.bid ? 0 : 0}</span>
      case 'ce_bid':
        return <span className="text-red-500 text-xs">{formatPrice(ce?.bid)}</span>
      case 'ce_ltp':
        return <span className={cn('font-semibold text-xs', ceFlashClass)}>{formatPrice(ce?.ltp)}</span>
      case 'ce_ask':
        return <span className="text-green-500 text-xs">{formatPrice(ce?.ask)}</span>
      case 'ce_ask_qty':
        return <span className="text-xs">{ce?.ask ? 0 : 0}</span>
      case 'ce_spread':
        return <span className={cn('text-xs', ceSpreadClass)}>{formatPrice(ceSpread)}</span>
      default:
        return null
    }
  }

  const getPeColumnValue = (key: ColumnKey) => {
    switch (key) {
      case 'pe_oi':
        return <span className="font-mono text-xs">{formatInLakhs(pe?.oi)}</span>
      case 'pe_volume':
        return <span className="font-mono text-xs">{formatInLakhs(pe?.volume)}</span>
      case 'pe_bid_qty':
        return <span className="text-xs">{pe?.bid ? 0 : 0}</span>
      case 'pe_bid':
        return <span className="text-red-500 text-xs">{formatPrice(pe?.bid)}</span>
      case 'pe_ltp':
        return <span className={cn('font-semibold text-xs', peFlashClass)}>{formatPrice(pe?.ltp)}</span>
      case 'pe_ask':
        return <span className="text-green-500 text-xs">{formatPrice(pe?.ask)}</span>
      case 'pe_ask_qty':
        return <span className="text-xs">{pe?.ask ? 0 : 0}</span>
      case 'pe_spread':
        return <span className={cn('text-xs', peSpreadClass)}>{formatPrice(peSpread)}</span>
      default:
        return null
    }
  }

  // Calculate total width for each side
  const ceTotalWidth = visibleCeColumns.reduce((sum, key) => sum + COLUMN_WIDTHS[key], 0)
  const peTotalWidth = visiblePeColumns.reduce((sum, key) => sum + COLUMN_WIDTHS[key], 0)

  return (
    <TableRow
      className={cn(
        'hover:bg-muted/50 relative',
        // No background for ATM and ITM, only OTM gets background
        // CE OTM = strikes above ATM
        // PE OTM = strikes below ATM (which is CE ITM)
      )}
      data-strike={strike.strike}
      data-label={label}
    >
      {/* CE cells */}
      {visibleCeColumns.length > 0 && (
        <TableCell
          className={cn(
            'p-0 relative',
            // OTM Call options get background (strikes above ATM)
            isCeOTM && !isATM && 'bg-amber-500/5'
          )}
          style={{ width: ceTotalWidth }}
        >
          {/* CE bar - spans the entire CE section */}
          <div
            className={cn('absolute left-0 top-0 bottom-0 pointer-events-none z-0 transition-all duration-300', ceBarClass)}
            style={{ width: `${ceBarPercent}%` }}
          />
          <div className="relative z-10 flex">
            {visibleCeColumns.map(key => {
              const colDef = COLUMN_DEFINITIONS.find(c => c.key === key)
              return (
                <div
                  key={key}
                  className={cn(
                    'px-2 py-1.5',
                    colDef?.align === 'right' && 'text-right',
                    colDef?.align === 'center' && 'text-center',
                    colDef?.align === 'left' && 'text-left'
                  )}
                  style={{ width: COLUMN_WIDTHS[key], minWidth: COLUMN_WIDTHS[key] }}
                >
                  {getCeColumnValue(key)}
                </div>
              )
            })}
          </div>
        </TableCell>
      )}

      {/* Strike cell - center column */}
      <TableCell
        className={cn(
          'text-center font-bold px-2 py-1.5 text-sm',
          isATM ? 'bg-primary/15' : 'bg-muted/30'
        )}
        style={{ width: COLUMN_WIDTHS.strike, minWidth: COLUMN_WIDTHS.strike }}
      >
        {strike.strike}
      </TableCell>

      {/* PE cells */}
      {visiblePeColumns.length > 0 && (
        <TableCell
          className={cn(
            'p-0 relative',
            // OTM Put options get background (strikes below ATM, which is ITM for CE)
            isPeOTM && !isATM && 'bg-amber-500/5'
          )}
          style={{ width: peTotalWidth }}
        >
          {/* PE bar - spans the entire PE section from right */}
          <div
            className={cn('absolute right-0 top-0 bottom-0 pointer-events-none z-0 transition-all duration-300', peBarClass)}
            style={{ width: `${peBarPercent}%` }}
          />
          <div className="relative z-10 flex">
            {visiblePeColumns.map(key => {
              const colDef = COLUMN_DEFINITIONS.find(c => c.key === key)
              return (
                <div
                  key={key}
                  className={cn(
                    'px-2 py-1.5',
                    colDef?.align === 'right' && 'text-right',
                    colDef?.align === 'center' && 'text-center',
                    colDef?.align === 'left' && 'text-left'
                  )}
                  style={{ width: COLUMN_WIDTHS[key], minWidth: COLUMN_WIDTHS[key] }}
                >
                  {getPeColumnValue(key)}
                </div>
              )
            })}
          </div>
        </TableCell>
      )}
    </TableRow>
  )
}

export default function OptionChain() {
  const { apiKey } = useAuthStore()
  const {
    visibleColumns,
    columnOrder,
    strikeCount,
    selectedUnderlying,
    barDataSource,
    barStyle,
    toggleColumn,
    reorderColumns,
    setStrikeCount,
    setSelectedUnderlying,
    setBarDataSource,
    setBarStyle,
    resetToDefaults,
  } = useOptionChainPreferences()

  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [expiries, setExpiries] = useState<string[]>([])
  const [previousData, setPreviousData] = useState<Map<number, OptionStrike>>(new Map())

  const underlyingInfo = UNDERLYINGS.find((u) => u.value === selectedUnderlying)
  const exchange = underlyingInfo?.brokerExchange ?? 'NSE_INDEX'
  const expiryExchange = underlyingInfo?.exchange ?? 'NFO'

  const { data, isConnected, error, lastUpdate, refetch, isLoading } = useOptionChainSSE(
    apiKey,
    selectedUnderlying,
    exchange,
    convertExpiryForAPI(selectedExpiry),
    strikeCount,
    { enabled: !!selectedExpiry, refreshInterval: 3000 }
  )

  useEffect(() => {
    const loadExpiries = async () => {
      if (!apiKey || !selectedUnderlying) return

      try {
        const response = await optionChainApi.getExpiries(apiKey, selectedUnderlying, expiryExchange)
        if (response.status === 'success' && response.data.length > 0) {
          setExpiries(response.data)
          if (!selectedExpiry) {
            setSelectedExpiry(response.data[0])
          }
        } else {
          toast.error(response.message || 'Failed to load expiries')
        }
      } catch (err) {
        console.error('Error loading expiries:', err)
        toast.error('Failed to load expiry dates')
      }
    }

    loadExpiries()
  }, [apiKey, selectedUnderlying, expiryExchange, selectedExpiry])

  useEffect(() => {
    if (data?.chain) {
      const newMap = new Map<number, OptionStrike>()
      data.chain.forEach((strike) => {
        newMap.set(strike.strike, strike)
      })
      setPreviousData(newMap)
    }
  }, [data?.chain])

  const handleUnderlyingChange = (value: string) => {
    const underlying = UNDERLYINGS.find((u) => u.value === value)
    if (underlying) {
      setSelectedUnderlying(value)
      setSelectedExpiry('')
      setExpiries([])
    }
  }

  const handleRefresh = () => {
    refetch()
  }

  const pcr = useMemo(() => (data?.chain ? calculatePCR(data.chain) : 0), [data?.chain])
  const totals = useMemo(() => (data?.chain ? calculateTotals(data.chain) : { ceVolume: 0, peVolume: 0, ceOi: 0, peOi: 0 }), [data?.chain])
  const maxBarValue = useMemo(() => (data?.chain ? getMaxValue(data.chain, barDataSource) : 1), [data?.chain, barDataSource])

  // Get ordered visible columns for each side
  const visibleCeColumns = useMemo(() => {
    return columnOrder.filter(key => {
      const col = COLUMN_DEFINITIONS.find(c => c.key === key)
      return col?.side === 'ce' && visibleColumns.includes(key)
    })
  }, [columnOrder, visibleColumns])

  const visiblePeColumns = useMemo(() => {
    return columnOrder.filter(key => {
      const col = COLUMN_DEFINITIONS.find(c => c.key === key)
      return col?.side === 'pe' && visibleColumns.includes(key)
    })
  }, [columnOrder, visibleColumns])

  // Calculate header widths
  const ceTotalWidth = visibleCeColumns.reduce((sum, key) => sum + COLUMN_WIDTHS[key], 0)
  const peTotalWidth = visiblePeColumns.reduce((sum, key) => sum + COLUMN_WIDTHS[key], 0)

  if (error) {
    return (
      <div className="flex items-center justify-center py-16">
        <Card className="max-w-md">
          <CardContent className="p-6">
            <div className="text-center text-red-500">
              <h2 className="text-xl font-bold mb-2">Error Loading Option Chain</h2>
              <p>{error}</p>
              <Button onClick={handleRefresh} className="mt-4">
                <RefreshCw className="h-4 w-4 mr-2" />
                Retry
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="py-6 space-y-6">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-6 w-6" />
          <h1 className="text-3xl font-bold">Option Chain</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <Select value={selectedUnderlying} onValueChange={handleUnderlyingChange}>
            <SelectTrigger className="w-36">
              <SelectValue placeholder="Select Underlying" />
            </SelectTrigger>
            <SelectContent>
              {UNDERLYINGS.map((u) => (
                <SelectItem key={u.value} value={u.value}>
                  {u.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={selectedExpiry} onValueChange={setSelectedExpiry} disabled={expiries.length === 0}>
            <SelectTrigger className="w-36">
              <SelectValue placeholder="Select Expiry" />
            </SelectTrigger>
            <SelectContent>
              {expiries.map((exp) => (
                <SelectItem key={exp} value={exp}>
                  {exp}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={String(strikeCount)} onValueChange={(v) => setStrikeCount(Number(v))}>
            <SelectTrigger className="w-36">
              <SelectValue placeholder="Strike Count" />
            </SelectTrigger>
            <SelectContent>
              {STRIKE_COUNTS.map((sc) => (
                <SelectItem key={sc.value} value={String(sc.value)}>
                  {sc.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <BarSettingsDropdown
            barDataSource={barDataSource}
            barStyle={barStyle}
            onBarDataSourceChange={setBarDataSource}
            onBarStyleChange={setBarStyle}
          />
          <ColumnConfigDropdown
            visibleColumns={visibleColumns}
            onToggleColumn={toggleColumn}
            onResetToDefaults={resetToDefaults}
          />
          <ColumnReorderPanel
            columnOrder={columnOrder}
            visibleColumns={visibleColumns}
            onReorderColumns={reorderColumns}
          />
          <Button onClick={handleRefresh} disabled={!selectedExpiry || isLoading}>
            <RefreshCw className={`h-4 w-4 mr-2 ${isLoading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {data && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <Card>
              <CardContent className="p-4">
                <div className="text-sm text-muted-foreground">{selectedUnderlying} Spot</div>
                <div className="text-2xl font-bold text-primary">{formatPrice(data.underlying_ltp)}</div>
                <div className="text-xs text-muted-foreground">
                  Prev Close: {formatPrice(data.underlying_prev_close)}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <div className="text-sm text-muted-foreground">ATM Strike</div>
                <div className="text-2xl font-bold">{data.atm_strike}</div>
                <div className="text-xs text-muted-foreground">Expiry: {data.expiry_date}</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <div className="text-sm text-muted-foreground">PCR</div>
                <div className={`text-2xl font-bold ${pcr > 1 ? 'text-green-500' : 'text-yellow-500'}`}>
                  {pcr.toFixed(2)}
                </div>
                <div className="text-xs text-muted-foreground">Put/Call Ratio</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <div className="text-sm text-muted-foreground">Total OI</div>
                <div className="text-sm mt-1">
                  <span className="text-green-500 font-mono">{formatInLakhs(totals.ceOi)}</span>
                  <span className="mx-2 text-muted-foreground">|</span>
                  <span className="text-red-500 font-mono">{formatInLakhs(totals.peOi)}</span>
                </div>
                <div className="h-2 bg-muted rounded-full overflow-hidden mt-2">
                  <div
                    className="h-full bg-gradient-to-r from-green-500 to-primary transition-all duration-500"
                    style={{ width: totals.ceOi + totals.peOi > 0 ? `${(totals.ceOi / (totals.ceOi + totals.peOi)) * 100}%` : '0%' }}
                  />
                </div>
                <div className="flex justify-between text-xs text-muted-foreground mt-1">
                  <span>PCR: {pcr.toFixed(2)}</span>
                </div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <Table className="w-full table-fixed">
                  <TableHeader>
                    {/* Section headers row */}
                    <TableRow className="bg-muted/30 border-b-0">
                      {visibleCeColumns.length > 0 && (
                        <TableHead
                          className="text-center text-green-500 font-bold text-sm border-r border-border"
                          style={{ width: ceTotalWidth }}
                        >
                          CALLS
                        </TableHead>
                      )}
                      <TableHead className="text-center" style={{ width: COLUMN_WIDTHS.strike }} />
                      {visiblePeColumns.length > 0 && (
                        <TableHead
                          className="text-center text-red-500 font-bold text-sm border-l border-border"
                          style={{ width: peTotalWidth }}
                        >
                          PUTS
                        </TableHead>
                      )}
                    </TableRow>
                    {/* Column headers row */}
                    <TableRow className="bg-muted/50">
                      {visibleCeColumns.length > 0 && (
                        <TableHead className="p-0 border-r border-border" style={{ width: ceTotalWidth }}>
                          <div className="flex">
                            {visibleCeColumns.map(key => {
                              const colDef = COLUMN_DEFINITIONS.find(c => c.key === key)
                              return (
                                <div
                                  key={key}
                                  className={cn(
                                    'px-2 py-2 text-xs font-medium',
                                    colDef?.align === 'right' && 'text-right',
                                    colDef?.align === 'center' && 'text-center',
                                    colDef?.align === 'left' && 'text-left'
                                  )}
                                  style={{ width: COLUMN_WIDTHS[key], minWidth: COLUMN_WIDTHS[key] }}
                                >
                                  {colDef?.label}
                                </div>
                              )
                            })}
                          </div>
                        </TableHead>
                      )}
                      <TableHead
                        className="text-center bg-muted/30 text-xs"
                        style={{ width: COLUMN_WIDTHS.strike }}
                      >
                        Strike
                      </TableHead>
                      {visiblePeColumns.length > 0 && (
                        <TableHead className="p-0 border-l border-border" style={{ width: peTotalWidth }}>
                          <div className="flex">
                            {visiblePeColumns.map(key => {
                              const colDef = COLUMN_DEFINITIONS.find(c => c.key === key)
                              return (
                                <div
                                  key={key}
                                  className={cn(
                                    'px-2 py-2 text-xs font-medium',
                                    colDef?.align === 'right' && 'text-right',
                                    colDef?.align === 'center' && 'text-center',
                                    colDef?.align === 'left' && 'text-left'
                                  )}
                                  style={{ width: COLUMN_WIDTHS[key], minWidth: COLUMN_WIDTHS[key] }}
                                >
                                  {colDef?.label}
                                </div>
                              )
                            })}
                          </div>
                        </TableHead>
                      )}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.chain.map((strike) => (
                      <OptionChainRow
                        key={strike.strike}
                        strike={strike}
                        previousData={previousData}
                        maxBarValue={maxBarValue}
                        visibleCeColumns={visibleCeColumns}
                        visiblePeColumns={visiblePeColumns}
                        barDataSource={barDataSource}
                        barStyle={barStyle}
                      />
                    ))}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>

          <div className="flex justify-between items-center text-sm text-muted-foreground">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <span>Connection:</span>
                <Badge variant={isConnected ? 'default' : 'destructive'}>{isConnected ? 'Connected' : 'Disconnected'}</Badge>
              </div>
              <div className="text-xs">
                Bar: {barDataSource === 'oi' ? 'OI' : 'Volume'} ({barStyle})
              </div>
            </div>
            <div>Last Update: {lastUpdate ? lastUpdate.toLocaleTimeString() : '-'}</div>
          </div>
        </>
      )}

      {!data && !error && (
        <div className="flex items-center justify-center py-16">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
        </div>
      )}
    </div>
  )
}
