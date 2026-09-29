// components/flow/panels/ConfigPanel.tsx
// Right sidebar for configuring selected nodes - Full implementation

import { useQuery } from '@tanstack/react-query'
import { Copy, Eye, EyeOff, Info, Loader2, Settings2, Trash2, X } from 'lucide-react'
import { useCallback, useState } from 'react'
import { useParams } from 'react-router'
import { flowQueryKeys, getIndexSymbolsLotSizes, getWebhookInfo } from '@/api/flow'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import type { PriceType } from '@/lib/flow/constants'
import {
  DAYS_OF_WEEK,
  defaultProductForExchange,
  EXCHANGES,
  EXPIRY_TYPES,
  INDEX_SYMBOLS,
  INDICATOR_CATALOG,
  INDICATOR_PARAMS,
  NODE_DEFINITIONS,
  OPTION_NODE_PRODUCT,
  OPTION_STRATEGIES,
  OPTION_TYPES,
  ORDER_ACTIONS,
  PRODUCT_TYPES,
  SCHEDULE_TYPES,
  strikeOffsetOptions,
} from '@/lib/flow/constants'
import { cn } from '@/lib/utils'
import { useFlowWorkflowStore } from '@/stores/flowWorkflowStore'
import type { BasketOrderItem } from '@/types/flow'
import { showToast } from '@/utils/toast'

/**
 * The Basket node's "no blanket product" choice. Radix needs a non-empty item
 * value, and the node stores the absence of a product rather than this string.
 */
const BASKET_PRODUCT_AUTO = 'AUTO'

import { CustomLegsFields } from './CustomLegsFields'
import { IndicatorParamsFields } from './IndicatorParamsFields'
import { MarginPositionsFields } from './MarginPositionsFields'
import {
  ActionField,
  ExchangeField,
  ExpiryField,
  PriceTypeField,
  ProductField,
  QuantityField,
} from './OrderFields'
import { getOptionsMultiStrategyUpdate, OrderPriceFields } from './OrderPriceFields'
import { TemplatableField } from './TemplatableField'

// ===== LOCAL CONSTANTS =====

const ALERT_CONDITIONS = [
  { value: 'above', label: 'Greater Than' },
  { value: 'below', label: 'Less Than' },
  { value: 'crosses_above', label: 'Crosses Above' },
  { value: 'crosses_below', label: 'Crosses Below' },
]

const ALERT_TRIGGERS = [
  { value: 'once', label: 'Only Once' },
  { value: 'every_time', label: 'Every Time' },
]

const ALERT_EXPIRATION = [
  { value: 'none', label: 'No Expiration' },
  { value: '1h', label: '1 Hour' },
  { value: '4h', label: '4 Hours' },
  { value: '1d', label: '1 Day' },
  { value: '1w', label: '1 Week' },
]

const VARIABLE_OPERATIONS = [
  { value: 'set', label: 'Set Value', description: 'Set variable to a value' },
  { value: 'get', label: 'Get Value', description: 'Copy from another variable' },
  { value: 'add', label: 'Add', description: 'Add to variable' },
  { value: 'subtract', label: 'Subtract', description: 'Subtract from variable' },
  { value: 'multiply', label: 'Multiply', description: 'Multiply variable' },
  { value: 'divide', label: 'Divide', description: 'Divide variable' },
  { value: 'increment', label: 'Increment', description: 'Add 1 to variable' },
  { value: 'decrement', label: 'Decrement', description: 'Subtract 1 from variable' },
  { value: 'parse_json', label: 'Parse JSON', description: 'Parse JSON string to object' },
  { value: 'stringify', label: 'Stringify', description: 'Convert to JSON string' },
  { value: 'append', label: 'Append', description: 'Append to string' },
]

const LOG_LEVELS = [
  { value: 'info', label: 'Info', color: 'text-blue-400' },
  { value: 'warn', label: 'Warning', color: 'text-yellow-400' },
  { value: 'error', label: 'Error', color: 'text-red-400' },
]

const TIME_OPERATORS = [
  { value: '==', label: 'Equals (=)', description: 'Exactly at this time' },
  { value: '>=', label: 'At or After (>=)', description: 'Time has passed' },
  { value: '<=', label: 'At or Before (<=)', description: 'Before this time' },
  { value: '>', label: 'After (>)', description: 'Strictly after' },
  { value: '<', label: 'Before (<)', description: 'Strictly before' },
]

const CONDITION_TYPES = [
  { value: 'entry', label: 'Entry' },
  { value: 'exit', label: 'Exit' },
  { value: 'custom', label: 'Custom' },
]

const HTTP_METHODS = [
  { value: 'GET', label: 'GET' },
  { value: 'POST', label: 'POST' },
  { value: 'PUT', label: 'PUT' },
  { value: 'DELETE', label: 'DEL' },
  { value: 'PATCH', label: 'PATCH' },
]

// Node type to display name
const NODE_TITLES: Record<string, string> = {
  start: 'Schedule Trigger',
  priceAlert: 'Price Alert',
  webhookTrigger: 'Webhook Trigger',
  orderUpdateTrigger: 'Order Update Trigger',
  placeOrder: 'Place Order',
  smartOrder: 'Smart Order',
  optionsOrder: 'Options Order',
  optionsMultiOrder: 'Multi-Leg Options',
  basketOrder: 'Basket Order',
  splitOrder: 'Split Order',
  cancelOrder: 'Cancel Order',
  cancelAllOrders: 'Cancel All Orders',
  closePositions: 'Close Positions',
  modifyOrder: 'Modify Order',
  getQuote: 'Get Quote',
  getDepth: 'Get Depth',
  getOrderStatus: 'Order Status',
  openPosition: 'Open Position',
  history: 'History Data',
  indicator: 'Indicator',
  priorPeriodOhlc: 'Prior Period OHLC',
  strategyPnl: 'Strategy P&L',
  barOffset: 'Bar Offset',
  expiry: 'Get Expiry',
  calendar: 'Calendar',
  intervals: 'Intervals',
  multiQuotes: 'Multi Quotes',
  symbol: 'Symbol Info',
  optionSymbol: 'Option Symbol',
  orderBook: 'Order Book',
  tradeBook: 'Trade Book',
  positionBook: 'Position Book',
  syntheticFuture: 'Synthetic Future',
  optionChain: 'Option Chain',
  holidays: 'Holidays',
  timings: 'Market Timings',
  holdings: 'Holdings',
  funds: 'Funds',
  margin: 'Margin Calculator',
  delay: 'Delay',
  waitUntil: 'Wait Until',
  log: 'Log',
  telegramAlert: 'Telegram Alert',
  whatsappAlert: 'WhatsApp Alert',
  variable: 'Variable',
  mathExpression: 'Math Expression',
  httpRequest: 'HTTP Request',
  timeWindow: 'Time Window',
  timeCondition: 'Time Condition',
  priceCondition: 'Price Condition',
  varCondition: 'Var Condition',
  positionCheck: 'Position Check',
  fundCheck: 'Fund Check',
  andGate: 'AND Gate',
  orGate: 'OR Gate',
  notGate: 'NOT Gate',
  group: 'Group',
  subscribeLtp: 'Subscribe LTP',
  subscribeQuote: 'Subscribe Quote',
  subscribeDepth: 'Subscribe Depth',
  unsubscribe: 'Unsubscribe',
}

/** Drop `params` keys the newly selected indicator does not accept.
 *
 * Left alone when the JSON is malformed or holds a {{variable}} reference -
 * that text is the user's to fix, and rewriting it would discard it. */
function pruneIndicatorParams(indicatorName: string, raw: string): string {
  const text = raw.trim()
  if (!text) return ''
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    return raw
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return raw
  const allowed = new Set((INDICATOR_PARAMS[indicatorName] ?? []).map((p) => p.name))
  const kept = Object.fromEntries(
    Object.entries(parsed as Record<string, unknown>).filter(([key]) => allowed.has(key))
  )
  return Object.keys(kept).length ? JSON.stringify(kept) : ''
}

function getNodeInfo(nodeType: string) {
  for (const category of Object.values(NODE_DEFINITIONS)) {
    const node = category.find((n) => n.type === nodeType)
    if (node) return node
  }
  return null
}

function basketOrdersText(orders: string | BasketOrderItem[] | undefined): string {
  if (Array.isArray(orders)) return JSON.stringify(orders, null, 2)
  return orders || ''
}

function basketOrdersToCsv(orders: BasketOrderItem[]): string {
  return orders
    .map((order) => [order.symbol, order.exchange, order.action, order.quantity].join(','))
    .join('\n')
}

export function ConfigPanel() {
  const { id: workflowId } = useParams<{ id: string }>()
  const { nodes, selectedNodeId, updateNodeData, deleteNode, selectNode } = useFlowWorkflowStore()
  const [showSecret, setShowSecret] = useState(false)

  const selectedNode = nodes.find((n) => n.id === selectedNodeId)
  const isWebhookTrigger = selectedNode?.type === 'webhookTrigger'

  const webhookQuery = useQuery({
    queryKey: flowQueryKeys.webhook(Number(workflowId)),
    queryFn: () => getWebhookInfo(Number(workflowId)),
    enabled: isWebhookTrigger && !!workflowId,
  })

  // Fetch dynamic lot sizes for index symbols from master contract DB
  const indexSymbolsQuery = useQuery({
    queryKey: flowQueryKeys.indexSymbols(),
    queryFn: getIndexSymbolsLotSizes,
    staleTime: 1000 * 60 * 60, // Cache for 1 hour (lot sizes don't change often)
  })

  // Helper to get lot size from DB for a given underlying
  const getLotSizeFromDb = (underlying: string): number | null => {
    const dbSymbol = indexSymbolsQuery.data?.find((s) => s.value === underlying)
    return dbSymbol?.lotSize || null
  }

  const isMcxUnderlying = (underlying: string): boolean =>
    INDEX_SYMBOLS.find((s) => s.value === underlying)?.exchange === 'MCX'

  // MCX contracts expire monthly, so the weekly choices have nothing to select
  // and would resolve to the nearest month anyway -- the label would be telling
  // the author something the run does not do.
  const expiryTypesFor = (underlying: string) =>
    isMcxUnderlying(underlying)
      ? EXPIRY_TYPES.filter((e) => e.value.endsWith('_month'))
      : EXPIRY_TYPES

  // Picking an MCX underlying while a weekly expiry is selected would leave the
  // Select rendering an empty trigger, so move it to the nearest equivalent.
  const applyUnderlying = (value: string) => {
    handleDataChange('underlying', value)
    const s = INDEX_SYMBOLS.find((x) => x.value === value)
    if (!s) return
    handleDataChange('exchange', s.exchange)
    if (s.exchange === 'MCX') {
      const expiryType = (nodeData.expiryType as string) || 'current_week'
      if (!expiryType.endsWith('_month')) handleDataChange('expiryType', 'current_month')
    }
  }

  const handleDataChange = useCallback(
    (key: string, value: unknown) => {
      if (selectedNodeId) updateNodeData(selectedNodeId, { [key]: value })
    },
    [selectedNodeId, updateNodeData]
  )

  const handleDelete = useCallback(() => {
    if (selectedNodeId) deleteNode(selectedNodeId)
  }, [selectedNodeId, deleteNode])
  const handleClose = useCallback(() => {
    selectNode(null)
  }, [selectNode])
  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text)
    showToast.success(`${label} copied`)
  }

  if (!selectedNode) {
    return (
      <div className="w-80 border-l border-border bg-card flex flex-col h-full">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Settings2 className="h-4 w-4 text-muted-foreground" />
            <span className="font-medium">Properties</span>
          </div>
        </div>
        <div className="flex-1 flex items-center justify-center p-6">
          <div className="text-center text-muted-foreground">
            <Settings2 className="h-12 w-12 mx-auto mb-3 opacity-30" />
            <p className="text-sm">Select a node to configure</p>
          </div>
        </div>
      </div>
    )
  }

  const nodeInfo = getNodeInfo(selectedNode.type || '')
  const nodeData = selectedNode.data as Record<string, unknown>
  const nodeType = selectedNode.type || 'unknown'
  const orderPriceType = (nodeData.priceType as PriceType | undefined) || 'MARKET'
  // What the Product control shows. A product the author picked is stored on
  // the node and always wins; with none stored the node follows its exchange,
  // so a derivative segment reads NRML and cash reads MIS. Options nodes trade
  // a derivative whatever their underlying's exchange field happens to be.
  const nodeProduct =
    (nodeData.product as string) ||
    (nodeType === 'optionsOrder' || nodeType === 'optionsMultiOrder'
      ? OPTION_NODE_PRODUCT
      : defaultProductForExchange(nodeData.exchange as string | undefined))
  const basketOrders = nodeData.orders as string | BasketOrderItem[] | undefined
  const nodeTitle = NODE_TITLES[nodeType] || nodeInfo?.label || nodeType

  return (
    <div className="w-80 border-l border-border bg-card flex flex-col h-full">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div>
          <h2 className="font-semibold text-sm">{nodeTitle}</h2>
          <p className="text-xs text-muted-foreground">Configure node</p>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-destructive hover:text-destructive"
            onClick={handleDelete}
            aria-label="Delete node"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={handleClose}
            aria-label="Close configuration panel"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="flex-1 min-h-0">
        <ScrollArea className="h-full">
          <div className="space-y-4 p-4">
            {/* ===== SCHEDULE/START ===== */}
            {nodeType === 'start' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Schedule Type</Label>
                  <Select
                    value={(nodeData.scheduleType as string) || 'daily'}
                    onValueChange={(v) => handleDataChange('scheduleType', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {SCHEDULE_TYPES.map((t) => (
                        <SelectItem key={t.value} value={t.value}>
                          {t.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {nodeData.scheduleType !== 'interval' && (
                  <div className="space-y-2">
                    <Label className="text-xs">Time</Label>
                    <Input
                      type="time"
                      className="h-8"
                      value={(nodeData.time as string) || '09:15'}
                      onChange={(e) => handleDataChange('time', e.target.value)}
                    />
                  </div>
                )}
                {nodeData.scheduleType === 'interval' && (
                  <div className="space-y-2">
                    <Label className="text-xs">Repeat Every</Label>
                    <div className="flex gap-2">
                      <Input
                        type="number"
                        min="1"
                        className="h-8 w-20"
                        value={(nodeData.intervalValue as number) || 1}
                        onChange={(e) =>
                          handleDataChange('intervalValue', parseInt(e.target.value, 10) || 1)
                        }
                      />
                      <Select
                        value={(nodeData.intervalUnit as string) || 'minutes'}
                        onValueChange={(v) => handleDataChange('intervalUnit', v)}
                      >
                        <SelectTrigger className="h-8 flex-1">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="seconds">Seconds</SelectItem>
                          <SelectItem value="minutes">Minutes</SelectItem>
                          <SelectItem value="hours">Hours</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                )}
                {(nodeData.scheduleType === 'daily' || nodeData.scheduleType === 'weekly') && (
                  <div className="space-y-2">
                    <Label className="text-xs">Run On Days</Label>
                    <div className="flex flex-wrap gap-1 mb-2">
                      <button
                        type="button"
                        onClick={() => handleDataChange('days', [0, 1, 2, 3, 4])}
                        className="rounded-md bg-muted px-2 py-1 text-[10px] hover:bg-accent"
                      >
                        Weekdays
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDataChange('days', [5, 6])}
                        className="rounded-md bg-muted px-2 py-1 text-[10px] hover:bg-accent"
                      >
                        Weekends
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDataChange('days', [0, 1, 2, 3, 4, 5, 6])}
                        className="rounded-md bg-muted px-2 py-1 text-[10px] hover:bg-accent"
                      >
                        All
                      </button>
                    </div>
                    <div className="flex flex-wrap gap-1">
                      {DAYS_OF_WEEK.map((day) => {
                        const days = (nodeData.days as number[]) || [0, 1, 2, 3, 4]
                        const sel = days.includes(day.value)
                        return (
                          <button
                            key={day.value}
                            type="button"
                            onClick={() =>
                              handleDataChange(
                                'days',
                                sel
                                  ? days.filter((d) => d !== day.value)
                                  : [...days, day.value].sort()
                              )
                            }
                            className={cn(
                              'flex h-8 w-8 items-center justify-center rounded-md text-xs font-medium',
                              sel
                                ? 'bg-primary text-primary-foreground'
                                : 'bg-muted text-muted-foreground hover:bg-accent'
                            )}
                          >
                            {day.label}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )}
                {nodeData.scheduleType === 'once' && (
                  <div className="space-y-2">
                    <Label className="text-xs">Date</Label>
                    <Input
                      type="date"
                      className="h-8"
                      value={(nodeData.executeAt as string) || ''}
                      onChange={(e) => handleDataChange('executeAt', e.target.value)}
                    />
                  </div>
                )}

                <Separator />

                {/* The scheduler has read these three since market-hours
                    gating was added, but nothing rendered them, so the window
                    could only be set by hand-editing the workflow JSON. */}
                <div className="flex items-center justify-between gap-2">
                  <Label className="text-xs">Only during market hours</Label>
                  <Switch
                    checked={nodeData.marketHoursOnly !== false}
                    onCheckedChange={(v) => handleDataChange('marketHoursOnly', v)}
                  />
                </div>

                {nodeData.marketHoursOnly !== false && (
                  <>
                    <div className="grid grid-cols-2 gap-2">
                      <div className="space-y-2">
                        <Label className="text-xs">Start</Label>
                        <Input
                          type="time"
                          className="h-8"
                          value={(nodeData.marketHoursStart as string) || '09:15'}
                          onChange={(e) => handleDataChange('marketHoursStart', e.target.value)}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label className="text-xs">End</Label>
                        <Input
                          type="time"
                          className="h-8"
                          value={(nodeData.marketHoursEnd as string) || '15:15'}
                          onChange={(e) => handleDataChange('marketHoursEnd', e.target.value)}
                        />
                      </div>
                    </div>
                    <ExchangeField
                      label="Calendar"
                      value={(nodeData.marketHoursExchange as string) || 'NSE'}
                      onChange={(v) => handleDataChange('marketHoursExchange', v)}
                    />
                    <p className="text-[10px] text-muted-foreground">
                      The window narrows the exchange's own session; it never reopens a holiday or a
                      weekend. Leave the calendar on the exchange you trade, so MCX and CRYPTO
                      inherit their real hours.
                    </p>
                  </>
                )}
              </>
            )}

            {/* ===== PRICE ALERT ===== */}
            {nodeType === 'priceAlert' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="RELIANCE"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Condition</Label>
                  <Select
                    value={(nodeData.condition as string) || 'above'}
                    onValueChange={(v) => handleDataChange('condition', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ALERT_CONDITIONS.map((c) => (
                        <SelectItem key={c.value} value={c.value}>
                          {c.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Target Price</Label>
                  <Input
                    type="number"
                    step="0.05"
                    className="h-8"
                    value={(nodeData.price as number) || ''}
                    onChange={(e) => handleDataChange('price', parseFloat(e.target.value) || 0)}
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Trigger</Label>
                  <Select
                    value={(nodeData.trigger as string) || 'once'}
                    onValueChange={(v) => handleDataChange('trigger', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ALERT_TRIGGERS.map((t) => (
                        <SelectItem key={t.value} value={t.value}>
                          {t.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Expiration</Label>
                  <Select
                    value={(nodeData.expiration as string) || 'none'}
                    onValueChange={(v) => handleDataChange('expiration', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ALERT_EXPIRATION.map((e) => (
                        <SelectItem key={e.value} value={e.value}>
                          {e.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-center justify-between rounded-lg border p-3">
                  <div>
                    <Label className="text-xs">Play Sound</Label>
                  </div>
                  <Switch
                    checked={(nodeData.playSound as boolean) ?? true}
                    onCheckedChange={(v) => handleDataChange('playSound', v)}
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Alert Message</Label>
                  <Input
                    className="h-8"
                    placeholder="Custom message"
                    value={(nodeData.message as string) || ''}
                    onChange={(e) => handleDataChange('message', e.target.value)}
                  />
                </div>
              </>
            )}

            {/* ===== WEBHOOK TRIGGER ===== */}
            {nodeType === 'webhookTrigger' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Label</Label>
                  <Input
                    className="h-8"
                    placeholder="TradingView Alert"
                    value={(nodeData.label as string) || ''}
                    onChange={(e) => handleDataChange('label', e.target.value)}
                  />
                </div>
                <Separator />
                {webhookQuery.isLoading ? (
                  <div className="flex justify-center py-4">
                    <Loader2 className="h-5 w-5 animate-spin" />
                  </div>
                ) : webhookQuery.data ? (
                  <>
                    <div className="space-y-2">
                      <Label className="text-xs">Webhook URL</Label>
                      <div className="flex gap-1">
                        <Input
                          readOnly
                          value={webhookQuery.data.webhook_url}
                          className="font-mono text-[10px] h-8"
                        />
                        <Button
                          variant="outline"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() =>
                            copyToClipboard(
                              nodeData.symbol
                                ? `${webhookQuery.data.webhook_url}/${nodeData.symbol}`
                                : webhookQuery.data.webhook_url,
                              'URL'
                            )
                          }
                          aria-label="Copy webhook URL"
                        >
                          <Copy className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs">Webhook Secret</Label>
                      <div className="flex gap-1">
                        <div className="relative flex-1">
                          <Input
                            readOnly
                            type={showSecret ? 'text' : 'password'}
                            value={webhookQuery.data.webhook_secret}
                            className="font-mono text-[10px] h-8 pr-8"
                          />
                          <Button
                            variant="ghost"
                            size="icon"
                            className="absolute right-0 top-0 h-8 w-8"
                            onClick={() => setShowSecret(!showSecret)}
                            aria-label={showSecret ? 'Hide webhook secret' : 'Show webhook secret'}
                          >
                            {showSecret ? (
                              <EyeOff className="h-3 w-3" />
                            ) : (
                              <Eye className="h-3 w-3" />
                            )}
                          </Button>
                        </div>
                        <Button
                          variant="outline"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() =>
                            copyToClipboard(webhookQuery.data.webhook_secret, 'Secret')
                          }
                          aria-label="Copy webhook secret"
                        >
                          <Copy className="h-3 w-3" />
                        </Button>
                      </div>
                    </div>
                    <div
                      className={cn(
                        'rounded-lg border p-2 text-center text-xs',
                        webhookQuery.data.webhook_enabled
                          ? 'border-green-500/30 bg-green-500/10 text-green-600'
                          : 'border-yellow-500/30 bg-yellow-500/10 text-yellow-600'
                      )}
                    >
                      {webhookQuery.data.webhook_enabled ? 'Webhook enabled' : 'Webhook disabled'}
                    </div>
                  </>
                ) : (
                  <div className="rounded-lg border-yellow-500/30 bg-yellow-500/10 p-3 text-center text-xs text-yellow-600">
                    Save workflow first
                  </div>
                )}
              </>
            )}

            {nodeType === 'orderUpdateTrigger' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Order ID (optional)</Label>
                  <Input
                    className="h-8"
                    placeholder="240221025997024"
                    value={(nodeData.orderId as string) || ''}
                    onChange={(e) => handleDataChange('orderId', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    A literal broker order id. {'{{variable}}'} references are not supported here -
                    a trigger has no upstream node to resolve them from. To react to an order this
                    workflow placed, filter by Symbol instead.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol (optional)</Label>
                  <Input
                    className="h-8"
                    placeholder="NIFTY28OCT2525950CE"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <p className="text-[10px] text-muted-foreground">
                  Set at least one of Order ID / Symbol - an unfiltered watch would fire on every
                  order in the account.
                </p>
                <div className="space-y-2">
                  <Label className="text-xs">Exchange (optional)</Label>
                  <Select
                    value={(nodeData.exchange as string) || 'ANY'}
                    onValueChange={(v) => handleDataChange('exchange', v === 'ANY' ? '' : v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ANY">Any exchange</SelectItem>
                      {EXCHANGES.map((e) => (
                        <SelectItem key={e.value} value={e.value}>
                          {e.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Status</Label>
                  <Select
                    value={(nodeData.status as string) || 'complete'}
                    onValueChange={(v) => handleDataChange('status', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="any">Any status change</SelectItem>
                      <SelectItem value="open">Open</SelectItem>
                      <SelectItem value="trigger pending">Trigger Pending</SelectItem>
                      <SelectItem value="complete">Complete (filled)</SelectItem>
                      <SelectItem value="rejected">Rejected</SelectItem>
                      <SelectItem value="cancelled">Cancelled</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Trigger</Label>
                  <Select
                    value={(nodeData.trigger as string) || 'once'}
                    onValueChange={(v) => handleDataChange('trigger', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="once">Once, then stop watching</SelectItem>
                      <SelectItem value="every_time">Every matching update</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </>
            )}

            {/* ===== PLACE ORDER ===== */}
            {nodeType === 'placeOrder' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="RELIANCE"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
                <ActionField
                  value={nodeData.action}
                  onChange={(v) => handleDataChange('action', v)}
                />
                <QuantityField
                  value={(nodeData.quantity as number) || 1}
                  onChange={(v) => handleDataChange('quantity', v)}
                />
                <ProductField
                  value={nodeProduct}
                  onChange={(v) => handleDataChange('product', v)}
                />
                <PriceTypeField
                  value={(nodeData.priceType as string) || 'MARKET'}
                  onChange={(v) => handleDataChange('priceType', v)}
                />
                <OrderPriceFields
                  priceType={orderPriceType}
                  price={nodeData.price ?? 0}
                  triggerPrice={nodeData.triggerPrice ?? 0}
                  onPriceChange={(value) => handleDataChange('price', value)}
                  onTriggerPriceChange={(value) => handleDataChange('triggerPrice', value)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="orderResult"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Use {`{{orderResult.orderid}}`}
                  </p>
                </div>
              </>
            )}

            {/* ===== SMART ORDER ===== */}
            {nodeType === 'smartOrder' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="RELIANCE"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
                <ActionField
                  value={nodeData.action}
                  onChange={(v) => handleDataChange('action', v)}
                />
                <QuantityField
                  value={(nodeData.quantity as number | undefined) ?? 1}
                  onChange={(v) => handleDataChange('quantity', v)}
                  min={0}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Position Size</Label>
                  <Input
                    type="number"
                    className="h-8"
                    value={(nodeData.positionSize as number) ?? 0}
                    onChange={(e) => {
                      const val = parseInt(e.target.value, 10)
                      handleDataChange('positionSize', Number.isNaN(val) ? 0 : val)
                    }}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Target position (positive=long, negative=short, 0=use quantity)
                  </p>
                </div>
                <ProductField
                  value={nodeProduct}
                  onChange={(v) => handleDataChange('product', v)}
                />
                <PriceTypeField
                  value={orderPriceType}
                  onChange={(v) => handleDataChange('priceType', v)}
                />
                <OrderPriceFields
                  priceType={orderPriceType}
                  price={nodeData.price ?? 0}
                  triggerPrice={nodeData.triggerPrice ?? 0}
                  onPriceChange={(value) => handleDataChange('price', value)}
                  onTriggerPriceChange={(value) => handleDataChange('triggerPrice', value)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="smartResult"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                </div>
              </>
            )}

            {/* ===== OPTIONS ORDER ===== */}
            {nodeType === 'optionsOrder' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Underlying</Label>
                  <Select
                    value={(nodeData.underlying as string) || 'NIFTY'}
                    onValueChange={(v) => {
                      applyUnderlying(v)
                      // Deliberately does NOT write the lot size into quantity.
                      // This field is a lot COUNT and the executor multiplies it
                      // by the lot size, so storing the lot size here squared it
                      // (NIFTY: 65 lots x 65 = 4,225 units instead of 65).
                      // The lot count is the user's; only the resolved preview
                      // below reflects the instrument's lot size.
                    }}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {INDEX_SYMBOLS.map((s) => (
                        <SelectItem key={s.value} value={s.value}>
                          {s.label} ({s.exchange})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <ExpiryField
                  value={(nodeData.expiryType as string) || 'current_week'}
                  onChange={(v) => handleDataChange('expiryType', v)}
                  options={expiryTypesFor((nodeData.underlying as string) || 'NIFTY')}
                />
                <TemplatableField
                  label="Strike Offset"
                  value={(nodeData.offset as string) || 'ATM'}
                  onChange={(v) => handleDataChange('offset', v)}
                  fallback="ATM"
                  placeholder="{{webhook.offset}}"
                  hint="Must resolve to ATM, ITM1-ITM50 or OTM1-OTM50."
                >
                  <Select
                    value={(nodeData.offset as string) || 'ATM'}
                    onValueChange={(v) => handleDataChange('offset', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {strikeOffsetOptions(nodeData.offset).map((o) => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TemplatableField>
                <TemplatableField
                  label="Option Type"
                  value={nodeData.optionType}
                  onChange={(v) => handleDataChange('optionType', v)}
                  fallback="CE"
                  placeholder="{{webhook.optionType}}"
                  hint="Must resolve to CE or PE."
                >
                  <div className="grid grid-cols-2 gap-2">
                    {OPTION_TYPES.map((o) => (
                      <button
                        key={o.value}
                        type="button"
                        onClick={() => handleDataChange('optionType', o.value)}
                        className={cn(
                          'rounded-lg border py-2 text-sm font-semibold',
                          nodeData.optionType === o.value
                            ? o.value === 'CE'
                              ? 'bg-green-500/20 border-green-500 text-green-600'
                              : 'bg-red-500/20 border-red-500 text-red-600'
                            : 'border-border bg-muted'
                        )}
                      >
                        {o.label}
                      </button>
                    ))}
                  </div>
                </TemplatableField>
                <ActionField
                  value={nodeData.action}
                  onChange={(v) => handleDataChange('action', v)}
                />
                <QuantityField
                  label="Quantity (Lots)"
                  value={nodeData.quantity ?? 1}
                  onChange={(v) => handleDataChange('quantity', v)}
                />
                {(() => {
                  const lotSize = getLotSizeFromDb((nodeData.underlying as string) || 'NIFTY')
                  const lots = nodeData.quantity ?? 1
                  // A reference has no lot count to multiply out until it
                  // resolves at run time, so the arithmetic is withheld rather
                  // than printed against the token.
                  if (!lotSize || typeof lots !== 'number') return null
                  return (
                    <p className="-mt-1 text-[10px] text-muted-foreground">
                      {lots} lot{lots === 1 ? '' : 's'} x {lotSize} ={' '}
                      <span className="font-medium text-foreground">{lots * lotSize} units</span>
                    </p>
                  )
                })()}
                <ProductField
                  value={nodeProduct}
                  onChange={(v) => handleDataChange('product', v)}
                />
                <PriceTypeField
                  value={(nodeData.priceType as string) || 'MARKET'}
                  onChange={(v) => handleDataChange('priceType', v)}
                />
                <OrderPriceFields
                  priceType={orderPriceType}
                  price={nodeData.price ?? 0}
                  triggerPrice={nodeData.triggerPrice ?? 0}
                  onPriceChange={(value) => handleDataChange('price', value)}
                  onTriggerPriceChange={(value) => handleDataChange('triggerPrice', value)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="optionOrder"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                </div>
              </>
            )}

            {/* ===== OPTIONS MULTI ORDER ===== */}
            {nodeType === 'optionsMultiOrder' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Strategy</Label>
                  <Select
                    value={(nodeData.strategy as string) || 'straddle'}
                    onValueChange={(strategy) => {
                      if (!selectedNodeId) return
                      updateNodeData(
                        selectedNodeId,
                        getOptionsMultiStrategyUpdate(
                          {
                            strategy: (nodeData.strategy as string) || 'straddle',
                            priceType: orderPriceType,
                          },
                          strategy
                        )
                      )
                    }}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {OPTION_STRATEGIES.map((s) => (
                        <SelectItem key={s.value} value={s.value}>
                          {s.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Underlying</Label>
                  <Select
                    value={(nodeData.underlying as string) || 'NIFTY'}
                    onValueChange={(v) => applyUnderlying(v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {INDEX_SYMBOLS.map((s) => (
                        <SelectItem key={s.value} value={s.value}>
                          {s.label} ({s.exchange})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <ExpiryField
                  value={(nodeData.expiryType as string) || 'current_week'}
                  onChange={(v) => handleDataChange('expiryType', v)}
                  options={expiryTypesFor((nodeData.underlying as string) || 'NIFTY')}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Action</Label>
                  <div className="grid grid-cols-2 gap-2">
                    {ORDER_ACTIONS.map((a) => (
                      <button
                        key={a.value}
                        type="button"
                        onClick={() => handleDataChange('action', a.value)}
                        className={cn(
                          'rounded-lg border py-2 text-sm font-semibold',
                          nodeData.action === a.value
                            ? a.value === 'BUY'
                              ? 'bg-green-500/20 border-green-500 text-green-600'
                              : 'bg-red-500/20 border-red-500 text-red-600'
                            : 'border-border bg-muted'
                        )}
                      >
                        {a.label}
                      </button>
                    ))}
                  </div>
                  <p className="text-[10px] text-muted-foreground">
                    {nodeData.action === 'BUY' ? 'Long strategy' : 'Short strategy'}
                  </p>
                </div>
                <QuantityField
                  label="Quantity (Lots)"
                  value={nodeData.quantity ?? 1}
                  onChange={(v) => handleDataChange('quantity', v)}
                />
                <ProductField
                  value={nodeProduct}
                  onChange={(v) => handleDataChange('product', v)}
                />
                <PriceTypeField
                  value={orderPriceType}
                  onChange={(v) => handleDataChange('priceType', v)}
                />
                <OrderPriceFields
                  priceType={orderPriceType}
                  price={nodeData.price ?? 0}
                  triggerPrice={nodeData.triggerPrice ?? 0}
                  onPriceChange={(value) => handleDataChange('price', value)}
                  onTriggerPriceChange={(value) => handleDataChange('triggerPrice', value)}
                />
                {nodeData.strategy === 'custom' && (
                  <p className="text-[10px] text-muted-foreground">
                    Custom legs inherit these common product and price fields when omitted. A
                    leg&apos;s explicit product, price type, price, or trigger price overrides the
                    common value.
                  </p>
                )}
                {orderPriceType === 'LIMIT' && nodeData.strategy !== 'custom' && (
                  <div>
                    <p className="text-[10px] text-muted-foreground">
                      Applied to every generated leg. A LIMIT order without a positive price is
                      rejected rather than sent at market.
                    </p>
                  </div>
                )}
                {/* Strategy Legs Preview */}
                <div className="rounded-lg border bg-muted/30 p-2">
                  <p className="text-[10px] font-medium mb-1.5">Strategy Legs:</p>
                  <div className="space-y-0.5 text-[10px] font-mono">
                    {nodeData.strategy === 'straddle' && (
                      <>
                        <div className="flex justify-between">
                          <span>ATM CE</span>
                          <span
                            className={
                              nodeData.action === 'BUY' ? 'text-green-600' : 'text-red-600'
                            }
                          >
                            {(nodeData.action as string) || 'SELL'}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span>ATM PE</span>
                          <span
                            className={
                              nodeData.action === 'BUY' ? 'text-green-600' : 'text-red-600'
                            }
                          >
                            {(nodeData.action as string) || 'SELL'}
                          </span>
                        </div>
                      </>
                    )}
                    {nodeData.strategy === 'strangle' && (
                      <>
                        <div className="flex justify-between">
                          <span>OTM2 CE</span>
                          <span
                            className={
                              nodeData.action === 'BUY' ? 'text-green-600' : 'text-red-600'
                            }
                          >
                            {(nodeData.action as string) || 'SELL'}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span>OTM2 PE</span>
                          <span
                            className={
                              nodeData.action === 'BUY' ? 'text-green-600' : 'text-red-600'
                            }
                          >
                            {(nodeData.action as string) || 'SELL'}
                          </span>
                        </div>
                      </>
                    )}
                    {nodeData.strategy === 'iron_condor' && (
                      <>
                        <div className="flex justify-between">
                          <span>OTM2 CE</span>
                          <span className="text-red-600">SELL</span>
                        </div>
                        <div className="flex justify-between">
                          <span>OTM4 CE</span>
                          <span className="text-green-600">BUY</span>
                        </div>
                        <div className="flex justify-between">
                          <span>OTM2 PE</span>
                          <span className="text-red-600">SELL</span>
                        </div>
                        <div className="flex justify-between">
                          <span>OTM4 PE</span>
                          <span className="text-green-600">BUY</span>
                        </div>
                      </>
                    )}
                    {nodeData.strategy === 'bull_call_spread' && (
                      <>
                        <div className="flex justify-between">
                          <span>ATM CE</span>
                          <span className="text-green-600">BUY</span>
                        </div>
                        <div className="flex justify-between">
                          <span>OTM2 CE</span>
                          <span className="text-red-600">SELL</span>
                        </div>
                      </>
                    )}
                    {nodeData.strategy === 'bear_put_spread' && (
                      <>
                        <div className="flex justify-between">
                          <span>ATM PE</span>
                          <span className="text-green-600">BUY</span>
                        </div>
                        <div className="flex justify-between">
                          <span>OTM2 PE</span>
                          <span className="text-red-600">SELL</span>
                        </div>
                      </>
                    )}
                    {nodeData.strategy === 'custom' && (
                      <p className="text-muted-foreground">Built below, leg by leg.</p>
                    )}
                  </div>
                </div>
                {nodeData.strategy === 'custom' && (
                  <CustomLegsFields
                    value={nodeData.legs}
                    onChange={(legs) => handleDataChange('legs', legs)}
                    commonPriceType={orderPriceType}
                    commonProduct={nodeProduct}
                    commonExpiryType={(nodeData.expiryType as string) || 'current_week'}
                    commonAction={(nodeData.action as string) || 'SELL'}
                    commonQuantity={(nodeData.quantity as number) || 1}
                    strangleWidth={(nodeData.strangleWidth as string) || 'OTM2'}
                    underlying={(nodeData.underlying as string) || 'NIFTY'}
                  />
                )}
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="multiLegOrder"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                </div>
              </>
            )}

            {/* ===== BASKET ORDER ===== */}
            {nodeType === 'basketOrder' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Basket Name</Label>
                  <Input
                    className="h-8"
                    placeholder="Morning Portfolio"
                    value={(nodeData.basketName as string) || ''}
                    onChange={(e) => handleDataChange('basketName', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Orders (SYMBOL,EXCHANGE,ACTION,QTY)</Label>
                  <Textarea
                    className="min-h-[100px] text-xs font-mono"
                    placeholder="RELIANCE,NSE,BUY,10&#10;INFY,NSE,BUY,5&#10;SBIN,NSE,SELL,20"
                    value={basketOrdersText(basketOrders)}
                    readOnly={Array.isArray(basketOrders)}
                    onChange={(e) => handleDataChange('orders', e.target.value)}
                  />
                  {Array.isArray(basketOrders) && (
                    <div className="space-y-2 rounded-md border p-2">
                      <p className="text-[10px] text-muted-foreground">
                        This imported per-order list is preserved read-only, including product and
                        price overrides. Converting to CSV keeps only symbol, exchange, action, and
                        quantity so the rows can be edited here.
                      </p>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-7 text-xs"
                        onClick={() => handleDataChange('orders', basketOrdersToCsv(basketOrders))}
                      >
                        Convert imported orders to CSV
                      </Button>
                    </div>
                  )}
                  <p className="text-[10px] text-muted-foreground">
                    Supported exchanges: NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCO
                  </p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Product</Label>
                  {/* One basket can mix segments, so the default is decided per
                      row rather than blanket: an NFO row goes NRML while an NSE
                      row goes MIS. Choosing a product here overrides all of
                      them. */}
                  <Select
                    value={(nodeData.product as string) || BASKET_PRODUCT_AUTO}
                    onValueChange={(v) =>
                      handleDataChange('product', v === BASKET_PRODUCT_AUTO ? undefined : v)
                    }
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={BASKET_PRODUCT_AUTO}>By row exchange</SelectItem>
                      {PRODUCT_TYPES.map((t) => (
                        <SelectItem key={t.value} value={t.value}>
                          {t.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <PriceTypeField
                  value={(nodeData.priceType as string) || 'MARKET'}
                  onChange={(v) => handleDataChange('priceType', v)}
                />
                <OrderPriceFields
                  priceType={orderPriceType}
                  price={nodeData.price ?? 0}
                  triggerPrice={nodeData.triggerPrice ?? 0}
                  onPriceChange={(value) => handleDataChange('price', value)}
                  onTriggerPriceChange={(value) => handleDataChange('triggerPrice', value)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="basketResult"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Use {`{{basketResult.results}}`} in other nodes
                  </p>
                </div>
              </>
            )}

            {/* ===== SPLIT ORDER ===== */}
            {nodeType === 'splitOrder' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="RELIANCE"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
                <ActionField
                  value={nodeData.action}
                  onChange={(v) => handleDataChange('action', v)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Total Quantity</Label>
                  <Input
                    type="number"
                    min={1}
                    className="h-8"
                    value={(nodeData.quantity as number) || 100}
                    onChange={(e) =>
                      handleDataChange('quantity', parseInt(e.target.value, 10) || 100)
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Split Size</Label>
                  <Input
                    type="number"
                    min={1}
                    className="h-8"
                    value={(nodeData.splitSize as number) || 50}
                    onChange={(e) =>
                      handleDataChange('splitSize', parseInt(e.target.value, 10) || 50)
                    }
                  />
                </div>
                <ProductField
                  value={nodeProduct}
                  onChange={(v) => handleDataChange('product', v)}
                />
                <PriceTypeField
                  value={orderPriceType}
                  onChange={(v) => handleDataChange('priceType', v)}
                />
                <OrderPriceFields
                  priceType={orderPriceType}
                  price={nodeData.price ?? 0}
                  triggerPrice={nodeData.triggerPrice ?? 0}
                  onPriceChange={(value) => handleDataChange('price', value)}
                  onTriggerPriceChange={(value) => handleDataChange('triggerPrice', value)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="splitResult"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Use {`{{splitResult.results}}`} in other nodes
                  </p>
                </div>
                <p className="text-[10px] text-muted-foreground">
                  Splits into{' '}
                  {Math.ceil(
                    ((nodeData.quantity as number) || 100) / ((nodeData.splitSize as number) || 50)
                  )}{' '}
                  orders
                </p>
              </>
            )}

            {/* ===== CANCEL ORDER ===== */}
            {nodeType === 'cancelOrder' && (
              <div className="space-y-2">
                <Label className="text-xs">Order ID</Label>
                <Input
                  className="h-8"
                  placeholder="{{orderResult.orderid}}"
                  value={(nodeData.orderId as string) || ''}
                  onChange={(e) => handleDataChange('orderId', e.target.value)}
                />
                <p className="text-[10px] text-muted-foreground">Use variable from Place Order</p>
              </div>
            )}

            {/* ===== CANCEL ALL / CLOSE POSITIONS ===== */}
            {nodeType === 'cancelAllOrders' && (
              <div className="rounded-lg border bg-muted/30 p-3">
                <p className="text-xs text-muted-foreground">
                  Cancels all open orders. No configuration needed.
                </p>
              </div>
            )}
            {nodeType === 'closePositions' && (
              <>
                <div className="rounded-lg border bg-muted/30 p-3">
                  <p className="text-xs text-muted-foreground">
                    Leave Symbol blank to square off every open position. Set it to close only that
                    position; Exchange and Product narrow it further.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="Blank = close all positions"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                {Boolean(nodeData.symbol) && (
                  <>
                    <ExchangeField
                      value={(nodeData.exchange as string) || 'NSE'}
                      onChange={(v) => handleDataChange('exchange', v)}
                    />
                    <ProductField
                      value={nodeProduct}
                      onChange={(v) => handleDataChange('product', v)}
                    />
                  </>
                )}
              </>
            )}

            {/* ===== MODIFY ORDER ===== */}
            {nodeType === 'modifyOrder' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Order ID</Label>
                  <Input
                    className="h-8"
                    placeholder="{{orderResult.orderid}}"
                    value={(nodeData.orderId as string) || ''}
                    onChange={(e) => handleDataChange('orderId', e.target.value)}
                  />
                </div>
                <div className="rounded-lg border bg-muted/30 p-3">
                  <p className="text-xs text-muted-foreground">
                    Symbol, exchange, side and product are read from the live order, so anything
                    left blank here stays as it is.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">New Price</Label>
                  <Input
                    type="number"
                    step="0.05"
                    className="h-8"
                    placeholder="Leave empty to keep"
                    value={(nodeData.newPrice as number) ?? ''}
                    onChange={(e) => handleDataChange('newPrice', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">New Quantity</Label>
                  <Input
                    type="number"
                    min={1}
                    className="h-8"
                    placeholder="Leave empty to keep"
                    value={(nodeData.newQuantity as number) ?? ''}
                    onChange={(e) => handleDataChange('newQuantity', e.target.value)}
                  />
                </div>
              </>
            )}

            {/* ===== DATA NODES ===== */}
            {nodeType === 'getQuote' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="RELIANCE"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="quote"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">Use {`{{quote.data.ltp}}`}</p>
                </div>
              </>
            )}

            {nodeType === 'getDepth' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="SBIN"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="depth"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Use {`{{depth.data.bids[0].price}}`}
                  </p>
                </div>
              </>
            )}

            {/* ===== GET ORDER STATUS ===== */}
            {nodeType === 'getOrderStatus' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Order ID</Label>
                  <Input
                    className="h-8"
                    placeholder="{{orderResult.orderid}}"
                    value={(nodeData.orderId as string) || ''}
                    onChange={(e) => handleDataChange('orderId', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Use variable from Place Order node
                  </p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="orderStatus"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Use {`{{orderStatus.data.order_status}}`}
                  </p>
                </div>
              </>
            )}

            {nodeType === 'openPosition' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="RELIANCE"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
                <ProductField
                  value={nodeProduct}
                  onChange={(v) => handleDataChange('product', v)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="position"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">Use {`{{position.quantity}}`}</p>
                </div>
              </>
            )}

            {nodeType === 'history' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="SBIN"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Interval</Label>
                  <Select
                    value={(nodeData.interval as string) || '1d'}
                    onValueChange={(v) => handleDataChange('interval', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="1m">1 Min</SelectItem>
                      <SelectItem value="5m">5 Min</SelectItem>
                      <SelectItem value="15m">15 Min</SelectItem>
                      <SelectItem value="1h">1 Hour</SelectItem>
                      <SelectItem value="1d">Daily</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Days</Label>
                  <Input
                    type="number"
                    min={1}
                    max={365}
                    className="h-8"
                    value={(nodeData.days as number) || 30}
                    onChange={(e) => handleDataChange('days', parseInt(e.target.value, 10) || 30)}
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="ohlcv"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                </div>
              </>
            )}

            {nodeType === 'indicator' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Indicator</Label>
                  <Select
                    value={(nodeData.indicatorName as string) || 'rsi'}
                    onValueChange={(v) => {
                      handleDataChange('indicatorName', v)
                      // Params are kwargs for the previously selected function.
                      // Carrying them over sends the new indicator a keyword it
                      // does not accept - ta.macd(period=14) is a TypeError -
                      // so keep only the names the new one actually takes.
                      handleDataChange(
                        'params',
                        pruneIndicatorParams(v, (nodeData.params as string) || '')
                      )
                    }}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="max-h-72">
                      {INDICATOR_CATALOG.map((ind) => (
                        <SelectItem key={ind.value} value={ind.value}>
                          {ind.label} ({ind.category})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Nest on another indicator (optional)</Label>
                  <Input
                    className="h-8"
                    placeholder="{{rsi1.series}}"
                    value={(nodeData.sourceSeries as string) || ''}
                    onChange={(e) => handleDataChange('sourceSeries', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Set to compute this indicator over another Indicator node's output (e.g. SMA of
                    RSI) instead of fetching fresh history. Accepts a raw History array too -{' '}
                    {'{{h.data}}'} uses each row's close. Only single-series indicators (SMA, EMA,
                    RSI, WMA, stdev, highest/lowest, ...) can be nested.
                  </p>
                </div>
                {nodeData.sourceSeries ? (
                  <div className="space-y-2">
                    <Label className="text-xs">Source Field (optional)</Label>
                    <Input
                      className="h-8"
                      placeholder="blank = auto (value, out0, close)"
                      value={(nodeData.sourceField as string) || ''}
                      onChange={(e) => handleDataChange('sourceField', e.target.value)}
                    />
                    <p className="text-[10px] text-muted-foreground">
                      Which field to read from each row, e.g. high, low, out1.
                    </p>
                  </div>
                ) : null}
                {!nodeData.sourceSeries && (
                  <>
                    <div className="space-y-2">
                      <Label className="text-xs">Symbol</Label>
                      <Input
                        className="h-8"
                        placeholder="RELIANCE"
                        value={(nodeData.symbol as string) || ''}
                        onChange={(e) => handleDataChange('symbol', e.target.value)}
                      />
                    </div>
                    <ExchangeField
                      value={(nodeData.exchange as string) || 'NSE'}
                      onChange={(v) => handleDataChange('exchange', v)}
                    />
                    <div className="space-y-2">
                      <Label className="text-xs">Interval</Label>
                      <Input
                        className="h-8"
                        placeholder="D, 5m, 1h, or a custom Historify interval"
                        value={(nodeData.interval as string) || 'D'}
                        onChange={(e) => handleDataChange('interval', e.target.value)}
                      />
                      <p className="text-[10px] text-muted-foreground">
                        Any interval your connected broker supports (check the Intervals node) - not
                        a fixed list.
                      </p>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs">Source</Label>
                      <Select
                        value={(nodeData.source as string) || 'api'}
                        onValueChange={(v) => handleDataChange('source', v)}
                      >
                        <SelectTrigger className="h-8">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="api">Broker API</SelectItem>
                          <SelectItem value="db">
                            Historify DB (custom intervals: 2m, 4m, W, M, Q)
                          </SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs">Lookback Bars</Label>
                      <Input
                        type="number"
                        min={5}
                        className="h-8"
                        value={(nodeData.lookbackBars as number) || 100}
                        onChange={(e) =>
                          handleDataChange('lookbackBars', parseInt(e.target.value, 10) || 100)
                        }
                      />
                    </div>
                  </>
                )}
                <IndicatorParamsFields
                  // Remount on either change so the number fields' in-progress
                  // text does not leak across nodes or indicators.
                  key={`${selectedNode.id}-${(nodeData.indicatorName as string) || 'rsi'}`}
                  indicatorName={(nodeData.indicatorName as string) || 'rsi'}
                  value={(nodeData.params as string) || ''}
                  onChange={(raw) => handleDataChange('params', raw)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Value N Bars Back</Label>
                  <Input
                    type="number"
                    min={0}
                    max={200}
                    className="h-8"
                    value={(nodeData.offsetBars as number) ?? 0}
                    onChange={(e) =>
                      handleDataChange('offsetBars', parseInt(e.target.value, 10) || 0)
                    }
                  />
                  <p className="text-[10px] text-muted-foreground">
                    0 = latest closed bar. Read it via {'{{name.at_offset.value}}'} (or{' '}
                    {'{{name.at_offset.out0}}'} for multi-output indicators). Prefer this over
                    indexing {'{{name.series[N]}}'}, whose offsets shift with Tail Bars.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Tail Bars</Label>
                  <Input
                    type="number"
                    min={1}
                    max={200}
                    className="h-8"
                    value={(nodeData.tailBars as number) || 5}
                    onChange={(e) =>
                      handleDataChange('tailBars', parseInt(e.target.value, 10) || 5)
                    }
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Length of {'{{ind.series}}'} - a fixed-length recent-history array so{' '}
                    {'{{ind.series[N]}}'} can address a specific historical bar.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="rsi1"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Access with {'{{name.latest.value}}'}, {'{{name.previous.value}}'}, or{' '}
                    {'{{name.series[N]}}'}. Multi-output indicators (MACD, BBands, ADX, ...) expose
                    out0, out1, ...
                  </p>
                </div>
              </>
            )}

            {nodeType === 'strategyPnl' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Strategy</Label>
                  <Input
                    className="h-8"
                    placeholder="blank = this workflow's name"
                    value={(nodeData.strategy as string) || ''}
                    onChange={(e) => handleDataChange('strategy', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Order nodes tag their orders with the workflow name, so leaving this blank
                    reports this workflow's own P&amp;L.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="spnl"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Exposes {'{{spnl.realized}}'}, {'{{spnl.unrealized}}'}, {'{{spnl.total}}'},{' '}
                    {'{{spnl.today_realized}}'}, {'{{spnl.open_quantity}}'}.
                  </p>
                </div>
              </>
            )}

            {nodeType === 'priorPeriodOhlc' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="NIFTY"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Period</Label>
                  <Select
                    value={(nodeData.period as string) || 'previous_day'}
                    onValueChange={(v) => handleDataChange('period', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="previous_hour">Previous Hour</SelectItem>
                      <SelectItem value="previous_day">Previous Day</SelectItem>
                      <SelectItem value="previous_week">Previous Week</SelectItem>
                      <SelectItem value="previous_month">Previous Month</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Source</Label>
                  <Select
                    value={(nodeData.source as string) || 'api'}
                    onValueChange={(v) => handleDataChange('source', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="api">Broker API</SelectItem>
                      <SelectItem value="db">Historify DB</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="pdhpdl"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Exposes {'{{name.pdh}}'}, {'{{name.pdl}}'}, {'{{name.pdc}}'} (also
                    {' {{name.high}}'}/{'low'}/{'close'}/{'open'}).
                  </p>
                </div>
              </>
            )}

            {nodeType === 'barOffset' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="RELIANCE"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Interval</Label>
                  <Input
                    className="h-8"
                    placeholder="D, 5m, 1h, or a custom Historify interval"
                    value={(nodeData.interval as string) || 'D'}
                    onChange={(e) => handleDataChange('interval', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Source</Label>
                  <Select
                    value={(nodeData.source as string) || 'api'}
                    onValueChange={(v) => handleDataChange('source', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="api">Broker API</SelectItem>
                      <SelectItem value="db">Historify DB</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Bars Back</Label>
                  <Input
                    type="number"
                    min={0}
                    className="h-8"
                    value={(nodeData.offsetBars as number) ?? 0}
                    onChange={(e) =>
                      handleDataChange('offsetBars', parseInt(e.target.value, 10) || 0)
                    }
                  />
                  <p className="text-[10px] text-muted-foreground">
                    0 = last CLOSED bar, 1 = one bar before that, ...
                  </p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="bar1"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                </div>
              </>
            )}

            {nodeType === 'expiry' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="NIFTY"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NFO'}
                  onChange={(v) => handleDataChange('exchange', v)}
                  fallback="NFO"
                />
                <div className="space-y-2">
                  <Label className="text-xs">Instrument Type</Label>
                  <Select
                    value={(nodeData.instrumenttype as string) || 'options'}
                    onValueChange={(v) => handleDataChange('instrumenttype', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="options">Options</SelectItem>
                      <SelectItem value="futures">Futures</SelectItem>
                    </SelectContent>
                  </Select>
                  <p className="text-[10px] text-muted-foreground">
                    Futures and options have different expiry calendars
                  </p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="expiries"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">Use {`{{expiries.data[0]}}`}</p>
                </div>
              </>
            )}

            {nodeType === 'multiQuotes' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbols (comma separated)</Label>
                  <Input
                    className="h-8"
                    placeholder="RELIANCE,INFY,TCS"
                    value={(nodeData.symbols as string) || ''}
                    onChange={(e) => handleDataChange('symbols', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="quotes"
                    value={(nodeData.outputVariable as string) || 'quotes'}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Use {`{{quotes.results[0].data.ltp}}`}
                  </p>
                </div>
              </>
            )}

            {nodeType === 'symbol' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="NIFTY30DEC25FUT"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NFO'}
                  onChange={(v) => handleDataChange('exchange', v)}
                  fallback="NFO"
                />
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="symbolInfo"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Use {`{{symbolInfo.data.lotsize}}`}
                  </p>
                </div>
              </>
            )}

            {nodeType === 'optionSymbol' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Underlying</Label>
                  <Input
                    className="h-8"
                    placeholder="NIFTY"
                    value={(nodeData.underlying as string) || ''}
                    onChange={(e) => handleDataChange('underlying', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE_INDEX'}
                  onChange={(v) => handleDataChange('exchange', v)}
                  fallback="NSE_INDEX"
                />
                <div className="space-y-2">
                  <Label className="text-xs">Expiry Date</Label>
                  <Input
                    className="h-8"
                    placeholder="30DEC25"
                    value={(nodeData.expiryDate as string) || ''}
                    onChange={(e) => handleDataChange('expiryDate', e.target.value)}
                  />
                </div>
                <TemplatableField
                  label="Strike Offset"
                  value={(nodeData.offset as string) || 'ATM'}
                  onChange={(v) => handleDataChange('offset', v)}
                  fallback="ATM"
                  placeholder="{{webhook.offset}}"
                  hint="Must resolve to ATM, ITM1-ITM50 or OTM1-OTM50."
                >
                  <Select
                    value={(nodeData.offset as string) || 'ATM'}
                    onValueChange={(v) => handleDataChange('offset', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {strikeOffsetOptions(nodeData.offset).map((o) => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TemplatableField>
                <div className="space-y-2">
                  <Label className="text-xs">Option Type</Label>
                  <div className="grid grid-cols-2 gap-2">
                    {['CE', 'PE'].map((t) => (
                      <button
                        key={t}
                        type="button"
                        onClick={() => handleDataChange('optionType', t)}
                        className={cn(
                          'rounded-lg border py-2 text-sm font-semibold',
                          nodeData.optionType === t
                            ? t === 'CE'
                              ? 'bg-green-500/20 border-green-500 text-green-600'
                              : 'bg-red-500/20 border-red-500 text-red-600'
                            : 'border-border bg-muted'
                        )}
                      >
                        {t === 'CE' ? 'Call' : 'Put'}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="optionSym"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                </div>
              </>
            )}

            {nodeType === 'calendar' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Date</Label>
                  <Input
                    type="date"
                    className="h-8"
                    value={(nodeData.date as string) || ''}
                    onChange={(e) => handleDataChange('date', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Leave blank for the current trading session date.
                  </p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="cal"
                    value={(nodeData.outputVariable as string) || 'cal'}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    {`{{cal.is_new_week}}`}, {`{{cal.is_new_month}}`}, {`{{cal.is_new_quarter}}`},{' '}
                    {`{{cal.is_trading_day}}`}
                  </p>
                </div>
              </>
            )}
            {nodeType === 'intervals' && (
              <div className="space-y-2">
                <Label className="text-xs">Output Variable</Label>
                <Input
                  className="h-8"
                  placeholder="intervals"
                  value={(nodeData.outputVariable as string) || 'intervals'}
                  onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                />
                <p className="text-[10px] text-muted-foreground">
                  Timeframes this broker supports. Use {`{{intervals.data.minutes}}`}
                </p>
              </div>
            )}
            {nodeType === 'orderBook' && (
              <div className="space-y-2">
                <Label className="text-xs">Output Variable</Label>
                <Input
                  className="h-8"
                  placeholder="orders"
                  value={(nodeData.outputVariable as string) || 'orders'}
                  onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                />
                <p className="text-[10px] text-muted-foreground">Use {`{{orders.data.orders}}`}</p>
              </div>
            )}
            {nodeType === 'tradeBook' && (
              <div className="space-y-2">
                <Label className="text-xs">Output Variable</Label>
                <Input
                  className="h-8"
                  placeholder="trades"
                  value={(nodeData.outputVariable as string) || 'trades'}
                  onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                />
                <p className="text-[10px] text-muted-foreground">Use {`{{trades.data}}`}</p>
              </div>
            )}
            {nodeType === 'positionBook' && (
              <div className="space-y-2">
                <Label className="text-xs">Output Variable</Label>
                <Input
                  className="h-8"
                  placeholder="positions"
                  value={(nodeData.outputVariable as string) || 'positions'}
                  onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                />
                <p className="text-[10px] text-muted-foreground">Use {`{{positions.data}}`}</p>
              </div>
            )}

            {nodeType === 'syntheticFuture' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Underlying</Label>
                  <Input
                    className="h-8"
                    placeholder="NIFTY"
                    value={(nodeData.underlying as string) || ''}
                    onChange={(e) => handleDataChange('underlying', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE_INDEX'}
                  onChange={(v) => handleDataChange('exchange', v)}
                  fallback="NSE_INDEX"
                />
                <div className="space-y-2">
                  <Label className="text-xs">Expiry Date</Label>
                  <Input
                    className="h-8"
                    placeholder="25NOV25"
                    value={(nodeData.expiryDate as string) || ''}
                    onChange={(e) => handleDataChange('expiryDate', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="synthFuture"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Use {`{{synthFuture.synthetic_future_price}}`}
                  </p>
                </div>
              </>
            )}

            {nodeType === 'optionChain' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Underlying</Label>
                  <Input
                    className="h-8"
                    placeholder="NIFTY"
                    value={(nodeData.underlying as string) || ''}
                    onChange={(e) => handleDataChange('underlying', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE_INDEX'}
                  onChange={(v) => handleDataChange('exchange', v)}
                  fallback="NSE_INDEX"
                />
                <div className="space-y-2">
                  <Label className="text-xs">Expiry Date</Label>
                  <Input
                    className="h-8"
                    placeholder="30DEC25"
                    value={(nodeData.expiryDate as string) || ''}
                    onChange={(e) => handleDataChange('expiryDate', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Strike Count</Label>
                  <Input
                    type="number"
                    className="h-8"
                    placeholder="10 (empty=full)"
                    value={(nodeData.strikeCount as number) || ''}
                    onChange={(e) =>
                      handleDataChange('strikeCount', parseInt(e.target.value, 10) || undefined)
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="chain"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">Use {`{{chain.atm_strike}}`}</p>
                </div>
              </>
            )}

            {nodeType === 'holidays' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Year</Label>
                  <Input
                    type="number"
                    className="h-8"
                    placeholder={String(new Date().getFullYear())}
                    value={(nodeData.year as number) || ''}
                    onChange={(e) =>
                      handleDataChange('year', parseInt(e.target.value, 10) || undefined)
                    }
                  />
                  <p className="text-[10px] text-muted-foreground">Empty = current year</p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="holidays"
                    value={(nodeData.outputVariable as string) || 'holidays'}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                </div>
              </>
            )}

            {nodeType === 'timings' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Date</Label>
                  <Input
                    type="date"
                    className="h-8"
                    value={(nodeData.date as string) || ''}
                    onChange={(e) => handleDataChange('date', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">Empty = today</p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="timings"
                    value={(nodeData.outputVariable as string) || 'timings'}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                </div>
              </>
            )}

            {nodeType === 'holdings' && (
              <div className="space-y-2">
                <Label className="text-xs">Output Variable</Label>
                <Input
                  className="h-8"
                  placeholder="holdings"
                  value={(nodeData.outputVariable as string) || 'holdings'}
                  onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                />
                <p className="text-[10px] text-muted-foreground">
                  Use {`{{holdings.data[0].symbol}}`}
                </p>
              </div>
            )}
            {nodeType === 'funds' && (
              <div className="space-y-2">
                <Label className="text-xs">Output Variable</Label>
                <Input
                  className="h-8"
                  placeholder="funds"
                  value={(nodeData.outputVariable as string) || 'funds'}
                  onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                />
                <p className="text-[10px] text-muted-foreground">
                  Use {`{{funds.data.availablecash}}`}
                </p>
              </div>
            )}

            {nodeType === 'margin' && (
              <>
                <MarginPositionsFields
                  value={(nodeData.positionsJson as string) || ''}
                  onChange={(raw) => handleDataChange('positionsJson', raw)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="marginResult"
                    value={(nodeData.outputVariable as string) || 'marginResult'}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                </div>
              </>
            )}

            {/* ===== STREAMING NODES ===== */}
            {nodeType === 'subscribeLtp' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="RELIANCE"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="ltp"
                    value={(nodeData.outputVariable as string) || 'ltp'}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">Real-time: {`{{ltp}}`}</p>
                </div>
              </>
            )}

            {nodeType === 'subscribeQuote' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="RELIANCE"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="quote"
                    value={(nodeData.outputVariable as string) || 'quote'}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Use {`{{quote.ltp}}`}, {`{{quote.open}}`}
                  </p>
                </div>
              </>
            )}

            {nodeType === 'subscribeDepth' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="RELIANCE"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="depth"
                    value={(nodeData.outputVariable as string) || 'depth'}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Use {`{{depth.bids[0].price}}`}
                  </p>
                </div>
              </>
            )}

            {nodeType === 'unsubscribe' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Stream Type</Label>
                  <Select
                    value={(nodeData.streamType as string) || 'all'}
                    onValueChange={(v) => handleDataChange('streamType', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ltp">LTP Only</SelectItem>
                      <SelectItem value="quote">Quote Only</SelectItem>
                      <SelectItem value="depth">Depth Only</SelectItem>
                      <SelectItem value="all">All Streams</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="Empty = all symbols"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
              </>
            )}

            {/* ===== UTILITY NODES ===== */}
            {nodeType === 'delay' && (
              <div className="space-y-2">
                <Label className="text-xs">Wait Duration</Label>
                <div className="flex gap-2">
                  <Input
                    type="number"
                    min={1}
                    className="h-8 flex-1"
                    value={(nodeData.delayValue as number) || 1}
                    onChange={(e) =>
                      handleDataChange('delayValue', parseInt(e.target.value, 10) || 1)
                    }
                  />
                  <Select
                    value={(nodeData.delayUnit as string) || 'seconds'}
                    onValueChange={(v) => handleDataChange('delayUnit', v)}
                  >
                    <SelectTrigger className="h-8 w-28">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="seconds">Seconds</SelectItem>
                      <SelectItem value="minutes">Minutes</SelectItem>
                      <SelectItem value="hours">Hours</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            )}

            {nodeType === 'waitUntil' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Target Time</Label>
                  <Input
                    type="time"
                    className="h-8"
                    value={(nodeData.targetTime as string) || '09:30'}
                    onChange={(e) => handleDataChange('targetTime', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Workflow pauses until this time
                  </p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Label</Label>
                  <Input
                    className="h-8"
                    placeholder="Wait for Entry"
                    value={(nodeData.label as string) || ''}
                    onChange={(e) => handleDataChange('label', e.target.value)}
                  />
                </div>
              </>
            )}

            {nodeType === 'log' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Log Level</Label>
                  <Select
                    value={(nodeData.level as string) || 'info'}
                    onValueChange={(v) => handleDataChange('level', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {LOG_LEVELS.map((l) => (
                        <SelectItem key={l.value} value={l.value}>
                          <span className={l.color}>{l.label}</span>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Message</Label>
                  <Textarea
                    className="min-h-[80px]"
                    placeholder="Log message with {{variables}}"
                    value={(nodeData.message as string) || ''}
                    onChange={(e) => handleDataChange('message', e.target.value)}
                  />
                </div>
              </>
            )}

            {nodeType === 'telegramAlert' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Message</Label>
                  <Textarea
                    className="min-h-[80px]"
                    placeholder="Order placed for {{orderResult.symbol}}"
                    value={(nodeData.message as string) || ''}
                    onChange={(e) => handleDataChange('message', e.target.value)}
                  />
                </div>
                <div className="rounded-lg border bg-muted/30 p-2">
                  <p className="text-[10px] text-muted-foreground">
                    Telegram delivery uses the account linked to the workflow owner's API key.
                  </p>
                </div>
              </>
            )}

            {nodeType === 'whatsappAlert' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">To (optional)</Label>
                  <Input
                    className="h-8"
                    placeholder="919876543210 - blank sends to yourself"
                    value={(nodeData.to as string) || ''}
                    onChange={(e) => handleDataChange('to', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Message</Label>
                  <Textarea
                    className="min-h-[80px]"
                    placeholder="Order placed for {{orderResult.symbol}}"
                    value={(nodeData.message as string) || ''}
                    onChange={(e) => handleDataChange('message', e.target.value)}
                  />
                </div>
                <div className="rounded-lg border bg-muted/30 p-2">
                  <p className="text-[10px] font-medium mb-1">Variables:</p>
                  <p className="text-[9px] font-mono text-muted-foreground">
                    {`{{orderResult.orderid}}`}, {`{{quote.ltp}}`}, {`{{timestamp}}`}
                  </p>
                </div>
                <p className="text-[10px] text-muted-foreground">
                  Requires the WhatsApp bot to be paired from the /whatsapp page first.
                </p>
              </>
            )}

            {nodeType === 'variable' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Variable Name</Label>
                  <Input
                    className="h-8"
                    placeholder="myLTP"
                    value={(nodeData.variableName as string) || ''}
                    onChange={(e) => handleDataChange('variableName', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Use: {`{{${(nodeData.variableName as string) || 'varName'}}}`}
                  </p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Operation</Label>
                  <Select
                    value={(nodeData.operation as string) || 'set'}
                    onValueChange={(v) => handleDataChange('operation', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {VARIABLE_OPERATIONS.map((o) => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                {['set', 'add', 'subtract', 'multiply', 'divide', 'append', 'parse_json'].includes(
                  nodeData.operation as string
                ) && (
                  <div className="space-y-2">
                    <Label className="text-xs">
                      {nodeData.operation === 'parse_json' ? 'JSON String' : 'Value'}
                    </Label>
                    {nodeData.operation === 'parse_json' ? (
                      <Textarea
                        className="min-h-[80px] font-mono"
                        placeholder='{"key": "value"}'
                        value={String(nodeData.value || '')}
                        onChange={(e) => handleDataChange('value', e.target.value)}
                      />
                    ) : (
                      <Input
                        className="h-8"
                        placeholder="Value or {{variable}}"
                        value={String(nodeData.value || '')}
                        onChange={(e) => handleDataChange('value', e.target.value)}
                      />
                    )}
                  </div>
                )}
                {['get', 'stringify'].includes(nodeData.operation as string) && (
                  <div className="space-y-2">
                    <Label className="text-xs">Source Variable</Label>
                    <Input
                      className="h-8"
                      placeholder="quoteData"
                      value={(nodeData.sourceVariable as string) || ''}
                      onChange={(e) => handleDataChange('sourceVariable', e.target.value)}
                    />
                  </div>
                )}
                {nodeData.operation === 'get' && (
                  <div className="space-y-2">
                    <Label className="text-xs">JSON Path</Label>
                    <Input
                      className="h-8"
                      placeholder="data.ltp"
                      value={(nodeData.jsonPath as string) || ''}
                      onChange={(e) => handleDataChange('jsonPath', e.target.value)}
                    />
                  </div>
                )}
              </>
            )}

            {nodeType === 'mathExpression' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Expression</Label>
                  <Textarea
                    className="min-h-[80px] font-mono"
                    placeholder="({{ltp}} * {{lotSize}}) + {{brokerage}}"
                    value={(nodeData.expression as string) || ''}
                    onChange={(e) => handleDataChange('expression', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">
                    Supports: +, -, *, /, %, ** (power)
                  </p>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="result"
                    value={(nodeData.outputVariable as string) || 'result'}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                </div>
              </>
            )}

            {nodeType === 'httpRequest' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Method</Label>
                  <div className="grid grid-cols-5 gap-1">
                    {HTTP_METHODS.map((m) => (
                      <button
                        key={m.value}
                        type="button"
                        onClick={() => handleDataChange('method', m.value)}
                        className={cn(
                          'rounded-md border py-1.5 text-[10px] font-bold',
                          nodeData.method === m.value
                            ? 'bg-primary text-primary-foreground'
                            : 'border-border bg-muted'
                        )}
                      >
                        {m.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">URL</Label>
                  <Input
                    className="h-8"
                    placeholder="https://api.example.com"
                    value={(nodeData.url as string) || ''}
                    onChange={(e) => handleDataChange('url', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Headers (JSON)</Label>
                  <Textarea
                    className="min-h-[60px] font-mono text-xs"
                    placeholder='{"Authorization": "Bearer {{token}}"}'
                    value={(nodeData.headers as string) || ''}
                    onChange={(e) => handleDataChange('headers', e.target.value)}
                  />
                </div>
                {['POST', 'PUT', 'PATCH'].includes((nodeData.method as string) || 'GET') && (
                  <div className="space-y-2">
                    <Label className="text-xs">Body (JSON)</Label>
                    <Textarea
                      className="min-h-[80px] font-mono text-xs"
                      placeholder='{"symbol": "{{webhook.symbol}}"}'
                      value={(nodeData.body as string) || ''}
                      onChange={(e) => handleDataChange('body', e.target.value)}
                    />
                  </div>
                )}
                <div className="space-y-2">
                  <Label className="text-xs">Timeout (ms)</Label>
                  <Input
                    type="number"
                    min={1000}
                    max={60000}
                    className="h-8"
                    value={(nodeData.timeout as number) || 30000}
                    onChange={(e) =>
                      handleDataChange('timeout', parseInt(e.target.value, 10) || 30000)
                    }
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Output Variable</Label>
                  <Input
                    className="h-8"
                    placeholder="apiResponse"
                    value={(nodeData.outputVariable as string) || ''}
                    onChange={(e) => handleDataChange('outputVariable', e.target.value)}
                  />
                  <p className="text-[10px] text-muted-foreground">Use {`{{apiResponse.data}}`}</p>
                </div>
              </>
            )}

            {/* ===== CONDITION NODES ===== */}
            {nodeType === 'timeWindow' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Start Time</Label>
                  <Input
                    type="time"
                    className="h-8"
                    value={(nodeData.startTime as string) || '09:15'}
                    onChange={(e) => handleDataChange('startTime', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">End Time</Label>
                  <Input
                    type="time"
                    className="h-8"
                    value={(nodeData.endTime as string) || '15:30'}
                    onChange={(e) => handleDataChange('endTime', e.target.value)}
                  />
                </div>
                <div className="flex items-center justify-between rounded-lg border p-3">
                  <div>
                    <Label className="text-xs">Invert Condition</Label>
                    <p className="text-[10px] text-muted-foreground">Trigger outside window</p>
                  </div>
                  <Switch
                    checked={(nodeData.invertCondition as boolean) || false}
                    onCheckedChange={(v) => handleDataChange('invertCondition', v)}
                  />
                </div>
              </>
            )}

            {nodeType === 'timeCondition' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Condition Type</Label>
                  <div className="grid grid-cols-3 gap-2">
                    {CONDITION_TYPES.map((t) => (
                      <button
                        key={t.value}
                        type="button"
                        onClick={() => handleDataChange('conditionType', t.value)}
                        className={cn(
                          'rounded-lg border py-2 text-sm font-semibold',
                          nodeData.conditionType === t.value
                            ? t.value === 'entry'
                              ? 'bg-green-500/20 border-green-500 text-green-600'
                              : t.value === 'exit'
                                ? 'bg-red-500/20 border-red-500 text-red-600'
                                : 'bg-primary text-primary-foreground'
                            : 'border-border bg-muted'
                        )}
                      >
                        {t.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Operator</Label>
                  <Select
                    value={(nodeData.operator as string) || '>='}
                    onValueChange={(v) => handleDataChange('operator', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {TIME_OPERATORS.map((o) => (
                        <SelectItem key={o.value} value={o.value}>
                          {o.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Target Time</Label>
                  <Input
                    type="time"
                    className="h-8"
                    value={(nodeData.targetTime as string) || '09:30'}
                    onChange={(e) => handleDataChange('targetTime', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Label</Label>
                  <Input
                    className="h-8"
                    placeholder="Market Open Entry"
                    value={(nodeData.label as string) || ''}
                    onChange={(e) => handleDataChange('label', e.target.value)}
                  />
                </div>
              </>
            )}

            {nodeType === 'priceCondition' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="RELIANCE"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Field</Label>
                  <Select
                    value={(nodeData.field as string) || 'ltp'}
                    onValueChange={(v) => handleDataChange('field', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ltp">LTP</SelectItem>
                      <SelectItem value="open">Open</SelectItem>
                      <SelectItem value="high">High</SelectItem>
                      <SelectItem value="low">Low</SelectItem>
                      <SelectItem value="prev_close">Prev Close</SelectItem>
                      <SelectItem value="change_percent">Change %</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Operator</Label>
                  <Select
                    value={(nodeData.operator as string) || '>'}
                    onValueChange={(v) => handleDataChange('operator', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value=">">&gt;</SelectItem>
                      <SelectItem value="<">&lt;</SelectItem>
                      <SelectItem value="==">=</SelectItem>
                      <SelectItem value=">=">&gt;=</SelectItem>
                      <SelectItem value="<=">&lt;=</SelectItem>
                      <SelectItem value="!=">!=</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Value</Label>
                  <Input
                    type="number"
                    step="0.05"
                    className="h-8"
                    value={(nodeData.value as number) || ''}
                    onChange={(e) => handleDataChange('value', parseFloat(e.target.value) || 0)}
                  />
                </div>
              </>
            )}

            {nodeType === 'varCondition' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Left Value</Label>
                  <Input
                    className="h-8"
                    placeholder="{{rsi1.latest.value}}"
                    value={(nodeData.leftValue as string) || ''}
                    onChange={(e) => handleDataChange('leftValue', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Operator</Label>
                  <Select
                    value={(nodeData.operator as string) || '>'}
                    onValueChange={(v) => handleDataChange('operator', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value=">">&gt;</SelectItem>
                      <SelectItem value="<">&lt;</SelectItem>
                      <SelectItem value="==">=</SelectItem>
                      <SelectItem value=">=">&gt;=</SelectItem>
                      <SelectItem value="<=">&lt;=</SelectItem>
                      <SelectItem value="!=">!=</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Right Value</Label>
                  <Input
                    className="h-8"
                    placeholder="30 or {{pdhpdl.pdh}}"
                    value={(nodeData.rightValue as string) || ''}
                    onChange={(e) => handleDataChange('rightValue', e.target.value)}
                  />
                </div>
                <p className="text-[10px] text-muted-foreground">
                  Compares any two values after {'{{...}}'} interpolation - an indicator output, a
                  prior-period level, a workflow variable, or a literal number.
                </p>
              </>
            )}

            {nodeType === 'positionCheck' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Symbol</Label>
                  <Input
                    className="h-8"
                    placeholder="RELIANCE"
                    value={(nodeData.symbol as string) || ''}
                    onChange={(e) => handleDataChange('symbol', e.target.value)}
                  />
                </div>
                <ExchangeField
                  value={(nodeData.exchange as string) || 'NSE'}
                  onChange={(v) => handleDataChange('exchange', v)}
                />
                <ProductField
                  value={nodeProduct}
                  onChange={(v) => handleDataChange('product', v)}
                />
                <div className="space-y-2">
                  <Label className="text-xs">Condition</Label>
                  <Select
                    value={(nodeData.condition as string) || 'exists'}
                    onValueChange={(v) => handleDataChange('condition', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="exists">Has Position</SelectItem>
                      <SelectItem value="not_exists">No Position</SelectItem>
                      <SelectItem value="quantity_above">Qty Above</SelectItem>
                      <SelectItem value="quantity_below">Qty Below</SelectItem>
                      <SelectItem value="pnl_above">P&L Above</SelectItem>
                      <SelectItem value="pnl_below">P&L Below</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {['quantity_above', 'quantity_below', 'pnl_above', 'pnl_below'].includes(
                  nodeData.condition as string
                ) && (
                  <div className="space-y-2">
                    <Label className="text-xs">Threshold</Label>
                    <Input
                      type="number"
                      className="h-8"
                      value={(nodeData.threshold as number) || ''}
                      onChange={(e) =>
                        handleDataChange('threshold', parseFloat(e.target.value) || 0)
                      }
                    />
                  </div>
                )}
              </>
            )}

            {nodeType === 'fundCheck' && (
              <div className="space-y-2">
                <Label className="text-xs">Minimum Available Funds</Label>
                <Input
                  type="number"
                  min={0}
                  className="h-8"
                  placeholder="10000"
                  value={(nodeData.minAvailable as number) || ''}
                  onChange={(e) =>
                    handleDataChange('minAvailable', parseFloat(e.target.value) || 0)
                  }
                />
                <p className="text-[10px] text-muted-foreground">Checks if margin is above this</p>
              </div>
            )}

            {nodeType === 'andGate' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Number of Inputs</Label>
                  <Select
                    value={String((nodeData.inputCount as number) || 2)}
                    onValueChange={(v) => handleDataChange('inputCount', parseInt(v, 10))}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="2">2 inputs</SelectItem>
                      <SelectItem value="3">3 inputs</SelectItem>
                      <SelectItem value="4">4 inputs</SelectItem>
                      <SelectItem value="5">5 inputs</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="rounded-lg bg-muted/50 p-3 text-xs">
                  <p className="font-medium mb-1">AND Gate</p>
                  <p className="text-muted-foreground">Yes only if ALL conditions true</p>
                </div>
              </>
            )}

            {nodeType === 'orGate' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Number of Inputs</Label>
                  <Select
                    value={String((nodeData.inputCount as number) || 2)}
                    onValueChange={(v) => handleDataChange('inputCount', parseInt(v, 10))}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="2">2 inputs</SelectItem>
                      <SelectItem value="3">3 inputs</SelectItem>
                      <SelectItem value="4">4 inputs</SelectItem>
                      <SelectItem value="5">5 inputs</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="rounded-lg bg-muted/50 p-3 text-xs">
                  <p className="font-medium mb-1">OR Gate</p>
                  <p className="text-muted-foreground">Yes if ANY condition true</p>
                </div>
              </>
            )}

            {nodeType === 'notGate' && (
              <div className="rounded-lg bg-muted/50 p-3 text-xs">
                <p className="font-medium mb-1">NOT Gate</p>
                <p className="text-muted-foreground">
                  Inverts the condition. True becomes False, False becomes True.
                </p>
              </div>
            )}

            {nodeType === 'group' && (
              <>
                <div className="space-y-2">
                  <Label className="text-xs">Group Name</Label>
                  <Input
                    className="h-8"
                    placeholder="Entry Logic"
                    value={(nodeData.label as string) || ''}
                    onChange={(e) => handleDataChange('label', e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-xs">Color</Label>
                  <Select
                    value={(nodeData.color as string) || 'default'}
                    onValueChange={(v) => handleDataChange('color', v)}
                  >
                    <SelectTrigger className="h-8">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="default">Default</SelectItem>
                      <SelectItem value="blue">Blue</SelectItem>
                      <SelectItem value="green">Green</SelectItem>
                      <SelectItem value="red">Red</SelectItem>
                      <SelectItem value="purple">Purple</SelectItem>
                      <SelectItem value="orange">Orange</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </>
            )}

            {/* ===== FALLBACK ===== */}
            {!NODE_TITLES[nodeType] && (
              <>
                {nodeInfo && (
                  <div className="rounded-lg border bg-muted/30 p-3">
                    <div className="flex items-start gap-2">
                      <Info className="h-4 w-4 text-muted-foreground mt-0.5" />
                      <div>
                        <p className="text-xs font-medium">{nodeInfo.label}</p>
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {nodeInfo.description}
                        </p>
                      </div>
                    </div>
                  </div>
                )}
                <Separator />
                <div className="space-y-2">
                  <Label className="text-xs">Node Label</Label>
                  <Input
                    className="h-8"
                    placeholder="Enter label..."
                    value={(nodeData.label as string) || ''}
                    onChange={(e) => handleDataChange('label', e.target.value)}
                  />
                </div>
              </>
            )}

            <Separator />
            <div className="space-y-2">
              <Label className="text-xs text-muted-foreground">Node ID</Label>
              <code className="block text-[10px] bg-muted px-2 py-1 rounded font-mono">
                {selectedNode.id}
              </code>
            </div>
          </div>
        </ScrollArea>
      </div>
    </div>
  )
}
