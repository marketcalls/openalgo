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
import { LOGICAL_COLUMNS } from '@/types/option-chain'

interface ColumnConfigDropdownProps {
  visibleColumns: ColumnKey[]
  onToggleColumn: (columnKey: ColumnKey | ColumnKey[]) => void
  onResetToDefaults: () => void
}

export function ColumnConfigDropdown({
  visibleColumns,
  onToggleColumn,
  onResetToDefaults,
}: ColumnConfigDropdownProps) {
  // The chain is mirrored, so each entry covers the CALL and PUT column
  // together. Listing them per side meant unchecking Delta twice to get it off
  // the table, and doubled the length of this menu.
  const groups = [
    { label: 'Price Columns', greek: false },
    { label: 'Greeks', greek: true },
  ] as const

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="icon" className="h-9 w-9">
          <Settings2 className="h-4 w-4" />
          <span className="sr-only">Column settings</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52 max-h-[70vh] overflow-y-auto">
        {groups.map((group, index) => {
          const columns = LOGICAL_COLUMNS.filter((col) => col.isGreek === group.greek)
          if (columns.length === 0) return null

          return (
            <div key={group.label}>
              {index > 0 && <DropdownMenuSeparator />}
              <DropdownMenuLabel>{group.label}</DropdownMenuLabel>
              {columns.map((col) => (
                <DropdownMenuCheckboxItem
                  key={col.label}
                  checked={col.keys.some((key) => visibleColumns.includes(key))}
                  onCheckedChange={() => onToggleColumn(col.keys)}
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
