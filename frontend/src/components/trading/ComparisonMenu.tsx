import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { COMPARISON_SCALES, type ComparisonScale } from '@/lib/trading/comparisonScale'
import type { SearchRow, TerminalComparisonState } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'
import { SymbolSearchDialog } from './SymbolSearchDialog'
import { Tip } from './Tip'

interface Props {
  state: TerminalComparisonState
  search(query: string, exchange?: string, limit?: number): Promise<SearchRow[]>
  onAdd(symbol: string, exchange: string): Promise<void>
  onRemove(id: string): void
  onModeChange(mode: ComparisonScale): void
  /** Hide or show one line; it stays on the chart either way. */
  onToggle?(id: string, visible: boolean): void
  /** Load a comparison whose history failed again. */
  onRetry?(id: string): Promise<void>
  disabled?: boolean
  container?: HTMLElement | null
}

/** A close the way a legend reads it: grouped, two decimals. */
function price(value: number): string {
  return value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function ComparisonMenu({
  state,
  search,
  onAdd,
  onRemove,
  onModeChange,
  onToggle,
  onRetry,
  disabled = false,
  container,
}: Props) {
  const hintId = useId()
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
  const retry = (id: string) => {
    setError(null)
    void onRetry?.(id).catch((cause: unknown) => {
      if (alive.current)
        setError(cause instanceof Error ? cause.message : 'The comparison could not be loaded')
    })
  }
  const scale = COMPARISON_SCALES.find((item) => item.value === state.mode) ?? COMPARISON_SCALES[0]
  const action =
    'shrink-0 rounded px-1 py-0.5 text-muted-foreground hover:bg-accent hover:text-foreground'

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <Tip
          disabled={open}
          tip={{
            title: 'Compare',
            sub: 'Overlay another instrument on this chart, in price, percent or its own scale',
          }}
        >
          <PopoverTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              className="h-8 shrink-0 gap-1 px-2.5 text-xs"
              disabled={disabled}
              aria-label="Comparisons"
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
        </Tip>
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
          <div className="space-y-1">
            <label className="flex items-center justify-between gap-3 text-xs">
              Scale
              <select
                aria-label="Comparison scale"
                aria-describedby={hintId}
                value={state.mode}
                onChange={(event) => onModeChange(event.target.value as ComparisonScale)}
                className="rounded border bg-background px-2 py-1"
              >
                {COMPARISON_SCALES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <p id={hintId} className="text-[11px] text-muted-foreground">
              {scale.hint}
            </p>
          </div>
          {state.items.length === 0 && (
            <p className="text-xs text-muted-foreground">Add symbols to compare with this chart.</p>
          )}
          <ul className="max-h-64 space-y-2 overflow-y-auto">
            {state.items.map((item) => (
              <li key={item.id} className="flex items-start gap-2 text-xs">
                <span
                  className={cn(
                    'mt-1 h-2 w-2 shrink-0 rounded-full',
                    !item.visible && 'opacity-30'
                  )}
                  style={{ backgroundColor: item.color }}
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <p className={cn('break-words', !item.visible && 'text-muted-foreground')}>
                    {item.label}
                  </p>
                  {item.status === 'ready' && item.visible && item.close !== undefined && (
                    <p className="tabular-nums text-muted-foreground">
                      {price(item.close)}
                      {item.change !== undefined && (
                        <span
                          className={cn(
                            'ml-1.5',
                            item.change >= 0
                              ? 'text-emerald-600 dark:text-emerald-400'
                              : 'text-rose-600 dark:text-rose-400'
                          )}
                        >
                          {item.change >= 0 ? '+' : ''}
                          {item.change.toFixed(2)}%
                        </span>
                      )}
                    </p>
                  )}
                  {!item.visible && <p className="text-muted-foreground">Hidden</p>}
                  {item.status === 'loading' && (
                    <output className="block text-muted-foreground">Loading history</output>
                  )}
                  {item.status === 'error' && (
                    <p role="alert" className="text-destructive">
                      {item.error || 'Comparison history unavailable'}
                    </p>
                  )}
                </div>
                {item.status === 'error' && onRetry && (
                  <button
                    type="button"
                    aria-label={`Retry ${item.label}`}
                    onClick={() => retry(item.id)}
                    className={action}
                  >
                    Retry
                  </button>
                )}
                {onToggle && (
                  <button
                    type="button"
                    aria-label={`${item.visible ? 'Hide' : 'Show'} ${item.label}`}
                    aria-pressed={!item.visible}
                    onClick={() => onToggle(item.id, !item.visible)}
                    className={action}
                  >
                    {item.visible ? 'Hide' : 'Show'}
                  </button>
                )}
                <button
                  type="button"
                  aria-label={`Remove ${item.label}`}
                  onClick={() => onRemove(item.id)}
                  className={action}
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
