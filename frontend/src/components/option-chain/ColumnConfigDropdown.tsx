import { Settings2, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { ColumnKey } from '@/types/option-chain'
import { COLUMN_DEFINITIONS } from '@/types/option-chain'

interface ColumnConfigDropdownProps {
  visibleColumns: ColumnKey[]
  onToggleColumn: (columnKey: ColumnKey) => void
  onResetToDefaults: () => void
}

export function ColumnConfigDropdown({
  visibleColumns,
  onToggleColumn,
  onResetToDefaults,
}: ColumnConfigDropdownProps) {
  const ceColumns = COLUMN_DEFINITIONS.filter(col => col.side === 'ce')
  const peColumns = COLUMN_DEFINITIONS.filter(col => col.side === 'pe')

  const isColumnVisible = (key: ColumnKey) => visibleColumns.includes(key)

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="icon" className="h-9 w-9">
          <Settings2 className="h-4 w-4" />
          <span className="sr-only">Column settings</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        <DropdownMenuLabel>CALLS Columns</DropdownMenuLabel>
        {ceColumns.map(col => (
          <DropdownMenuCheckboxItem
            key={col.key}
            checked={isColumnVisible(col.key)}
            onCheckedChange={() => onToggleColumn(col.key)}
          >
            {col.label}
          </DropdownMenuCheckboxItem>
        ))}

        <DropdownMenuSeparator />

        <DropdownMenuLabel>PUTS Columns</DropdownMenuLabel>
        {peColumns.map(col => (
          <DropdownMenuCheckboxItem
            key={col.key}
            checked={isColumnVisible(col.key)}
            onCheckedChange={() => onToggleColumn(col.key)}
          >
            {col.label}
          </DropdownMenuCheckboxItem>
        ))}

        <DropdownMenuSeparator />

        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start px-2"
          onClick={onResetToDefaults}
        >
          <RotateCcw className="mr-2 h-4 w-4" />
          Reset to Defaults
        </Button>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
