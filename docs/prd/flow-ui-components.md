# Flow UI Components Guide

This guide documents the React components that make up the Flow visual workflow builder.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FlowEditor Page                               │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │                    ReactFlow Canvas                              ││
│  │  ┌─────────────────────────────────────────────────────────────┐││
│  │  │                     Nodes                                    │││
│  │  │  StartNode, PlaceOrderNode, PriceConditionNode, etc.        │││
│  │  └─────────────────────────────────────────────────────────────┘││
│  │  ┌─────────────────────────────────────────────────────────────┐││
│  │  │                     Edges                                    │││
│  │  │  InsertableEdge (custom edge with node insertion)           │││
│  │  └─────────────────────────────────────────────────────────────┘││
│  └─────────────────────────────────────────────────────────────────┘│
│        │                    │                    │                   │
│  ┌─────▼─────┐      ┌──────▼──────┐      ┌─────▼─────┐             │
│  │NodePalette│      │ ConfigPanel │      │  LogPanel │             │
│  │(Left)     │      │  (Right)    │      │ (Bottom)  │             │
│  └───────────┘      └─────────────┘      └───────────┘             │
└─────────────────────────────────────────────────────────────────────┘
```

## Key Files

| File | Purpose | Lines |
|------|---------|-------|
| `pages/flow/FlowEditor.tsx` | Main editor page | ~300 |
| `components/flow/nodes/index.ts` | Node registry | ~220 |
| `components/flow/nodes/BaseNode.tsx` | Base node component | ~220 |
| `components/flow/panels/NodePalette.tsx` | Left sidebar | ~200 |
| `components/flow/panels/ConfigPanel.tsx` | Right sidebar | ~550 |
| `components/flow/panels/ExecutionLogPanel.tsx` | Bottom panel | ~100 |
| `components/flow/edges/InsertableEdge.tsx` | Custom edge | ~150 |
| `stores/flowWorkflowStore.ts` | Zustand state | ~150 |
| `lib/flow/constants.ts` | Node definitions | ~650 |
| `types/flow.ts` | TypeScript types | ~750 |

## Main Editor

**File:** `frontend/src/pages/flow/FlowEditor.tsx`

```typescript
import { ReactFlow, Background, Controls, MiniMap, Panel } from '@xyflow/react'
import { nodeTypes } from '@/components/flow/nodes'
import { edgeTypes } from '@/components/flow/edges'
import { NodePalette } from '@/components/flow/panels/NodePalette'
import { ConfigPanel } from '@/components/flow/panels/ConfigPanel'
import { useFlowWorkflowStore } from '@/stores/flowWorkflowStore'

export function FlowEditor() {
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    selectedNodeId,
  } = useFlowWorkflowStore()

  return (
    <div className="h-screen w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        fitView
        snapToGrid
        snapGrid={[15, 15]}
      >
        <Background variant="dots" gap={15} />
        <Controls />
        <MiniMap />

        {/* Left Panel - Node Palette */}
        <Panel position="top-left">
          <NodePalette />
        </Panel>

        {/* Right Panel - Config */}
        <Panel position="top-right">
          {selectedNodeId && <ConfigPanel />}
        </Panel>
      </ReactFlow>

      {/* Bottom Panel - Logs */}
      <ExecutionLogPanel />
    </div>
  )
}
```

## Node Components

### Base Node

**File:** `frontend/src/components/flow/nodes/BaseNode.tsx`

Provides consistent styling and handles for all nodes.

```typescript
interface BaseNodeProps {
  category: 'trigger' | 'action' | 'condition' | 'data' | 'utility'
  icon: ReactNode
  title: string
  subtitle?: string
  hasInput?: boolean
  hasOutput?: boolean
  hasConditionalOutputs?: boolean
  children?: ReactNode
}

export function BaseNode({
  category,
  icon,
  title,
  subtitle,
  hasInput = true,
  hasOutput = true,
  hasConditionalOutputs = false,
  children,
}: BaseNodeProps) {
  // Category-based colors
  const categoryColors = {
    trigger: 'bg-green-500/10 text-green-500 border-green-500/20',
    action: 'bg-blue-500/10 text-blue-500 border-blue-500/20',
    condition: 'bg-amber-500/10 text-amber-500 border-amber-500/20',
    data: 'bg-purple-500/10 text-purple-500 border-purple-500/20',
    utility: 'bg-gray-500/10 text-gray-500 border-gray-500/20',
  }

  return (
    <div className={`workflow-node ${categoryColors[category]}`}>
      {/* Input Handle */}
      {hasInput && (
        <Handle
          type="target"
          position={Position.Top}
          className="!bg-primary !w-2 !h-2"
        />
      )}

      {/* Node Content */}
      <div className="p-2 min-w-[140px]">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="node-icon">{icon}</div>
          <div>
            <div className="text-xs font-medium">{title}</div>
            {subtitle && (
              <div className="text-[9px] text-muted-foreground">{subtitle}</div>
            )}
          </div>
        </div>
        {children}
      </div>

      {/* Output Handle(s) */}
      {hasOutput && !hasConditionalOutputs && (
        <Handle
          type="source"
          position={Position.Bottom}
          className="!bg-primary !w-2 !h-2"
        />
      )}

      {/* Conditional Outputs (True/False) */}
      {hasConditionalOutputs && (
        <>
          <Handle
            type="source"
            position={Position.Bottom}
            id="true"
            className="!bg-green-500 !w-2 !h-2"
            style={{ left: '30%' }}
          />
          <Handle
            type="source"
            position={Position.Bottom}
            id="false"
            className="!bg-red-500 !w-2 !h-2"
            style={{ left: '70%' }}
          />
        </>
      )}
    </div>
  )
}
```

### Helper Components

```typescript
// Display key-value data row
export function NodeDataRow({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string | number
  mono?: boolean
}) {
  return (
    <div className="flex justify-between text-[10px]">
      <span className="text-muted-foreground">{label}</span>
      <span className={mono ? 'font-mono' : ''}>{value}</span>
    </div>
  )
}

// Badge for buy/sell actions
export function NodeBadge({
  variant = 'default',
  children,
}: {
  variant?: 'buy' | 'sell' | 'default'
  children: ReactNode
}) {
  const colors = {
    buy: 'bg-green-500/10 text-green-500',
    sell: 'bg-red-500/10 text-red-500',
    default: 'bg-gray-500/10 text-gray-500',
  }

  return (
    <span className={`px-1.5 py-0.5 rounded text-[9px] ${colors[variant]}`}>
      {children}
    </span>
  )
}

// Info row with multiple items
export function NodeInfoRow({ items }: { items: Array<{ label: string; value: string }> }) {
  return (
    <div className="flex gap-2 text-[9px]">
      {items.map((item, i) => (
        <span key={i} className="text-muted-foreground">
          {item.label}: <span className="text-foreground">{item.value}</span>
        </span>
      ))}
    </div>
  )
}
```

### Node Type Registry

**File:** `frontend/src/components/flow/nodes/index.ts`

```typescript
import { StartNode } from './StartNode'
import { PlaceOrderNode } from './PlaceOrderNode'
import { SmartOrderNode } from './SmartOrderNode'
import { PriceConditionNode } from './PriceConditionNode'
// ... 50+ imports

export {
  StartNode,
  PlaceOrderNode,
  SmartOrderNode,
  PriceConditionNode,
  // ... exports
}

// Registry for ReactFlow
export const nodeTypes = {
  start: StartNode,
  placeOrder: PlaceOrderNode,
  smartOrder: SmartOrderNode,
  priceCondition: PriceConditionNode,
  optionsOrder: OptionsOrderNode,
  optionsMultiOrder: OptionsMultiOrderNode,
  basketOrder: BasketOrderNode,
  splitOrder: SplitOrderNode,
  modifyOrder: ModifyOrderNode,
  cancelOrder: CancelOrderNode,
  cancelAllOrders: CancelAllOrdersNode,
  closePositions: ClosePositionsNode,
  positionCheck: PositionCheckNode,
  fundCheck: FundCheckNode,
  timeWindow: TimeWindowNode,
  timeCondition: TimeConditionNode,
  andGate: AndGateNode,
  orGate: OrGateNode,
  notGate: NotGateNode,
  getQuote: GetQuoteNode,
  getDepth: GetDepthNode,
  history: HistoryNode,
  openPosition: OpenPositionNode,
  orderBook: OrderBookNode,
  tradeBook: TradeBookNode,
  positionBook: PositionBookNode,
  holdings: HoldingsNode,
  funds: FundsNode,
  symbol: SymbolNode,
  optionSymbol: OptionSymbolNode,
  expiry: ExpiryNode,
  optionChain: OptionChainNode,
  intervals: IntervalsNode,
  holidays: HolidaysNode,
  timings: TimingsNode,
  subscribeLtp: SubscribeLTPNode,
  subscribeQuote: SubscribeQuoteNode,
  subscribeDepth: SubscribeDepthNode,
  unsubscribe: UnsubscribeNode,
  variable: VariableNode,
  delay: DelayNode,
  waitUntil: WaitUntilNode,
  log: LogNode,
  telegramAlert: TelegramAlertNode,
  mathExpression: MathExpressionNode,
  webhookTrigger: WebhookTriggerNode,
  priceAlert: PriceAlertNode,
  httpRequest: HttpRequestNode,
  group: GroupNode,
} as const
```

## Panels

### Node Palette

**File:** `frontend/src/components/flow/panels/NodePalette.tsx`

Drag-and-drop node selection panel.

```typescript
import { NODE_DEFINITIONS } from '@/lib/flow/constants'

export function NodePalette() {
  const onDragStart = (event: DragEvent, nodeType: string) => {
    event.dataTransfer?.setData('application/reactflow', nodeType)
    event.dataTransfer!.effectAllowed = 'move'
  }

  return (
    <div className="w-64 bg-background border rounded-lg shadow-lg">
      <Tabs defaultValue="triggers">
        <TabsList className="w-full">
          <TabsTrigger value="triggers">Triggers</TabsTrigger>
          <TabsTrigger value="actions">Actions</TabsTrigger>
          <TabsTrigger value="conditions">Conditions</TabsTrigger>
          <TabsTrigger value="data">Data</TabsTrigger>
          <TabsTrigger value="utility">Utility</TabsTrigger>
        </TabsList>

        <TabsContent value="triggers">
          {NODE_DEFINITIONS.TRIGGERS.map((node) => (
            <div
              key={node.type}
              className="p-2 border-b cursor-grab hover:bg-accent"
              draggable
              onDragStart={(e) => onDragStart(e, node.type)}
            >
              <div className="font-medium text-sm">{node.label}</div>
              <div className="text-xs text-muted-foreground">
                {node.description}
              </div>
            </div>
          ))}
        </TabsContent>

        {/* Similar for other categories */}
      </Tabs>
    </div>
  )
}
```

### Config Panel

**File:** `frontend/src/components/flow/panels/ConfigPanel.tsx`

Dynamic configuration form based on selected node type.

```typescript
import { useFlowWorkflowStore } from '@/stores/flowWorkflowStore'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Label } from '@/components/ui/label'

export function ConfigPanel() {
  const { nodes, selectedNodeId, updateNodeData } = useFlowWorkflowStore()

  const selectedNode = nodes.find((n) => n.id === selectedNodeId)
  if (!selectedNode) return null

  const nodeType = selectedNode.type
  const nodeData = selectedNode.data

  const handleDataChange = (key: string, value: any) => {
    updateNodeData(selectedNodeId!, { [key]: value })
  }

  return (
    <div className="w-80 bg-background border rounded-lg shadow-lg p-4">
      <h3 className="font-semibold mb-4">Configure Node</h3>

      {/* Dynamic form based on node type */}
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

          <div className="space-y-2">
            <Label className="text-xs">Exchange</Label>
            <Select
              value={(nodeData.exchange as string) || 'NSE'}
              onValueChange={(v) => handleDataChange('exchange', v)}
            >
              <SelectTrigger className="h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {EXCHANGES.map((ex) => (
                  <SelectItem key={ex} value={ex}>{ex}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label className="text-xs">Action</Label>
            <RadioGroup
              value={(nodeData.action as string) || 'BUY'}
              onValueChange={(v) => handleDataChange('action', v)}
              className="flex gap-4"
            >
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="BUY" id="buy" />
                <Label htmlFor="buy">BUY</Label>
              </div>
              <div className="flex items-center space-x-2">
                <RadioGroupItem value="SELL" id="sell" />
                <Label htmlFor="sell">SELL</Label>
              </div>
            </RadioGroup>
          </div>

          <div className="space-y-2">
            <Label className="text-xs">Quantity</Label>
            <Input
              type="number"
              className="h-8"
              placeholder="1"
              value={(nodeData.quantity as number) || ''}
              onChange={(e) => handleDataChange('quantity', parseInt(e.target.value))}
            />
          </div>
        </>
      )}

      {nodeType === 'priceCondition' && (
        <>
          {/* Price condition fields */}
        </>
      )}

      {/* ... 50+ node type configurations */}
    </div>
  )
}
```

### Execution Log Panel

**File:** `frontend/src/components/flow/panels/ExecutionLogPanel.tsx`

```typescript
interface LogEntry {
  time: string
  message: string
  level: 'info' | 'warn' | 'error'
}

export function ExecutionLogPanel({ logs }: { logs: LogEntry[] }) {
  return (
    <div className="h-48 bg-background border-t overflow-auto">
      <div className="p-2">
        <h4 className="text-sm font-semibold mb-2">Execution Logs</h4>
        <div className="space-y-1 font-mono text-xs">
          {logs.map((log, i) => (
            <div
              key={i}
              className={cn(
                'flex gap-2',
                log.level === 'error' && 'text-red-500',
                log.level === 'warn' && 'text-amber-500'
              )}
            >
              <span className="text-muted-foreground">[{log.time}]</span>
              <span>{log.message}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
```

## Custom Edge

**File:** `frontend/src/components/flow/edges/InsertableEdge.tsx`

Custom edge that allows inserting nodes mid-connection.

```typescript
import { BaseEdge, EdgeProps, getBezierPath } from '@xyflow/react'

export function InsertableEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  sourceHandleId,
  style = {},
  markerEnd,
}: EdgeProps) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  })

  // Color based on condition handle
  const edgeColor = sourceHandleId === 'true'
    ? '#22c55e'  // green
    : sourceHandleId === 'false'
    ? '#ef4444'  // red
    : '#6b7280'  // gray

  return (
    <>
      <BaseEdge
        path={edgePath}
        markerEnd={markerEnd}
        style={{ ...style, stroke: edgeColor }}
      />

      {/* Insert button */}
      <foreignObject
        width={20}
        height={20}
        x={labelX - 10}
        y={labelY - 10}
        className="edge-insert-button"
      >
        <button
          className="w-5 h-5 rounded-full bg-primary text-white flex items-center justify-center opacity-0 hover:opacity-100 transition-opacity"
          onClick={() => {/* Insert node logic */}}
        >
          +
        </button>
      </foreignObject>

      {/* Condition label */}
      {sourceHandleId && (
        <text
          x={labelX}
          y={labelY - 15}
          className="text-[10px] fill-muted-foreground"
          textAnchor="middle"
        >
          {sourceHandleId}
        </text>
      )}
    </>
  )
}

export const edgeTypes = {
  insertable: InsertableEdge,
}
```

## State Management

**File:** `frontend/src/stores/flowWorkflowStore.ts`

Zustand store for workflow state.

```typescript
import { create } from 'zustand'
import { Node, Edge, Connection, applyNodeChanges, applyEdgeChanges, addEdge } from '@xyflow/react'

interface WorkflowState {
  // Workflow data
  id: number | null
  name: string
  nodes: Node[]
  edges: Edge[]
  isActive: boolean

  // Selection
  selectedNodeId: string | null

  // Actions
  setWorkflow: (workflow: any) => void
  setNodes: (nodes: Node[]) => void
  setEdges: (edges: Edge[]) => void
  updateNodeData: (nodeId: string, data: Partial<any>) => void
  onNodesChange: (changes: any[]) => void
  onEdgesChange: (changes: any[]) => void
  onConnect: (connection: Connection) => void
  setSelectedNodeId: (nodeId: string | null) => void
  deleteSelected: () => void
  addNode: (type: string, position: { x: number; y: number }) => void
}

export const useFlowWorkflowStore = create<WorkflowState>((set, get) => ({
  id: null,
  name: '',
  nodes: [],
  edges: [],
  isActive: false,
  selectedNodeId: null,

  setWorkflow: (workflow) => set({
    id: workflow.id,
    name: workflow.name,
    nodes: workflow.nodes || [],
    edges: workflow.edges || [],
    isActive: workflow.is_active,
  }),

  setNodes: (nodes) => set({ nodes }),

  setEdges: (edges) => set({ edges }),

  updateNodeData: (nodeId, data) => set((state) => ({
    nodes: state.nodes.map((node) =>
      node.id === nodeId
        ? { ...node, data: { ...node.data, ...data } }
        : node
    ),
  })),

  onNodesChange: (changes) => set((state) => ({
    nodes: applyNodeChanges(changes, state.nodes),
  })),

  onEdgesChange: (changes) => set((state) => ({
    edges: applyEdgeChanges(changes, state.edges),
  })),

  onConnect: (connection) => set((state) => ({
    edges: addEdge(
      { ...connection, type: 'insertable' },
      state.edges
    ),
  })),

  setSelectedNodeId: (nodeId) => set({ selectedNodeId: nodeId }),

  deleteSelected: () => set((state) => {
    if (!state.selectedNodeId) return state
    return {
      nodes: state.nodes.filter((n) => n.id !== state.selectedNodeId),
      edges: state.edges.filter(
        (e) => e.source !== state.selectedNodeId && e.target !== state.selectedNodeId
      ),
      selectedNodeId: null,
    }
  }),

  addNode: (type, position) => set((state) => {
    const newNode: Node = {
      id: `${type}_${Date.now()}`,
      type,
      position,
      data: DEFAULT_NODE_DATA[type] || {},
    }
    return { nodes: [...state.nodes, newNode] }
  }),
}))
```

## Constants

**File:** `frontend/src/lib/flow/constants.ts`

```typescript
// Node definitions for palette
export const NODE_DEFINITIONS = {
  TRIGGERS: [
    { type: 'start', label: 'Start', description: 'Schedule-based trigger', category: 'trigger' },
    { type: 'webhookTrigger', label: 'Webhook', description: 'External HTTP trigger', category: 'trigger' },
    { type: 'priceAlert', label: 'Price Alert', description: 'Price condition trigger', category: 'trigger' },
    { type: 'httpRequest', label: 'HTTP Request', description: 'API request trigger', category: 'trigger' },
  ],
  ACTIONS: [
    { type: 'placeOrder', label: 'Place Order', description: 'Place regular order', category: 'action' },
    { type: 'smartOrder', label: 'Smart Order', description: 'Position-aware order', category: 'action' },
    // ... more nodes
  ],
  CONDITIONS: [...],
  DATA: [...],
  UTILITIES: [...],
}

// Default node data
export const DEFAULT_NODE_DATA: Record<string, any> = {
  start: {
    scheduleType: 'daily',
    time: '09:15',
    days: ['mon', 'tue', 'wed', 'thu', 'fri'],
  },
  placeOrder: {
    symbol: '',
    exchange: 'NSE',
    action: 'BUY',
    quantity: 1,
    product: 'MIS',
    priceType: 'MARKET',
  },
  // ... more defaults
}

// Dropdown options
export const EXCHANGES = ['NSE', 'NFO', 'BSE', 'MCX', 'CDS', 'BFO']
export const PRODUCTS = ['MIS', 'CNC', 'NRML']
export const PRICE_TYPES = ['MARKET', 'LIMIT', 'SL', 'SL-M']
export const OPTIONS_STRATEGIES = ['STRADDLE', 'STRANGLE', 'SPREAD', 'IRON_CONDOR']
export const OPERATORS = ['>', '<', '==', '>=', '<=', '!=']
export const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
```

## UI Component Library

Flow uses **shadcn/ui** components:

| Component | Usage |
|-----------|-------|
| `Input` | Text/number inputs |
| `Select` | Dropdown selections |
| `RadioGroup` | Radio button groups |
| `Switch` | Toggle switches |
| `Tabs` | Tab navigation |
| `Label` | Form labels |
| `Button` | Action buttons |
| `Textarea` | Multi-line text |
| `ToggleGroup` | Multi-select (days) |

## Styling

### Node Styles

```css
/* workflow-node base styles */
.workflow-node {
  @apply bg-background border rounded-lg shadow-sm;
  @apply transition-all duration-200;
}

.workflow-node.selected {
  @apply ring-2 ring-primary;
}

.workflow-node:hover {
  @apply shadow-md;
}

/* Category colors */
.node-trigger { @apply border-green-500/30; }
.node-action { @apply border-blue-500/30; }
.node-condition { @apply border-amber-500/30; }
.node-data { @apply border-purple-500/30; }
.node-utility { @apply border-gray-500/30; }
```

### Icon Styles

```css
.node-icon {
  @apply w-6 h-6 rounded flex items-center justify-center;
}
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `@xyflow/react` | Visual workflow canvas |
| `zustand` | State management |
| `lucide-react` | Icons |
| `@radix-ui/*` | UI primitives |
| `tailwindcss` | Styling |
