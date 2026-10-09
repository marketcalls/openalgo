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
 *
 * A value input's `group` is a heading the rows under it sit beneath, and its
 * `tooltip` is a line of help under its row. Both are how a script explains
 * itself (`stdlib.md` 13.2): a label has to be short enough for the grid, and
 * the sentence saying what the number actually does has nowhere else to go.
 *
 * One place where a study has to be told apart from a JavaScript indicator: an
 * OpenScript interval input takes only the language's timeframes, so its
 * choices are rebuilt from the terminal's (see `openscriptIntervals.ts`).
 *
 * On a transformed chart (Heikin Ashi, Renko, range bars, line break) the
 * Inputs tab leads with Compute on: the elements drawn, or the raw bars under
 * them. It is not one of the study's own inputs, so it is held apart from them
 * and handed back beside the patch.
 */
import {
  Fragment,
  type ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { numberProblem, pickedPrice } from '@/lib/trading/inputValidation'
import { isScriptInstance } from '@/lib/trading/openscriptFiles'
import { scriptIntervalChoices } from '@/lib/trading/openscriptIntervals'
import type { IndicatorField, IndicatorSettingsRequest, InputPick } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'
import { PlotStyleRow } from './PlotStyleRow'
import { TickBox } from './TickBox'

type BarSource = NonNullable<IndicatorSettingsRequest['barSource']>

/** The Compute on row, drawn by the same control as the study's own selects. */
const BAR_SOURCE_FIELD: IndicatorField = {
  key: 'barSource',
  type: 'select',
  label: 'Compute on',
  options: [
    { label: 'Chart bars', value: 'chart' },
    { label: 'Underlying bars', value: 'underlying' },
  ],
  tooltip:
    'Chart bars are the bricks or candles drawn. Underlying bars are the time bars they are built from, read at the bar each one completed on.',
}

interface Props {
  req: IndicatorSettingsRequest | null
  /** The pane's symbol, so an `expiries` field knows whose expiries to list. */
  symbol?: string
  /**
   * The chart's own interval, as the terminal holds it (`5m`, `D`).
   *
   * What "Chart interval" means for an OpenScript study, which cannot store an
   * empty interval the way a JavaScript indicator can. Without it that choice
   * is left out rather than guessed.
   */
  chartInterval?: string
  /** `barSource` is passed only when the form offered the choice. */
  onApply(instanceId: string, patch: Record<string, unknown>, barSource?: BarSource): void
  onDefaults(instanceId: string): Promise<Record<string, unknown> | null>
  onClose(): void
  /**
   * Take the next click on the chart as this input's value. Returns the
   * cancel; `onValue` gets null when the pick ends without one. Absent, the
   * form offers no Pick buttons.
   */
  onPick?(field: IndicatorField, onValue: (value: InputPick | null) => void): () => void
}

/** Input types a click on the chart can fill: a price, a bar time, or a wall clock. */
const PICKABLE = new Set(['price', 'timestamp', 'time'])

/** The form's values after a pick, the paired time included when the input has one. */
function withPick(
  values: Record<string, unknown>,
  field: IndicatorField,
  pick: InputPick,
  inputs: readonly IndicatorField[]
): Record<string, unknown> {
  const out = { ...values }
  if (field.type === 'price') {
    if (pick.price !== undefined) out[field.key] = pickedPrice(pick.price)
    const pair = field.timeKey ? inputs.find((f) => f.key === field.timeKey) : undefined
    if (pair) out[pair.key] = pair.type === 'time' ? pick.clock : pick.time
  } else if (field.type === 'time') {
    if (pick.clock !== undefined) out[field.key] = pick.clock
  } else if (pick.time !== undefined) out[field.key] = pick.time
  return out
}

/** A field as the dialog draws it: the terminal's shape, help text included. */
export type SettingsFieldShape = IndicatorField

const SOURCES = ['open', 'high', 'low', 'close', 'hl2', 'hlc3', 'ohlc4']
const LINE_STYLES = ['solid', 'dashed', 'dotted']

/**
 * Input types the engine defines as strings the indicator parses itself, so the
 * dialog's job is a text box and a hint of the shape rather than a widget per
 * type. A session picker would be a different control that still has to hand
 * back the same string.
 *
 * 'time' (2.4.0) is a wall-clock instant in the chart's timezone, carried as a
 * string rather than as epoch seconds precisely so a layout saved in one zone
 * restores to the same clock in another. It is a text box for the same reason
 * a session is: the value is the string.
 */
const TEXT_TYPES = new Set(['text', 'time'])
const TEXT_PLACEHOLDER: Record<string, string | undefined> = {
  time: 'YYYY-MM-DD HH:MM',
}

/** Shared control chrome — compact, flat, dark-first. */
export const CONTROL =
  'h-7 rounded border border-border bg-background px-2 text-[13px] text-foreground outline-none transition-colors focus:border-primary'

export function IndicatorSettingsDialog({
  req,
  symbol,
  chartInterval,
  onApply,
  onDefaults,
  onClose,
  onPick,
}: Props) {
  const [values, setValues] = useState<Record<string, unknown>>({})
  /** The input waiting for a click on the chart, and how to stop waiting. */
  const [picking, setPicking] = useState<{ label: string; kind: string; cancel(): void } | null>(
    null
  )
  const pickingRef = useRef(picking)
  pickingRef.current = picking
  // A form closed mid-pick takes the pick with it.
  useEffect(() => () => pickingRef.current?.cancel(), [])
  const [barSource, setBarSource] = useState<BarSource | undefined>(undefined)
  const [tab, setTab] = useState<'inputs' | 'style'>('inputs')
  const script = req !== null && isScriptInstance(req.instanceId)

  /**
   * Stored values, with every OpenScript interval spelled the language's way.
   *
   * An empty interval, which is what "Chart interval" stored before, and a
   * broker code such as `D` are both refused at load with OS6001, so a study
   * holding one is not running. Showing it as the choice it maps to means Ok
   * puts it right; showing it as stored would leave the select disagreeing
   * with the value behind it.
   */
  const normalise = useCallback(
    (given: Record<string, unknown>): Record<string, unknown> => {
      if (!req || !script) return given
      const out = { ...given }
      for (const f of req.inputs) {
        if (f.type !== 'interval') continue
        out[f.key] = scriptIntervalChoices(f.options, chartInterval, given[f.key]).value
      }
      return out
    },
    [req, script, chartInterval]
  )

  useEffect(() => {
    setValues(req ? normalise({ ...req.values }) : {})
    setBarSource(req?.barSource)
    setTab(req && req.inputs.length === 0 && req.barSource === undefined ? 'style' : 'inputs')
  }, [req, normalise])

  // Attached before the form is painted. The form mounts on its first opening,
  // and a passive effect can run after the first paint, so an Escape pressed
  // the moment the form appeared went unheard.
  useLayoutEffect(() => {
    if (!req) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      // Escape while picking puts the form back rather than closing it.
      if (pickingRef.current) pickingRef.current.cancel()
      else onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [req, onClose])

  const fields: SettingsFieldShape[] = useMemo(() => {
    if (!req) return []
    if (tab === 'style') return req.styleInputs
    if (!script) return req.inputs
    return req.inputs.map((f) =>
      f.type === 'interval'
        ? { ...f, options: scriptIntervalChoices(f.options, chartInterval, values[f.key]).choices }
        : f
    )
  }, [req, tab, script, chartInterval, values])

  if (!req) return null

  const set = (key: string, v: unknown) => setValues((prev) => ({ ...prev, [key]: v }))
  const startPick = (field: IndicatorField) => {
    if (!onPick || pickingRef.current) return
    let finished = false
    const cancel = onPick(field, (pick) => {
      finished = true
      setPicking(null)
      if (pick) setValues((prev) => withPick(prev, field, pick, req.inputs))
    })
    if (!finished)
      setPicking({ label: field.label, kind: field.type === 'price' ? 'price' : 'time', cancel })
  }
  const apply = () => {
    // A number the engine would refuse keeps the form open on the tab that
    // holds it, where its message already says what is wrong.
    const refused = [
      ...req.inputs.map((field) => ['inputs', field] as const),
      ...req.styleInputs.map((field) => ['style', field] as const),
    ].find(([, field]) => field.key in values && numberProblem(field, values[field.key]))
    if (refused) {
      setTab(refused[0])
      return
    }
    if (barSource === undefined) onApply(req.instanceId, values)
    else onApply(req.instanceId, values, barSource)
    onClose()
  }
  const reset = async () => {
    const d = await onDefaults(req.instanceId)
    if (d) setValues(normalise(d))
    if (barSource !== undefined) setBarSource('chart')
  }

  const tabs: { key: 'inputs' | 'style'; label: string; n: number }[] = [
    {
      key: 'inputs',
      label: 'Inputs',
      n: req.inputs.length + (req.barSource === undefined ? 0 : 1),
    },
    { key: 'style', label: 'Style', n: req.styleInputs.length },
  ]

  return (
    <div
      className={cn(
        'absolute inset-0 z-40 flex items-center justify-center',
        picking ? 'pointer-events-none' : 'bg-black/50'
      )}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      role="presentation"
    >
      {picking && (
        <output className="pointer-events-auto absolute left-1/2 top-3 z-10 flex -translate-x-1/2 items-center gap-3 rounded-lg border bg-popover px-3 py-2 text-xs shadow-lg">
          <span>
            Click the chart to pick the {picking.kind} for{' '}
            <span className="font-medium">{picking.label}</span>
          </span>
          <button
            type="button"
            className="rounded border border-border px-2 py-1 hover:bg-accent"
            onClick={() => picking.cancel()}
          >
            Cancel
          </button>
        </output>
      )}
      <div
        className={cn(
          'flex max-h-[92%] w-[340px] flex-col rounded-lg border bg-popover shadow-2xl',
          picking && 'invisible'
        )}
      >
        {/* Title */}
        <div className="flex items-center justify-between px-4 pb-2 pt-3">
          <h3 className="text-[15px] font-semibold tracking-tight">{req.name}</h3>
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
              {barSource !== undefined && (
                <SettingsField
                  field={BAR_SOURCE_FIELD}
                  id={`${req.instanceId}-barSource`}
                  value={barSource}
                  onChange={(v) => setBarSource(v === 'underlying' ? 'underlying' : 'chart')}
                />
              )}
              {inputGroupsOf(fields).map(([heading, group]) => (
                <Fragment key={heading}>
                  {heading !== '' && (
                    <h4 className="col-span-2 pt-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                      {heading}
                    </h4>
                  )}
                  {group.map((f) =>
                    f.type === 'expiries' ? (
                      <ExpiryPicker
                        key={f.key}
                        field={f}
                        id={`${req.instanceId}-${f.key}`}
                        value={values[f.key]}
                        count={Number(values.expiries) || 1}
                        exchange={exchangeOf(
                          values.exchange,
                          underlyingOf(values.underlying, symbol)
                        )}
                        underlying={underlyingOf(values.underlying, symbol)}
                        onChange={(v) => set(f.key, v)}
                      />
                    ) : (
                      <SettingsField
                        key={f.key}
                        field={f}
                        id={`${req.instanceId}-${f.key}`}
                        value={values[f.key]}
                        onChange={(v) => set(f.key, v)}
                        onPick={onPick && PICKABLE.has(f.type) ? () => startPick(f) : undefined}
                      />
                    )
                  )}
                </Fragment>
              ))}
            </div>
          )}
          {fields.length === 0 && (tab === 'style' || barSource === undefined) && (
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

/**
 * The expiry pick list, the way Sensibull ticks its own: the nearest option
 * expiries for the underlying, each a checkbox, stored as a comma-separated
 * string so it stays one ordinary indicator setting.
 *
 * Ticking nothing leaves the string empty, which the indicator reads as "the
 * nearest N", so the boxes show that fallback pre-ticked until the user makes
 * a choice of their own.
 */
const EXPIRY_CHOICES = 8
// The profile endpoint sums at most this many expiries (MAX_EXPIRIES in
// blueprints/oiprofile.py) and drops the rest, so the picker stops there too.
const MAX_PICKED_EXPIRIES = 6

/** Same derivation the OI Profile indicator uses: typed name, else the chart's. */
function underlyingOf(typed: unknown, symbol: string | undefined): string {
  const t = String(typed ?? '')
    .trim()
    .toUpperCase()
  if (t) return t
  return String(symbol ?? '')
    .toUpperCase()
    .replace(/\d{2}[A-Z]{3}\d{2}FUT$/, '')
    .replace(/[^A-Z0-9]/g, '')
}

/** Same Auto rule the OI Profile uses: the BSE indices trade on BFO. */
function exchangeOf(typed: unknown, underlying: string): string {
  const t = String(typed ?? '')
    .trim()
    .toUpperCase()
  if (t && t !== 'AUTO') return t
  return /^(SENSEX|BANKEX)/.test(underlying) ? 'BFO' : 'NFO'
}

/** 22SEP26 -> "22 Sep", which is how a trader reads an expiry off a chain. */
function expiryLabel(e: string): string {
  const m = /^(\d{2})([A-Z]{3})/.exec(e)
  return m ? `${m[1]} ${m[2].charAt(0)}${m[2].slice(1).toLowerCase()}` : e
}

function ExpiryPicker({
  field,
  id,
  value,
  count,
  exchange,
  underlying,
  onChange,
}: {
  field: IndicatorField
  id: string
  value: unknown
  count: number
  exchange: string
  underlying: string
  onChange(v: unknown): void
}) {
  const [available, setAvailable] = useState<string[]>([])

  useEffect(() => {
    // A new underlying's list is not the old one's: clear it at once, so an
    // old expiry can never be ticked and saved while the new list loads, or
    // after it fails to load.
    setAvailable([])
    if (!underlying) return
    let alive = true
    const url =
      `/search/api/expiries?exchange=${encodeURIComponent(exchange)}` +
      `&underlying=${encodeURIComponent(underlying)}&instrumenttype=options`
    fetch(url, { credentials: 'same-origin' })
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => {
        if (!alive) return
        const list = Array.isArray(body?.expiries) ? body.expiries : []
        // The search API answers 26-NOV-25; the profile wants 26NOV25.
        setAvailable(
          list
            .slice(0, EXPIRY_CHOICES)
            .map((e: unknown) => String(e).replace(/-/g, '').toUpperCase())
        )
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [exchange, underlying])

  const picked = String(value ?? '')
    .toUpperCase()
    .split(',')
    .map((e) => e.replace(/[^A-Z0-9]/g, ''))
    .filter(Boolean)
  // Nothing ticked means the indicator's own "nearest N" fallback, so show it.
  const shown = picked.length ? picked : available.slice(0, Math.max(1, count))

  const toggle = (e: string) => {
    const next = shown.includes(e) ? shown.filter((x) => x !== e) : [...shown, e]
    // Keep chain order, not click order, so the string reads like the list.
    onChange(available.filter((x) => next.includes(x)).join(','))
  }

  const label = (
    <span id={id} className="self-start pt-0.5 text-[13px] text-muted-foreground">
      {field.label}
    </span>
  )

  if (available.length === 0) {
    return (
      <>
        {label}
        <span className="text-[13px] text-muted-foreground">
          {underlying ? 'No expiries found' : 'Set an underlying'}
        </span>
      </>
    )
  }

  return (
    <>
      {label}
      <fieldset className="flex min-w-0 flex-col gap-1.5 border-0 p-0" aria-labelledby={id}>
        {available.map((e) => (
          <label key={e} className="flex cursor-pointer items-center gap-2 text-[13px]">
            <TickBox
              id={`${id}-${e}`}
              checked={shown.includes(e)}
              disabled={!shown.includes(e) && shown.length >= MAX_PICKED_EXPIRIES}
              onChange={() => toggle(e)}
            />
            {expiryLabel(e)}
          </label>
        ))}
      </fieldset>
    </>
  )
}

/**
 * Value inputs, bucketed under their `group` heading in first-seen order.
 *
 * Bucketed rather than headed wherever the group changes, because the language
 * says a group is a heading the dialog groups rows under: a script that
 * declares a second "Bands" input further down the file means it to sit with
 * the first, not under a second "Bands" heading. Rows with no group keep the
 * empty key and are drawn without a heading.
 */
function inputGroupsOf(fields: SettingsFieldShape[]): [string, SettingsFieldShape[]][] {
  const out = new Map<string, SettingsFieldShape[]>()
  for (const f of fields) {
    const k = f.group ?? ''
    const list = out.get(k) ?? []
    list.push(f)
    out.set(k, list)
  }
  return [...out]
}

/**
 * One label -> control row, rendered by the field's declared type.
 *
 * Exported because the chart settings dialog renders the same vocabulary: the
 * engine describes its own settings with `IndicatorInput`, so both forms share
 * one control set and a new widget only has to be written once.
 */
export function SettingsField({
  field,
  id,
  value,
  onChange,
  onPick,
}: {
  field: SettingsFieldShape
  id: string
  value: unknown
  onChange(v: unknown): void
  /** Offer a Pick button that fills this input from a click on the chart. */
  onPick?: () => void
}) {
  const label = (
    <label htmlFor={id} title={field.unavailable} className="text-[13px] text-muted-foreground">
      {field.label}
    </label>
  )
  // The declaration's help text, on its own line under the row and spanning
  // both columns. Written out rather than hidden behind a hover, because a
  // hover is not there on a touch screen or to a keyboard, and the sentence is
  // the part of the row that says what the number does.
  const helpId = field.tooltip ? `${id}-help` : undefined
  const problem = numberProblem(field, value)
  const errorId = problem ? `${id}-error` : undefined
  const describedBy = [helpId, errorId].filter(Boolean).join(' ') || undefined
  const pick = onPick ? (
    <button
      type="button"
      onClick={onPick}
      disabled={!!field.unavailable}
      aria-label={`Pick ${field.label} on the chart`}
      className="h-7 shrink-0 rounded border border-border px-1.5 text-[11px] text-muted-foreground transition-colors hover:border-primary hover:text-foreground disabled:opacity-40"
    >
      Pick
    </button>
  ) : null
  const row = (control: ReactNode) => (
    <>
      {label}
      {pick ? (
        <div className="flex w-full min-w-0 items-center gap-1">
          {control}
          {pick}
        </div>
      ) : (
        control
      )}
      {field.tooltip && (
        <p id={helpId} className="col-span-2 -mt-2 text-[11px] leading-snug text-muted-foreground">
          {field.tooltip}
        </p>
      )}
      {problem && (
        <p
          id={errorId}
          aria-live="polite"
          className="col-span-2 -mt-2 text-[11px] text-destructive"
        >
          {problem}
        </p>
      )}
    </>
  )

  if (field.type === 'boolean') {
    return row(
      <TickBox
        id={id}
        checked={value === true}
        onChange={onChange}
        disabled={!!field.unavailable}
      />
    )
  }

  if (field.type === 'color') {
    const v = typeof value === 'string' ? value : '#4f8cff'
    return row(
      <div className="flex items-center gap-2">
        <input
          id={id}
          type="color"
          disabled={!!field.unavailable}
          value={v}
          onChange={(e) => onChange(e.target.value)}
          aria-label={field.label}
          aria-describedby={helpId}
          // A colour control is a swatch, not a bar: square and small enough
          // that a column of them reads as a palette rather than as blocks.
          // Native swatch chrome is bulky, so it is clipped to a flat chip.
          className="h-[26px] w-[26px] cursor-pointer rounded-md border border-border bg-transparent p-0 [&::-moz-color-swatch]:rounded [&::-moz-color-swatch]:border-0 [&::-webkit-color-swatch-wrapper]:p-[3px] [&::-webkit-color-swatch]:rounded [&::-webkit-color-swatch]:border-0"
        />
      </div>
    )
  }

  // 'interval' (2.4.0) is a select like the others: the terminal fills its
  // options with the intervals this broker actually serves, so a study can
  // never be handed a timeframe the feed cannot answer. Falling back to the
  // chart's own interval (the empty value) is what an unfilled list means.
  // An OpenScript study arrives here with its options already rebuilt, since
  // the language takes neither the empty value nor a code such as `D`.
  if (field.type === 'source' || field.type === 'select' || field.type === 'interval') {
    const opts = field.options
      ? field.options.map((o) => ({ label: o.label, value: String(o.value) }))
      : field.type === 'interval'
        ? [{ label: 'Chart interval', value: '' }]
        : (field.type === 'source' ? SOURCES : LINE_STYLES).map((o) => ({
            label: o.charAt(0).toUpperCase() + o.slice(1),
            value: o,
          }))
    return row(
      <div className="relative w-full">
        <select
          id={id}
          disabled={!!field.unavailable}
          value={String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
          aria-describedby={helpId}
          className={cn(CONTROL, 'w-full appearance-none pr-7')}
        >
          {opts.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <svg
          viewBox="0 0 10 10"
          className="pointer-events-none absolute right-2 top-1/2 h-2.5 w-2.5 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        >
          <path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" strokeWidth={1.5} />
        </svg>
      </div>
    )
  }

  // Everything below falls through to the number control, so a string-valued
  // input needs its own branch: `<input type="number">` rejects a value like
  // '0915-1015' outright and renders an empty box with spinner arrows.
  if (TEXT_TYPES.has(field.type)) {
    return row(
      <input
        id={id}
        type="text"
        disabled={!!field.unavailable}
        value={typeof value === 'string' ? value : ''}
        onChange={(e) => onChange(e.target.value)}
        placeholder={TEXT_PLACEHOLDER[field.type]}
        aria-describedby={helpId}
        className={cn(CONTROL, 'w-full min-w-0')}
      />
    )
  }

  const step = field.step ?? 1
  const nudge = (dir: 1 | -1) => {
    const cur = Number(value)
    const next = (Number.isFinite(cur) ? cur : 0) + dir * step
    const clamped = Math.min(
      field.max ?? Number.POSITIVE_INFINITY,
      Math.max(field.min ?? -Number.POSITIVE_INFINITY, next)
    )
    // Step can be fractional (0.5 thickness); round to its precision so the
    // value never drifts into 1.4000000000000001.
    onChange(Number(clamped.toFixed(String(step).split('.')[1]?.length ?? 0)))
  }
  return row(
    <div
      className={cn(
        CONTROL,
        'flex w-full min-w-0 items-center gap-1 p-0 pl-2',
        problem && 'border-destructive'
      )}
    >
      <input
        id={id}
        type="number"
        disabled={!!field.unavailable}
        value={typeof value === 'number' || typeof value === 'string' ? String(value) : ''}
        min={field.min}
        max={field.max}
        step={step}
        onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
        aria-describedby={describedBy}
        aria-invalid={problem ? true : undefined}
        // The native spinner is a bright, oversized chrome control; ours
        // matches the theme and is always visible.
        className="w-full min-w-0 bg-transparent text-[13px] outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
      />
      <span className="flex h-full flex-col justify-center border-l border-border">
        <button
          type="button"
          aria-label="Increase"
          disabled={!!field.unavailable}
          onClick={() => nudge(1)}
          className="flex h-3 w-5 items-center justify-center text-muted-foreground hover:text-foreground"
        >
          <svg viewBox="0 0 10 6" className="h-1.5 w-2.5" aria-hidden="true">
            <path d="M1 5 5 1.5 9 5" fill="none" stroke="currentColor" strokeWidth={1.6} />
          </svg>
        </button>
        <button
          type="button"
          aria-label="Decrease"
          disabled={!!field.unavailable}
          onClick={() => nudge(-1)}
          className="flex h-3 w-5 items-center justify-center text-muted-foreground hover:text-foreground"
        >
          <svg viewBox="0 0 10 6" className="h-1.5 w-2.5" aria-hidden="true">
            <path d="M1 1 5 4.5 9 1" fill="none" stroke="currentColor" strokeWidth={1.6} />
          </svg>
        </button>
      </span>
    </div>
  )
}
