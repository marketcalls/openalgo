/**
 * Choose what a chart's CSV download holds: every loaded bar or only those on
 * screen, which studies, and whether the comparison closes come along.
 *
 * Drawn over the chart it belongs to, like the pane's other short forms, and
 * gone the moment the file is written. Everything starts ticked, so pressing
 * Download at once writes exactly the file the menu wrote before there was a
 * choice.
 */
import { useEffect, useId, useState } from 'react'
import type { DataExportOptions } from '@/lib/trading/chartDataExport'
import { TickBox } from './TickBox'

interface Props {
  /** What the file is of, such as `NIFTY 5m`. */
  source: string
  studies: readonly { id: string; name: string }[]
  comparisons: number
  /** Writes the file; throws with a sentence when it cannot. */
  onDownload(options: DataExportOptions): void
  onClose(): void
}

export function ChartDataDialog({ source, studies, comparisons, onDownload, onClose }: Props) {
  const id = useId()
  const [range, setRange] = useState<'all' | 'visible'>('all')
  const [chosen, setChosen] = useState<ReadonlySet<string>>(() => new Set(studies.map((s) => s.id)))
  const [withComparisons, setWithComparisons] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const download = () => {
    setError('')
    try {
      onDownload({
        range,
        // In the chart's own order, whatever order they were ticked in.
        studies: studies.filter((study) => chosen.has(study.id)).map((study) => study.id),
        comparisons: withComparisons,
      })
      onClose()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The chart data could not be exported')
    }
  }
  const row = 'flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-xs hover:bg-accent'

  return (
    <div
      className="pointer-events-auto absolute inset-0 z-40 flex items-center justify-center bg-black/45"
      role="presentation"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        className="flex max-h-[calc(100%-24px)] w-[320px] max-w-[calc(100%-24px)] flex-col rounded-lg border bg-popover shadow-xl"
      >
        <div className="px-4 pb-2 pt-3">
          <h4 id={`${id}-title`} className="text-sm font-medium">
            Download chart data
          </h4>
          <p className="text-xs text-muted-foreground">{source}</p>
        </div>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 pb-3">
          <fieldset className="space-y-0.5">
            <legend className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Bars
            </legend>
            {(
              [
                ['all', 'All loaded bars'],
                ['visible', 'Bars on screen'],
              ] as const
            ).map(([value, label]) => (
              <label key={value} className={row}>
                <input
                  type="radio"
                  name={`${id}-range`}
                  value={value}
                  checked={range === value}
                  onChange={() => setRange(value)}
                  className="accent-primary"
                />
                {label}
              </label>
            ))}
          </fieldset>
          <fieldset className="space-y-0.5">
            <legend className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Studies
            </legend>
            {studies.length === 0 && (
              <p className="px-1 text-xs text-muted-foreground">No studies on this chart</p>
            )}
            {studies.map((study) => (
              <label key={study.id} className={row}>
                <TickBox
                  checked={chosen.has(study.id)}
                  onChange={(next) =>
                    setChosen((previous) => {
                      const out = new Set(previous)
                      if (next) out.add(study.id)
                      else out.delete(study.id)
                      return out
                    })
                  }
                />
                <span className="min-w-0 truncate">{study.name}</span>
              </label>
            ))}
          </fieldset>
          {comparisons > 0 && (
            <label className={row}>
              <TickBox checked={withComparisons} onChange={setWithComparisons} />
              Comparison closes ({comparisons})
            </label>
          )}
          {error && (
            <p role="alert" className="text-xs text-destructive">
              {error}
            </p>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t px-4 py-2.5">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={download}
            className="rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90"
          >
            Download CSV
          </button>
        </div>
      </div>
    </div>
  )
}
