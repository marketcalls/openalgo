/**
 * Indicator settings form, in the shape a charting package uses: title bar,
 * Inputs / Style tabs, a two-column label→control grid, and a footer with
 * Defaults on the left and Cancel / Ok on the right.
 *
 * The chart engine is canvas-only and ships no DOM, so it emits
 * `indicatorSettings` and the host renders this. Every field comes from the
 * descriptor — its value `inputs` and the generated per-plot style inputs — so
 * one component covers MACD, Bollinger, Supertrend and anything you register,
 * with no indicator-specific code.
 */
import { useEffect, useMemo, useState } from 'react'
import type { IndicatorField, IndicatorSettingsRequest } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'
import { PlotStyleRow } from './PlotStyleRow'

interface Props {
  req: IndicatorSettingsRequest | null
  onApply(instanceId: string, patch: Record<string, unknown>): void
  onDefaults(instanceId: string): Promise<Record<string, unknown> | null>
  onClose(): void
}

const SOURCES = ['open', 'high', 'low', 'close', 'hl2', 'hlc3', 'ohlc4']
const LINE_STYLES = ['solid', 'dashed', 'dotted']

/** Shared control chrome — compact, flat, dark-first. */
const CONTROL =
  'h-7 rounded border border-border bg-background px-2 text-[13px] text-foreground outline-none transition-colors focus:border-primary'

export function IndicatorSettingsDialog({ req, onApply, onDefaults, onClose }: Props) {
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [tab, setTab] = useState<'inputs' | 'style'>('inputs')

  useEffect(() => {
    setValues(req ? { ...req.values } : {})
    setTab(req && req.inputs.length === 0 ? 'style' : 'inputs')
  }, [req])

  useEffect(() => {
    if (!req) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [req, onClose])

  const fields = useMemo(
    () => (req ? (tab === 'inputs' ? req.inputs : req.styleInputs) : []),
    [req, tab]
  )

  if (!req) return null

  const set = (key: string, v: unknown) => setValues((prev) => ({ ...prev, [key]: v }))
  const apply = () => {
    onApply(req.instanceId, values)
    onClose()
  }
  const reset = async () => {
    const d = await onDefaults(req.instanceId)
    if (d) setValues(d)
  }

  const tabs: { key: 'inputs' | 'style'; label: string; n: number }[] = [
    { key: 'inputs', label: 'Inputs', n: req.inputs.length },
    { key: 'style', label: 'Style', n: req.styleInputs.length },
  ]

  return (
    <div
      className="absolute inset-0 z-40 flex items-center justify-center bg-black/50"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      role="presentation"
    >
      <div className="flex max-h-[92%] w-[340px] flex-col rounded-lg border bg-popover shadow-2xl">
        {/* Title */}
        <div className="flex items-center justify-between px-4 pb-2 pt-3">
          <h3 className="text-[15px] font-semibold tracking-tight">{req.name}</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="-mr-1 rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        {/* Tabs — underlined active, like a charting package's settings sheet */}
        <div className="flex gap-4 border-b px-4">
          {tabs.map((t) => (
            <button
              type="button"
              key={t.key}
              disabled={t.n === 0}
              onClick={() => setTab(t.key)}
              className={cn(
                '-mb-px border-b-2 pb-2 text-[13px] transition-colors',
                t.n === 0 && 'cursor-not-allowed opacity-40',
                tab === t.key
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
          {tab === 'style' ? (
            // One row per plot — the generated style inputs are flat, but each
            // carries its plot title as `group`, so they regroup cleanly.
            <div className="flex flex-col gap-2.5">
              {groupsOf(fields).map(([title, group]) => (
                <PlotStyleRow
                  key={title}
                  title={title}
                  fields={group}
                  values={values}
                  onChange={set}
                />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-[minmax(0,1fr)_150px] items-center gap-x-5 gap-y-3">
              {fields.map((f) => (
                <Field
                  key={f.key}
                  field={f}
                  id={`${req.instanceId}-${f.key}`}
                  value={values[f.key]}
                  onChange={(v) => set(f.key, v)}
                />
              ))}
            </div>
          )}
          {fields.length === 0 && (
            <p className="py-3 text-[13px] text-muted-foreground">Nothing to configure here.</p>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-2 border-t px-4 py-2.5">
          <button
            type="button"
            onClick={() => void reset()}
            className="flex items-center gap-2 rounded border border-foreground/25 px-2.5 py-1 text-[13px] text-muted-foreground transition-colors hover:border-foreground/50 hover:text-foreground"
          >
            Defaults
            <svg viewBox="0 0 10 10" className="h-2.5 w-2.5 opacity-70" aria-hidden="true">
              <path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" strokeWidth={1.4} />
            </svg>
          </button>
          <div className="flex gap-2">
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

/** Style inputs, bucketed by the plot they belong to, in first-seen order. */
function groupsOf(fields: IndicatorField[]): [string, IndicatorField[]][] {
  const out = new Map<string, IndicatorField[]>()
  for (const f of fields) {
    const k = f.group ?? f.label
    const list = out.get(k) ?? []
    list.push(f)
    out.set(k, list)
  }
  return [...out]
}

/** One label → control row, rendered by the field's declared type. */
function Field({
  field,
  id,
  value,
  onChange,
}: {
  field: IndicatorField
  id: string
  value: unknown
  onChange(v: unknown): void
}) {
  const label = (
    <label htmlFor={id} className="text-[13px] text-muted-foreground">
      {field.label}
    </label>
  )

  if (field.type === 'boolean') {
    return (
      <>
        {label}
        <input
          id={id}
          type="checkbox"
          checked={value === true}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 accent-[hsl(var(--primary))]"
        />
      </>
    )
  }

  if (field.type === 'color') {
    const v = typeof value === 'string' ? value : '#4f8cff'
    return (
      <>
        {label}
        <div className="flex items-center gap-2">
          <input
            id={id}
            type="color"
            value={v}
            onChange={(e) => onChange(e.target.value)}
            aria-label={field.label}
            // Native swatch chrome is bulky; clip it to a flat colour chip.
            className="h-6 w-10 cursor-pointer rounded border border-border bg-transparent p-0 [&::-moz-color-swatch]:rounded-sm [&::-moz-color-swatch]:border-0 [&::-webkit-color-swatch-wrapper]:p-0.5 [&::-webkit-color-swatch]:rounded-sm [&::-webkit-color-swatch]:border-0"
          />
        </div>
      </>
    )
  }

  if (field.type === 'source' || field.type === 'select') {
    const opts = field.options
      ? field.options.map((o) => ({ label: o.label, value: String(o.value) }))
      : (field.type === 'source' ? SOURCES : LINE_STYLES).map((o) => ({
          label: o.charAt(0).toUpperCase() + o.slice(1),
          value: o,
        }))
    return (
      <>
        {label}
        <div className="relative w-full">
          <select
            id={id}
            value={String(value ?? '')}
            onChange={(e) => onChange(e.target.value)}
            className={cn(CONTROL, 'w-full appearance-none pr-7')}
          >
            {opts.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <svg viewBox="0 0 10 10" className="pointer-events-none absolute right-2 top-1/2 h-2.5 w-2.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true">
            <path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" strokeWidth={1.5} />
          </svg>
        </div>
      </>
    )
  }

  const step = field.step ?? 1
  const nudge = (dir: 1 | -1) => {
    const cur = Number(value)
    const next = (Number.isFinite(cur) ? cur : 0) + dir * step
    const clamped = Math.min(field.max ?? Number.POSITIVE_INFINITY, Math.max(field.min ?? -Number.POSITIVE_INFINITY, next))
    // Step can be fractional (0.5 thickness); round to its precision so the
    // value never drifts into 1.4000000000000001.
    onChange(Number(clamped.toFixed(String(step).split('.')[1]?.length ?? 0)))
  }
  return (
    <>
      {label}
      <div className={cn(CONTROL, 'flex w-full items-center gap-1 p-0 pl-2')}>
        <input
          id={id}
          type="number"
          value={typeof value === 'number' || typeof value === 'string' ? String(value) : ''}
          min={field.min}
          max={field.max}
          step={step}
          onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
          // The native spinner is a bright, oversized chrome control; ours
          // matches the theme and is always visible.
          className="w-full min-w-0 bg-transparent text-[13px] outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
        />
        <span className="flex h-full flex-col justify-center border-l border-border">
          <button type="button" aria-label="Increase" onClick={() => nudge(1)} className="flex h-3 w-5 items-center justify-center text-muted-foreground hover:text-foreground">
            <svg viewBox="0 0 10 6" className="h-1.5 w-2.5" aria-hidden="true"><path d="M1 5 5 1.5 9 5" fill="none" stroke="currentColor" strokeWidth={1.6} /></svg>
          </button>
          <button type="button" aria-label="Decrease" onClick={() => nudge(-1)} className="flex h-3 w-5 items-center justify-center text-muted-foreground hover:text-foreground">
            <svg viewBox="0 0 10 6" className="h-1.5 w-2.5" aria-hidden="true"><path d="M1 1 5 4.5 9 1" fill="none" stroke="currentColor" strokeWidth={1.6} /></svg>
          </button>
        </span>
      </div>
    </>
  )
}
