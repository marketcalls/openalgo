# Flow Node Creation Guide

This guide explains how to create new nodes for the Flow visual workflow builder.

## Overview

Adding a new node requires changes in both the frontend (React component) and backend (Python executor). Each node needs:

1. **TypeScript interface** - Data structure definition
2. **React component** - Visual representation
3. **Node registration** - Export and register in node types
4. **Constants** - Default values and metadata
5. **Config panel UI** - Configuration form
6. **Backend executor** - Execution logic

## Directory Structure

```
frontend/src/
├── types/
│   └── flow.ts                    # TypeScript interfaces
├── lib/flow/
│   └── constants.ts               # Node definitions & defaults
├── components/flow/
│   ├── nodes/
│   │   ├── index.ts               # Node type registry
│   │   ├── BaseNode.tsx           # Base component
│   │   └── YourNewNode.tsx        # Your new node
│   └── panels/
│       └── ConfigPanel.tsx        # Configuration UI

services/
└── flow_executor_service.py       # Backend execution
```

## Step 1: Define TypeScript Interface

**File:** `frontend/src/types/flow.ts`

```typescript
// Add your node data interface
export interface YourNewNodeData {
  label?: string
  symbol?: string
  exchange?: string
  threshold?: number
  action?: 'BUY' | 'SELL'
  outputVariable?: string  // For storing results
}

// Add to the appropriate union type
export type ActionNodeData =
  | PlaceOrderNodeData
  | SmartOrderNodeData
  | YourNewNodeData  // Add here
  // ...
```

### Common Field Patterns

```typescript
// For nodes that fetch data and store in variable
outputVariable?: string

// For trading nodes
symbol?: string
exchange?: string  // NSE, NFO, BSE, etc.
action?: 'BUY' | 'SELL'
quantity?: number
product?: 'MIS' | 'CNC' | 'NRML'
priceType?: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'

// For condition nodes
operator?: '>' | '<' | '==' | '>=' | '<=' | '!='
value?: number

// For time-based nodes
time?: string  // HH:MM format
days?: string[]  // ['mon', 'tue', ...]
```

## Step 2: Create React Component

**File:** `frontend/src/components/flow/nodes/YourNewNode.tsx`

### Using BaseNode (Recommended)

```typescript
import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { YourIcon } from 'lucide-react'
import { BaseNode, NodeDataRow, NodeBadge } from './BaseNode'
import type { YourNewNodeData } from '@/types/flow'

interface YourNewNodeProps extends NodeProps {
  data: YourNewNodeData
}

export const YourNewNode = memo(({ data, selected }: YourNewNodeProps) => {
  return (
    <BaseNode
      category="action"  // trigger | action | condition | data | utility
      icon={<YourIcon className="h-3 w-3" />}
      title="Your Node"
      subtitle={data.symbol || 'Configure symbol'}
      hasInput={true}
      hasOutput={true}
      hasConditionalOutputs={false}  // true for condition nodes
    >
      {/* Display configured values */}
      {data.symbol && (
        <NodeDataRow label="Symbol" value={data.symbol} />
      )}
      {data.exchange && (
        <NodeDataRow label="Exchange" value={data.exchange} />
      )}
      {data.action && (
        <NodeBadge variant={data.action === 'BUY' ? 'buy' : 'sell'}>
          {data.action}
        </NodeBadge>
      )}
    </BaseNode>
  )
})

YourNewNode.displayName = 'YourNewNode'
```

### Manual Implementation (Full Control)

```typescript
import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { YourIcon } from 'lucide-react'
import type { YourNewNodeData } from '@/types/flow'

interface YourNewNodeProps extends NodeProps {
  data: YourNewNodeData
}

export const YourNewNode = memo(({ data, selected }: YourNewNodeProps) => {
  return (
    <div className={`workflow-node ${selected ? 'selected' : ''}`}>
      {/* Input handle */}
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-primary !w-2 !h-2"
      />

      {/* Node content */}
      <div className="p-2 min-w-[140px]">
        {/* Header */}
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="node-icon bg-blue-500/10 text-blue-500">
            <YourIcon className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium">Your Node</div>
            <div className="text-[9px] text-muted-foreground">
              {data.symbol || 'Configure'}
            </div>
          </div>
        </div>

        {/* Data display */}
        <div className="space-y-0.5 text-[10px]">
          {data.symbol && (
            <div className="flex justify-between">
              <span className="text-muted-foreground">Symbol</span>
              <span className="font-mono">{data.symbol}</span>
            </div>
          )}
        </div>
      </div>

      {/* Output handle */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-primary !w-2 !h-2"
      />
    </div>
  )
})

YourNewNode.displayName = 'YourNewNode'
```

### Conditional Node (True/False Outputs)

```typescript
export const YourConditionNode = memo(({ data, selected }: Props) => {
  return (
    <BaseNode
      category="condition"
      icon={<GitBranch className="h-3 w-3" />}
      title="Your Condition"
      hasInput={true}
      hasConditionalOutputs={true}  // Adds true/false handles
    >
      {/* Content */}
    </BaseNode>
  )
})
```

## Step 3: Register the Node

**File:** `frontend/src/components/flow/nodes/index.ts`

```typescript
// Import your node
import { YourNewNode } from './YourNewNode'

// Export it
export { YourNewNode }

// Add to nodeTypes registry
export const nodeTypes = {
  // ... existing nodes
  yourNewNode: YourNewNode,
} as const
```

## Step 4: Add Constants

**File:** `frontend/src/lib/flow/constants.ts`

### Node Definition (for palette)

```typescript
export const NODE_DEFINITIONS = {
  ACTIONS: [
    // ... existing
    {
      type: 'yourNewNode',
      label: 'Your Node',
      description: 'Brief description of what it does',
      category: 'action',
    },
  ],
  // Or add to appropriate category:
  // TRIGGERS, CONDITIONS, DATA, UTILITIES
}
```

### Default Data

```typescript
export const DEFAULT_NODE_DATA: Record<string, unknown> = {
  // ... existing
  yourNewNode: {
    label: '',
    symbol: '',
    exchange: 'NSE',
    threshold: 0,
    action: 'BUY',
    outputVariable: '',
  },
}
```

## Step 5: Add Config Panel UI

**File:** `frontend/src/components/flow/panels/ConfigPanel.tsx`

Add a section for your node type:

```typescript
{nodeType === 'yourNewNode' && (
  <>
    {/* Symbol input */}
    <div className="space-y-2">
      <Label className="text-xs">Symbol</Label>
      <Input
        className="h-8"
        placeholder="RELIANCE"
        value={(nodeData.symbol as string) || ''}
        onChange={(e) => handleDataChange('symbol', e.target.value)}
      />
    </div>

    {/* Exchange dropdown */}
    <div className="space-y-2">
      <Label className="text-xs">Exchange</Label>
      <Select
        value={(nodeData.exchange as string) || 'NSE'}
        onValueChange={(value) => handleDataChange('exchange', value)}
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

    {/* Action radio buttons */}
    <div className="space-y-2">
      <Label className="text-xs">Action</Label>
      <RadioGroup
        value={(nodeData.action as string) || 'BUY'}
        onValueChange={(value) => handleDataChange('action', value)}
        className="flex gap-4"
      >
        <div className="flex items-center space-x-2">
          <RadioGroupItem value="BUY" id="buy" />
          <Label htmlFor="buy" className="text-xs">BUY</Label>
        </div>
        <div className="flex items-center space-x-2">
          <RadioGroupItem value="SELL" id="sell" />
          <Label htmlFor="sell" className="text-xs">SELL</Label>
        </div>
      </RadioGroup>
    </div>

    {/* Number input */}
    <div className="space-y-2">
      <Label className="text-xs">Threshold</Label>
      <Input
        type="number"
        className="h-8"
        placeholder="100"
        value={(nodeData.threshold as number) || ''}
        onChange={(e) => handleDataChange('threshold', parseFloat(e.target.value) || 0)}
      />
    </div>

    {/* Output variable */}
    <div className="space-y-2">
      <Label className="text-xs">Store Result In</Label>
      <Input
        className="h-8"
        placeholder="result"
        value={(nodeData.outputVariable as string) || ''}
        onChange={(e) => handleDataChange('outputVariable', e.target.value)}
      />
      <p className="text-[10px] text-muted-foreground">
        Access with {'{{result}}'} in other nodes
      </p>
    </div>
  </>
)}
```

### Common UI Components

```typescript
// Text input
<Input
  className="h-8"
  placeholder="Example"
  value={(nodeData.field as string) || ''}
  onChange={(e) => handleDataChange('field', e.target.value)}
/>

// Number input
<Input
  type="number"
  step="0.01"
  className="h-8"
  value={(nodeData.field as number) || ''}
  onChange={(e) => handleDataChange('field', parseFloat(e.target.value))}
/>

// Select dropdown
<Select
  value={(nodeData.field as string) || 'default'}
  onValueChange={(value) => handleDataChange('field', value)}
>
  <SelectTrigger className="h-8">
    <SelectValue />
  </SelectTrigger>
  <SelectContent>
    <SelectItem value="opt1">Option 1</SelectItem>
    <SelectItem value="opt2">Option 2</SelectItem>
  </SelectContent>
</Select>

// Checkbox/Switch
<div className="flex items-center space-x-2">
  <Switch
    checked={(nodeData.enabled as boolean) || false}
    onCheckedChange={(checked) => handleDataChange('enabled', checked)}
  />
  <Label className="text-xs">Enable feature</Label>
</div>

// Multi-select (days of week)
<ToggleGroup
  type="multiple"
  value={(nodeData.days as string[]) || []}
  onValueChange={(value) => handleDataChange('days', value)}
  className="flex flex-wrap gap-1"
>
  {['mon', 'tue', 'wed', 'thu', 'fri'].map((day) => (
    <ToggleGroupItem
      key={day}
      value={day}
      className="h-6 px-2 text-xs"
    >
      {day.toUpperCase()}
    </ToggleGroupItem>
  ))}
</ToggleGroup>

// Textarea
<Textarea
  className="min-h-[60px] text-xs"
  placeholder="Enter message..."
  value={(nodeData.message as string) || ''}
  onChange={(e) => handleDataChange('message', e.target.value)}
/>
```

## Step 6: Add Backend Executor

**File:** `services/flow_executor_service.py`

### Add Execution Method

```python
class NodeExecutor:
    # ... existing methods

    def execute_your_new_node(self, node_data: dict) -> dict:
        """Execute your new node"""
        # Get node parameters with interpolation
        symbol = self.context.interpolate(self.get_str(node_data, "symbol"))
        exchange = self.get_str(node_data, "exchange", "NSE")
        threshold = self.get_float(node_data, "threshold", 0)
        action = self.get_str(node_data, "action", "BUY")

        # Validate required fields
        if not symbol:
            return {"status": "error", "message": "Symbol is required"}

        # Execute your logic
        try:
            # Example: fetch data
            quote = self.client.get_quote(symbol, exchange)
            ltp = quote.get("data", {}).get("ltp", 0)

            # Example: conditional logic
            if ltp > threshold:
                result = self.client.place_order(
                    symbol=symbol,
                    exchange=exchange,
                    action=action,
                    quantity=1,
                    price_type="MARKET",
                    product="MIS"
                )
            else:
                result = {"status": "skipped", "message": f"LTP {ltp} <= threshold {threshold}"}

            # Store result in output variable if specified
            self.store_output(node_data, result)

            return result

        except Exception as e:
            self.log(f"Error in your_new_node: {str(e)}", "error")
            return {"status": "error", "message": str(e)}
```

### Register in Node Chain Executor

```python
def execute_node_chain(node_id, nodes, edge_map, executor, context, ...):
    # ... existing code

    # Add your node type
    elif node_type == "yourNewNode":
        result = executor.execute_your_new_node(node_data)

    # ... rest of code
```

### Helper Methods

```python
class NodeExecutor:
    def get_str(self, data: dict, key: str, default: str = "") -> str:
        """Get string value from node data"""
        return str(data.get(key, default) or default)

    def get_int(self, data: dict, key: str, default: int = 0) -> int:
        """Get integer value from node data"""
        try:
            return int(data.get(key, default) or default)
        except (ValueError, TypeError):
            return default

    def get_float(self, data: dict, key: str, default: float = 0.0) -> float:
        """Get float value from node data"""
        try:
            return float(data.get(key, default) or default)
        except (ValueError, TypeError):
            return default

    def get_bool(self, data: dict, key: str, default: bool = False) -> bool:
        """Get boolean value from node data"""
        return bool(data.get(key, default))

    def store_output(self, node_data: dict, result: dict):
        """Store result in output variable"""
        output_var = node_data.get("outputVariable")
        if output_var:
            self.context.set_variable(output_var, result)

    def log(self, message: str, level: str = "info"):
        """Add log entry"""
        self.logs.append({
            "time": datetime.now().isoformat(),
            "message": message,
            "level": level
        })
```

### Condition Node Pattern

```python
def execute_your_condition_node(self, node_data: dict, node_id: str) -> dict:
    """Execute condition node - returns True/False for branching"""
    value = self.get_float(node_data, "value")
    operator = self.get_str(node_data, "operator", ">")
    threshold = self.get_float(node_data, "threshold")

    # Evaluate condition
    result = False
    if operator == ">":
        result = value > threshold
    elif operator == "<":
        result = value < threshold
    elif operator == "==":
        result = value == threshold
    # ... more operators

    # Store condition result for edge routing
    self.context.set_condition_result(node_id, result)

    self.log(f"Condition: {value} {operator} {threshold} = {result}")
    return {"result": result}
```

## Variable Interpolation

The `WorkflowContext` supports variable interpolation with `{{variableName}}` syntax:

### Built-in Variables

| Variable | Description |
|----------|-------------|
| `{{timestamp}}` | Current ISO timestamp |
| `{{date}}` | Current date (YYYY-MM-DD) |
| `{{time}}` | Current time (HH:MM:SS) |
| `{{hour}}` | Current hour |
| `{{minute}}` | Current minute |
| `{{weekday}}` | Day name (Monday, etc.) |

### User Variables

Set via Variable node or `outputVariable` field:

```python
# In your executor
self.context.set_variable("myResult", {"ltp": 100.50})

# Access in other nodes
symbol = self.context.interpolate("{{myResult.ltp}}")  # "100.5"
```

### Nested Access

```python
# If variable contains: {"data": {"ltp": 100, "volume": 5000}}
self.context.interpolate("{{quote.data.ltp}}")  # "100"
```

## Complete Example: ATR Stop-Loss Node

### 1. TypeScript Interface

```typescript
export interface AtrStopLossNodeData {
  label?: string
  symbol?: string
  exchange?: string
  period?: number
  multiplier?: number
  action?: 'BUY' | 'SELL'
  outputVariable?: string
}
```

### 2. React Component

```typescript
export const AtrStopLossNode = memo(({ data, selected }: Props) => {
  return (
    <BaseNode
      category="data"
      icon={<TrendingDown className="h-3 w-3" />}
      title="ATR Stop-Loss"
      subtitle={data.symbol || 'Configure'}
      hasInput={true}
      hasOutput={true}
    >
      {data.symbol && <NodeDataRow label="Symbol" value={data.symbol} />}
      {data.period && <NodeDataRow label="Period" value={data.period} />}
      {data.multiplier && <NodeDataRow label="Multiplier" value={`${data.multiplier}x`} />}
    </BaseNode>
  )
})
```

### 3. Backend Executor

```python
def execute_atr_stop_loss(self, node_data: dict) -> dict:
    symbol = self.context.interpolate(self.get_str(node_data, "symbol"))
    exchange = self.get_str(node_data, "exchange", "NSE")
    period = self.get_int(node_data, "period", 14)
    multiplier = self.get_float(node_data, "multiplier", 2.0)
    action = self.get_str(node_data, "action", "BUY")

    # Fetch historical data
    history = self.client.get_history(symbol, exchange, "D", days=period + 5)
    df = pd.DataFrame(history.get("data", []))

    # Calculate ATR
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift())
    low_close = abs(df['low'] - df['close'].shift())
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = true_range.rolling(window=period).mean().iloc[-1]

    # Calculate stop-loss
    ltp = df['close'].iloc[-1]
    if action == "BUY":
        stop_loss = ltp - (atr * multiplier)
    else:
        stop_loss = ltp + (atr * multiplier)

    result = {
        "symbol": symbol,
        "ltp": ltp,
        "atr": round(atr, 2),
        "stop_loss": round(stop_loss, 2),
        "action": action
    }

    self.store_output(node_data, result)
    self.log(f"ATR Stop-Loss: {symbol} ATR={atr:.2f} SL={stop_loss:.2f}")

    return result
```

## Testing Your Node

1. **Frontend**: Run `npm run dev` in `/frontend`
2. **Check palette**: Your node should appear in the appropriate category
3. **Drag to canvas**: Verify it renders correctly
4. **Configure**: Test the config panel inputs
5. **Execute**: Create a simple workflow and test execution
6. **Check logs**: Verify execution logs show expected output

## Best Practices

1. **Use BaseNode** for consistent styling
2. **Memoize components** with `memo()` for performance
3. **Validate inputs** in backend executor
4. **Log meaningful messages** for debugging
5. **Store results** in outputVariable for chaining
6. **Handle errors gracefully** with try/catch
7. **Support interpolation** for dynamic values
8. **Add helpful placeholders** in config panel
