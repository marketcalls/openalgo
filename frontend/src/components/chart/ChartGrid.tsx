/**
 * The chart pane grid, and the control that picks its shape.
 *
 * Shared rather than page-local because the arrangement is the part a user
 * recognises between surfaces: the same seven presets, the same glyphs, the
 * same order. The grid itself owns no chart state. It hands each cell an id and
 * asks the caller what to draw in it, so a page can keep a symbol and interval
 * per pane without this file knowing what either of those is.
 */

import { LayoutGrid } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { LAYOUTS, LayoutIcon, type LayoutPreset } from '@/lib/chart/layouts'
import { cn } from '@/lib/utils'

export interface ChartGridProps {
  preset: LayoutPreset
  /** Called once per cell, in order. `paneId` is stable for the preset. */
  renderPane: (paneId: string, index: number) => ReactNode
  className?: string
}

export function ChartGrid({ preset, renderPane, className }: ChartGridProps) {
  return (
    <div
      className={cn('grid min-h-0 flex-1 gap-1 p-1', className)}
      style={{
        gridTemplateColumns: preset.cols,
        gridTemplateRows: preset.rows,
        gridTemplateAreas: preset.areas,
      }}
    >
      {preset.cells.map((cell, index) => (
        // Keyed by the cell name and its position, so switching preset gives a
        // pane that has genuinely moved a new identity and remounts its chart
        // rather than resizing a stale one.
        <div key={`${preset.id}-${cell}`} style={{ gridArea: cell }} className="flex min-h-0">
          {renderPane(cell, index)}
        </div>
      ))}
    </div>
  )
}

export interface ChartLayoutPickerProps {
  layoutId: string
  onChange: (layoutId: string) => void
  className?: string
}

/** The preset chooser, drawn as a grid of previews rather than a text list. */
export function ChartLayoutPicker({ layoutId, onChange, className }: ChartLayoutPickerProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className={cn('h-9 w-9', className)}
          title="Chart layout"
          aria-label="Chart layout"
        >
          <LayoutGrid className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        <div className="grid grid-cols-4 gap-1 p-1">
          {LAYOUTS.map((preset) => (
            <DropdownMenuItem
              key={preset.id}
              onSelect={() => onChange(preset.id)}
              title={preset.label}
              className={cn(
                'flex aspect-square flex-col items-center justify-center gap-1 rounded border',
                preset.id === layoutId
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'text-muted-foreground'
              )}
            >
              <LayoutIcon preset={preset} />
              <span className="font-medium text-[9px]">{preset.cells.length}</span>
            </DropdownMenuItem>
          ))}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
