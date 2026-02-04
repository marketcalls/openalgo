// components/trading/PlaceOrderDialog.tsx
// Reusable order placement dialog with real-time quotes and market depth
// Uses WebSocket for real-time data with REST API fallback (like Holdings/Positions)

import { useCallback, useEffect, useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useAuthStore } from '@/stores/authStore'
import { useMarketData } from '@/hooks/useMarketData'
import { tradingApi, type QuotesData, type DepthData } from '@/api/trading'
import { showToast } from '@/utils/toast'
import { cn } from '@/lib/utils'
import { QuoteHeader } from './QuoteHeader'
import { MarketDepthPanel } from './MarketDepthPanel'

// Price types for order dialog
// Backend API accepts: MARKET, LIMIT, SL (Stop Loss Limit), SL-M (Stop Loss Market)
const PRICE_TYPES = [
  { value: 'MARKET', label: 'Market' },
  { value: 'LIMIT', label: 'Limit' },
  { value: 'SL-M', label: 'SL-M' },      // Stop Loss Market (trigger only)
  { value: 'SL', label: 'SL-L' },         // Stop Loss Limit (trigger + price)
] as const

// Product types based on exchange
const FNO_PRODUCT_TYPES = [
  { value: 'NRML', label: 'NRML' },
  { value: 'MIS', label: 'MIS' },
] as const

const EQUITY_PRODUCT_TYPES = [
  { value: 'CNC', label: 'CNC' },
  { value: 'MIS', label: 'MIS' },
] as const

export interface PlaceOrderDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  symbol?: string
  exchange?: string
  action?: 'BUY' | 'SELL'
  quantity?: number
  lotSize?: number
  tickSize?: number
  product?: 'MIS' | 'NRML' | 'CNC'
  priceType?: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
  strategy?: string
  onSuccess?: (orderId: string) => void
  onError?: (error: string) => void
}

// Tick size validation helpers
function roundToTick(price: number, tickSize: number): number {
  if (tickSize <= 0) return price
  // Use toFixed to avoid floating point precision issues (e.g., 140.95000000000002)
  return Number((Math.round(price / tickSize) * tickSize).toFixed(2))
}

function adjustPrice(price: number, tickSize: number, direction: 'up' | 'down'): number {
  const rounded = roundToTick(price, tickSize)
  if (direction === 'up') {
    return Number((rounded + tickSize).toFixed(2))
  }
  return Math.max(0, Number((rounded - tickSize).toFixed(2)))
}

// Check if exchange is F&O/Commodity/Currency (uses NRML/MIS)
// NSE, BSE = Equity → CNC/MIS
// NFO, BFO, CDS, BCD, MCX, NCDEX = F&O/Currency/Commodity → NRML/MIS
function isFnOExchange(exchange: string): boolean {
  return ['NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NCDEX'].includes(exchange)
}

export function PlaceOrderDialog({
  open,
  onOpenChange,
  symbol = '',
  exchange = '',
  action: initialAction = 'BUY',
  quantity: initialQuantity,
  lotSize = 1,
  tickSize = 0.05,
  product: initialProduct = 'NRML',
  priceType: initialPriceType = 'MARKET',
  strategy = 'OptionChain',
  onSuccess,
  onError,
}: PlaceOrderDialogProps) {
  const { apiKey } = useAuthStore()

  // Form state
  const [formAction, setFormAction] = useState<'BUY' | 'SELL'>(initialAction)
  const [formQuantity, setFormQuantity] = useState(initialQuantity ?? lotSize)
  const [formPriceType, setFormPriceType] = useState(initialPriceType)
  const [formProduct, setFormProduct] = useState(initialProduct)
  const [formPrice, setFormPrice] = useState(0)
  const [formTriggerPrice, setFormTriggerPrice] = useState(0)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isDepthExpanded, setIsDepthExpanded] = useState(false)
  const [quantityMode, setQuantityMode] = useState<'lots' | 'shares'>('lots')
  const [lotMultiplier, setLotMultiplier] = useState(1)

  // REST API fallback data (like useLivePrice pattern)
  const [restQuotes, setRestQuotes] = useState<QuotesData | null>(null)
  const [restDepth, setRestDepth] = useState<DepthData | null>(null)
  const [isLoadingQuotes, setIsLoadingQuotes] = useState(false)

  // Get available product types based on exchange
  const productTypes = isFnOExchange(exchange) ? FNO_PRODUCT_TYPES : EQUITY_PRODUCT_TYPES

  // Fetch quotes via REST API (fallback when WebSocket not available)
  const fetchQuotes = useCallback(async () => {
    if (!apiKey || !symbol || !exchange) return

    setIsLoadingQuotes(true)
    try {
      const response = await tradingApi.getQuotes(apiKey, symbol, exchange)
      if (response.status === 'success' && response.data) {
        setRestQuotes(response.data)
      }
    } catch {
      // Silently fail - REST quotes is a fallback mechanism
      console.debug('REST quotes fetch failed')
    } finally {
      setIsLoadingQuotes(false)
    }
  }, [apiKey, symbol, exchange])

  // Fetch depth via REST API (fallback when WebSocket depth not available)
  const fetchDepth = useCallback(async () => {
    if (!apiKey || !symbol || !exchange) return

    try {
      const response = await tradingApi.getDepth(apiKey, symbol, exchange)
      if (response.status === 'success' && response.data) {
        setRestDepth(response.data)
      }
    } catch {
      // Silently fail - REST depth is a fallback mechanism
      console.debug('REST depth fetch failed')
    }
  }, [apiKey, symbol, exchange])

  // Reset form when dialog opens with new values
  useEffect(() => {
    if (open) {
      setFormAction(initialAction)
      setFormQuantity(initialQuantity ?? lotSize)
      setFormPriceType(initialPriceType)
      // Set default product based on exchange, validate initialProduct is valid for exchange
      const isFnO = isFnOExchange(exchange)
      const defaultProduct = isFnO ? 'NRML' : 'CNC'
      // Validate product: CNC not valid for F&O, NRML not valid for equity
      const validProducts = isFnO ? ['NRML', 'MIS'] : ['CNC', 'MIS']
      const productToUse = initialProduct && validProducts.includes(initialProduct)
        ? initialProduct
        : defaultProduct
      setFormProduct(productToUse)
      setFormPrice(0)
      setFormTriggerPrice(0)
      setIsDepthExpanded(false)
      setQuantityMode('lots')
      setLotMultiplier(1)
      setRestQuotes(null)
      setRestDepth(null)

      // Fetch REST quotes and depth immediately when dialog opens
      fetchQuotes()
      fetchDepth()
    }
  }, [open, initialAction, initialQuantity, lotSize, initialPriceType, initialProduct, exchange, fetchQuotes, fetchDepth])

  // Real-time market data via WebSocket
  const { data: marketDataMap, isConnected } = useMarketData({
    symbols: symbol && exchange ? [{ symbol, exchange }] : [],
    mode: 'Depth',
    enabled: open && !!symbol && !!exchange,
  })

  const wsData = marketDataMap.get(`${exchange}:${symbol}`)?.data

  // Convert REST depth format (bids/asks) to WebSocket depth format (buy/sell)
  const restDepthConverted = restDepth ? {
    buy: restDepth.bids.map(level => ({ price: level.price, quantity: level.quantity })),
    sell: restDepth.asks.map(level => ({ price: level.price, quantity: level.quantity })),
  } : undefined

  // Merge WebSocket and REST data - WebSocket takes priority when available
  // This ensures data shows immediately from REST, then updates from WebSocket
  const mergedData = {
    ltp: wsData?.ltp ?? restDepth?.ltp ?? restQuotes?.ltp,
    close: wsData?.close ?? restDepth?.prev_close ?? restQuotes?.prev_close,
    change: wsData?.change,
    change_percent: wsData?.change_percent,
    // Bid/Ask: prefer WebSocket depth, then REST depth, then WebSocket quote, then REST quotes
    bidPrice: wsData?.depth?.buy?.[0]?.price ?? restDepthConverted?.buy?.[0]?.price ?? wsData?.bid_price ?? restQuotes?.bid,
    askPrice: wsData?.depth?.sell?.[0]?.price ?? restDepthConverted?.sell?.[0]?.price ?? wsData?.ask_price ?? restQuotes?.ask,
    bidSize: wsData?.depth?.buy?.[0]?.quantity ?? restDepthConverted?.buy?.[0]?.quantity ?? wsData?.bid_size,
    askSize: wsData?.depth?.sell?.[0]?.quantity ?? restDepthConverted?.sell?.[0]?.quantity ?? wsData?.ask_size,
    // Depth: prefer WebSocket, fallback to REST depth
    depth: wsData?.depth ?? restDepthConverted,
  }

  // Calculate change from REST data if WebSocket doesn't have it
  const displayChange = mergedData.change ?? (mergedData.ltp && mergedData.close ? mergedData.ltp - mergedData.close : undefined)
  const displayChangePercent = mergedData.change_percent ?? (displayChange && mergedData.close ? (displayChange / mergedData.close) * 100 : undefined)

  // Set price to LTP when switching to LIMIT and LTP is available
  useEffect(() => {
    if (formPriceType !== 'MARKET' && mergedData.ltp && formPrice === 0) {
      setFormPrice(roundToTick(mergedData.ltp, tickSize))
    }
  }, [formPriceType, mergedData.ltp, formPrice, tickSize])

  // Validation - determine which price fields are needed:
  // LIMIT: price only
  // SL-M (Stop Loss Market): trigger price only
  // SL (Stop Loss Limit): both price and trigger price
  const needsPrice = formPriceType === 'LIMIT' || formPriceType === 'SL'
  const needsTrigger = formPriceType === 'SL-M' || formPriceType === 'SL'

  const isValid = useCallback(() => {
    if (!symbol || !exchange) return false
    if (!apiKey) return false
    if (formQuantity <= 0) return false
    if (needsPrice && formPrice <= 0) return false
    if (needsTrigger && formTriggerPrice <= 0) return false
    return true
  }, [symbol, exchange, apiKey, formQuantity, needsPrice, formPrice, needsTrigger, formTriggerPrice])

  // Submit order
  const handleSubmit = async () => {
    if (!isValid()) {
      showToast.error('Please fill all required fields')
      return
    }

    if (!apiKey) {
      showToast.error('API key not found. Please set up your API key.')
      onError?.('API key not found')
      return
    }

    setIsSubmitting(true)
    try {
      // Price types are now directly mapped to API values
      // Backend accepts: MARKET, LIMIT, SL (Stop Loss Limit), SL-M (Stop Loss Market)
      const apiPriceType = formPriceType as 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'

      const orderRequest = {
        apikey: apiKey,
        strategy,
        exchange,
        symbol,
        action: formAction,
        quantity: formQuantity,
        pricetype: apiPriceType,
        product: formProduct,
        ...(needsPrice && { price: formPrice }),
        ...(needsTrigger && { trigger_price: formTriggerPrice }),
      }

      const response = await tradingApi.placeOrder(orderRequest)

      // Response structure: { status: "success", orderid: "..." } or { status: "error", message: "..." }
      // Note: orderid is at root level, not in data field
      const orderid = (response as unknown as { orderid?: string }).orderid
      if (response.status === 'success' && orderid) {
        // Toast is shown by useSocket when WebSocket receives order update
        onSuccess?.(orderid)
        onOpenChange(false)
      } else {
        const errorMsg = response.message || 'Order placement failed'
        showToast.error(errorMsg, 'orders')
        onError?.(errorMsg)
      }
    } catch (err: unknown) {
      // Extract error message from axios error response or fallback to error message
      let errorMsg = 'Order placement failed'
      if (err && typeof err === 'object') {
        const axiosError = err as { response?: { data?: { message?: string } }; message?: string }
        if (axiosError.response?.data?.message) {
          errorMsg = axiosError.response.data.message
        } else if (axiosError.message) {
          errorMsg = axiosError.message
        }
      }
      showToast.error(errorMsg, 'orders')
      onError?.(errorMsg)
    } finally {
      setIsSubmitting(false)
    }
  }

  // Quantity change handler
  const handleQuantityChange = (value: string) => {
    const num = parseInt(value) || 0
    if (quantityMode === 'lots') {
      // In lots mode, multiply by lot size
      setFormQuantity(num * lotSize)
      setLotMultiplier(num)
    } else {
      // In shares mode, ensure it's a multiple of lot size
      const roundedQty = Math.max(lotSize, Math.round(num / lotSize) * lotSize)
      setFormQuantity(roundedQty)
      setLotMultiplier(roundedQty / lotSize)
    }
  }

  // Get display quantity based on mode
  const displayQuantity = quantityMode === 'lots' ? lotMultiplier : formQuantity

  // Determine if we're still loading initial data
  const isLoading = isLoadingQuotes && !mergedData.ltp && !isConnected

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[420px]" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span>Place Order -</span>
            <span className={formAction === 'BUY' ? 'text-green-500' : 'text-red-500'}>
              {formAction}
            </span>
            <span className="text-muted-foreground font-normal text-sm truncate">
              {symbol}
            </span>
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Quote Header - merged WebSocket + REST data */}
          <QuoteHeader
            exchange={exchange}
            ltp={mergedData.ltp}
            prevClose={mergedData.close}
            change={displayChange}
            changePercent={displayChangePercent}
            bidPrice={mergedData.bidPrice}
            askPrice={mergedData.askPrice}
            bidSize={mergedData.bidSize}
            askSize={mergedData.askSize}
            isLoading={isLoading}
          />

          {/* Market Depth Panel - only from WebSocket */}
          <MarketDepthPanel
            depth={mergedData.depth}
            isExpanded={isDepthExpanded}
            onToggle={() => setIsDepthExpanded(!isDepthExpanded)}
            maxLevels={5}
          />

          {/* Action Toggle */}
          <div className="space-y-2">
            <Label className="text-xs">Action</Label>
            <div className="flex gap-2">
              <Button
                type="button"
                variant={formAction === 'BUY' ? 'default' : 'outline'}
                className={cn(
                  'flex-1',
                  formAction === 'BUY' && 'bg-green-600 hover:bg-green-700'
                )}
                onClick={() => setFormAction('BUY')}
              >
                BUY
              </Button>
              <Button
                type="button"
                variant={formAction === 'SELL' ? 'default' : 'outline'}
                className={cn(
                  'flex-1',
                  formAction === 'SELL' && 'bg-red-600 hover:bg-red-700'
                )}
                onClick={() => setFormAction('SELL')}
              >
                SELL
              </Button>
            </div>
          </div>

          {/* Quantity with Mode Toggle */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label className="text-xs">Quantity</Label>
              <div className="flex gap-1">
                <button
                  type="button"
                  onClick={() => setQuantityMode('lots')}
                  className={cn(
                    'px-2 py-0.5 text-[10px] rounded',
                    quantityMode === 'lots'
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-muted text-muted-foreground hover:bg-muted/80'
                  )}
                >
                  Lots
                </button>
                <button
                  type="button"
                  onClick={() => setQuantityMode('shares')}
                  className={cn(
                    'px-2 py-0.5 text-[10px] rounded',
                    quantityMode === 'shares'
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-muted text-muted-foreground hover:bg-muted/80'
                  )}
                >
                  Shares
                </button>
              </div>
            </div>
            <Input
              type="number"
              value={displayQuantity}
              onChange={(e) => handleQuantityChange(e.target.value)}
              min={1}
            />
            <div className="flex justify-between text-[10px] text-muted-foreground">
              <span>Lot size: {lotSize}</span>
              <span>Total qty: {formQuantity}</span>
            </div>
          </div>

          {/* Price Type and Product in row */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-2">
              <Label className="text-xs">Price Type</Label>
              <Select value={formPriceType} onValueChange={(v) => setFormPriceType(v as typeof formPriceType)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {PRICE_TYPES.map((pt) => (
                    <SelectItem key={pt.value} value={pt.value}>
                      {pt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label className="text-xs">Product</Label>
              <Select value={formProduct} onValueChange={(v) => setFormProduct(v as typeof formProduct)}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {productTypes.map((pt) => (
                    <SelectItem key={pt.value} value={pt.value}>
                      {pt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Price Input (conditional) */}
          {needsPrice && (
            <div className="space-y-2">
              <Label className="text-xs">Price</Label>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="px-2"
                  onClick={() => setFormPrice(adjustPrice(formPrice, tickSize, 'down'))}
                >
                  -
                </Button>
                <Input
                  type="number"
                  value={formPrice}
                  onChange={(e) => setFormPrice(parseFloat(e.target.value) || 0)}
                  onBlur={() => setFormPrice(roundToTick(formPrice, tickSize))}
                  className="flex-1 text-center"
                  step={tickSize}
                  min={0}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="px-2"
                  onClick={() => setFormPrice(adjustPrice(formPrice, tickSize, 'up'))}
                >
                  +
                </Button>
              </div>
              <p className="text-[10px] text-muted-foreground">Tick size: {tickSize}</p>
            </div>
          )}

          {/* Trigger Price Input (conditional) */}
          {needsTrigger && (
            <div className="space-y-2">
              <Label className="text-xs">Trigger Price</Label>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="px-2"
                  onClick={() => setFormTriggerPrice(adjustPrice(formTriggerPrice, tickSize, 'down'))}
                >
                  -
                </Button>
                <Input
                  type="number"
                  value={formTriggerPrice}
                  onChange={(e) => setFormTriggerPrice(parseFloat(e.target.value) || 0)}
                  onBlur={() => setFormTriggerPrice(roundToTick(formTriggerPrice, tickSize))}
                  className="flex-1 text-center"
                  step={tickSize}
                  min={0}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="px-2"
                  onClick={() => setFormTriggerPrice(adjustPrice(formTriggerPrice, tickSize, 'up'))}
                >
                  +
                </Button>
              </div>
            </div>
          )}
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={!isValid() || isSubmitting}
            className={cn(
              formAction === 'BUY' ? 'bg-green-600 hover:bg-green-700' : 'bg-red-600 hover:bg-red-700'
            )}
          >
            {isSubmitting ? 'Placing...' : `Place ${formAction} Order`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
