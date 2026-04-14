/**
 * Variable Node
 * Store, calculate, and manipulate variables in workflow
 * Supports: set, get, add, subtract, multiply, divide, parse JSON
 */

import { memo } from 'react'
import { Handle, Position } from '@xyflow/react'
import { Variable } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { VariableNodeData } from '@/types/flow'

interface VariableNodeProps {
  data: VariableNodeData
  selected?: boolean
}

const operationLabels: Record<string, string> = {
  set: '=',
  get: 'GET',
  add: '+',
  subtract: '-',
  multiply: '*',
  divide: '/',
  parse_json: 'JSON',
  stringify: 'STR',
  increment: '++',
  decrement: '--',
  append: '+=',
}

const operationDescriptions: Record<string, string> = {
  set: 'Set Value',
  get: 'Get Value',
  add: 'Add',
  subtract: 'Subtract',
  multiply: 'Multiply',
  divide: 'Divide',
  parse_json: 'Parse JSON',
  stringify: 'To String',
  increment: 'Increment',
  decrement: 'Decrement',
  append: 'Append',
}

export const VariableNode = memo(({ data, selected }: VariableNodeProps) => {
  const displayValue = typeof data.value === 'object'
    ? `${JSON.stringify(data.value).slice(0, 20)}...`
    : String(data.value || '').slice(0, 20)

  return (
    <div
      className={cn(
        'workflow-node node-utility min-w-[120px]',
        selected && 'selected'
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!top-0 !-translate-y-1/2"
      />
      <div className="p-2">
        <div className="mb-1.5 flex items-center gap-1.5">
          <div className="node-icon flex h-5 w-5 items-center justify-center rounded">
            <Variable className="h-3 w-3" />
          </div>
          <div>
            <div className="text-xs font-medium leading-tight">Variable</div>
            <div className="text-[9px] text-muted-foreground">
              {operationDescriptions[data.operation] || 'Set'}
            </div>
          </div>
        </div>
        <div className="space-y-1">
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">Name</span>
            <span className="mono-data text-[10px] font-medium text-primary">
              {data.variableName || 'var'}
            </span>
          </div>
          <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
            <span className="text-[10px] text-muted-foreground">
              {operationLabels[data.operation] || '='}
            </span>
            <span className="mono-data text-[10px] font-medium">
              {displayValue || '-'}
            </span>
          </div>
        </div>
        <div className="mt-1.5 text-center text-[8px] text-muted-foreground">
          Use: {`{{${data.variableName || 'var'}}}`}
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bottom-0 !translate-y-1/2"
      />
    </div>
  )
})

VariableNode.displayName = 'VariableNode'
