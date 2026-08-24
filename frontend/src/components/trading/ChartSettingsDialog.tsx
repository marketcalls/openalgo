/**
 * Chart settings form: the dialog behind the toolbar's gear.
 *
 * The chart engine is canvas-only and ships no DOM, so it describes its own
 * settings declaratively -- `chartSettingsSchema` returns the tabs and their
 * controls, `readChartSettings` the current values, `applyChartSettings` takes
 * a patch. Nothing here hardcodes a setting, so a control the engine adds in a
 * later version appears without a change to this file.
 *
 * It reuses `SettingsField` from the indicator dialog because the engine
 * deliberately describes chart settings with the same input vocabulary. The one
 * widget it adds is `colorPair`: a bullish/bearish pair is one row, and drawing
 * it as two stacked colour rows costs three times the height for the property a
 * trader changes most.
 */
import { useEffect, useMemo, useState } from 'react'
import type {
  ChartSettingsField,
  ChartSettingsPairField,
  ChartSettingsRequest,
} from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'
import { SettingsField } from './IndicatorSettingsDialog'
import { TickBox } from './TickBox'

type Value = string | number | boolean

interface Props {
  req: ChartSettingsRequest | null
  onApply(patch: Record<string, Value>): void
  onClose(): void
}

const isPair = (f: ChartSettingsField): f is ChartSettingsPairField => f.type === 'colorPair'

export function ChartSettingsDialog({ req, onApply, onClose }: Props) {
  const [values, setValues] = useState<Record<string, Value>>({})
  const [tabId, setTabId] = useState<string>('')

  useEffect(() => {
    setValues(req ? { ...req.values } : {})
    setTabId(req?.tabs[0]?.id ?? '')
  }, [req])

  useEffect(() => {
    if (!req) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [req, onClose])

  const tab = useMemo(
    () => req?.tabs.find((t) => t.id === tabId) ?? req?.tabs[0] ?? null,
    [req, tabId]
  )

  /**
   * What reset restores: this terminal's own baseline, handed over by the host.
   *
   * Deliberately NOT assembled from the schema's per-control defaults, even
   * though every engine input publishes one. Those are the ENGINE's defaults,
   * and this host does not build a bare engine chart: it turns the corner
   * session clock and the bar countdown on at construction, and the grid is
   * owned by the context menu under a separate key. Resetting to the schema
   * would switch off chrome nobody touched and pick a fight over the grid.
   * See `snapshotChartDefaults` for where the baseline is taken.
   *
   * Colours in it are the chart's ACTIVE THEME's, not a fixed palette, so
   * resetting in dark mode restores the dark candles rather than the light ones.
   */
  const defaults = useMemo(() => req?.defaults ?? {}, [req])

  /**
   * Whether anything, on any tab, currently deviates. Drives the reset
   * control's disabled state, which is the honest answer to "is this chart
   * already at defaults" and cheaper to read than hunting five tabs for a
   * changed swatch.
   */
  const deviates = useMemo(
    () => Object.entries(defaults).some(([k, v]) => values[k] !== undefined && values[k] !== v),
    [defaults, values]
  )

  if (!req || !tab) return null

  const set = (key: string, v: unknown) => setValues((prev) => ({ ...prev, [key]: v as Value }))

  /**
   * Send only what changed. The engine writes exactly the keys it is handed, so
   * a one-control edit stays a one-key patch -- which is also what gets
   * persisted, keeping a pane's stored settings to what the user actually
   * chose rather than a snapshot of every default.
   */
  const apply = () => {
    const patch: Record<string, Value> = {}
    for (const [k, v] of Object.entries(values)) {
      if (req.values[k] !== v) patch[k] = v
    }
    if (Object.keys(patch).length) onApply(patch)
    onClose()
  }

  return (
    <div
      className="absolute inset-0 z-40 flex items-center justify-center bg-black/50"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      role="presentation"
    >
      <div className="flex max-h-[92%] w-[380px] flex-col rounded-lg border bg-popover shadow-2xl">
        {/* Title */}
        <div className="flex shrink-0 items-center justify-between px-4 pb-2 pt-3">
          <h3 className="text-[15px] font-semibold tracking-tight">Chart settings</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mr-1 rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <svg
              viewBox="0 0 24 24"
              className="h-4 w-4"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.8}
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        {/* Tabs. Five of them, so the row scrolls rather than wraps: a wrapped
            tab strip changes the dialog's height as you move between tabs.

            `shrink-0` is load-bearing, and its absence was a real bug. The
            fields panel below is `flex-1`, i.e. `flex: 1 1 0%`, and a flex item
            whose basis is 0 has a *scaled shrink factor of 0*: it absorbs none
            of the overflow when the dialog hits `max-h`. The browser took the
            excess out of the only children with a non-zero basis instead, this
            strip among them, squeezing it from 28px to 16.6px. `overflow-x-auto`
            also computes `overflow-y` to `auto`, so the squeezed strip clipped
            rather than spilled, and it clipped exactly the descender band: the
            `p` in `Appearance` and the `g` in `Trading` lost their tails while
            `Price`, `Readout` and `Axes` looked untouched. It only reproduced on
            those two tabs because their panels are the tall ones, so they are
            the ones that push the dialog into its `max-h` in the first place.

            `leading-5` is belt and braces: `text-[13px]` is an arbitrary size,
            which sets font-size ONLY and inherits its line-height, unlike
            `text-sm` which ships a paired one. Pinning it makes the row's height
            deterministic rather than a function of whatever leading it sits in. */}
        <div className="flex shrink-0 gap-4 overflow-x-auto no-scrollbar border-b px-4">
          {req.tabs.map((t) => (
            <button
              type="button"
              key={t.id}
              onClick={() => setTabId(t.id)}
              className={cn(
                '-mb-px shrink-0 border-b-2 pb-2 text-[13px] leading-5 transition-colors',
                t.id === tab.id
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              )}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Fields */}
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          <div className="grid grid-cols-[minmax(0,1fr)_150px] items-center gap-x-5 gap-y-3">
            {groupsOf(tab.inputs).map(([heading, group]) => (
              <FieldGroup
                key={`${tab.id}-${heading}`}
                heading={heading}
                fields={group}
                tabId={tab.id}
                values={values}
                onChange={set}
              />
            ))}
          </div>
          {tab.inputs.length === 0 && (
            <p className="py-3 text-[13px] text-muted-foreground">Nothing to configure here.</p>
          )}
        </div>

        {/* Footer: secondary action bottom left, confirming action last.

            Reset covers EVERY tab, not the visible one. The engine has no
            "reset the chart" call, so this is assembled from the per-control
            defaults the schema already declares, and a reset that silently
            stopped at the tab you happened to be looking at would be the kind
            of half-truth worth not shipping. It is deferred like every other
            edit here: it fills the form, and Cancel still walks away from it. */}
        <div className="flex shrink-0 items-center justify-between gap-2 border-t px-4 py-2.5">
          <button
            type="button"
            disabled={!deviates}
            onClick={() => setValues((prev) => ({ ...prev, ...defaults }))}
            title={
              deviates
                ? 'Restore every control on every tab to its default'
                : 'Every control is already at its default'
            }
            className="rounded px-2 py-1 text-[13px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
          >
            Reset to defaults
          </button>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-foreground/25 px-3.5 py-1 text-[13px] transition-colors hover:border-foreground/50 hover:bg-accent"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={apply}
              className="rounded bg-foreground px-5 py-1 text-[13px] font-medium text-background transition-opacity hover:opacity-90"
            >
              Ok
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

/** Controls bucketed by their `group` sub-heading, in first-seen order. */
function groupsOf(fields: ChartSettingsField[]): [string, ChartSettingsField[]][] {
  const out = new Map<string, ChartSettingsField[]>()
  for (const f of fields) {
    const k = f.group ?? ''
    const list = out.get(k) ?? []
    list.push(f)
    out.set(k, list)
  }
  return [...out]
}

/** One sub-heading and the rows under it. Both span the full two-column grid. */
function FieldGroup({
  heading,
  fields,
  tabId,
  values,
  onChange,
}: {
  heading: string
  fields: ChartSettingsField[]
  tabId: string
  values: Record<string, Value>
  onChange(key: string, v: unknown): void
}) {
  return (
    <>
      {heading && (
        <div className="col-span-2 pt-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {heading}
        </div>
      )}
      {fields.map((f) =>
        isPair(f) ? (
          <ColorPairRow key={f.key} field={f} values={values} onChange={onChange} />
        ) : (
          <SettingsField
            key={f.key}
            field={f}
            id={`chart-${tabId}-${f.key}`}
            value={values[f.key]}
            onChange={(v) => onChange(f.key, v)}
          />
        )
      )}
    </>
  )
}

/**
 * `[x] Borders   [up] [down]` -- two swatches on one labelled row.
 *
 * The checkbox is drawn only when the pair actually has a visibility flag
 * behind it. A candle body is always painted, so a checkbox there would be a
 * control that does nothing.
 */
function ColorPairRow({
  field,
  values,
  onChange,
}: {
  field: ChartSettingsPairField
  values: Record<string, Value>
  onChange(key: string, v: unknown): void
}) {
  const enabledKey = field.enabled?.key
  const on = enabledKey ? values[enabledKey] !== false : true

  return (
    <>
      <div className="flex items-center gap-2">
        {enabledKey && (
          <TickBox
            id={`chart-${enabledKey}`}
            checked={on}
            onChange={(next) => onChange(enabledKey, next)}
            label={field.label}
          />
        )}
        <span className="text-[13px] text-muted-foreground">{field.label}</span>
      </div>
      <div className={cn('flex items-center gap-2', !on && 'pointer-events-none opacity-40')}>
        {[field.up, field.down].map((side) => (
          <input
            key={side.key}
            type="color"
            value={
              typeof values[side.key] === 'string' ? (values[side.key] as string) : side.default
            }
            onChange={(e) => onChange(side.key, e.target.value)}
            aria-label={`${field.label} ${side.label}`}
            title={side.label}
            className="h-[26px] w-[26px] cursor-pointer rounded-md border border-border bg-transparent p-0 [&::-moz-color-swatch]:rounded [&::-moz-color-swatch]:border-0 [&::-webkit-color-swatch-wrapper]:p-[3px] [&::-webkit-color-swatch]:rounded [&::-webkit-color-swatch]:border-0"
          />
        ))}
      </div>
    </>
  )
}
