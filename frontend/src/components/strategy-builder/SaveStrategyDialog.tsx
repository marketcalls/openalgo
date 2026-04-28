import { useEffect, useState } from 'react'
import { Briefcase, FlaskConical } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import type { Watchlist } from '@/api/strategy-portfolio'

export interface SaveStrategyDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSave: (name: string, watchlist: Watchlist) => Promise<void>
  /** Pre-fills when saving over an existing entry. */
  defaultName?: string
  defaultWatchlist?: Watchlist
  /** True when editing an existing entry (changes button label). */
  isUpdate?: boolean
  busy?: boolean
}

const WATCHLIST_OPTIONS: Array<{
  value: Watchlist
  label: string
  description: string
  icon: typeof Briefcase
  color: string
}> = [
  {
    value: 'mytrades',
    label: 'MyTrades',
    description: 'Live or intended-live positions',
    icon: Briefcase,
    color: 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/40',
  },
  {
    value: 'simulation',
    label: 'Simulation',
    description: 'Paper / what-if scenarios',
    icon: FlaskConical,
    color: 'bg-violet-500/10 text-violet-700 dark:text-violet-400 border-violet-500/40',
  },
]

export function SaveStrategyDialog({
  open,
  onOpenChange,
  onSave,
  defaultName = '',
  defaultWatchlist = 'mytrades',
  isUpdate = false,
  busy = false,
}: SaveStrategyDialogProps) {
  const [name, setName] = useState(defaultName)
  const [watchlist, setWatchlist] = useState<Watchlist>(defaultWatchlist)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      setName(defaultName)
      setWatchlist(defaultWatchlist)
      setError(null)
    }
  }, [open, defaultName, defaultWatchlist])

  const submit = async () => {
    const trimmed = name.trim()
    if (!trimmed) {
      setError('Strategy name is required')
      return
    }
    setError(null)
    try {
      await onSave(trimmed, watchlist)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{isUpdate ? 'Update Strategy' : 'Save Strategy'}</DialogTitle>
          <DialogDescription>
            Store this strategy in one of your two watchlists so you can revisit or replay it
            later.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1">
            <label className="text-[11px] font-medium text-muted-foreground">Strategy Name</label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. NIFTY Bull Call Spread"
              className="h-10"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') submit()
              }}
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-[11px] font-medium text-muted-foreground">
              Save to watchlist
            </label>
            <div className="grid grid-cols-2 gap-2">
              {WATCHLIST_OPTIONS.map((opt) => {
                const Icon = opt.icon
                const selected = watchlist === opt.value
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setWatchlist(opt.value)}
                    className={cn(
                      'flex flex-col items-start gap-1 rounded-lg border-2 p-3 text-left transition-all',
                      selected
                        ? opt.color
                        : 'border-border bg-card hover:border-muted-foreground/40'
                    )}
                  >
                    <Icon className="h-4 w-4" />
                    <span className="text-sm font-semibold">{opt.label}</span>
                    <span className="text-[10px] leading-tight text-muted-foreground">
                      {opt.description}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          {error && (
            <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-700 dark:text-rose-400">
              {error}
            </p>
          )}
        </div>

        <DialogFooter className="flex-row justify-end gap-2">
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button size="sm" onClick={submit} disabled={busy}>
            {busy ? 'Saving…' : isUpdate ? 'Update' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
