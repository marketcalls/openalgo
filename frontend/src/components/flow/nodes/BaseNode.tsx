// components/flow/nodes/BaseNode.tsx
// Base node component used as placeholder until specific nodes are implemented

import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import { NODE_DEFINITIONS } from '@/lib/flow/constants'
import { useFlowWorkflowStore } from '@/stores/flowWorkflowStore'
import { cn } from '@/lib/utils'

// Get node info from definitions
function getNodeInfo(nodeType: string) {
  for (const category of Object.values(NODE_DEFINITIONS)) {
    const node = category.find(n => n.type === nodeType)
    if (node) return node
  }
  return null
}

// Get category color based on node type
function getCategoryColor(nodeType: string): string {
  // Triggers - Orange
  if (['start', 'priceAlert', 'webhookTrigger'].includes(nodeType)) {
    return 'border-orange-500/50 bg-orange-500/5'
  }
  // Actions - Blue
  if (['placeOrder', 'smartOrder', 'optionsOrder', 'optionsMultiOrder', 'basketOrder', 'splitOrder', 'modifyOrder'].includes(nodeType)) {
    return 'border-blue-500/50 bg-blue-500/5'
  }
  // Cancel/Close - Red
  if (['cancelOrder', 'cancelAllOrders', 'closePositions'].includes(nodeType)) {
    return 'border-red-500/50 bg-red-500/5'
  }
  // Conditions - Purple
  if (['timeCondition', 'positionCheck', 'fundCheck', 'priceCondition', 'timeWindow', 'andGate', 'orGate', 'notGate'].includes(nodeType)) {
    return 'border-purple-500/50 bg-purple-500/5'
  }
  // Data - Cyan
  if (['getQuote', 'getDepth', 'history', 'multiQuotes'].includes(nodeType)) {
    return 'border-cyan-500/50 bg-cyan-500/5'
  }
  // Options - Pink
  if (['optionSymbol', 'optionChain', 'syntheticFuture', 'expiry'].includes(nodeType)) {
    return 'border-pink-500/50 bg-pink-500/5'
  }
  // Streaming - Green
  if (['subscribeLtp', 'subscribeQuote', 'subscribeDepth', 'unsubscribe'].includes(nodeType)) {
    return 'border-green-500/50 bg-green-500/5'
  }
  // Default
  return 'border-border bg-card'
}

interface BaseNodeData {
  label?: string
  [key: string]: unknown
}

function BaseNodeComponent({ id, type, data, selected }: NodeProps) {
  const nodeInfo = getNodeInfo(type || '')
  const nodeData = data as BaseNodeData
  const { selectedNodeId } = useFlowWorkflowStore()

  const isSelected = selected || selectedNodeId === id
  const colorClass = getCategoryColor(type || '')

  const displayLabel = nodeData.label || nodeInfo?.label || type

  return (
    <div
      className={cn(
        'min-w-[140px] rounded-lg border-2 px-3 py-2 shadow-sm transition-all',
        colorClass,
        isSelected && 'ring-2 ring-primary ring-offset-2 ring-offset-background'
      )}
    >
      {/* Input Handle */}
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-primary !border-background !w-3 !h-3"
      />

      {/* Node Content */}
      <div className="text-center">
        <div className="text-xs font-medium truncate">{displayLabel}</div>
        {nodeInfo && (
          <div className="text-[10px] text-muted-foreground truncate mt-0.5">
            {nodeInfo.description}
          </div>
        )}
      </div>

      {/* Output Handle */}
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-primary !border-background !w-3 !h-3"
      />
    </div>
  )
}

export const BaseNode = memo(BaseNodeComponent)
