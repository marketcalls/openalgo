// components/flow/panels/NodePalette.tsx
// Left sidebar with draggable node items organized by category

import {
  Clock,
  ShoppingCart,
  Zap,
  TrendingUp,
  XCircle,
  Square,
  Briefcase,
  Wallet,
  Send,
  Bell,
  Timer,
  Hourglass,
  Layers,
  Package,
  Split,
  Pencil,
  FileSearch,
  BarChart3,
  Layers3,
  Calendar,
  Variable,
  FileText,
  Group,
  Webhook,
  Globe,
  Tag,
  Target,
  ClipboardList,
  Receipt,
  Calculator,
  Grid3X3,
  CalendarX,
  Radio,
  RadioTower,
  WifiOff,
  Shield,
  Sigma,
} from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'

interface NodeItemProps {
  type: string
  label: string
  description: string
  icon: React.ReactNode
  color: string
  onDragStart: (event: React.DragEvent, nodeType: string) => void
}

function NodeItem({ type, label, description, icon, color, onDragStart }: NodeItemProps) {
  return (
    <div
      draggable
      onDragStart={(e) => onDragStart(e, type)}
      className={cn(
        'group cursor-grab rounded-lg border border-border bg-card p-2.5 transition-all duration-200',
        'hover:border-primary/50 hover:shadow-md active:cursor-grabbing'
      )}
    >
      <div className="flex items-center gap-2.5">
        <div
          className={cn(
            'flex h-7 w-7 items-center justify-center rounded-md',
            color
          )}
        >
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-medium">{label}</div>
          <div className="truncate text-[10px] text-muted-foreground">{description}</div>
        </div>
      </div>
    </div>
  )
}

interface NodePaletteProps {
  onDragStart: (event: React.DragEvent, nodeType: string) => void
}

export function NodePalette({ onDragStart }: NodePaletteProps) {
  const triggers = [
    {
      type: 'start',
      label: 'Schedule',
      description: 'Start on schedule',
      icon: <Clock className="h-3.5 w-3.5 text-orange-500" />,
      color: 'bg-orange-500/10',
    },
    {
      type: 'priceAlert',
      label: 'Price Alert',
      description: 'Trigger on price',
      icon: <Bell className="h-3.5 w-3.5 text-orange-500" />,
      color: 'bg-orange-500/10',
    },
    {
      type: 'webhookTrigger',
      label: 'Webhook',
      description: 'External trigger',
      icon: <Webhook className="h-3.5 w-3.5 text-orange-500" />,
      color: 'bg-orange-500/10',
    },
  ]

  const actions = [
    {
      type: 'placeOrder',
      label: 'Place Order',
      description: 'Basic order',
      icon: <ShoppingCart className="h-3.5 w-3.5 text-blue-500" />,
      color: 'bg-blue-500/10',
    },
    {
      type: 'smartOrder',
      label: 'Smart Order',
      description: 'Position-aware',
      icon: <Zap className="h-3.5 w-3.5 text-blue-500" />,
      color: 'bg-blue-500/10',
    },
    {
      type: 'optionsOrder',
      label: 'Options Order',
      description: 'ATM/ITM/OTM',
      icon: <TrendingUp className="h-3.5 w-3.5 text-blue-500" />,
      color: 'bg-blue-500/10',
    },
    {
      type: 'optionsMultiOrder',
      label: 'Multi-Leg',
      description: 'Options strategies',
      icon: <Layers className="h-3.5 w-3.5 text-blue-500" />,
      color: 'bg-blue-500/10',
    },
    {
      type: 'basketOrder',
      label: 'Basket Order',
      description: 'Multiple orders',
      icon: <Package className="h-3.5 w-3.5 text-blue-500" />,
      color: 'bg-blue-500/10',
    },
    {
      type: 'splitOrder',
      label: 'Split Order',
      description: 'Large order split',
      icon: <Split className="h-3.5 w-3.5 text-blue-500" />,
      color: 'bg-blue-500/10',
    },
    {
      type: 'modifyOrder',
      label: 'Modify Order',
      description: 'Edit order',
      icon: <Pencil className="h-3.5 w-3.5 text-blue-500" />,
      color: 'bg-blue-500/10',
    },
    {
      type: 'cancelOrder',
      label: 'Cancel Order',
      description: 'Cancel by ID',
      icon: <XCircle className="h-3.5 w-3.5 text-red-500" />,
      color: 'bg-red-500/10',
    },
    {
      type: 'cancelAllOrders',
      label: 'Cancel All',
      description: 'Cancel orders',
      icon: <XCircle className="h-3.5 w-3.5 text-red-500" />,
      color: 'bg-red-500/10',
    },
    {
      type: 'closePositions',
      label: 'Close Positions',
      description: 'Square off all',
      icon: <Square className="h-3.5 w-3.5 text-red-500" />,
      color: 'bg-red-500/10',
    },
  ]

  const conditions = [
    {
      type: 'timeCondition',
      label: 'Time Condition',
      description: 'Entry/Exit time',
      icon: <Clock className="h-3.5 w-3.5 text-purple-500" />,
      color: 'bg-purple-500/10',
    },
    {
      type: 'positionCheck',
      label: 'Position Check',
      description: 'Check position',
      icon: <Briefcase className="h-3.5 w-3.5 text-purple-500" />,
      color: 'bg-purple-500/10',
    },
    {
      type: 'fundCheck',
      label: 'Fund Check',
      description: 'Check funds',
      icon: <Wallet className="h-3.5 w-3.5 text-purple-500" />,
      color: 'bg-purple-500/10',
    },
    {
      type: 'priceCondition',
      label: 'Price Check',
      description: 'Check price',
      icon: <TrendingUp className="h-3.5 w-3.5 text-purple-500" />,
      color: 'bg-purple-500/10',
    },
    {
      type: 'timeWindow',
      label: 'Time Window',
      description: 'Market hours',
      icon: <Clock className="h-3.5 w-3.5 text-purple-500" />,
      color: 'bg-purple-500/10',
    },
    {
      type: 'andGate',
      label: 'AND Gate',
      description: 'All must be true',
      icon: <span className="text-[9px] font-bold text-purple-500">AND</span>,
      color: 'bg-purple-500/10',
    },
    {
      type: 'orGate',
      label: 'OR Gate',
      description: 'Any can be true',
      icon: <span className="text-[9px] font-bold text-purple-500">OR</span>,
      color: 'bg-purple-500/10',
    },
    {
      type: 'notGate',
      label: 'NOT Gate',
      description: 'Invert condition',
      icon: <span className="text-[9px] font-bold text-purple-500">NOT</span>,
      color: 'bg-purple-500/10',
    },
  ]

  const data = [
    {
      type: 'getQuote',
      label: 'Get Quote',
      description: 'Real-time quote',
      icon: <BarChart3 className="h-3.5 w-3.5 text-cyan-500" />,
      color: 'bg-cyan-500/10',
    },
    {
      type: 'getDepth',
      label: 'Get Depth',
      description: 'Bid/ask depth',
      icon: <Layers3 className="h-3.5 w-3.5 text-cyan-500" />,
      color: 'bg-cyan-500/10',
    },
    {
      type: 'getOrderStatus',
      label: 'Order Status',
      description: 'Check order',
      icon: <FileSearch className="h-3.5 w-3.5 text-orange-500" />,
      color: 'bg-orange-500/10',
    },
    {
      type: 'history',
      label: 'History',
      description: 'OHLCV data',
      icon: <TrendingUp className="h-3.5 w-3.5 text-cyan-500" />,
      color: 'bg-cyan-500/10',
    },
    {
      type: 'openPosition',
      label: 'Open Position',
      description: 'Get position',
      icon: <Briefcase className="h-3.5 w-3.5 text-violet-500" />,
      color: 'bg-violet-500/10',
    },
    {
      type: 'expiry',
      label: 'Expiry Dates',
      description: 'F&O expiry',
      icon: <Calendar className="h-3.5 w-3.5 text-pink-500" />,
      color: 'bg-pink-500/10',
    },
    {
      type: 'multiQuotes',
      label: 'Multi Quotes',
      description: 'Multiple symbols',
      icon: <BarChart3 className="h-3.5 w-3.5 text-cyan-500" />,
      color: 'bg-cyan-500/10',
    },
    {
      type: 'symbol',
      label: 'Symbol Info',
      description: 'Get symbol details',
      icon: <Tag className="h-3.5 w-3.5 text-teal-500" />,
      color: 'bg-teal-500/10',
    },
    {
      type: 'optionSymbol',
      label: 'Option Symbol',
      description: 'Resolve options',
      icon: <Target className="h-3.5 w-3.5 text-pink-500" />,
      color: 'bg-pink-500/10',
    },
    {
      type: 'orderBook',
      label: 'Order Book',
      description: 'All orders',
      icon: <ClipboardList className="h-3.5 w-3.5 text-orange-500" />,
      color: 'bg-orange-500/10',
    },
    {
      type: 'tradeBook',
      label: 'Trade Book',
      description: 'Executed trades',
      icon: <Receipt className="h-3.5 w-3.5 text-orange-500" />,
      color: 'bg-orange-500/10',
    },
    {
      type: 'positionBook',
      label: 'Position Book',
      description: 'All positions',
      icon: <Briefcase className="h-3.5 w-3.5 text-violet-500" />,
      color: 'bg-violet-500/10',
    },
    {
      type: 'syntheticFuture',
      label: 'Synthetic Future',
      description: 'Calc future price',
      icon: <Calculator className="h-3.5 w-3.5 text-pink-500" />,
      color: 'bg-pink-500/10',
    },
    {
      type: 'optionChain',
      label: 'Option Chain',
      description: 'Full chain data',
      icon: <Grid3X3 className="h-3.5 w-3.5 text-pink-500" />,
      color: 'bg-pink-500/10',
    },
    {
      type: 'holdings',
      label: 'Holdings',
      description: 'Portfolio holdings',
      icon: <Briefcase className="h-3.5 w-3.5 text-amber-500" />,
      color: 'bg-amber-500/10',
    },
    {
      type: 'funds',
      label: 'Funds',
      description: 'Account balance',
      icon: <Wallet className="h-3.5 w-3.5 text-amber-500" />,
      color: 'bg-amber-500/10',
    },
    {
      type: 'margin',
      label: 'Margin Calc',
      description: 'Margin required',
      icon: <Shield className="h-3.5 w-3.5 text-amber-500" />,
      color: 'bg-amber-500/10',
    },
  ]

  const streaming = [
    {
      type: 'subscribeLtp',
      label: 'Subscribe LTP',
      description: 'Live price stream',
      icon: <Radio className="h-3.5 w-3.5 text-green-500" />,
      color: 'bg-green-500/10',
    },
    {
      type: 'subscribeQuote',
      label: 'Subscribe Quote',
      description: 'Live OHLC stream',
      icon: <RadioTower className="h-3.5 w-3.5 text-green-500" />,
      color: 'bg-green-500/10',
    },
    {
      type: 'subscribeDepth',
      label: 'Subscribe Depth',
      description: 'Live order book',
      icon: <Layers3 className="h-3.5 w-3.5 text-green-500" />,
      color: 'bg-green-500/10',
    },
    {
      type: 'unsubscribe',
      label: 'Unsubscribe',
      description: 'Stop streaming',
      icon: <WifiOff className="h-3.5 w-3.5 text-red-500" />,
      color: 'bg-red-500/10',
    },
  ]

  const utilities = [
    {
      type: 'variable',
      label: 'Variable',
      description: 'Store values',
      icon: <Variable className="h-3.5 w-3.5 text-purple-400" />,
      color: 'bg-purple-400/10',
    },
    {
      type: 'mathExpression',
      label: 'Math',
      description: 'Calculate expression',
      icon: <Sigma className="h-3.5 w-3.5 text-purple-500" />,
      color: 'bg-purple-500/10',
    },
    {
      type: 'log',
      label: 'Log',
      description: 'Debug message',
      icon: <FileText className="h-3.5 w-3.5 text-blue-400" />,
      color: 'bg-blue-400/10',
    },
    {
      type: 'telegramAlert',
      label: 'Telegram',
      description: 'Send alert',
      icon: <Send className="h-3.5 w-3.5 text-[#0088cc]" />,
      color: 'bg-[#0088cc]/10',
    },
    {
      type: 'delay',
      label: 'Delay',
      description: 'Wait duration',
      icon: <Timer className="h-3.5 w-3.5 text-muted-foreground" />,
      color: 'bg-muted',
    },
    {
      type: 'waitUntil',
      label: 'Wait Until',
      description: 'Wait until time',
      icon: <Hourglass className="h-3.5 w-3.5 text-amber-500" />,
      color: 'bg-amber-500/10',
    },
    {
      type: 'group',
      label: 'Group',
      description: 'Group nodes',
      icon: <Group className="h-3.5 w-3.5 text-muted-foreground" />,
      color: 'bg-muted',
    },
    {
      type: 'httpRequest',
      label: 'HTTP Request',
      description: 'API call',
      icon: <Globe className="h-3.5 w-3.5 text-primary" />,
      color: 'bg-primary/10',
    },
    {
      type: 'holidays',
      label: 'Holidays',
      description: 'Market holidays',
      icon: <CalendarX className="h-3.5 w-3.5 text-purple-400" />,
      color: 'bg-purple-400/10',
    },
    {
      type: 'timings',
      label: 'Timings',
      description: 'Market hours',
      icon: <Clock className="h-3.5 w-3.5 text-purple-400" />,
      color: 'bg-purple-400/10',
    },
  ]

  return (
    <div className="flex h-full flex-col border-r border-border bg-card">
      <div className="shrink-0 border-b border-border p-3">
        <h2 className="text-sm font-semibold">Nodes</h2>
        <p className="text-[10px] text-muted-foreground">
          Drag nodes to the canvas
        </p>
      </div>
      <Tabs defaultValue="triggers" className="flex-1 flex flex-col min-h-0">
        <div className="shrink-0 border-b border-border px-1 py-1.5">
          <TabsList className="h-7 w-full">
            <TabsTrigger value="triggers" className="flex-1 text-[8px] px-0.5">
              Trigger
            </TabsTrigger>
            <TabsTrigger value="actions" className="flex-1 text-[8px] px-0.5">
              Action
            </TabsTrigger>
            <TabsTrigger value="data" className="flex-1 text-[8px] px-0.5">
              Data
            </TabsTrigger>
            <TabsTrigger value="stream" className="flex-1 text-[8px] px-0.5">
              Stream
            </TabsTrigger>
            <TabsTrigger value="conditions" className="flex-1 text-[8px] px-0.5">
              Logic
            </TabsTrigger>
            <TabsTrigger value="utilities" className="flex-1 text-[8px] px-0.5">
              Util
            </TabsTrigger>
          </TabsList>
        </div>
        <div className="flex-1 min-h-0 relative">
          <TabsContent value="triggers" className="m-0 absolute inset-0">
            <ScrollArea className="h-full">
              <div className="space-y-1.5 p-2">
                {triggers.map((node) => (
                  <NodeItem
                    key={node.type}
                    {...node}
                    onDragStart={onDragStart}
                  />
                ))}
              </div>
            </ScrollArea>
          </TabsContent>
          <TabsContent value="actions" className="m-0 absolute inset-0">
            <ScrollArea className="h-full">
              <div className="space-y-1.5 p-2">
                {actions.map((node) => (
                  <NodeItem
                    key={node.type}
                    {...node}
                    onDragStart={onDragStart}
                  />
                ))}
              </div>
            </ScrollArea>
          </TabsContent>
          <TabsContent value="data" className="m-0 absolute inset-0">
            <ScrollArea className="h-full">
              <div className="space-y-1.5 p-2">
                {data.map((node) => (
                  <NodeItem
                    key={node.type}
                    {...node}
                    onDragStart={onDragStart}
                  />
                ))}
              </div>
            </ScrollArea>
          </TabsContent>
          <TabsContent value="stream" className="m-0 absolute inset-0">
            <ScrollArea className="h-full">
              <div className="space-y-1.5 p-2">
                {streaming.map((node) => (
                  <NodeItem
                    key={node.type}
                    {...node}
                    onDragStart={onDragStart}
                  />
                ))}
              </div>
            </ScrollArea>
          </TabsContent>
          <TabsContent value="conditions" className="m-0 absolute inset-0">
            <ScrollArea className="h-full">
              <div className="space-y-1.5 p-2">
                {conditions.map((node) => (
                  <NodeItem
                    key={node.type}
                    {...node}
                    onDragStart={onDragStart}
                  />
                ))}
              </div>
            </ScrollArea>
          </TabsContent>
          <TabsContent value="utilities" className="m-0 absolute inset-0">
            <ScrollArea className="h-full">
              <div className="space-y-1.5 p-2">
                {utilities.map((node) => (
                  <NodeItem
                    key={node.type}
                    {...node}
                    onDragStart={onDragStart}
                  />
                ))}
              </div>
            </ScrollArea>
          </TabsContent>
        </div>
      </Tabs>
    </div>
  )
}
