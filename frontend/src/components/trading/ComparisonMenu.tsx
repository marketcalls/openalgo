import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { SearchRow, TerminalComparisonState } from '@/lib/trading/terminal'
import { SymbolSearchDialog } from './SymbolSearchDialog'

interface Props {
  state: TerminalComparisonState
  search(query: string, exchange?: string, limit?: number): Promise<SearchRow[]>
  onAdd(symbol: string, exchange: string): Promise<void>
  onRemove(id: string): void
  onModeChange(mode: 'price' | 'percentage'): void
  disabled?: boolean
  container?: HTMLElement | null
}

export function ComparisonMenu({
  state,
  search,
  onAdd,
  onRemove,
  onModeChange,
  disabled = false,
  container,
}: Props) {
  const [open, setOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  useEffect(() => {
    if (disabled) {
      setOpen(false)
      setSearchOpen(false)
    }
  }, [disabled])
  const add = useCallback(
    (row: SearchRow) => {
      if (disabled || row.expression) return
      setSearchOpen(false)
      setOpen(true)
      setError(null)
      void onAdd(row.symbol, String(row.exchange)).catch((cause: unknown) => {
        if (alive.current)
          setError(cause instanceof Error ? cause.message : 'Unable to add comparison')
      })
    },
    [disabled, onAdd]
  )

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className="h-8 shrink-0 gap-1 px-2.5 text-xs"
            disabled={disabled}
            aria-label="Comparisons"
            title="Overlay another instrument on this chart"
          >
            Compare
            {/* The same count chip Indicators wears, because it says the same
                thing. `Compare (2)` beside `Indicators 2` was two spellings of
                one idea in one row, and the parenthesised one reads as part of
                the word rather than as a tally. */}
            {state.items.length > 0 && (
              <span className="rounded bg-primary/15 px-1 text-[10px] font-medium text-primary">
                {state.items.length}
              </span>
            )}
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" container={container} className="w-80 space-y-3 p-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-medium">Comparisons</span>
            <button
              type="button"
              className="rounded border px-2 py-1 text-xs hover:bg-accent"
              onClick={() => {
                setOpen(false)
                setSearchOpen(true)
              }}
            >
              Add comparison
            </button>
          </div>
          <label className="flex items-center justify-between gap-3 text-xs">
            Scale
            <select
              aria-label="Comparison scale"
              value={state.mode}
              onChange={(event) => onModeChange(event.target.value as 'price' | 'percentage')}
              className="rounded border bg-background px-2 py-1"
            >
              <option value="price">Price</option>
              <option value="percentage">Percentage</option>
            </select>
          </label>
          {state.items.length === 0 && (
            <p className="text-xs text-muted-foreground">Add symbols to compare with this chart.</p>
          )}
          <ul className="max-h-64 space-y-2 overflow-y-auto">
            {state.items.map((item) => (
              <li key={item.id} className="flex items-start gap-2 text-xs">
                <span
                  className="mt-1 h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: item.color }}
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <p className="break-words">{item.label}</p>
                  {item.status === 'loading' && (
                    <output className="block text-muted-foreground">Loading history</output>
                  )}
                  {item.status === 'error' && (
                    <p role="alert" className="text-destructive">
                      {item.error || 'Comparison history unavailable'}
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  aria-label={`Remove ${item.label}`}
                  onClick={() => onRemove(item.id)}
                  className="shrink-0 rounded px-1 py-0.5 text-muted-foreground hover:bg-accent hover:text-foreground"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
          {error && (
            <p role="alert" className="text-xs text-destructive">
              {error}
            </p>
          )}
        </PopoverContent>
      </Popover>
      <SymbolSearchDialog
        open={searchOpen}
        onOpenChange={setSearchOpen}
        mode="comparison"
        title="Add comparison symbol"
        search={search}
        onPick={add}
        container={container}
      />
    </>
  )
}
