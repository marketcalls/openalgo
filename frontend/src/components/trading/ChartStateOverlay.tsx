/**
 * The card a pane shows over its chart while the chart is not simply showing
 * bars: dots for a slow load, a no data card, or a failed load with Try again
 * and Dismiss.
 *
 * It never covers the chart with a scrim. A failed load leaves the previous
 * chart where it was, readable and usable around the card, and Dismiss takes
 * the card away. Only the card itself takes the pointer, and the loading
 * dots take nothing.
 */
import { type ChartStateView, chartStateCopy } from '@/lib/trading/chartState'
import { cn } from '@/lib/utils'

interface Props {
  view: ChartStateView | null
  onRetry(): void
  onDismiss(): void
}

const BUTTON =
  'rounded border border-border px-2 py-1 text-xs hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring'

export function ChartStateOverlay({ view, onRetry, onDismiss }: Props) {
  if (!view || view.kind === 'ready') return null
  const copy = chartStateCopy(view)
  const loading = view.kind === 'loading'
  return (
    <div
      className="pointer-events-none absolute inset-0 z-[15] flex items-center justify-center p-3"
      data-chart-state={view.kind}
    >
      <div
        role={copy.role}
        aria-live={copy.role === 'alert' ? 'assertive' : 'polite'}
        className={cn(
          'max-w-[min(22rem,100%)] rounded-lg border border-border bg-popover/95 text-center shadow-lg backdrop-blur',
          loading ? 'px-3 py-2' : 'pointer-events-auto px-4 py-3'
        )}
      >
        {loading ? (
          <div className="flex flex-col items-center gap-1.5">
            <span className="flex gap-1" aria-hidden="true">
              {[0, 1, 2].map((i) => (
                <span
                  key={i}
                  className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground motion-reduce:animate-none"
                  style={{ animationDelay: `${i * 150}ms` }}
                />
              ))}
            </span>
            <span className="text-[11px] text-muted-foreground">{copy.title}</span>
          </div>
        ) : (
          <>
            <p className="break-words text-sm font-medium text-foreground">{copy.title}</p>
            <p className="mt-1 break-words text-xs leading-relaxed text-muted-foreground">
              {copy.text}
            </p>
            <div className="mt-3 flex justify-center gap-2">
              <button type="button" className={BUTTON} onClick={onRetry}>
                Try again
              </button>
              <button type="button" className={BUTTON} onClick={onDismiss}>
                Dismiss
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
