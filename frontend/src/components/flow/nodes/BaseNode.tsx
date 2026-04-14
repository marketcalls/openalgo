/**
 * Base Node Component
 * Provides shared styling and structure for all workflow nodes
 */

import { memo, type ReactNode } from 'react'
import { Handle, Position } from '@xyflow/react'
import { cn } from '@/lib/utils'

export type NodeCategory = 'trigger' | 'action' | 'condition' | 'data' | 'utility'

interface BaseNodeProps {
  /** Node category for styling */
  category: NodeCategory
  /** Whether the node is selected */
  selected?: boolean
  /** Icon component */
  icon: ReactNode
  /** Node title */
  title: string
  /** Subtitle (e.g., exchange name) */
  subtitle?: string
  /** Whether to show input handle */
  hasInput?: boolean
  /** Whether to show output handle */
  hasOutput?: boolean
  /** Whether to show true/false outputs (for conditions) */
  hasConditionalOutputs?: boolean
  /** Node body content */
  children?: ReactNode
  /** Additional class names */
  className?: string
  /** Minimum width */
  minWidth?: number
}

const categoryStyles: Record<NodeCategory, { border: string; iconBg: string }> = {
  trigger: {
    border: 'border-l-node-trigger',
    iconBg: 'bg-node-trigger/20 text-node-trigger',
  },
  action: {
    border: 'border-l-node-action',
    iconBg: 'bg-node-action/20 text-node-action',
  },
  condition: {
    border: 'border-l-node-condition',
    iconBg: 'bg-node-condition/20 text-node-condition',
  },
  data: {
    border: 'border-l-[hsl(var(--primary))]',
    iconBg: 'bg-primary/20 text-primary',
  },
  utility: {
    border: 'border-l-muted-foreground',
    iconBg: 'bg-muted text-muted-foreground',
  },
}

export const BaseNode = memo(function BaseNode({
  category,
  selected,
  icon,
  title,
  subtitle,
  hasInput = false,
  hasOutput = true,
  hasConditionalOutputs = false,
  children,
  className,
  minWidth = 120,
}: BaseNodeProps) {
  const styles = categoryStyles[category]

  return (
    <div
      className={cn(
        'workflow-node rounded-lg border border-border bg-card',
        'border-l-2',
        styles.border,
        selected && 'ring-2 ring-primary ring-offset-2 ring-offset-background',
        className
      )}
      style={{ minWidth }}
    >
      {/* Input Handle */}
      {hasInput && (
        <Handle
          type="target"
          position={Position.Top}
          className="!top-0 !h-3 !w-3 !-translate-y-1/2 !rounded-full !border-2 !border-background !bg-muted-foreground"
        />
      )}

      {/* Node Content */}
      <div className="p-2">
        {/* Header */}
        <div className="mb-1.5 flex items-center gap-1.5">
          <div
            className={cn(
              'flex h-5 w-5 items-center justify-center rounded',
              styles.iconBg
            )}
          >
            {icon}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-xs font-medium leading-tight">
              {title}
            </div>
            {subtitle && (
              <div className="truncate text-[9px] text-muted-foreground">
                {subtitle}
              </div>
            )}
          </div>
        </div>

        {/* Body */}
        {children && <div className="space-y-1">{children}</div>}
      </div>

      {/* Output Handle(s) */}
      {hasConditionalOutputs ? (
        <>
          {/* True output (left) */}
          <Handle
            type="source"
            position={Position.Bottom}
            id="true"
            className="!bottom-0 !left-1/4 !h-3 !w-3 !translate-y-1/2 !rounded-full !border-2 !border-background !bg-buy"
          />
          {/* False output (right) */}
          <Handle
            type="source"
            position={Position.Bottom}
            id="false"
            className="!bottom-0 !left-3/4 !h-3 !w-3 !translate-y-1/2 !rounded-full !border-2 !border-background !bg-sell"
          />
        </>
      ) : hasOutput ? (
        <Handle
          type="source"
          position={Position.Bottom}
          className="!bottom-0 !h-3 !w-3 !translate-y-1/2 !rounded-full !border-2 !border-background !bg-muted-foreground"
        />
      ) : null}
    </div>
  )
})

/**
 * Node Data Row - Displays a label/value pair
 */
interface NodeDataRowProps {
  label: string
  value: string | number | undefined
  mono?: boolean
}

export function NodeDataRow({ label, value, mono = true }: NodeDataRowProps) {
  return (
    <div className="flex items-center justify-between rounded bg-muted/50 px-1.5 py-1">
      <span className="text-[10px] text-muted-foreground">{label}</span>
      <span
        className={cn(
          'text-[10px] font-medium',
          mono && 'font-mono'
        )}
      >
        {value ?? '-'}
      </span>
    </div>
  )
}

/**
 * Node Badge - Displays BUY/SELL or other status badges
 */
interface NodeBadgeProps {
  variant: 'buy' | 'sell' | 'default'
  children: ReactNode
}

export function NodeBadge({ variant, children }: NodeBadgeProps) {
  return (
    <span
      className={cn(
        'rounded px-1 py-0.5 text-[9px] font-semibold',
        variant === 'buy' && 'bg-buy/20 text-buy',
        variant === 'sell' && 'bg-sell/20 text-sell',
        variant === 'default' && 'bg-muted text-muted-foreground'
      )}
    >
      {children}
    </span>
  )
}

/**
 * Node Info Row - Simple inline info display
 */
interface NodeInfoRowProps {
  items: Array<{ label?: string; value: string | number | undefined }>
}

export function NodeInfoRow({ items }: NodeInfoRowProps) {
  return (
    <div className="flex items-center justify-between text-[9px] text-muted-foreground">
      {items.map((item, i) => (
        <span key={i}>
          {item.label && `${item.label}: `}
          {item.value ?? '-'}
        </span>
      ))}
    </div>
  )
}
