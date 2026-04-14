import { ArrowLeft, FileText, Plus, RefreshCw, Search, Trash2, Upload } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
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
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import type { Strategy, StrategySymbolMapping, SymbolSearchResult } from '@/types/strategy'
import { EXCHANGES, getProductTypes } from '@/types/strategy'

export default function ConfigureSymbols() {
  const { strategyId } = useParams<{ strategyId: string }>()
  const [strategy, setStrategy] = useState<Strategy | null>(null)
  const [mappings, setMappings] = useState<StrategySymbolMapping[]>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  // Single symbol form
  const [symbolSearch, setSymbolSearch] = useState('')
  const [searchResults, setSearchResults] = useState<SymbolSearchResult[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [selectedSymbol, setSelectedSymbol] = useState<SymbolSearchResult | null>(null)
  const [exchange, setExchange] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [productType, setProductType] = useState('')

  // Bulk symbols form
  const [csvData, setCsvData] = useState('')

  // Delete confirmation
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [mappingToDelete, setMappingToDelete] = useState<number | null>(null)

  const fetchStrategy = async () => {
    if (!strategyId) return
    try {
      setLoading(true)
      const data = await strategyApi.getStrategy(Number(strategyId))
      setStrategy(data.strategy)
      setMappings(data.mappings || [])
    } catch (error) {
      showToast.error('Failed to load strategy', 'strategy')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStrategy()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Debounced symbol search
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
      } catch (error) {
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

  const handleSymbolSelect = (result: SymbolSearchResult) => {
    setSelectedSymbol(result)
    setSymbolSearch(result.symbol)
    setExchange(result.exchange)
    setSearchOpen(false)
    // Set default product type based on exchange
    const products = getProductTypes(result.exchange)
    setProductType(products[0])
  }

  const handleSingleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!selectedSymbol) {
      showToast.error('Please select a symbol', 'strategy')
      return
    }
    if (!exchange) {
      showToast.error('Please select an exchange', 'strategy')
      return
    }
    if (!quantity || Number(quantity) < 1) {
      showToast.error('Quantity must be at least 1', 'strategy')
      return
    }
    if (!productType) {
      showToast.error('Please select a product type', 'strategy')
      return
    }

    try {
      setSubmitting(true)
      const response = await strategyApi.addSymbolMapping(Number(strategyId), {
        symbol: selectedSymbol.symbol,
        exchange,
        quantity: Number(quantity),
        product_type: productType,
      })

      if (response.status === 'success') {
        showToast.success('Symbol added successfully', 'strategy')
        // Reset form
        setSelectedSymbol(null)
        setSymbolSearch('')
        setExchange('')
        setQuantity('1')
        setProductType('')
        // Refresh mappings
        fetchStrategy()
      } else {
        showToast.error(response.message || 'Failed to add symbol', 'strategy')
      }
    } catch (error) {
      showToast.error('Failed to add symbol', 'strategy')
    } finally {
      setSubmitting(false)
    }
  }

  const handleBulkSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!csvData.trim()) {
      showToast.error('Please enter CSV data', 'strategy')
      return
    }

    try {
      setSubmitting(true)
      const response = await strategyApi.addBulkSymbols(Number(strategyId), csvData)

      if (response.status === 'success') {
        const { added = 0, failed = 0 } = response.data || {}
        showToast.success(`Added ${added} symbols${failed > 0 ? `, ${failed} failed` : ''}`, 'strategy')
        setCsvData('')
        fetchStrategy()
      } else {
        showToast.error(response.message || 'Failed to add symbols', 'strategy')
      }
    } catch (error) {
      showToast.error('Failed to add symbols', 'strategy')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDeleteMapping = async () => {
    if (mappingToDelete === null || !strategyId) return

    try {
      const response = await strategyApi.deleteSymbolMapping(Number(strategyId), mappingToDelete)
      if (response.status === 'success') {
        setMappings(mappings.filter((m) => m.id !== mappingToDelete))
        showToast.success('Symbol removed', 'strategy')
      } else {
        showToast.error(response.message || 'Failed to remove symbol', 'strategy')
      }
    } catch (error) {
      showToast.error('Failed to remove symbol', 'strategy')
    } finally {
      setDeleteDialogOpen(false)
      setMappingToDelete(null)
    }
  }

  const productTypes = exchange ? getProductTypes(exchange) : []

  if (loading) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-64" />
        <Skeleton className="h-48" />
      </div>
    )
  }

  if (!strategy) {
    return null
  }

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Back Button */}
      <Button variant="ghost" asChild>
        <Link to={`/strategy/${strategyId}`}>
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to {strategy.name}
        </Link>
      </Button>

      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Configure Symbols</h1>
          <p className="text-muted-foreground">Add symbols to {strategy.name}</p>
        </div>
        <Button variant="outline" onClick={fetchStrategy}>
          <RefreshCw className="h-4 w-4 mr-2" />
          Refresh
        </Button>
      </div>

      {/* Add Symbols */}
      <Card>
        <CardHeader>
          <CardTitle>Add Symbols</CardTitle>
          <CardDescription>Add individual symbols or bulk import from CSV</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="single">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="single">
                <Plus className="h-4 w-4 mr-2" />
                Single Symbol
              </TabsTrigger>
              <TabsTrigger value="bulk">
                <Upload className="h-4 w-4 mr-2" />
                Bulk Import
              </TabsTrigger>
            </TabsList>

            {/* Single Symbol Tab */}
            <TabsContent value="single">
              <form onSubmit={handleSingleSubmit} className="space-y-4 mt-4">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                  {/* Symbol Search */}
                  <div className="space-y-2">
                    <Label>Symbol</Label>
                    <Popover open={searchOpen} onOpenChange={setSearchOpen}>
                      <PopoverTrigger asChild>
                        <Button
                          variant="outline"
                          role="combobox"
                          aria-expanded={searchOpen}
                          className="w-full justify-between font-normal"
                        >
                          {selectedSymbol ? selectedSymbol.symbol : 'Search symbol...'}
                          <Search className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent className="w-[300px] p-0" align="start">
                        <Command>
                          <CommandInput
                            placeholder="Search symbols..."
                            value={symbolSearch}
                            onValueChange={setSymbolSearch}
                          />
                          <CommandList>
                            <CommandEmpty>
                              {searchLoading ? 'Searching...' : 'No symbols found.'}
                            </CommandEmpty>
                            <CommandGroup>
                              {searchResults.map((result) => (
                                <CommandItem
                                  key={`${result.symbol}-${result.exchange}`}
                                  value={result.symbol}
                                  onSelect={() => handleSymbolSelect(result)}
                                >
                                  <div className="flex flex-col">
                                    <span className="font-medium">{result.symbol}</span>
                                    <span className="text-xs text-muted-foreground">
                                      {result.name} • {result.exchange}
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

                  {/* Exchange */}
                  <div className="space-y-2">
                    <Label>Exchange</Label>
                    <Select
                      value={exchange}
                      onValueChange={(value) => {
                        setExchange(value)
                        setProductType('')
                      }}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select exchange" />
                      </SelectTrigger>
                      <SelectContent>
                        {EXCHANGES.map((ex) => (
                          <SelectItem key={ex} value={ex}>
                            {ex}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  {/* Quantity */}
                  <div className="space-y-2">
                    <Label>Quantity</Label>
                    <Input
                      type="number"
                      min="1"
                      value={quantity}
                      onChange={(e) => setQuantity(e.target.value)}
                      placeholder="Enter quantity"
                    />
                  </div>

                  {/* Product Type */}
                  <div className="space-y-2">
                    <Label>Product Type</Label>
                    <Select value={productType} onValueChange={setProductType} disabled={!exchange}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select product" />
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
                </div>

                <Button type="submit" disabled={submitting}>
                  {submitting ? 'Adding...' : 'Add Symbol'}
                </Button>
              </form>
            </TabsContent>

            {/* Bulk Import Tab */}
            <TabsContent value="bulk">
              <form onSubmit={handleBulkSubmit} className="space-y-4 mt-4">
                <div className="space-y-2">
                  <Label>CSV Data</Label>
                  <Textarea
                    placeholder="Symbol,Exchange,Quantity,Product&#10;RELIANCE,NSE,100,CNC&#10;TATAMOTORS,NSE,50,MIS"
                    value={csvData}
                    onChange={(e) => setCsvData(e.target.value)}
                    rows={6}
                    maxLength={102400}
                    className="font-mono text-sm"
                  />
                  <p className="text-xs text-muted-foreground">
                    Format: Symbol,Exchange,Quantity,Product (one per line, no header row). Max
                    100KB.
                  </p>
                </div>

                <div className="flex items-center gap-4">
                  <Button type="submit" disabled={submitting}>
                    {submitting ? 'Importing...' : 'Import Symbols'}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setCsvData('')}
                    disabled={!csvData}
                  >
                    Clear
                  </Button>
                </div>
              </form>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      {/* Current Mappings */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            Current Symbol Mappings
          </CardTitle>
          <CardDescription>
            {mappings.length} symbol{mappings.length !== 1 ? 's' : ''} configured
          </CardDescription>
        </CardHeader>
        <CardContent>
          {mappings.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <p>No symbols configured yet.</p>
              <p className="text-sm">Add symbols using the form above.</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Exchange</TableHead>
                  <TableHead className="text-right">Quantity</TableHead>
                  <TableHead>Product</TableHead>
                  <TableHead className="text-right">Added</TableHead>
                  <TableHead className="w-16"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {mappings.map((mapping) => (
                  <TableRow key={mapping.id}>
                    <TableCell className="font-medium">{mapping.symbol}</TableCell>
                    <TableCell>
                      <Badge variant="outline">{mapping.exchange}</Badge>
                    </TableCell>
                    <TableCell className="text-right">{mapping.quantity}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{mapping.product_type}</Badge>
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground text-sm">
                      {new Date(mapping.created_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="text-red-500 hover:text-red-600 hover:bg-red-50"
                        onClick={() => {
                          setMappingToDelete(mapping.id)
                          setDeleteDialogOpen(true)
                        }}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove Symbol</DialogTitle>
            <DialogDescription>
              Are you sure you want to remove this symbol from the strategy? This action cannot be
              undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDeleteMapping}>
              Remove Symbol
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
