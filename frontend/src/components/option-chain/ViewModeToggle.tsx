import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { ViewMode } from '@/types/option-chain'
import { VIEW_MODES } from '@/types/option-chain'

interface ViewModeToggleProps {
  viewMode: ViewMode
  onViewModeChange: (mode: ViewMode) => void
}

/**
 * Segmented Price / Greeks switch for the option chain.
 *
 * Switching is instant and costs nothing: Greeks are computed for every leg on
 * each tick regardless of which preset is on screen, so this only swaps which
 * columns are rendered. No refetch, no resubscribe.
 */
export function ViewModeToggle({ viewMode, onViewModeChange }: ViewModeToggleProps) {
  return (
    <fieldset
      className="inline-flex h-9 items-center rounded-md border bg-muted/40 p-0.5"
      aria-label="Chain view mode"
      title="Switch columns between prices and Greeks (shortcut: G)"
    >
      {VIEW_MODES.map((mode) => {
        const isActive = viewMode === mode.value
        return (
          <Button
            key={mode.value}
            type="button"
            variant="ghost"
            size="sm"
            aria-pressed={isActive}
            onClick={() => onViewModeChange(mode.value)}
            className={cn(
              'h-8 px-3 text-xs font-medium transition-colors',
              isActive
                ? 'bg-background text-foreground shadow-sm hover:bg-background'
                : 'text-muted-foreground hover:text-foreground'
            )}
          >
            {mode.label}
          </Button>
        )
      })}
    </fieldset>
  )
}
