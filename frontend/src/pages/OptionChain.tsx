import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronsUpDown, RefreshCw, TrendingUp, Wifi, WifiOff } from 'lucide-react'
import { useAuthStore } from '@/stores/authStore'
import { useOptionChainLive } from '@/hooks/useOptionChainLive'
import { useOptionChainPreferences } from '@/hooks/useOptionChainPreferences'
import { oiProfileApi } from '@/api/oi-profile'
import type { BarDataSource, BarStyle, ColumnKey, OptionStrike } from '@/types/option-chain'
import { COLUMN_DEFINITIONS } from '@/types/option-chain'
import { BarSettingsDropdown, ColumnConfigDropdown, ColumnReorderPanel } from '@/components/option-chain'
import { PlaceOrderDialog } from '@/components/trading'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
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
import { cn } from '@/lib/utils'

const FNO_EXCHANGES = [
  { value: 'NFO', label: 'NFO' },
  { value: 'BFO', label: 'BFO' },
]

const DEFAULT_UNDERLYINGS: Record<string, string[]> = {
  NFO: ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'],
  BFO: ['SENSEX', 'BANKEX'],
}

const STRIKE_COUNTS = [
  { value: 5, label: '5 strikes' },
  { value: 10, label: '10 strikes' },
  { value: 15, label: '15 strikes' },
  { value: 20, label: '20 strikes' },
  { value: 25, label: '25 strikes' },
]

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

interface PlaceOrderParams {
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  lotSize: number
  tickSize: number
}

interface OptionChainRowProps {
  strike: OptionStrike
  previousStrike: OptionStrike | undefined
  maxBarValue: number
  visibleCeColumns: ColumnKey[]
  visiblePeColumns: ColumnKey[]
  barDataSource: BarDataSource
  barStyle: BarStyle
  optionExchange: string
  onPlaceOrder: (params: PlaceOrderParams) => void
}

// Memoized row component to prevent unnecessary re-renders
const OptionChainRow = React.memo(function OptionChainRow({
  strike,
  previousStrike,
  maxBarValue,
  visibleCeColumns,
  visiblePeColumns,
  barDataSource,
  barStyle,
  optionExchange,
  onPlaceOrder,
}: OptionChainRowProps) {
  const ce = strike.ce
  const pe = strike.pe
  const label = ce?.label ?? pe?.label ?? ''
  const isATM = label === 'ATM'

  // For CE: OTM means strike > ATM (label starts with OTM)
  // For PE: OTM means strike < ATM (which is ITM for CE)
  const isCeOTM = label.startsWith('OTM')
  const isPeOTM = label.startsWith('ITM')

  // Flash animation for LTP changes
  const ceLtpChanged = previousStrike?.ce?.ltp !== undefined && previousStrike.ce.ltp !== ce?.ltp
  const peLtpChanged = previousStrike?.pe?.ltp !== undefined && previousStrike.pe.ltp !== pe?.ltp

  const ceFlashClass = ceLtpChanged ? (ce && previousStrike?.ce && ce.ltp > previousStrike.ce.ltp ? 'bg-green-500/30' : 'bg-red-500/30') : ''
  const peFlashClass = peLtpChanged ? (pe && previousStrike?.pe && pe.ltp > previousStrike.pe.ltp ? 'bg-green-500/30' : 'bg-red-500/30') : ''

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

  // Use tabular-nums for consistent number widths to prevent layout shifts
  const numClass = 'font-mono tabular-nums text-xs'

  const getCeColumnValue = (key: ColumnKey) => {
    switch (key) {
      case 'ce_oi':
        return <span className={numClass}>{formatInLakhs(ce?.oi)}</span>
      case 'ce_volume':
        return <span className={numClass}>{formatInLakhs(ce?.volume)}</span>
      case 'ce_bid_qty':
        return <span className={numClass}>{ce?.bid_qty ?? 0}</span>
      case 'ce_bid':
        return <span className={cn(numClass, 'text-red-500')}>{formatPrice(ce?.bid)}</span>
      case 'ce_ltp':
        return <span className={cn(numClass, 'font-semibold', ceFlashClass)}>{formatPrice(ce?.ltp)}</span>
      case 'ce_ask':
        return <span className={cn(numClass, 'text-green-500')}>{formatPrice(ce?.ask)}</span>
      case 'ce_ask_qty':
        return <span className={numClass}>{ce?.ask_qty ?? 0}</span>
      case 'ce_spread':
        return <span className={cn(numClass, ceSpreadClass)}>{formatPrice(ceSpread)}</span>
      default:
        return null
    }
  }

  const getPeColumnValue = (key: ColumnKey) => {
    switch (key) {
      case 'pe_oi':
        return <span className={numClass}>{formatInLakhs(pe?.oi)}</span>
      case 'pe_volume':
        return <span className={numClass}>{formatInLakhs(pe?.volume)}</span>
      case 'pe_bid_qty':
        return <span className={numClass}>{pe?.bid_qty ?? 0}</span>
      case 'pe_bid':
        return <span className={cn(numClass, 'text-red-500')}>{formatPrice(pe?.bid)}</span>
      case 'pe_ltp':
        return <span className={cn(numClass, 'font-semibold', peFlashClass)}>{formatPrice(pe?.ltp)}</span>
      case 'pe_ask':
        return <span className={cn(numClass, 'text-green-500')}>{formatPrice(pe?.ask)}</span>
      case 'pe_ask_qty':
        return <span className={numClass}>{pe?.ask_qty ?? 0}</span>
      case 'pe_spread':
        return <span className={cn(numClass, peSpreadClass)}>{formatPrice(peSpread)}</span>
      default:
        return null
    }
  }

  return (
    <TableRow
      className={cn(
        'hover:bg-muted/50 relative group',
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
        >
          {/* CE bar - spans the entire CE section */}
          <div
            className={cn('absolute left-0 top-0 bottom-0 pointer-events-none z-0 transition-all duration-300', ceBarClass)}
            style={{ width: `${ceBarPercent}%` }}
          />
          {/* CE Buy/Sell buttons - appear on hover (positioned near strike) */}
          {ce && (
            <div className={cn(
              'absolute right-1 top-1/2 -translate-y-1/2 z-20',
              'flex gap-0.5',
              'opacity-0 group-hover:opacity-100 transition-opacity'
            )}>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onPlaceOrder({
                    symbol: ce.symbol,
                    exchange: optionExchange,
                    action: 'BUY',
                    lotSize: ce.lotsize ?? 1,
                    tickSize: ce.tick_size ?? 0.05,
                  })
                }}
                className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-green-600 text-white hover:bg-green-700"
              >
                B
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onPlaceOrder({
                    symbol: ce.symbol,
                    exchange: optionExchange,
                    action: 'SELL',
                    lotSize: ce.lotsize ?? 1,
                    tickSize: ce.tick_size ?? 0.05,
                  })
                }}
                className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-amber-600 text-white hover:bg-amber-700"
              >
                S
              </button>
            </div>
          )}
          <div className="relative z-10 flex">
            {visibleCeColumns.map(key => {
              const colDef = COLUMN_DEFINITIONS.find(c => c.key === key)
              return (
                <div
                  key={key}
                  className={cn(
                    'flex-1 px-2 py-1.5 min-w-0',
                    colDef?.align === 'right' && 'text-right',
                    colDef?.align === 'center' && 'text-center',
                    colDef?.align === 'left' && 'text-left'
                  )}
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
          'text-center font-bold px-2 py-1.5 text-sm w-20 min-w-20',
          isATM ? 'bg-primary/15' : 'bg-muted/30'
        )}
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
        >
          {/* PE bar - spans the entire PE section from right */}
          <div
            className={cn('absolute right-0 top-0 bottom-0 pointer-events-none z-0 transition-all duration-300', peBarClass)}
            style={{ width: `${peBarPercent}%` }}
          />
          {/* PE Buy/Sell buttons - appear on hover (positioned near strike) */}
          {pe && (
            <div className={cn(
              'absolute left-1 top-1/2 -translate-y-1/2 z-20',
              'flex gap-0.5',
              'opacity-0 group-hover:opacity-100 transition-opacity'
            )}>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onPlaceOrder({
                    symbol: pe.symbol,
                    exchange: optionExchange,
                    action: 'BUY',
                    lotSize: pe.lotsize ?? 1,
                    tickSize: pe.tick_size ?? 0.05,
                  })
                }}
                className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-green-600 text-white hover:bg-green-700"
              >
                B
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation()
                  onPlaceOrder({
                    symbol: pe.symbol,
                    exchange: optionExchange,
                    action: 'SELL',
                    lotSize: pe.lotsize ?? 1,
                    tickSize: pe.tick_size ?? 0.05,
                  })
                }}
                className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-amber-600 text-white hover:bg-amber-700"
              >
                S
              </button>
            </div>
          )}
          <div className="relative z-10 flex">
            {visiblePeColumns.map(key => {
              const colDef = COLUMN_DEFINITIONS.find(c => c.key === key)
              return (
                <div
                  key={key}
                  className={cn(
                    'flex-1 px-2 py-1.5 min-w-0',
                    colDef?.align === 'right' && 'text-right',
                    colDef?.align === 'center' && 'text-center',
                    colDef?.align === 'left' && 'text-left'
                  )}
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
})

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

  const [selectedExchange, setSelectedExchange] = useState('NFO')
  const [underlyings, setUnderlyings] = useState<string[]>(DEFAULT_UNDERLYINGS.NFO)
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [expiries, setExpiries] = useState<string[]>([])
  // Use ref for previous data to avoid causing re-renders and enable proper flash animation
  const previousDataRef = useRef<Map<number, OptionStrike>>(new Map())
  const [orderDialog, setOrderDialog] = useState<{
    open: boolean
    symbol: string
    exchange: string
    action: 'BUY' | 'SELL'
    quantity: number
    lotSize: number
    tickSize: number
  } | null>(null)

  const optionExchange = selectedExchange
  // Send NFO/BFO directly — backend resolves correct exchange for index vs stock
  const exchange = selectedExchange

  const { data, isConnected, isStreaming, isPaused, error, lastUpdate, refetch, isLoading, streamingSymbols } = useOptionChainLive(
    apiKey,
    selectedUnderlying,
    exchange,
    optionExchange,
    convertExpiryForAPI(selectedExpiry),
    strikeCount,
    { enabled: !!selectedExpiry, oiRefreshInterval: 30000, pauseWhenHidden: true }
  )

  // Fetch underlyings when exchange changes
  useEffect(() => {
    const defaults = DEFAULT_UNDERLYINGS[selectedExchange] || []
    setUnderlyings(defaults)
    setSelectedUnderlying(defaults[0] || '')
    setExpiries([])
    setSelectedExpiry('')

    let cancelled = false
    const fetchUnderlyings = async () => {
      try {
        const response = await oiProfileApi.getUnderlyings(selectedExchange)
        if (cancelled) return
        if (response.status === 'success' && response.underlyings.length > 0) {
          setUnderlyings(response.underlyings)
          if (!response.underlyings.includes(defaults[0])) {
            setSelectedUnderlying(response.underlyings[0])
          }
        }
      } catch {
        // Keep defaults
      }
    }
    fetchUnderlyings()
    return () => {
      cancelled = true
    }
  }, [selectedExchange])

  // Fetch expiries when underlying changes
  useEffect(() => {
    if (!selectedUnderlying) return
    setExpiries([])
    setSelectedExpiry('')

    let cancelled = false
    const fetchExpiries = async () => {
      try {
        const response = await oiProfileApi.getExpiries(selectedExchange, selectedUnderlying)
        if (cancelled) return
        if (response.status === 'success' && response.expiries.length > 0) {
          setExpiries(response.expiries)
          setSelectedExpiry(response.expiries[0])
        } else {
          setExpiries([])
          setSelectedExpiry('')
        }
      } catch {
        if (cancelled) return
        showToast.error('Failed to load expiry dates')
      }
    }
    fetchExpiries()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedUnderlying])

  // Update previous data ref after render (for flash animation)
  // Using useEffect to update AFTER the current data is rendered
  useEffect(() => {
    if (data?.chain) {
      // Schedule the ref update for after render so the current render uses old previous data
      const timeoutId = setTimeout(() => {
        const newMap = new Map<number, OptionStrike>()
        data.chain.forEach((strike) => {
          newMap.set(strike.strike, strike)
        })
        previousDataRef.current = newMap
      }, 100) // Short delay to allow flash animation to show
      return () => clearTimeout(timeoutId)
    }
  }, [data?.chain])

  const handleUnderlyingChange = (value: string) => {
    setSelectedUnderlying(value)
    setSelectedExpiry('')
    setExpiries([])
  }

  const handleRefresh = () => {
    refetch()
  }

  const handlePlaceOrder = useCallback((params: PlaceOrderParams) => {
    setOrderDialog({
      open: true,
      symbol: params.symbol,
      exchange: params.exchange,
      action: params.action,
      quantity: params.lotSize,
      lotSize: params.lotSize,
      tickSize: params.tickSize,
    })
  }, [])

  // Memoized callback for dialog close to prevent re-renders
  const handleOrderDialogClose = useCallback((open: boolean) => {
    if (!open) setOrderDialog(null)
  }, [])

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
          <Select value={selectedExchange} onValueChange={setSelectedExchange}>
            <SelectTrigger className="w-24">
              <SelectValue placeholder="Exchange" />
            </SelectTrigger>
            <SelectContent>
              {FNO_EXCHANGES.map((ex) => (
                <SelectItem key={ex.value} value={ex.value}>
                  {ex.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Popover open={underlyingOpen} onOpenChange={setUnderlyingOpen}>
            <PopoverTrigger asChild>
              <Button variant="outline" role="combobox" aria-expanded={underlyingOpen} className="w-36 justify-between">
                {selectedUnderlying || 'Select Underlying'}
                <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-48 p-0" align="start">
              <Command>
                <CommandInput placeholder="Search underlying..." />
                <CommandList>
                  <CommandEmpty>No underlying found</CommandEmpty>
                  <CommandGroup>
                    {underlyings.map((u) => (
                      <CommandItem
                        key={u}
                        value={u}
                        onSelect={() => {
                          handleUnderlyingChange(u)
                          setUnderlyingOpen(false)
                        }}
                      >
                        <Check className={`mr-2 h-4 w-4 ${selectedUnderlying === u ? 'opacity-100' : 'opacity-0'}`} />
                        {u}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
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
                  <span className="text-green-500 font-mono tabular-nums">{formatInLakhs(totals.ceOi)}</span>
                  <span className="mx-2 text-muted-foreground">|</span>
                  <span className="text-red-500 font-mono tabular-nums">{formatInLakhs(totals.peOi)}</span>
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
                        <TableHead className="text-center text-green-500 font-bold text-sm border-r border-border">
                          CALLS
                        </TableHead>
                      )}
                      <TableHead className="text-center w-20 min-w-20" />
                      {visiblePeColumns.length > 0 && (
                        <TableHead className="text-center text-red-500 font-bold text-sm border-l border-border">
                          PUTS
                        </TableHead>
                      )}
                    </TableRow>
                    {/* Column headers row */}
                    <TableRow className="bg-muted/50">
                      {visibleCeColumns.length > 0 && (
                        <TableHead className="p-0 border-r border-border">
                          <div className="flex">
                            {visibleCeColumns.map(key => {
                              const colDef = COLUMN_DEFINITIONS.find(c => c.key === key)
                              return (
                                <div
                                  key={key}
                                  className={cn(
                                    'flex-1 px-2 py-2 text-xs font-medium min-w-0',
                                    colDef?.align === 'right' && 'text-right',
                                    colDef?.align === 'center' && 'text-center',
                                    colDef?.align === 'left' && 'text-left'
                                  )}
                                >
                                  {colDef?.label}
                                </div>
                              )
                            })}
                          </div>
                        </TableHead>
                      )}
                      <TableHead className="text-center bg-muted/30 text-xs w-20 min-w-20">
                        Strike
                      </TableHead>
                      {visiblePeColumns.length > 0 && (
                        <TableHead className="p-0 border-l border-border">
                          <div className="flex">
                            {visiblePeColumns.map(key => {
                              const colDef = COLUMN_DEFINITIONS.find(c => c.key === key)
                              return (
                                <div
                                  key={key}
                                  className={cn(
                                    'flex-1 px-2 py-2 text-xs font-medium min-w-0',
                                    colDef?.align === 'right' && 'text-right',
                                    colDef?.align === 'center' && 'text-center',
                                    colDef?.align === 'left' && 'text-left'
                                  )}
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
                        previousStrike={previousDataRef.current.get(strike.strike)}
                        maxBarValue={maxBarValue}
                        visibleCeColumns={visibleCeColumns}
                        visiblePeColumns={visiblePeColumns}
                        barDataSource={barDataSource}
                        barStyle={barStyle}
                        optionExchange={optionExchange}
                        onPlaceOrder={handlePlaceOrder}
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
                {isStreaming ? (
                  <Wifi className="h-4 w-4 text-green-500" />
                ) : (
                  <WifiOff className="h-4 w-4 text-muted-foreground" />
                )}
                <Badge variant={isStreaming ? 'default' : isConnected ? 'secondary' : 'destructive'}>
                  {isPaused ? 'Paused' : isStreaming ? `Streaming ${streamingSymbols} symbols` : isConnected ? 'Polling' : 'Disconnected'}
                </Badge>
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

      {/* Place Order Dialog */}
      <PlaceOrderDialog
        open={orderDialog?.open ?? false}
        onOpenChange={handleOrderDialogClose}
        symbol={orderDialog?.symbol}
        exchange={orderDialog?.exchange}
        action={orderDialog?.action}
        quantity={orderDialog?.quantity}
        lotSize={orderDialog?.lotSize}
        tickSize={orderDialog?.tickSize}
        strategy="OptionChain"
      />
    </div>
  )
}
