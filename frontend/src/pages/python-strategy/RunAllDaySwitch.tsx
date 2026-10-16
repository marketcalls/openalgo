import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'

/** Every day of the week, which is what a 24/7 crypto strategy runs on. */
export const ALL_DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']

/** The start time a 24/7 strategy is saved with; it has no stop time. */
export const ALL_DAY_START = '00:00'

/**
 * The choice to run a crypto strategy around the clock.
 *
 * On, the strategy is saved with no stop time and every day of the week, so
 * the schedule never stops it. Off, it gets a start and stop time like any
 * other exchange.
 */
export function RunAllDaySwitch({
  checked,
  onCheckedChange,
}: {
  checked: boolean
  onCheckedChange(checked: boolean): void
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-lg border p-3">
      <div className="space-y-1">
        <Label htmlFor="run_24x7">Run 24/7</Label>
        <p className="text-xs text-muted-foreground">
          {checked
            ? 'The schedule never stops this strategy. It runs until you stop it, and if the script exits on its own it is started again at 00:00 IST.'
            : 'The strategy runs only between the start and stop time below, on the days you pick.'}
        </p>
      </div>
      <Switch id="run_24x7" checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  )
}
