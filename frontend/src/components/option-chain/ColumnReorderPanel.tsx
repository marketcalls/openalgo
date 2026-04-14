import { useState } from 'react'
import { GripVertical, Columns3 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogFooter,
  DialogClose,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { ColumnKey } from '@/types/option-chain'
import { COLUMN_DEFINITIONS } from '@/types/option-chain'
import { cn } from '@/lib/utils'

interface ColumnReorderPanelProps {
  columnOrder: ColumnKey[]
  visibleColumns: ColumnKey[]
  onReorderColumns: (newOrder: ColumnKey[]) => void
}

interface DraggableColumnProps {
  columnKey: ColumnKey
  label: string
  side: 'ce' | 'pe'
  isVisible: boolean
  isDragging: boolean
  onDragStart: (e: React.DragEvent, key: ColumnKey) => void
  onDragOver: (e: React.DragEvent) => void
  onDrop: (e: React.DragEvent, key: ColumnKey) => void
  onDragEnd: () => void
}

function DraggableColumn({
  columnKey,
  label,
  side,
  isVisible,
  isDragging,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
}: DraggableColumnProps) {
  return (
    <div
      draggable
      onDragStart={(e) => onDragStart(e, columnKey)}
      onDragOver={onDragOver}
      onDrop={(e) => onDrop(e, columnKey)}
      onDragEnd={onDragEnd}
      className={cn(
        'flex items-center gap-2 rounded-md border px-3 py-2 cursor-grab active:cursor-grabbing transition-all',
        isDragging && 'opacity-50 border-dashed',
        isVisible ? 'bg-card' : 'bg-muted/50 opacity-60',
        side === 'ce' ? 'border-l-2 border-l-green-500' : 'border-r-2 border-r-red-500'
      )}
    >
      <GripVertical className="h-4 w-4 text-muted-foreground flex-shrink-0" />
      <span className="text-sm flex-1">{label}</span>
      <span className={cn(
        'text-xs px-1.5 py-0.5 rounded',
        side === 'ce' ? 'bg-green-500/10 text-green-500' : 'bg-red-500/10 text-red-500'
      )}>
        {side === 'ce' ? 'CE' : 'PE'}
      </span>
    </div>
  )
}

export function ColumnReorderPanel({
  columnOrder,
  visibleColumns,
  onReorderColumns,
}: ColumnReorderPanelProps) {
  const [localOrder, setLocalOrder] = useState<ColumnKey[]>(columnOrder)
  const [draggedItem, setDraggedItem] = useState<ColumnKey | null>(null)
  const [open, setOpen] = useState(false)

  // Filter out strike column - it's always in the center
  const ceColumns = localOrder.filter(key => {
    const col = COLUMN_DEFINITIONS.find(c => c.key === key)
    return col?.side === 'ce'
  })

  const peColumns = localOrder.filter(key => {
    const col = COLUMN_DEFINITIONS.find(c => c.key === key)
    return col?.side === 'pe'
  })

  const getColumnLabel = (key: ColumnKey): string => {
    const col = COLUMN_DEFINITIONS.find(c => c.key === key)
    return col?.label ?? key
  }

  const getColumnSide = (key: ColumnKey): 'ce' | 'pe' => {
    const col = COLUMN_DEFINITIONS.find(c => c.key === key)
    return col?.side === 'pe' ? 'pe' : 'ce'
  }

  const handleDragStart = (e: React.DragEvent, key: ColumnKey) => {
    setDraggedItem(key)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', key)
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }

  const handleDrop = (e: React.DragEvent, targetKey: ColumnKey) => {
    e.preventDefault()
    if (!draggedItem || draggedItem === targetKey) {
      return
    }

    // Only allow reordering within the same side (CE or PE)
    const draggedSide = getColumnSide(draggedItem)
    const targetSide = getColumnSide(targetKey)

    if (draggedSide !== targetSide) {
      return
    }

    const newOrder = [...localOrder]
    const draggedIndex = newOrder.indexOf(draggedItem)
    const targetIndex = newOrder.indexOf(targetKey)

    newOrder.splice(draggedIndex, 1)
    newOrder.splice(targetIndex, 0, draggedItem)

    setLocalOrder(newOrder)
  }

  const handleDragEnd = () => {
    setDraggedItem(null)
  }

  const handleSave = () => {
    onReorderColumns(localOrder)
    setOpen(false)
  }

  const handleOpenChange = (isOpen: boolean) => {
    setOpen(isOpen)
    if (isOpen) {
      setLocalOrder(columnOrder)
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" size="icon" className="h-9 w-9">
          <Columns3 className="h-4 w-4" />
          <span className="sr-only">Reorder columns</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Reorder Columns</DialogTitle>
          <DialogDescription>
            Drag columns to reorder them. CE and PE columns can only be reordered within their respective sections.
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <h4 className="text-sm font-medium mb-2 text-green-500">CALLS (CE)</h4>
            <ScrollArea className="h-64 pr-2">
              <div className="space-y-1.5">
                {ceColumns.map(key => (
                  <DraggableColumn
                    key={key}
                    columnKey={key}
                    label={getColumnLabel(key)}
                    side="ce"
                    isVisible={visibleColumns.includes(key)}
                    isDragging={draggedItem === key}
                    onDragStart={handleDragStart}
                    onDragOver={handleDragOver}
                    onDrop={handleDrop}
                    onDragEnd={handleDragEnd}
                  />
                ))}
              </div>
            </ScrollArea>
          </div>

          <div>
            <h4 className="text-sm font-medium mb-2 text-red-500">PUTS (PE)</h4>
            <ScrollArea className="h-64 pr-2">
              <div className="space-y-1.5">
                {peColumns.map(key => (
                  <DraggableColumn
                    key={key}
                    columnKey={key}
                    label={getColumnLabel(key)}
                    side="pe"
                    isVisible={visibleColumns.includes(key)}
                    isDragging={draggedItem === key}
                    onDragStart={handleDragStart}
                    onDragOver={handleDragOver}
                    onDrop={handleDrop}
                    onDragEnd={handleDragEnd}
                  />
                ))}
              </div>
            </ScrollArea>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <DialogClose asChild>
            <Button variant="outline">Cancel</Button>
          </DialogClose>
          <Button onClick={handleSave}>Save Order</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
