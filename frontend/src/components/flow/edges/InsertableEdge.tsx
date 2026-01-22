// components/flow/edges/InsertableEdge.tsx
// Custom edge with a "+" button to insert nodes between connected nodes

import { useState, useCallback } from 'react'
import {
  EdgeLabelRenderer,
  getSmoothStepPath,
  useReactFlow,
  type EdgeProps,
} from '@xyflow/react'
import { Plus } from 'lucide-react'
import { cn } from '@/lib/utils'
import { DEFAULT_NODE_DATA } from '@/lib/flow/constants'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

// Node categories for the dropdown menu
const NODE_MENU = {
  Actions: [
    { type: 'placeOrder', label: 'Place Order' },
    { type: 'smartOrder', label: 'Smart Order' },
    { type: 'optionsOrder', label: 'Options Order' },
    { type: 'optionsMultiOrder', label: 'Multi-Leg Options' },
    { type: 'closePositions', label: 'Close Positions' },
    { type: 'cancelAllOrders', label: 'Cancel All' },
  ],
  Logic: [
    { type: 'timeCondition', label: 'Time Condition' },
    { type: 'positionCheck', label: 'Position Check' },
    { type: 'fundCheck', label: 'Fund Check' },
    { type: 'priceCondition', label: 'Price Check' },
    { type: 'timeWindow', label: 'Time Window' },
  ],
  Data: [
    { type: 'getQuote', label: 'Get Quote' },
    { type: 'getDepth', label: 'Get Depth' },
    { type: 'openPosition', label: 'Open Position' },
  ],
  Utility: [
    { type: 'waitUntil', label: 'Wait Until' },
    { type: 'delay', label: 'Delay' },
    { type: 'telegramAlert', label: 'Telegram Alert' },
    { type: 'log', label: 'Log' },
    { type: 'variable', label: 'Variable' },
  ],
}

let nodeIdCounter = 1000

export function InsertableEdge({
  id,
  source,
  target,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  sourceHandleId,
  targetHandleId,
  markerEnd,
  selected,
  animated,
}: EdgeProps) {
  const [isHovered, setIsHovered] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const { setNodes, setEdges, getNodes, getEdges } = useReactFlow()

  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  })

  const insertNode = useCallback(
    (nodeType: string) => {
      const nodes = getNodes()
      const edges = getEdges()

      // Generate unique node ID
      const newNodeId = `node_${Date.now()}_${nodeIdCounter++}`

      // Calculate position (midpoint between source and target)
      const sourceNode = nodes.find((n) => n.id === source)
      const targetNode = nodes.find((n) => n.id === target)

      if (!sourceNode || !targetNode) return

      const newX = (sourceNode.position.x + targetNode.position.x) / 2
      const newY = (sourceNode.position.y + targetNode.position.y) / 2 + 50

      // Get default data for the node type
      const defaultData = DEFAULT_NODE_DATA[nodeType as keyof typeof DEFAULT_NODE_DATA] || {}

      // Create new node
      const newNode = {
        id: newNodeId,
        type: nodeType,
        position: { x: newX, y: newY },
        data: { ...defaultData },
      }

      // Remove the original edge
      const filteredEdges = edges.filter((e) => e.id !== id)

      // Create two new edges: source -> newNode and newNode -> target
      const newEdge1 = {
        id: `edge-${Date.now()}-1`,
        source,
        target: newNodeId,
        sourceHandle: sourceHandleId || undefined,
        type: 'insertable',
        animated: true,
      }

      const newEdge2 = {
        id: `edge-${Date.now()}-2`,
        source: newNodeId,
        target,
        targetHandle: targetHandleId || undefined,
        type: 'insertable',
        animated: true,
      }

      // Update nodes and edges
      setNodes([...nodes, newNode])
      setEdges([...filteredEdges, newEdge1, newEdge2])
      setMenuOpen(false)
    },
    [source, target, sourceHandleId, targetHandleId, id, getNodes, getEdges, setNodes, setEdges]
  )

  return (
    <>
      {/* Render path directly instead of BaseEdge for better control */}
      <path
        d={edgePath}
        fill="none"
        strokeWidth={isHovered || selected ? 3 : 2}
        stroke={isHovered || selected ? '#3b82f6' : '#888888'}
        strokeDasharray={animated ? '5 5' : undefined}
        style={{
          animation: animated ? 'dashdraw 0.5s linear infinite' : undefined,
        }}
        className="react-flow__edge-path"
        markerEnd={markerEnd}
      />
      <EdgeLabelRenderer>
        <div
          className="nodrag nopan pointer-events-auto absolute"
          style={{
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
          }}
          onMouseEnter={() => setIsHovered(true)}
          onMouseLeave={() => !menuOpen && setIsHovered(false)}
        >
          <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className={cn(
                  'flex h-5 w-5 items-center justify-center rounded-full border bg-background shadow-sm transition-all',
                  'hover:scale-110 hover:border-primary hover:bg-primary hover:text-primary-foreground',
                  (isHovered || menuOpen) ? 'opacity-100 scale-100' : 'opacity-0 scale-75',
                  selected && 'opacity-100 scale-100'
                )}
              >
                <Plus className="h-3 w-3" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="center" className="w-48">
              {Object.entries(NODE_MENU).map(([category, nodes]) => (
                <DropdownMenuSub key={category}>
                  <DropdownMenuSubTrigger>
                    <span>{category}</span>
                  </DropdownMenuSubTrigger>
                  <DropdownMenuSubContent>
                    {nodes.map((node) => (
                      <DropdownMenuItem
                        key={node.type}
                        onClick={() => insertNode(node.type)}
                      >
                        {node.label}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </EdgeLabelRenderer>
    </>
  )
}
