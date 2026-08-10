import { RotateCcw, Settings2 } from 'lucide-react'
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
  const isColumnVisible = (key: ColumnKey) => visibleColumns.includes(key)

  // Price and Greek columns are listed separately. Both modes draw from the
  // same pool, so either group can be enabled from either mode.
  const groups = [
    { label: 'CALLS Price', side: 'ce', greek: false },
    { label: 'CALLS Greeks', side: 'ce', greek: true },
    { label: 'PUTS Price', side: 'pe', greek: false },
    { label: 'PUTS Greeks', side: 'pe', greek: true },
  ] as const

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="icon" className="h-9 w-9">
          <Settings2 className="h-4 w-4" />
          <span className="sr-only">Column settings</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48 max-h-[70vh] overflow-y-auto">
        {groups.map((group, index) => {
          const columns = COLUMN_DEFINITIONS.filter(
            (col) => col.side === group.side && Boolean(col.isGreek) === group.greek
          )
          if (columns.length === 0) return null

          return (
            <div key={group.label}>
              {index > 0 && <DropdownMenuSeparator />}
              <DropdownMenuLabel>{group.label}</DropdownMenuLabel>
              {columns.map((col) => (
                <DropdownMenuCheckboxItem
                  key={col.key}
                  checked={isColumnVisible(col.key)}
                  onCheckedChange={() => onToggleColumn(col.key)}
                >
                  {col.label}
                </DropdownMenuCheckboxItem>
              ))}
            </div>
          )
        })}

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
