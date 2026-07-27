// components/flow/panels/ConfigPanel.tsx
// Right sidebar for configuring selected nodes - Full implementation

import { useCallback, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { showToast } from '@/utils/toast'
import { X, Trash2, Settings2, Info, Copy, Eye, EyeOff, Loader2 } from 'lucide-react'
import { useFlowWorkflowStore } from '@/stores/flowWorkflowStore'
import { getWebhookInfo, getIndexSymbolsLotSizes, flowQueryKeys } from '@/api/flow'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  NODE_DEFINITIONS,
  EXCHANGES,
  SCHEDULE_TYPES,
  DAYS_OF_WEEK,
  PRODUCT_TYPES,
  PRICE_TYPES,
  ORDER_ACTIONS,
  OPTION_TYPES,
  STRIKE_OFFSETS,
  OPTION_STRATEGIES,
  INDEX_SYMBOLS,
  EXPIRY_TYPES,
} from '@/lib/flow/constants'
import { cn } from '@/lib/utils'

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
  start: 'Schedule Trigger', priceAlert: 'Price Alert', webhookTrigger: 'Webhook Trigger',
  placeOrder: 'Place Order', smartOrder: 'Smart Order', optionsOrder: 'Options Order',
  optionsMultiOrder: 'Multi-Leg Options', basketOrder: 'Basket Order', splitOrder: 'Split Order',
  cancelOrder: 'Cancel Order', cancelAllOrders: 'Cancel All Orders', closePositions: 'Close Positions',
  modifyOrder: 'Modify Order', getQuote: 'Get Quote', getDepth: 'Get Depth', getOrderStatus: 'Order Status',
  openPosition: 'Open Position', history: 'History Data', expiry: 'Get Expiry',
  multiQuotes: 'Multi Quotes', symbol: 'Symbol Info', optionSymbol: 'Option Symbol',
  orderBook: 'Order Book', tradeBook: 'Trade Book', positionBook: 'Position Book',
  syntheticFuture: 'Synthetic Future', optionChain: 'Option Chain', holidays: 'Holidays',
  timings: 'Market Timings', holdings: 'Holdings', funds: 'Funds', margin: 'Margin Calculator',
  delay: 'Delay', waitUntil: 'Wait Until', log: 'Log', telegramAlert: 'Telegram Alert',
  variable: 'Variable', mathExpression: 'Math Expression', httpRequest: 'HTTP Request',
  timeWindow: 'Time Window', timeCondition: 'Time Condition', priceCondition: 'Price Condition',
  positionCheck: 'Position Check', fundCheck: 'Fund Check', andGate: 'AND Gate',
  orGate: 'OR Gate', notGate: 'NOT Gate', group: 'Group',
  subscribeLtp: 'Subscribe LTP', subscribeQuote: 'Subscribe Quote', subscribeDepth: 'Subscribe Depth',
  unsubscribe: 'Unsubscribe',
}

function getNodeInfo(nodeType: string) {
  for (const category of Object.values(NODE_DEFINITIONS)) {
    const node = category.find(n => n.type === nodeType)
    if (node) return node
  }
  return null
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
    const dbSymbol = indexSymbolsQuery.data?.find(s => s.value === underlying)
    return dbSymbol?.lotSize || null
  }

  const handleDataChange = useCallback((key: string, value: unknown) => {
    if (selectedNodeId) updateNodeData(selectedNodeId, { [key]: value })
  }, [selectedNodeId, updateNodeData])

  const handleDelete = useCallback(() => { if (selectedNodeId) deleteNode(selectedNodeId) }, [selectedNodeId, deleteNode])
  const handleClose = useCallback(() => { selectNode(null) }, [selectNode])
  const copyToClipboard = (text: string, label: string) => { navigator.clipboard.writeText(text); showToast.success(`${label} copied`) }

  if (!selectedNode) {
    return (
      <div className="w-80 border-l border-border bg-card flex flex-col h-full">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2"><Settings2 className="h-4 w-4 text-muted-foreground" /><span className="font-medium">Properties</span></div>
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
  const nodeTitle = NODE_TITLES[nodeType] || nodeInfo?.label || nodeType

  return (
    <div className="w-80 border-l border-border bg-card flex flex-col h-full">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <div><h2 className="font-semibold text-sm">{nodeTitle}</h2><p className="text-xs text-muted-foreground">Configure node</p></div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive hover:text-destructive" onClick={handleDelete}><Trash2 className="h-4 w-4" /></Button>
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={handleClose}><X className="h-4 w-4" /></Button>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="space-y-4 p-4">

          {/* ===== SCHEDULE/START ===== */}
          {nodeType === 'start' && (<>
            <div className="space-y-2"><Label className="text-xs">Schedule Type</Label>
              <Select value={(nodeData.scheduleType as string) || 'daily'} onValueChange={(v) => handleDataChange('scheduleType', v)}>
                <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
                <SelectContent>{SCHEDULE_TYPES.map((t) => (<SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>))}</SelectContent>
              </Select></div>
            {nodeData.scheduleType !== 'interval' && (<div className="space-y-2"><Label className="text-xs">Time</Label><Input type="time" className="h-8" value={(nodeData.time as string) || '09:15'} onChange={(e) => handleDataChange('time', e.target.value)} /></div>)}
            {nodeData.scheduleType === 'interval' && (<div className="space-y-2"><Label className="text-xs">Repeat Every</Label><div className="flex gap-2"><Input type="number" min="1" className="h-8 w-20" value={(nodeData.intervalValue as number) || 1} onChange={(e) => handleDataChange('intervalValue', parseInt(e.target.value, 10) || 1)} /><Select value={(nodeData.intervalUnit as string) || 'minutes'} onValueChange={(v) => handleDataChange('intervalUnit', v)}><SelectTrigger className="h-8 flex-1"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="seconds">Seconds</SelectItem><SelectItem value="minutes">Minutes</SelectItem><SelectItem value="hours">Hours</SelectItem></SelectContent></Select></div></div>)}
            {(nodeData.scheduleType === 'daily' || nodeData.scheduleType === 'weekly') && (<div className="space-y-2"><Label className="text-xs">Run On Days</Label><div className="flex flex-wrap gap-1 mb-2"><button type="button" onClick={() => handleDataChange('days', [0,1,2,3,4])} className="rounded-md bg-muted px-2 py-1 text-[10px] hover:bg-accent">Weekdays</button><button type="button" onClick={() => handleDataChange('days', [5,6])} className="rounded-md bg-muted px-2 py-1 text-[10px] hover:bg-accent">Weekends</button><button type="button" onClick={() => handleDataChange('days', [0,1,2,3,4,5,6])} className="rounded-md bg-muted px-2 py-1 text-[10px] hover:bg-accent">All</button></div><div className="flex flex-wrap gap-1">{DAYS_OF_WEEK.map((day) => { const days = (nodeData.days as number[]) || [0,1,2,3,4]; const sel = days.includes(day.value); return (<button key={day.value} type="button" onClick={() => handleDataChange('days', sel ? days.filter(d => d !== day.value) : [...days, day.value].sort())} className={cn('flex h-8 w-8 items-center justify-center rounded-md text-xs font-medium', sel ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:bg-accent')}>{day.label}</button>)})}</div></div>)}
            {nodeData.scheduleType === 'once' && (<div className="space-y-2"><Label className="text-xs">Date</Label><Input type="date" className="h-8" value={(nodeData.executeAt as string) || ''} onChange={(e) => handleDataChange('executeAt', e.target.value)} /></div>)}
          </>)}

          {/* ===== PRICE ALERT ===== */}
          {nodeType === 'priceAlert' && (<>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="RELIANCE" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXCHANGES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Condition</Label><Select value={(nodeData.condition as string) || 'above'} onValueChange={(v) => handleDataChange('condition', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{ALERT_CONDITIONS.map((c) => (<SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Target Price</Label><Input type="number" step="0.05" className="h-8" value={(nodeData.price as number) || ''} onChange={(e) => handleDataChange('price', parseFloat(e.target.value) || 0)} /></div>
            <div className="space-y-2"><Label className="text-xs">Trigger</Label><Select value={(nodeData.trigger as string) || 'once'} onValueChange={(v) => handleDataChange('trigger', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{ALERT_TRIGGERS.map((t) => (<SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Expiration</Label><Select value={(nodeData.expiration as string) || 'none'} onValueChange={(v) => handleDataChange('expiration', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{ALERT_EXPIRATION.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="flex items-center justify-between rounded-lg border p-3"><div><Label className="text-xs">Play Sound</Label></div><Switch checked={(nodeData.playSound as boolean) ?? true} onCheckedChange={(v) => handleDataChange('playSound', v)} /></div>
            <div className="space-y-2"><Label className="text-xs">Alert Message</Label><Input className="h-8" placeholder="Custom message" value={(nodeData.message as string) || ''} onChange={(e) => handleDataChange('message', e.target.value)} /></div>
          </>)}

          {/* ===== WEBHOOK TRIGGER ===== */}
          {nodeType === 'webhookTrigger' && (<>
            <div className="space-y-2"><Label className="text-xs">Label</Label><Input className="h-8" placeholder="TradingView Alert" value={(nodeData.label as string) || ''} onChange={(e) => handleDataChange('label', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="RELIANCE" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="NSE">NSE</SelectItem><SelectItem value="BSE">BSE</SelectItem><SelectItem value="NFO">NFO</SelectItem><SelectItem value="CDS">CDS</SelectItem><SelectItem value="MCX">MCX</SelectItem></SelectContent></Select></div>
            <Separator />
            {webhookQuery.isLoading ? (<div className="flex justify-center py-4"><Loader2 className="h-5 w-5 animate-spin" /></div>) : webhookQuery.data ? (<>
              <div className="space-y-2"><Label className="text-xs">Webhook URL</Label><div className="flex gap-1"><Input readOnly value={nodeData.symbol ? `${webhookQuery.data.webhook_url}/${nodeData.symbol}` : webhookQuery.data.webhook_url} className="font-mono text-[10px] h-8" /><Button variant="outline" size="icon" className="h-8 w-8" onClick={() => copyToClipboard(nodeData.symbol ? `${webhookQuery.data.webhook_url}/${nodeData.symbol}` : webhookQuery.data.webhook_url, 'URL')}><Copy className="h-3 w-3" /></Button></div></div>
              <div className="space-y-2"><Label className="text-xs">Webhook Secret</Label><div className="flex gap-1"><div className="relative flex-1"><Input readOnly type={showSecret ? 'text' : 'password'} value={webhookQuery.data.webhook_secret} className="font-mono text-[10px] h-8 pr-8" /><Button variant="ghost" size="icon" className="absolute right-0 top-0 h-8 w-8" onClick={() => setShowSecret(!showSecret)}>{showSecret ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}</Button></div><Button variant="outline" size="icon" className="h-8 w-8" onClick={() => copyToClipboard(webhookQuery.data.webhook_secret, 'Secret')}><Copy className="h-3 w-3" /></Button></div></div>
              <div className={cn("rounded-lg border p-2 text-center text-xs", webhookQuery.data.webhook_enabled ? "border-green-500/30 bg-green-500/10 text-green-600" : "border-yellow-500/30 bg-yellow-500/10 text-yellow-600")}>{webhookQuery.data.webhook_enabled ? "Webhook enabled" : "Webhook disabled"}</div>
            </>) : (<div className="rounded-lg border-yellow-500/30 bg-yellow-500/10 p-3 text-center text-xs text-yellow-600">Save workflow first</div>)}
          </>)}

          {/* ===== PLACE ORDER ===== */}
          {nodeType === 'placeOrder' && (<>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="RELIANCE" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXCHANGES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Action</Label><div className="grid grid-cols-2 gap-2">{ORDER_ACTIONS.map((a) => (<button key={a.value} type="button" onClick={() => handleDataChange('action', a.value)} className={cn('rounded-lg border py-2 text-sm font-semibold', nodeData.action === a.value ? a.value === 'BUY' ? 'bg-green-500/20 border-green-500 text-green-600' : 'bg-red-500/20 border-red-500 text-red-600' : 'border-border bg-muted')}>{a.label}</button>))}</div></div>
            <div className="space-y-2"><Label className="text-xs">Quantity</Label><Input type="number" min={1} className="h-8" value={(nodeData.quantity as number) || 1} onChange={(e) => handleDataChange('quantity', parseInt(e.target.value, 10) || 1)} /></div>
            <div className="space-y-2"><Label className="text-xs">Product</Label><Select value={(nodeData.product as string) || 'MIS'} onValueChange={(v) => handleDataChange('product', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{PRODUCT_TYPES.map((t) => (<SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Price Type</Label><Select value={(nodeData.priceType as string) || 'MARKET'} onValueChange={(v) => handleDataChange('priceType', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{PRICE_TYPES.map((t) => (<SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>))}</SelectContent></Select></div>
            {(nodeData.priceType === 'LIMIT' || nodeData.priceType === 'SL') && (<div className="space-y-2"><Label className="text-xs">Price</Label><Input type="number" step="0.05" className="h-8" value={(nodeData.price as number) || 0} onChange={(e) => handleDataChange('price', parseFloat(e.target.value) || 0)} /></div>)}
            {(nodeData.priceType === 'SL' || nodeData.priceType === 'SL-M') && (<div className="space-y-2"><Label className="text-xs">Trigger Price</Label><Input type="number" step="0.05" className="h-8" value={(nodeData.triggerPrice as number) || 0} onChange={(e) => handleDataChange('triggerPrice', parseFloat(e.target.value) || 0)} /></div>)}
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="orderResult" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{orderResult.orderid}}`}</p></div>
          </>)}

          {/* ===== SMART ORDER ===== */}
          {nodeType === 'smartOrder' && (<>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="RELIANCE" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXCHANGES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Action</Label><div className="grid grid-cols-2 gap-2">{ORDER_ACTIONS.map((a) => (<button key={a.value} type="button" onClick={() => handleDataChange('action', a.value)} className={cn('rounded-lg border py-2 text-sm font-semibold', nodeData.action === a.value ? a.value === 'BUY' ? 'bg-green-500/20 border-green-500 text-green-600' : 'bg-red-500/20 border-red-500 text-red-600' : 'border-border bg-muted')}>{a.label}</button>))}</div></div>
            <div className="space-y-2"><Label className="text-xs">Quantity</Label><Input type="number" min={1} className="h-8" value={(nodeData.quantity as number) || 1} onChange={(e) => handleDataChange('quantity', parseInt(e.target.value, 10) || 1)} /></div>
            <div className="space-y-2"><Label className="text-xs">Position Size</Label><Input type="number" className="h-8" value={(nodeData.positionSize as number) ?? 0} onChange={(e) => { const val = parseInt(e.target.value, 10); handleDataChange('positionSize', isNaN(val) ? 0 : val) }} /><p className="text-[10px] text-muted-foreground">Target position (positive=long, negative=short, 0=use quantity)</p></div>
            <div className="space-y-2"><Label className="text-xs">Product</Label><Select value={(nodeData.product as string) || 'MIS'} onValueChange={(v) => handleDataChange('product', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{PRODUCT_TYPES.map((t) => (<SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="smartResult" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /></div>
          </>)}

          {/* ===== OPTIONS ORDER ===== */}
          {nodeType === 'optionsOrder' && (<>
            <div className="space-y-2"><Label className="text-xs">Underlying</Label><Select value={(nodeData.underlying as string) || 'NIFTY'} onValueChange={(v) => { handleDataChange('underlying', v); const s = INDEX_SYMBOLS.find(x => x.value === v); if (s) { handleDataChange('exchange', s.exchange) } const lotSize = getLotSizeFromDb(v); if (lotSize) { handleDataChange('quantity', lotSize) } }}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{INDEX_SYMBOLS.map((s) => (<SelectItem key={s.value} value={s.value}>{s.label} ({s.exchange})</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Expiry</Label><Select value={(nodeData.expiryType as string) || 'current_week'} onValueChange={(v) => handleDataChange('expiryType', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXPIRY_TYPES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Strike Offset</Label><Select value={(nodeData.offset as string) || 'ATM'} onValueChange={(v) => handleDataChange('offset', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{STRIKE_OFFSETS.map((o) => (<SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Option Type</Label><div className="grid grid-cols-2 gap-2">{OPTION_TYPES.map((o) => (<button key={o.value} type="button" onClick={() => handleDataChange('optionType', o.value)} className={cn('rounded-lg border py-2 text-sm font-semibold', nodeData.optionType === o.value ? o.value === 'CE' ? 'bg-green-500/20 border-green-500 text-green-600' : 'bg-red-500/20 border-red-500 text-red-600' : 'border-border bg-muted')}>{o.label}</button>))}</div></div>
            <div className="space-y-2"><Label className="text-xs">Action</Label><div className="grid grid-cols-2 gap-2">{ORDER_ACTIONS.map((a) => (<button key={a.value} type="button" onClick={() => handleDataChange('action', a.value)} className={cn('rounded-lg border py-2 text-sm font-semibold', nodeData.action === a.value ? a.value === 'BUY' ? 'bg-green-500/20 border-green-500 text-green-600' : 'bg-red-500/20 border-red-500 text-red-600' : 'border-border bg-muted')}>{a.label}</button>))}</div></div>
            <div className="space-y-2"><Label className="text-xs">Quantity (Lots)</Label><Input type="number" min={1} className="h-8" value={(nodeData.quantity as number) || 1} onChange={(e) => handleDataChange('quantity', parseInt(e.target.value, 10) || 1)} /></div>
            <div className="space-y-2"><Label className="text-xs">Product</Label><Select value={(nodeData.product as string) || 'MIS'} onValueChange={(v) => handleDataChange('product', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="MIS">MIS</SelectItem><SelectItem value="NRML">NRML</SelectItem></SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Price Type</Label><Select value={(nodeData.priceType as string) || 'MARKET'} onValueChange={(v) => handleDataChange('priceType', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{PRICE_TYPES.map((t) => (<SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>))}</SelectContent></Select></div>
            {(nodeData.priceType === 'LIMIT' || nodeData.priceType === 'SL') && (<div className="space-y-2"><Label className="text-xs">Price</Label><Input type="number" step="0.05" className="h-8" value={(nodeData.price as number) || 0} onChange={(e) => handleDataChange('price', parseFloat(e.target.value) || 0)} /></div>)}
            {(nodeData.priceType === 'SL' || nodeData.priceType === 'SL-M') && (<div className="space-y-2"><Label className="text-xs">Trigger Price</Label><Input type="number" step="0.05" className="h-8" value={(nodeData.triggerPrice as number) || 0} onChange={(e) => handleDataChange('triggerPrice', parseFloat(e.target.value) || 0)} /></div>)}
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="optionOrder" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /></div>
          </>)}

          {/* ===== OPTIONS MULTI ORDER ===== */}
          {nodeType === 'optionsMultiOrder' && (<>
            <div className="space-y-2"><Label className="text-xs">Strategy</Label><Select value={(nodeData.strategy as string) || 'straddle'} onValueChange={(v) => handleDataChange('strategy', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{OPTION_STRATEGIES.map((s) => (<SelectItem key={s.value} value={s.value}>{s.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Underlying</Label><Select value={(nodeData.underlying as string) || 'NIFTY'} onValueChange={(v) => { handleDataChange('underlying', v); const s = INDEX_SYMBOLS.find(x => x.value === v); if (s) handleDataChange('exchange', s.exchange) }}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{INDEX_SYMBOLS.map((s) => (<SelectItem key={s.value} value={s.value}>{s.label} ({s.exchange})</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Expiry</Label><Select value={(nodeData.expiryType as string) || 'current_week'} onValueChange={(v) => handleDataChange('expiryType', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXPIRY_TYPES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Action</Label><div className="grid grid-cols-2 gap-2">{ORDER_ACTIONS.map((a) => (<button key={a.value} type="button" onClick={() => handleDataChange('action', a.value)} className={cn('rounded-lg border py-2 text-sm font-semibold', nodeData.action === a.value ? a.value === 'BUY' ? 'bg-green-500/20 border-green-500 text-green-600' : 'bg-red-500/20 border-red-500 text-red-600' : 'border-border bg-muted')}>{a.label}</button>))}</div><p className="text-[10px] text-muted-foreground">{nodeData.action === 'BUY' ? 'Long strategy' : 'Short strategy'}</p></div>
            <div className="space-y-2"><Label className="text-xs">Quantity (Lots)</Label><Input type="number" min={1} className="h-8" value={(nodeData.quantity as number) || 1} onChange={(e) => handleDataChange('quantity', parseInt(e.target.value, 10) || 1)} /></div>
            <div className="space-y-2"><Label className="text-xs">Product</Label><Select value={(nodeData.product as string) || 'MIS'} onValueChange={(v) => handleDataChange('product', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="MIS">MIS</SelectItem><SelectItem value="NRML">NRML</SelectItem></SelectContent></Select></div>
            {/* Strategy Legs Preview */}
            <div className="rounded-lg border bg-muted/30 p-2">
              <p className="text-[10px] font-medium mb-1.5">Strategy Legs:</p>
              <div className="space-y-0.5 text-[10px] font-mono">
                {nodeData.strategy === 'straddle' && (<><div className="flex justify-between"><span>ATM CE</span><span className={nodeData.action === 'BUY' ? 'text-green-600' : 'text-red-600'}>{(nodeData.action as string) || 'SELL'}</span></div><div className="flex justify-between"><span>ATM PE</span><span className={nodeData.action === 'BUY' ? 'text-green-600' : 'text-red-600'}>{(nodeData.action as string) || 'SELL'}</span></div></>)}
                {nodeData.strategy === 'strangle' && (<><div className="flex justify-between"><span>OTM2 CE</span><span className={nodeData.action === 'BUY' ? 'text-green-600' : 'text-red-600'}>{(nodeData.action as string) || 'SELL'}</span></div><div className="flex justify-between"><span>OTM2 PE</span><span className={nodeData.action === 'BUY' ? 'text-green-600' : 'text-red-600'}>{(nodeData.action as string) || 'SELL'}</span></div></>)}
                {nodeData.strategy === 'iron_condor' && (<><div className="flex justify-between"><span>OTM2 CE</span><span className="text-red-600">SELL</span></div><div className="flex justify-between"><span>OTM4 CE</span><span className="text-green-600">BUY</span></div><div className="flex justify-between"><span>OTM2 PE</span><span className="text-red-600">SELL</span></div><div className="flex justify-between"><span>OTM4 PE</span><span className="text-green-600">BUY</span></div></>)}
                {nodeData.strategy === 'bull_call_spread' && (<><div className="flex justify-between"><span>ATM CE</span><span className="text-green-600">BUY</span></div><div className="flex justify-between"><span>OTM2 CE</span><span className="text-red-600">SELL</span></div></>)}
                {nodeData.strategy === 'bear_put_spread' && (<><div className="flex justify-between"><span>ATM PE</span><span className="text-green-600">BUY</span></div><div className="flex justify-between"><span>OTM2 PE</span><span className="text-red-600">SELL</span></div></>)}
                {nodeData.strategy === 'custom' && (<p className="text-muted-foreground">Configure custom legs via API</p>)}
              </div>
            </div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="multiLegOrder" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /></div>
          </>)}

          {/* ===== BASKET ORDER ===== */}
          {nodeType === 'basketOrder' && (<>
            <div className="space-y-2"><Label className="text-xs">Basket Name</Label><Input className="h-8" placeholder="Morning Portfolio" value={(nodeData.basketName as string) || ''} onChange={(e) => handleDataChange('basketName', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Orders (SYMBOL,EXCHANGE,ACTION,QTY)</Label><Textarea className="min-h-[100px] text-xs font-mono" placeholder="RELIANCE,NSE,BUY,10&#10;INFY,NSE,BUY,5&#10;SBIN,NSE,SELL,20" value={(nodeData.orders as string) || ''} onChange={(e) => handleDataChange('orders', e.target.value)} /><p className="text-[10px] text-muted-foreground">Supported exchanges: NSE, BSE, NFO, BFO, CDS, BCD, MCX</p></div>
            <div className="space-y-2"><Label className="text-xs">Product</Label><Select value={(nodeData.product as string) || 'MIS'} onValueChange={(v) => handleDataChange('product', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{PRODUCT_TYPES.map((t) => (<SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Price Type</Label><Select value={(nodeData.priceType as string) || 'MARKET'} onValueChange={(v) => handleDataChange('priceType', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{PRICE_TYPES.map((t) => (<SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="basketResult" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{basketResult.results}}`} in other nodes</p></div>
          </>)}

          {/* ===== SPLIT ORDER ===== */}
          {nodeType === 'splitOrder' && (<>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="RELIANCE" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXCHANGES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Action</Label><div className="grid grid-cols-2 gap-2">{ORDER_ACTIONS.map((a) => (<button key={a.value} type="button" onClick={() => handleDataChange('action', a.value)} className={cn('rounded-lg border py-2 text-sm font-semibold', nodeData.action === a.value ? a.value === 'BUY' ? 'bg-green-500/20 border-green-500 text-green-600' : 'bg-red-500/20 border-red-500 text-red-600' : 'border-border bg-muted')}>{a.label}</button>))}</div></div>
            <div className="space-y-2"><Label className="text-xs">Total Quantity</Label><Input type="number" min={1} className="h-8" value={(nodeData.quantity as number) || 100} onChange={(e) => handleDataChange('quantity', parseInt(e.target.value, 10) || 100)} /></div>
            <div className="space-y-2"><Label className="text-xs">Split Size</Label><Input type="number" min={1} className="h-8" value={(nodeData.splitSize as number) || 50} onChange={(e) => handleDataChange('splitSize', parseInt(e.target.value, 10) || 50)} /></div>
            <div className="space-y-2"><Label className="text-xs">Product</Label><Select value={(nodeData.product as string) || 'MIS'} onValueChange={(v) => handleDataChange('product', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{PRODUCT_TYPES.map((t) => (<SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="splitResult" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{splitResult.results}}`} in other nodes</p></div>
            <p className="text-[10px] text-muted-foreground">Splits into {Math.ceil(((nodeData.quantity as number) || 100) / ((nodeData.splitSize as number) || 50))} orders</p>
          </>)}

          {/* ===== CANCEL ORDER ===== */}
          {nodeType === 'cancelOrder' && (<div className="space-y-2"><Label className="text-xs">Order ID</Label><Input className="h-8" placeholder="{{orderResult.orderid}}" value={(nodeData.orderId as string) || ''} onChange={(e) => handleDataChange('orderId', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use variable from Place Order</p></div>)}

          {/* ===== CANCEL ALL / CLOSE POSITIONS ===== */}
          {nodeType === 'cancelAllOrders' && (<div className="rounded-lg border bg-muted/30 p-3"><p className="text-xs text-muted-foreground">Cancels all open orders. No configuration needed.</p></div>)}
          {nodeType === 'closePositions' && (<div className="rounded-lg border bg-muted/30 p-3"><p className="text-xs text-muted-foreground">Closes all open positions. No configuration needed.</p></div>)}

          {/* ===== MODIFY ORDER ===== */}
          {nodeType === 'modifyOrder' && (<>
            <div className="space-y-2"><Label className="text-xs">Order ID</Label><Input className="h-8" placeholder="{{orderResult.orderid}}" value={(nodeData.orderId as string) || ''} onChange={(e) => handleDataChange('orderId', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">New Price</Label><Input type="number" step="0.05" className="h-8" placeholder="Leave empty to keep" value={(nodeData.newPrice as number) || ''} onChange={(e) => handleDataChange('newPrice', parseFloat(e.target.value) || 0)} /></div>
            <div className="space-y-2"><Label className="text-xs">New Quantity</Label><Input type="number" min={1} className="h-8" placeholder="Leave empty to keep" value={(nodeData.newQuantity as number) || ''} onChange={(e) => handleDataChange('newQuantity', parseInt(e.target.value, 10) || 0)} /></div>
          </>)}

          {/* ===== DATA NODES ===== */}
          {nodeType === 'getQuote' && (<>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="RELIANCE" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXCHANGES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="quote" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{quote.data.ltp}}`}</p></div>
          </>)}

          {nodeType === 'getDepth' && (<>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="SBIN" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXCHANGES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="depth" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{depth.data.bids[0].price}}`}</p></div>
          </>)}

          {/* ===== GET ORDER STATUS ===== */}
          {nodeType === 'getOrderStatus' && (<>
            <div className="space-y-2"><Label className="text-xs">Order ID</Label><Input className="h-8" placeholder="{{orderResult.orderid}}" value={(nodeData.orderId as string) || ''} onChange={(e) => handleDataChange('orderId', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use variable from Place Order node</p></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="orderStatus" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{orderStatus.data.order_status}}`}</p></div>
          </>)}

          {nodeType === 'openPosition' && (<>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="RELIANCE" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXCHANGES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Product</Label><Select value={(nodeData.product as string) || 'MIS'} onValueChange={(v) => handleDataChange('product', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{PRODUCT_TYPES.map((t) => (<SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="position" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{position.quantity}}`}</p></div>
          </>)}

          {nodeType === 'history' && (<>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="SBIN" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXCHANGES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Interval</Label><Select value={(nodeData.interval as string) || '1d'} onValueChange={(v) => handleDataChange('interval', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="1m">1 Min</SelectItem><SelectItem value="5m">5 Min</SelectItem><SelectItem value="15m">15 Min</SelectItem><SelectItem value="1h">1 Hour</SelectItem><SelectItem value="1d">Daily</SelectItem></SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Days</Label><Input type="number" min={1} max={365} className="h-8" value={(nodeData.days as number) || 30} onChange={(e) => handleDataChange('days', parseInt(e.target.value, 10) || 30)} /></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="ohlcv" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /></div>
          </>)}

          {nodeType === 'expiry' && (<>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="NIFTY" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NFO'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="NFO">NFO</SelectItem><SelectItem value="BFO">BFO</SelectItem><SelectItem value="MCX">MCX</SelectItem><SelectItem value="CDS">CDS</SelectItem></SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="expiries" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{expiries.data[0]}}`}</p></div>
          </>)}

          {nodeType === 'multiQuotes' && (<>
            <div className="space-y-2"><Label className="text-xs">Symbols (comma separated)</Label><Input className="h-8" placeholder="RELIANCE,INFY,TCS" value={(nodeData.symbols as string) || ''} onChange={(e) => handleDataChange('symbols', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXCHANGES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="quotes" value={(nodeData.outputVariable as string) || 'quotes'} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{quotes.results[0].data.ltp}}`}</p></div>
          </>)}

          {nodeType === 'symbol' && (<>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="NIFTY30DEC25FUT" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NFO'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXCHANGES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="symbolInfo" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{symbolInfo.data.lotsize}}`}</p></div>
          </>)}

          {nodeType === 'optionSymbol' && (<>
            <div className="space-y-2"><Label className="text-xs">Underlying</Label><Input className="h-8" placeholder="NIFTY" value={(nodeData.underlying as string) || ''} onChange={(e) => handleDataChange('underlying', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE_INDEX'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="NSE_INDEX">NSE Index</SelectItem><SelectItem value="BSE_INDEX">BSE Index</SelectItem></SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Expiry Date</Label><Input className="h-8" placeholder="30DEC25" value={(nodeData.expiryDate as string) || ''} onChange={(e) => handleDataChange('expiryDate', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Strike Offset</Label><Select value={(nodeData.offset as string) || 'ATM'} onValueChange={(v) => handleDataChange('offset', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="ATM">ATM</SelectItem><SelectItem value="ITM1">ITM 1</SelectItem><SelectItem value="ITM2">ITM 2</SelectItem><SelectItem value="OTM1">OTM 1</SelectItem><SelectItem value="OTM2">OTM 2</SelectItem><SelectItem value="OTM3">OTM 3</SelectItem></SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Option Type</Label><div className="grid grid-cols-2 gap-2">{['CE', 'PE'].map((t) => (<button key={t} type="button" onClick={() => handleDataChange('optionType', t)} className={cn('rounded-lg border py-2 text-sm font-semibold', nodeData.optionType === t ? t === 'CE' ? 'bg-green-500/20 border-green-500 text-green-600' : 'bg-red-500/20 border-red-500 text-red-600' : 'border-border bg-muted')}>{t === 'CE' ? 'Call' : 'Put'}</button>))}</div></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="optionSym" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /></div>
          </>)}

          {nodeType === 'orderBook' && (<div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="orders" value={(nodeData.outputVariable as string) || 'orders'} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{orders.data.orders}}`}</p></div>)}
          {nodeType === 'tradeBook' && (<div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="trades" value={(nodeData.outputVariable as string) || 'trades'} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{trades.data}}`}</p></div>)}
          {nodeType === 'positionBook' && (<div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="positions" value={(nodeData.outputVariable as string) || 'positions'} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{positions.data}}`}</p></div>)}

          {nodeType === 'syntheticFuture' && (<>
            <div className="space-y-2"><Label className="text-xs">Underlying</Label><Input className="h-8" placeholder="NIFTY" value={(nodeData.underlying as string) || ''} onChange={(e) => handleDataChange('underlying', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE_INDEX'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="NSE_INDEX">NSE Index</SelectItem><SelectItem value="BSE_INDEX">BSE Index</SelectItem></SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Expiry Date</Label><Input className="h-8" placeholder="25NOV25" value={(nodeData.expiryDate as string) || ''} onChange={(e) => handleDataChange('expiryDate', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="synthFuture" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{synthFuture.synthetic_future_price}}`}</p></div>
          </>)}

          {nodeType === 'optionChain' && (<>
            <div className="space-y-2"><Label className="text-xs">Underlying</Label><Input className="h-8" placeholder="NIFTY" value={(nodeData.underlying as string) || ''} onChange={(e) => handleDataChange('underlying', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE_INDEX'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="NSE_INDEX">NSE Index</SelectItem><SelectItem value="BSE_INDEX">BSE Index</SelectItem></SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Expiry Date</Label><Input className="h-8" placeholder="30DEC25" value={(nodeData.expiryDate as string) || ''} onChange={(e) => handleDataChange('expiryDate', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Strike Count</Label><Input type="number" className="h-8" placeholder="10 (empty=full)" value={(nodeData.strikeCount as number) || ''} onChange={(e) => handleDataChange('strikeCount', parseInt(e.target.value, 10) || undefined)} /></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="chain" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{chain.atm_strike}}`}</p></div>
          </>)}

          {nodeType === 'holidays' && (<>
            <div className="space-y-2"><Label className="text-xs">Year</Label><Input type="number" className="h-8" placeholder={String(new Date().getFullYear())} value={(nodeData.year as number) || ''} onChange={(e) => handleDataChange('year', parseInt(e.target.value, 10) || undefined)} /><p className="text-[10px] text-muted-foreground">Empty = current year</p></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="holidays" value={(nodeData.outputVariable as string) || 'holidays'} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /></div>
          </>)}

          {nodeType === 'timings' && (<>
            <div className="space-y-2"><Label className="text-xs">Date</Label><Input type="date" className="h-8" value={(nodeData.date as string) || ''} onChange={(e) => handleDataChange('date', e.target.value)} /><p className="text-[10px] text-muted-foreground">Empty = today</p></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="timings" value={(nodeData.outputVariable as string) || 'timings'} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /></div>
          </>)}

          {nodeType === 'holdings' && (<div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="holdings" value={(nodeData.outputVariable as string) || 'holdings'} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{holdings.data[0].symbol}}`}</p></div>)}
          {nodeType === 'funds' && (<div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="funds" value={(nodeData.outputVariable as string) || 'funds'} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{funds.data.availablecash}}`}</p></div>)}

          {nodeType === 'margin' && (<>
            <div className="space-y-2"><Label className="text-xs">Positions (JSON)</Label><Textarea className="min-h-[100px] text-xs font-mono" placeholder={`[{"symbol": "NIFTY25DEC25FUT", "exchange": "NFO", "action": "BUY", "quantity": 75}]`} value={(nodeData.positionsJson as string) || ''} onChange={(e) => handleDataChange('positionsJson', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="marginResult" value={(nodeData.outputVariable as string) || 'marginResult'} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /></div>
          </>)}

          {/* ===== STREAMING NODES ===== */}
          {nodeType === 'subscribeLtp' && (<>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="RELIANCE" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXCHANGES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="ltp" value={(nodeData.outputVariable as string) || 'ltp'} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Real-time: {`{{ltp}}`}</p></div>
          </>)}

          {nodeType === 'subscribeQuote' && (<>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="RELIANCE" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXCHANGES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="quote" value={(nodeData.outputVariable as string) || 'quote'} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{quote.ltp}}`}, {`{{quote.open}}`}</p></div>
          </>)}

          {nodeType === 'subscribeDepth' && (<>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="RELIANCE" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXCHANGES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="depth" value={(nodeData.outputVariable as string) || 'depth'} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{depth.bids[0].price}}`}</p></div>
          </>)}

          {nodeType === 'unsubscribe' && (<>
            <div className="space-y-2"><Label className="text-xs">Stream Type</Label><Select value={(nodeData.streamType as string) || 'all'} onValueChange={(v) => handleDataChange('streamType', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="ltp">LTP Only</SelectItem><SelectItem value="quote">Quote Only</SelectItem><SelectItem value="depth">Depth Only</SelectItem><SelectItem value="all">All Streams</SelectItem></SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="Empty = all symbols" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXCHANGES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
          </>)}

          {/* ===== UTILITY NODES ===== */}
          {nodeType === 'delay' && (<>
            <div className="space-y-2"><Label className="text-xs">Wait Duration</Label><div className="flex gap-2"><Input type="number" min={1} className="h-8 flex-1" value={(nodeData.delayValue as number) || 1} onChange={(e) => handleDataChange('delayValue', parseInt(e.target.value, 10) || 1)} /><Select value={(nodeData.delayUnit as string) || 'seconds'} onValueChange={(v) => handleDataChange('delayUnit', v)}><SelectTrigger className="h-8 w-28"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="seconds">Seconds</SelectItem><SelectItem value="minutes">Minutes</SelectItem><SelectItem value="hours">Hours</SelectItem></SelectContent></Select></div></div>
          </>)}

          {nodeType === 'waitUntil' && (<>
            <div className="space-y-2"><Label className="text-xs">Target Time</Label><Input type="time" className="h-8" value={(nodeData.targetTime as string) || '09:30'} onChange={(e) => handleDataChange('targetTime', e.target.value)} /><p className="text-[10px] text-muted-foreground">Workflow pauses until this time</p></div>
            <div className="space-y-2"><Label className="text-xs">Label</Label><Input className="h-8" placeholder="Wait for Entry" value={(nodeData.label as string) || ''} onChange={(e) => handleDataChange('label', e.target.value)} /></div>
          </>)}

          {nodeType === 'log' && (<>
            <div className="space-y-2"><Label className="text-xs">Log Level</Label><Select value={(nodeData.level as string) || 'info'} onValueChange={(v) => handleDataChange('level', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{LOG_LEVELS.map((l) => (<SelectItem key={l.value} value={l.value}><span className={l.color}>{l.label}</span></SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Message</Label><Textarea className="min-h-[80px]" placeholder="Log message with {{variables}}" value={(nodeData.message as string) || ''} onChange={(e) => handleDataChange('message', e.target.value)} /></div>
          </>)}

          {nodeType === 'telegramAlert' && (<>
            <div className="space-y-2"><Label className="text-xs">OpenAlgo Username</Label><Input className="h-8" placeholder="Your login ID" value={(nodeData.username as string) || ''} onChange={(e) => handleDataChange('username', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Message</Label><Textarea className="min-h-[80px]" placeholder="Order placed for {{orderResult.symbol}}" value={(nodeData.message as string) || ''} onChange={(e) => handleDataChange('message', e.target.value)} /></div>
            <div className="rounded-lg border bg-muted/30 p-2"><p className="text-[10px] font-medium mb-1">Variables:</p><p className="text-[9px] font-mono text-muted-foreground">{`{{orderResult.orderid}}`}, {`{{quote.ltp}}`}, {`{{timestamp}}`}</p></div>
          </>)}

          {nodeType === 'variable' && (<>
            <div className="space-y-2"><Label className="text-xs">Variable Name</Label><Input className="h-8" placeholder="myLTP" value={(nodeData.variableName as string) || ''} onChange={(e) => handleDataChange('variableName', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use: {`{{${(nodeData.variableName as string) || 'varName'}}}`}</p></div>
            <div className="space-y-2"><Label className="text-xs">Operation</Label><Select value={(nodeData.operation as string) || 'set'} onValueChange={(v) => handleDataChange('operation', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{VARIABLE_OPERATIONS.map((o) => (<SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>))}</SelectContent></Select></div>
            {['set', 'add', 'subtract', 'multiply', 'divide', 'append', 'parse_json'].includes(nodeData.operation as string) && (<div className="space-y-2"><Label className="text-xs">{nodeData.operation === 'parse_json' ? 'JSON String' : 'Value'}</Label>{nodeData.operation === 'parse_json' ? (<Textarea className="min-h-[80px] font-mono" placeholder='{"key": "value"}' value={String(nodeData.value || '')} onChange={(e) => handleDataChange('value', e.target.value)} />) : (<Input className="h-8" placeholder="Value or {{variable}}" value={String(nodeData.value || '')} onChange={(e) => handleDataChange('value', e.target.value)} />)}</div>)}
            {['get', 'stringify'].includes(nodeData.operation as string) && (<div className="space-y-2"><Label className="text-xs">Source Variable</Label><Input className="h-8" placeholder="quoteData" value={(nodeData.sourceVariable as string) || ''} onChange={(e) => handleDataChange('sourceVariable', e.target.value)} /></div>)}
            {nodeData.operation === 'get' && (<div className="space-y-2"><Label className="text-xs">JSON Path</Label><Input className="h-8" placeholder="data.ltp" value={(nodeData.jsonPath as string) || ''} onChange={(e) => handleDataChange('jsonPath', e.target.value)} /></div>)}
          </>)}

          {nodeType === 'mathExpression' && (<>
            <div className="space-y-2"><Label className="text-xs">Expression</Label><Textarea className="min-h-[80px] font-mono" placeholder="({{ltp}} * {{lotSize}}) + {{brokerage}}" value={(nodeData.expression as string) || ''} onChange={(e) => handleDataChange('expression', e.target.value)} /><p className="text-[10px] text-muted-foreground">Supports: +, -, *, /, %, ** (power)</p></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="result" value={(nodeData.outputVariable as string) || 'result'} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /></div>
          </>)}

          {nodeType === 'httpRequest' && (<>
            <div className="space-y-2"><Label className="text-xs">Method</Label><div className="grid grid-cols-5 gap-1">{HTTP_METHODS.map((m) => (<button key={m.value} type="button" onClick={() => handleDataChange('method', m.value)} className={cn('rounded-md border py-1.5 text-[10px] font-bold', nodeData.method === m.value ? 'bg-primary text-primary-foreground' : 'border-border bg-muted')}>{m.label}</button>))}</div></div>
            <div className="space-y-2"><Label className="text-xs">URL</Label><Input className="h-8" placeholder="https://api.example.com" value={(nodeData.url as string) || ''} onChange={(e) => handleDataChange('url', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Headers (JSON)</Label><Textarea className="min-h-[60px] font-mono text-xs" placeholder='{"Authorization": "Bearer {{token}}"}' value={(nodeData.headers as string) || ''} onChange={(e) => handleDataChange('headers', e.target.value)} /></div>
            {['POST', 'PUT', 'PATCH'].includes((nodeData.method as string) || 'GET') && (<div className="space-y-2"><Label className="text-xs">Body (JSON)</Label><Textarea className="min-h-[80px] font-mono text-xs" placeholder='{"symbol": "{{webhook.symbol}}"}' value={(nodeData.body as string) || ''} onChange={(e) => handleDataChange('body', e.target.value)} /></div>)}
            <div className="space-y-2"><Label className="text-xs">Timeout (ms)</Label><Input type="number" min={1000} max={60000} className="h-8" value={(nodeData.timeout as number) || 30000} onChange={(e) => handleDataChange('timeout', parseInt(e.target.value, 10) || 30000)} /></div>
            <div className="space-y-2"><Label className="text-xs">Output Variable</Label><Input className="h-8" placeholder="apiResponse" value={(nodeData.outputVariable as string) || ''} onChange={(e) => handleDataChange('outputVariable', e.target.value)} /><p className="text-[10px] text-muted-foreground">Use {`{{apiResponse.data}}`}</p></div>
          </>)}

          {/* ===== CONDITION NODES ===== */}
          {nodeType === 'timeWindow' && (<>
            <div className="space-y-2"><Label className="text-xs">Start Time</Label><Input type="time" className="h-8" value={(nodeData.startTime as string) || '09:15'} onChange={(e) => handleDataChange('startTime', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">End Time</Label><Input type="time" className="h-8" value={(nodeData.endTime as string) || '15:30'} onChange={(e) => handleDataChange('endTime', e.target.value)} /></div>
            <div className="flex items-center justify-between rounded-lg border p-3"><div><Label className="text-xs">Invert Condition</Label><p className="text-[10px] text-muted-foreground">Trigger outside window</p></div><Switch checked={(nodeData.invertCondition as boolean) || false} onCheckedChange={(v) => handleDataChange('invertCondition', v)} /></div>
          </>)}

          {nodeType === 'timeCondition' && (<>
            <div className="space-y-2"><Label className="text-xs">Condition Type</Label><div className="grid grid-cols-3 gap-2">{CONDITION_TYPES.map((t) => (<button key={t.value} type="button" onClick={() => handleDataChange('conditionType', t.value)} className={cn('rounded-lg border py-2 text-sm font-semibold', nodeData.conditionType === t.value ? t.value === 'entry' ? 'bg-green-500/20 border-green-500 text-green-600' : t.value === 'exit' ? 'bg-red-500/20 border-red-500 text-red-600' : 'bg-primary text-primary-foreground' : 'border-border bg-muted')}>{t.label}</button>))}</div></div>
            <div className="space-y-2"><Label className="text-xs">Operator</Label><Select value={(nodeData.operator as string) || '>='} onValueChange={(v) => handleDataChange('operator', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{TIME_OPERATORS.map((o) => (<SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Target Time</Label><Input type="time" className="h-8" value={(nodeData.targetTime as string) || '09:30'} onChange={(e) => handleDataChange('targetTime', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Label</Label><Input className="h-8" placeholder="Market Open Entry" value={(nodeData.label as string) || ''} onChange={(e) => handleDataChange('label', e.target.value)} /></div>
          </>)}

          {nodeType === 'priceCondition' && (<>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="RELIANCE" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXCHANGES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Field</Label><Select value={(nodeData.field as string) || 'ltp'} onValueChange={(v) => handleDataChange('field', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="ltp">LTP</SelectItem><SelectItem value="open">Open</SelectItem><SelectItem value="high">High</SelectItem><SelectItem value="low">Low</SelectItem><SelectItem value="prev_close">Prev Close</SelectItem><SelectItem value="change_percent">Change %</SelectItem></SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Operator</Label><Select value={(nodeData.operator as string) || '>'} onValueChange={(v) => handleDataChange('operator', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value=">">&gt;</SelectItem><SelectItem value="<">&lt;</SelectItem><SelectItem value="==">=</SelectItem><SelectItem value=">=">&gt;=</SelectItem><SelectItem value="<=">&lt;=</SelectItem><SelectItem value="!=">!=</SelectItem></SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Value</Label><Input type="number" step="0.05" className="h-8" value={(nodeData.value as number) || ''} onChange={(e) => handleDataChange('value', parseFloat(e.target.value) || 0)} /></div>
          </>)}

          {nodeType === 'positionCheck' && (<>
            <div className="space-y-2"><Label className="text-xs">Symbol</Label><Input className="h-8" placeholder="RELIANCE" value={(nodeData.symbol as string) || ''} onChange={(e) => handleDataChange('symbol', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Exchange</Label><Select value={(nodeData.exchange as string) || 'NSE'} onValueChange={(v) => handleDataChange('exchange', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{EXCHANGES.map((e) => (<SelectItem key={e.value} value={e.value}>{e.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Product</Label><Select value={(nodeData.product as string) || 'MIS'} onValueChange={(v) => handleDataChange('product', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent>{PRODUCT_TYPES.map((t) => (<SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>))}</SelectContent></Select></div>
            <div className="space-y-2"><Label className="text-xs">Condition</Label><Select value={(nodeData.condition as string) || 'exists'} onValueChange={(v) => handleDataChange('condition', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="exists">Has Position</SelectItem><SelectItem value="not_exists">No Position</SelectItem><SelectItem value="quantity_above">Qty Above</SelectItem><SelectItem value="quantity_below">Qty Below</SelectItem><SelectItem value="pnl_above">P&L Above</SelectItem><SelectItem value="pnl_below">P&L Below</SelectItem></SelectContent></Select></div>
            {['quantity_above', 'quantity_below', 'pnl_above', 'pnl_below'].includes(nodeData.condition as string) && (<div className="space-y-2"><Label className="text-xs">Threshold</Label><Input type="number" className="h-8" value={(nodeData.threshold as number) || ''} onChange={(e) => handleDataChange('threshold', parseFloat(e.target.value) || 0)} /></div>)}
          </>)}

          {nodeType === 'fundCheck' && (<div className="space-y-2"><Label className="text-xs">Minimum Available Funds</Label><Input type="number" min={0} className="h-8" placeholder="10000" value={(nodeData.minAvailable as number) || ''} onChange={(e) => handleDataChange('minAvailable', parseFloat(e.target.value) || 0)} /><p className="text-[10px] text-muted-foreground">Checks if margin is above this</p></div>)}

          {nodeType === 'andGate' && (<>
            <div className="space-y-2"><Label className="text-xs">Number of Inputs</Label><Select value={String((nodeData.inputCount as number) || 2)} onValueChange={(v) => handleDataChange('inputCount', parseInt(v, 10))}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="2">2 inputs</SelectItem><SelectItem value="3">3 inputs</SelectItem><SelectItem value="4">4 inputs</SelectItem><SelectItem value="5">5 inputs</SelectItem></SelectContent></Select></div>
            <div className="rounded-lg bg-muted/50 p-3 text-xs"><p className="font-medium mb-1">AND Gate</p><p className="text-muted-foreground">Yes only if ALL conditions true</p></div>
          </>)}

          {nodeType === 'orGate' && (<>
            <div className="space-y-2"><Label className="text-xs">Number of Inputs</Label><Select value={String((nodeData.inputCount as number) || 2)} onValueChange={(v) => handleDataChange('inputCount', parseInt(v, 10))}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="2">2 inputs</SelectItem><SelectItem value="3">3 inputs</SelectItem><SelectItem value="4">4 inputs</SelectItem><SelectItem value="5">5 inputs</SelectItem></SelectContent></Select></div>
            <div className="rounded-lg bg-muted/50 p-3 text-xs"><p className="font-medium mb-1">OR Gate</p><p className="text-muted-foreground">Yes if ANY condition true</p></div>
          </>)}

          {nodeType === 'notGate' && (<div className="rounded-lg bg-muted/50 p-3 text-xs"><p className="font-medium mb-1">NOT Gate</p><p className="text-muted-foreground">Inverts the condition. True becomes False, False becomes True.</p></div>)}

          {nodeType === 'group' && (<>
            <div className="space-y-2"><Label className="text-xs">Group Name</Label><Input className="h-8" placeholder="Entry Logic" value={(nodeData.label as string) || ''} onChange={(e) => handleDataChange('label', e.target.value)} /></div>
            <div className="space-y-2"><Label className="text-xs">Color</Label><Select value={(nodeData.color as string) || 'default'} onValueChange={(v) => handleDataChange('color', v)}><SelectTrigger className="h-8"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="default">Default</SelectItem><SelectItem value="blue">Blue</SelectItem><SelectItem value="green">Green</SelectItem><SelectItem value="red">Red</SelectItem><SelectItem value="purple">Purple</SelectItem><SelectItem value="orange">Orange</SelectItem></SelectContent></Select></div>
          </>)}

          {/* ===== FALLBACK ===== */}
          {!NODE_TITLES[nodeType] && (<>
            {nodeInfo && (<div className="rounded-lg border bg-muted/30 p-3"><div className="flex items-start gap-2"><Info className="h-4 w-4 text-muted-foreground mt-0.5" /><div><p className="text-xs font-medium">{nodeInfo.label}</p><p className="text-xs text-muted-foreground mt-0.5">{nodeInfo.description}</p></div></div></div>)}
            <Separator />
            <div className="space-y-2"><Label className="text-xs">Node Label</Label><Input className="h-8" placeholder="Enter label..." value={(nodeData.label as string) || ''} onChange={(e) => handleDataChange('label', e.target.value)} /></div>
          </>)}

          <Separator />
          <div className="space-y-2"><Label className="text-xs text-muted-foreground">Node ID</Label><code className="block text-[10px] bg-muted px-2 py-1 rounded font-mono">{selectedNode.id}</code></div>
        </div>
      </ScrollArea>
    </div>
  )
}