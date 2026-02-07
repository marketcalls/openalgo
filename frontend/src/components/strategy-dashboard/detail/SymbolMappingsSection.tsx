import { Loader2, Plus, Search, Trash2, Upload } from 'lucide-react'
import type React from 'react'
import { useCallback, useEffect, useState } from 'react'
import { showToast } from '@/utils/toast'
import { strategyApi } from '@/api/strategy'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import type { AddSymbolRequest, StrategySymbolMapping, SymbolSearchResult } from '@/types/strategy'
import {
  EXPIRY_TYPES,
  OFFSET_VALUES,
  OPTION_TYPES,
  UNDERLYING_EXCHANGE_MAP,
  getProductTypes,
  isDerivativeExchange,
} from '@/types/strategy'

interface SymbolMappingsSectionProps {
  strategyId: number
  mappings: StrategySymbolMapping[]
  onRefresh: () => void
}

export function SymbolMappingsSection({
  strategyId,
  mappings,
  onRefresh,
}: SymbolMappingsSectionProps) {
  // Add symbol form state
  const [showAddForm, setShowAddForm] = useState(false)
  const [exchange, setExchange] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [productType, setProductType] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Equity: symbol search
  const [symbolSearch, setSymbolSearch] = useState('')
  const [searchResults, setSearchResults] = useState<SymbolSearchResult[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [selectedSymbol, setSelectedSymbol] = useState<SymbolSearchResult | null>(null)

  // Derivatives: underlying browser + instrument config
  const [underlyings, setUnderlyings] = useState<string[]>([])
  const [underlyingSearch, setUnderlyingSearch] = useState('')
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [selectedUnderlying, setSelectedUnderlying] = useState('')
  const [underlyingsLoading, setUnderlyingsLoading] = useState(false)
  const [instrumentType, setInstrumentType] = useState<'futures' | 'options'>('futures')
  const [expiryType, setExpiryType] = useState('')
  const [offset, setOffset] = useState('')
  const [optionType, setOptionType] = useState('')

  // Bulk import
  const [bulkDialogOpen, setBulkDialogOpen] = useState(false)
  const [csvData, setCsvData] = useState('')

  const isDerivative = isDerivativeExchange(exchange)

  // Load underlyings when derivative exchange changes
  useEffect(() => {
    if (!isDerivative || !exchange) {
      setUnderlyings([])
      return
    }
    let cancelled = false
    setUnderlyingsLoading(true)
    strategyApi
      .searchUnderlyings(exchange)
      .then((result) => {
        if (!cancelled) setUnderlyings(result)
      })
      .catch(() => {
        if (!cancelled) setUnderlyings([])
      })
      .finally(() => {
        if (!cancelled) setUnderlyingsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [exchange, isDerivative])

  // Equity symbol search with debounce
  const searchSymbols = useCallback(
    async (query: string) => {
      if (query.length < 2) {
        setSearchResults([])
        return
      }
      try {
        setSearchLoading(true)
        const results = await strategyApi.searchSymbols(query, exchange || undefined)
        setSearchResults(results)
      } catch {
        // ignore
      } finally {
        setSearchLoading(false)
      }
    },
    [exchange]
  )

  useEffect(() => {
    const timer = setTimeout(() => {
      searchSymbols(symbolSearch)
    }, 300)
    return () => clearTimeout(timer)
  }, [symbolSearch, searchSymbols])

  // Filter underlyings client-side
  const filteredUnderlyings = underlyingSearch
    ? underlyings.filter((u) => u.toLowerCase().includes(underlyingSearch.toLowerCase()))
    : underlyings

  const handleExchangeChange = (value: string) => {
    setExchange(value)
    // Reset all downstream fields
    setSelectedSymbol(null)
    setSymbolSearch('')
    setSearchResults([])
    setSelectedUnderlying('')
    setUnderlyingSearch('')
    setInstrumentType('futures')
    setExpiryType('')
    setOffset('')
    setOptionType('')
    setQuantity('1')
    // Auto-set first product type
    const products = getProductTypes(value)
    setProductType(products[0] || '')
  }

  const handleSymbolSelect = (result: SymbolSearchResult) => {
    setSelectedSymbol(result)
    setSymbolSearch(result.symbol)
    setSearchOpen(false)
  }

  const handleUnderlyingSelect = (underlying: string) => {
    setSelectedUnderlying(underlying)
    setUnderlyingSearch(underlying)
    setUnderlyingOpen(false)
  }

  const resetForm = () => {
    setExchange('')
    setSelectedSymbol(null)
    setSymbolSearch('')
    setSearchResults([])
    setSelectedUnderlying('')
    setUnderlyingSearch('')
    setInstrumentType('futures')
    setExpiryType('')
    setOffset('')
    setOptionType('')
    setQuantity('1')
    setProductType('')
    setShowAddForm(false)
  }

  const handleAddSymbol = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!exchange || !quantity || Number(quantity) < 1 || !productType) {
      showToast.error('Please fill all required fields', 'strategy')
      return
    }

    if (isDerivative) {
      // Validate derivative fields
      if (!selectedUnderlying) {
        showToast.error('Please select an underlying', 'strategy')
        return
      }
      if (!expiryType) {
        showToast.error('Expiry type is required', 'strategy')
        return
      }
      if (instrumentType === 'options' && (!offset || !optionType)) {
        showToast.error('Strike offset and option type are required for options', 'strategy')
        return
      }
    } else {
      if (!selectedSymbol) {
        showToast.error('Please select a symbol', 'strategy')
        return
      }
    }

    try {
      setSubmitting(true)

      const data: AddSymbolRequest = isDerivative
        ? {
            symbol: selectedUnderlying,
            exchange,
            quantity: Number(quantity),
            product_type: productType,
            order_mode: instrumentType === 'futures' ? 'futures' : 'single_option',
            underlying: selectedUnderlying,
            underlying_exchange: UNDERLYING_EXCHANGE_MAP[exchange] || exchange,
            expiry_type: expiryType as AddSymbolRequest['expiry_type'],
            ...(instrumentType === 'options' && { offset, option_type: optionType }),
          }
        : {
            symbol: selectedSymbol!.symbol,
            exchange,
            quantity: Number(quantity),
            product_type: productType,
          }

      const response = await strategyApi.addSymbolMapping(strategyId, data)
      if (response.status === 'success') {
        showToast.success('Symbol added', 'strategy')
        resetForm()
        onRefresh()
      } else {
        showToast.error(response.message || 'Failed to add symbol', 'strategy')
      }
    } catch {
      showToast.error('Failed to add symbol', 'strategy')
    } finally {
      setSubmitting(false)
    }
  }

  const handleBulkImport = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!csvData.trim()) {
      showToast.error('Please enter CSV data', 'strategy')
      return
    }
    try {
      setSubmitting(true)
      const response = await strategyApi.addBulkSymbols(strategyId, csvData)
      if (response.status === 'success') {
        const { added = 0, failed = 0 } = response.data || {}
        showToast.success(
          `Added ${added} symbols${failed > 0 ? `, ${failed} failed` : ''}`,
          'strategy'
        )
        setCsvData('')
        setBulkDialogOpen(false)
        onRefresh()
      } else {
        showToast.error(response.message || 'Failed to import', 'strategy')
      }
    } catch {
      showToast.error('Failed to import symbols', 'strategy')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDeleteMapping = async (mappingId: number) => {
    try {
      const response = await strategyApi.deleteSymbolMapping(strategyId, mappingId)
      if (response.status === 'success') {
        showToast.success('Symbol removed', 'strategy')
        onRefresh()
      } else {
        showToast.error(response.message || 'Failed to remove', 'strategy')
      }
    } catch {
      showToast.error('Failed to remove symbol', 'strategy')
    }
  }

  const productTypes = exchange ? getProductTypes(exchange) : []

  /** Format config display for a mapping row */
  const formatConfig = (m: StrategySymbolMapping): string => {
    const mode = m.order_mode || 'equity'
    if (mode === 'equity') return '—'
    const expiry = m.expiry_type?.replace(/_/g, ' ') || ''
    if (mode === 'futures') return expiry
    // options
    const parts = [expiry, m.offset, m.option_type].filter(Boolean)
    return parts.join(' · ') || '—'
  }

  /** Derive display type from order_mode */
  const formatType = (mode?: string): string => {
    switch (mode) {
      case 'futures':
        return 'Futures'
      case 'single_option':
        return 'Options'
      default:
        return 'Equity'
    }
  }

  return (
    <>
      <Card>
        <CardHeader className="pb-3 flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-sm">Symbol Mappings ({mappings.length})</CardTitle>
            <CardDescription className="text-xs">
              Symbols configured for webhook signals
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setBulkDialogOpen(true)}>
              <Upload className="h-3.5 w-3.5 mr-1" />
              Bulk Import
            </Button>
            <Button size="sm" onClick={() => setShowAddForm(!showAddForm)}>
              <Plus className="h-3.5 w-3.5 mr-1" />
              Add Symbol
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* ── Add Symbol Form ── */}
          {showAddForm && (
            <form
              onSubmit={handleAddSymbol}
              className="p-3 border rounded-lg bg-muted/30 space-y-3"
            >
              {/* Row 1: Exchange selector */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                <div className="space-y-1">
                  <Label className="text-xs">Exchange</Label>
                  <Select value={exchange} onValueChange={handleExchangeChange}>
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue placeholder="Select exchange..." />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="NSE" className="text-xs">
                        NSE
                      </SelectItem>
                      <SelectItem value="BSE" className="text-xs">
                        BSE
                      </SelectItem>
                      <SelectItem value="NFO" className="text-xs">
                        NFO (Equity Derivatives)
                      </SelectItem>
                      <SelectItem value="BFO" className="text-xs">
                        BFO (BSE Derivatives)
                      </SelectItem>
                      <SelectItem value="MCX" className="text-xs">
                        MCX (Commodity)
                      </SelectItem>
                      <SelectItem value="CDS" className="text-xs">
                        CDS (Currency)
                      </SelectItem>
                      <SelectItem value="BCD" className="text-xs">
                        BCD (BSE Currency)
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {/* Row 1 continued: Symbol/Underlying search (only after exchange) */}
                {exchange && !isDerivative && (
                  <div className="space-y-1">
                    <Label className="text-xs">Symbol</Label>
                    <Popover open={searchOpen} onOpenChange={setSearchOpen}>
                      <PopoverTrigger asChild>
                        <Button
                          variant="outline"
                          role="combobox"
                          aria-expanded={searchOpen}
                          className="w-full justify-between font-normal h-8 text-xs"
                        >
                          {selectedSymbol ? selectedSymbol.symbol : 'Search symbol...'}
                          <Search className="ml-1 h-3 w-3 shrink-0 opacity-50" />
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent className="w-[300px] p-0" align="start">
                        <Command>
                          <CommandInput
                            placeholder="Type to search..."
                            value={symbolSearch}
                            onValueChange={setSymbolSearch}
                          />
                          <CommandList>
                            <CommandEmpty>
                              {searchLoading
                                ? 'Searching...'
                                : symbolSearch.length < 2
                                  ? 'Type to search symbols...'
                                  : 'No symbols found.'}
                            </CommandEmpty>
                            <CommandGroup>
                              {searchResults.map((result) => (
                                <CommandItem
                                  key={`${result.symbol}-${result.exchange}`}
                                  value={`${result.symbol} ${result.name}`}
                                  onSelect={() => handleSymbolSelect(result)}
                                >
                                  <div className="flex flex-col">
                                    <span className="font-medium text-sm">{result.symbol}</span>
                                    <span className="text-xs text-muted-foreground">
                                      {result.name} &bull; {result.exchange}
                                      {result.instrumenttype && ` &bull; ${result.instrumenttype}`}
                                    </span>
                                  </div>
                                </CommandItem>
                              ))}
                            </CommandGroup>
                          </CommandList>
                        </Command>
                      </PopoverContent>
                    </Popover>
                  </div>
                )}

                {exchange && isDerivative && (
                  <div className="space-y-1">
                    <Label className="text-xs">Underlying</Label>
                    <Popover open={underlyingOpen} onOpenChange={setUnderlyingOpen}>
                      <PopoverTrigger asChild>
                        <Button
                          variant="outline"
                          role="combobox"
                          aria-expanded={underlyingOpen}
                          className="w-full justify-between font-normal h-8 text-xs"
                          disabled={underlyingsLoading}
                        >
                          {underlyingsLoading
                            ? 'Loading...'
                            : selectedUnderlying || 'Search underlying...'}
                          <Search className="ml-1 h-3 w-3 shrink-0 opacity-50" />
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent className="w-[300px] p-0" align="start">
                        <Command>
                          <CommandInput
                            placeholder="Search underlying..."
                            value={underlyingSearch}
                            onValueChange={setUnderlyingSearch}
                          />
                          <CommandList>
                            <CommandEmpty>
                              {underlyingsLoading
                                ? 'Loading underlyings...'
                                : underlyings.length === 0
                                  ? 'No underlyings available.'
                                  : 'No match found.'}
                            </CommandEmpty>
                            <CommandGroup>
                              {filteredUnderlyings.slice(0, 50).map((u) => (
                                <CommandItem
                                  key={u}
                                  value={u}
                                  onSelect={() => handleUnderlyingSelect(u)}
                                >
                                  <span className="font-medium text-sm">{u}</span>
                                </CommandItem>
                              ))}
                              {filteredUnderlyings.length > 50 && (
                                <CommandItem disabled>
                                  <span className="text-xs text-muted-foreground">
                                    +{filteredUnderlyings.length - 50} more — refine search
                                  </span>
                                </CommandItem>
                              )}
                            </CommandGroup>
                          </CommandList>
                        </Command>
                      </PopoverContent>
                    </Popover>
                  </div>
                )}

                {/* Quantity + Product (always, once exchange selected) */}
                {exchange && (
                  <>
                    <div className="space-y-1">
                      <Label className="text-xs">Quantity</Label>
                      <Input
                        type="number"
                        min="1"
                        value={quantity}
                        onChange={(e) => setQuantity(e.target.value)}
                        className="h-8 text-xs"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label className="text-xs">Product</Label>
                      <Select value={productType} onValueChange={setProductType}>
                        <SelectTrigger className="h-8 text-xs">
                          <SelectValue placeholder="Product" />
                        </SelectTrigger>
                        <SelectContent>
                          {productTypes.map((pt) => (
                            <SelectItem key={pt} value={pt}>
                              {pt}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  </>
                )}
              </div>

              {/* Row 2: Derivative instrument configuration */}
              {isDerivative && selectedUnderlying && (
                <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                  <div className="space-y-1">
                    <Label className="text-xs">Instrument</Label>
                    <Tabs
                      value={instrumentType}
                      onValueChange={(v) => {
                        setInstrumentType(v as 'futures' | 'options')
                        setOffset('')
                        setOptionType('')
                      }}
                    >
                      <TabsList className="grid w-full grid-cols-2 h-8">
                        <TabsTrigger value="futures" className="text-xs">
                          Futures
                        </TabsTrigger>
                        <TabsTrigger value="options" className="text-xs">
                          Options
                        </TabsTrigger>
                      </TabsList>
                    </Tabs>
                  </div>

                  <div className="space-y-1">
                    <Label className="text-xs">Expiry Type</Label>
                    <Select value={expiryType} onValueChange={setExpiryType}>
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue placeholder="Select expiry..." />
                      </SelectTrigger>
                      <SelectContent>
                        {EXPIRY_TYPES.map((et) => (
                          <SelectItem key={et.value} value={et.value}>
                            {et.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  {instrumentType === 'options' && (
                    <>
                      <div className="space-y-1">
                        <Label className="text-xs">Option Type</Label>
                        <Select value={optionType} onValueChange={setOptionType}>
                          <SelectTrigger className="h-8 text-xs">
                            <SelectValue placeholder="CE / PE" />
                          </SelectTrigger>
                          <SelectContent>
                            {OPTION_TYPES.map((ot) => (
                              <SelectItem key={ot} value={ot}>
                                {ot}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="space-y-1">
                        <Label className="text-xs">Strike Offset</Label>
                        <Select value={offset} onValueChange={setOffset}>
                          <SelectTrigger className="h-8 text-xs">
                            <SelectValue placeholder="ATM / ITM / OTM" />
                          </SelectTrigger>
                          <SelectContent className="max-h-[200px]">
                            {OFFSET_VALUES.map((o) => (
                              <SelectItem key={o} value={o}>
                                {o}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </>
                  )}
                </div>
              )}

              {/* Action buttons */}
              <div className="flex gap-2">
                <Button type="submit" size="sm" disabled={submitting || !exchange}>
                  {submitting ? (
                    <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                  ) : (
                    <Plus className="h-3.5 w-3.5 mr-1" />
                  )}
                  Add
                </Button>
                <Button type="button" variant="ghost" size="sm" onClick={resetForm}>
                  Cancel
                </Button>
              </div>
            </form>
          )}

          {/* ── Mappings Table ── */}
          {mappings.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <p className="text-sm">No symbols configured yet.</p>
              <p className="text-xs mt-1">Click &quot;Add Symbol&quot; to get started.</p>
            </div>
          ) : (
            <div className="relative w-full overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Exchange</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead>Config</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead>Product</TableHead>
                    <TableHead className="w-12" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {mappings.map((mapping) => (
                    <TableRow key={mapping.id}>
                      <TableCell className="font-medium">
                        {mapping.underlying || mapping.symbol}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-xs">
                          {mapping.exchange}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="text-xs">
                          {formatType(mapping.order_mode)}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatConfig(mapping)}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {mapping.quantity}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="text-xs">
                          {mapping.product_type}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950"
                          onClick={() => handleDeleteMapping(mapping.id)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Bulk Import Dialog */}
      <Dialog open={bulkDialogOpen} onOpenChange={setBulkDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Bulk Import Symbols</DialogTitle>
            <DialogDescription>
              Paste CSV data: Symbol,Exchange,Quantity,Product (one per line, no header).
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleBulkImport}>
            <Textarea
              placeholder={'RELIANCE,NSE,100,CNC\nTATAMOTORS,NSE,50,MIS'}
              value={csvData}
              onChange={(e) => setCsvData(e.target.value)}
              rows={6}
              maxLength={102400}
              className="font-mono text-sm"
            />
            <DialogFooter className="mt-4">
              <Button type="button" variant="outline" onClick={() => setBulkDialogOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={submitting}>
                {submitting ? 'Importing...' : 'Import'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
