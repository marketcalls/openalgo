/**
 * Renko and point and figure settings: the short form behind the button that
 * appears beside the chart type while one of the two is on screen.
 *
 * The chart settings Price tab already lists every option the transform
 * declares. This is the compact form a trader reaches for while looking at the
 * boxes: their colours, a percent preset, the size and how it is measured, the
 * ATR length, the reversal, and which prices move them.
 *
 * It writes exactly what the Price tab writes, as one patch through the same
 * `applyChartSettings`: the `transform.*` keys are kept per instrument and
 * chart type by the terminal, and the colours with the pane's settings. So the
 * two surfaces never disagree, and a choice made here shows in the Price tab.
 * The colour rows are read from the request rather than named here, so the
 * dialog offers exactly the colours the renderer paints.
 */
import {
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ChartSettingsPairField, ChartSettingsRequest } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'
import { ColorPairRow } from './ChartSettingsDialog'
import { CONTROL } from './IndicatorSettingsDialog'

type Value = string | number | boolean
export type BoxChartType = 'renko' | 'point-figure'
type Mode = 'fixed' | 'percent' | 'atr' | 'atrPercent'

interface Props {
  type: BoxChartType
  req: ChartSettingsRequest | null
  onApply(patch: Record<string, Value>): void
  onClose(): void
}

const TITLE: Record<BoxChartType, string> = {
  renko: 'Renko settings',
  'point-figure': 'Point & Figure settings',
}

/** The percent presets each type offers. */
const PRESETS: Record<BoxChartType, number[]> = {
  renko: [0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5],
  'point-figure': [0.05, 0.1, 0.15, 0.25, 0.5, 1, 2, 3],
}

/** The colour rows each renderer reads. A Renko brick spans its open and close exactly, so it has no wick. */
const COLOR_ROWS: Record<BoxChartType, string[]> = {
  renko: ['symbol.body', 'symbol.borders'],
  'point-figure': ['symbol.body'],
}

const MODES: { value: Mode; label: string }[] = [
  { value: 'fixed', label: 'Absolute' },
  { value: 'percent', label: 'Percent' },
  { value: 'atr', label: 'ATR' },
  { value: 'atrPercent', label: 'ATR %' },
]

/** The option the size box edits in each mode: ATR % is a percent of the ATR, so it shares the percent. */
const SIZE_KEY: Record<Mode, string> = {
  fixed: 'transform.boxSize',
  percent: 'transform.percent',
  atr: 'transform.atrMultiplier',
  atrPercent: 'transform.percent',
}

const usesAtr = (mode: Mode) => mode === 'atr' || mode === 'atrPercent'
const asMode = (v: unknown): Mode => (MODES.some((m) => m.value === v) ? (v as Mode) : 'fixed')

/** A preset as its button shows it: two decimals under one percent, whole above. */
const presetText = (p: number) => `${p < 1 ? p.toFixed(2) : String(p)}%`

/** The value a key holds in the draft, as the text its box shows. */
const asText = (v: Value | undefined) => (v === undefined ? '' : String(v))

/** Why a typed size cannot be used, or null. Blank or 0 in Absolute sizes the box from the loaded history. */
function sizeProblem(mode: Mode, text: string): string | null {
  const trimmed = text.trim()
  const n = trimmed === '' && mode === 'fixed' ? 0 : Number(trimmed)
  if (trimmed === '' && mode !== 'fixed') return 'Enter a number above 0'
  if (!Number.isFinite(n))
    return mode === 'fixed' ? 'Enter 0 or a positive number' : 'Enter a number above 0'
  if (mode === 'fixed' ? n < 0 : n <= 0)
    return mode === 'fixed' ? 'Enter 0 or a positive number' : 'Enter a number above 0'
  return null
}

function lengthProblem(text: string): string | null {
  const n = Number(text.trim())
  return text.trim() !== '' && Number.isInteger(n) && n >= 1
    ? null
    : 'Enter a whole number, 1 or more'
}

export function BoxChartSettingsDialog({ type, req, onApply, onClose }: Props) {
  const id = useId()
  const [values, setValues] = useState<Record<string, Value>>({})
  // What the two number boxes show. Kept apart from `values` so a half-typed
  // entry stays visible to be corrected rather than snapping back.
  const [sizeText, setSizeText] = useState('')
  const [lengthText, setLengthText] = useState('')

  const mode = asMode(values['transform.mode'])

  useEffect(() => {
    const next = req ? { ...req.values } : {}
    setValues(next)
    const m = asMode(next['transform.mode'])
    const size = next[SIZE_KEY[m]]
    setSizeText(m === 'fixed' && size === 0 ? '' : asText(size))
    setLengthText(asText(next['transform.atrPeriod'] ?? 14))
  }, [req])

  useLayoutEffect(() => {
    if (!req) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [req, onClose])

  // A modal takes the keyboard while it is open and hands it back when it
  // closes, so Tab cannot wander into the chart controls it covers.
  const dialogRef = useRef<HTMLDivElement>(null)
  const open = req !== null
  useEffect(() => {
    if (!open) return
    const before = document.activeElement as HTMLElement | null
    // The size is the control a trader reaches for, and a visible one: focus on
    // the bare container would show no ring.
    const size = document.getElementById(`${id}-size`)
    ;(size ?? dialogRef.current)?.focus()
    return () => before?.focus?.()
  }, [open, id])
  const keepFocus = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Tab' || !dialogRef.current) return
    const focusable = [
      ...dialogRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled])'
      ),
    ]
    if (focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (
      e.shiftKey &&
      (document.activeElement === first || document.activeElement === dialogRef.current)
    ) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  const colorRows = useMemo(() => {
    const price = req?.tabs.find((t) => t.id === 'price')?.inputs ?? []
    return COLOR_ROWS[type].flatMap((key) =>
      price.filter((f): f is ChartSettingsPairField => f.type === 'colorPair' && f.key === key)
    )
  }, [req, type])

  if (!req) return null

  const set = (key: string, v: unknown) => setValues((prev) => ({ ...prev, [key]: v as Value }))
  const sizeError = sizeProblem(mode, sizeText)
  const lengthError = usesAtr(mode) ? lengthProblem(lengthText) : null

  const chooseMode = (next: Mode) => {
    set('transform.mode', next)
    // A size typed for another method means nothing in this one.
    const size = values[SIZE_KEY[next]]
    setSizeText(next === 'fixed' && size === 0 ? '' : asText(size))
  }
  const typeSize = (text: string) => {
    setSizeText(text)
    if (sizeProblem(mode, text) === null) set(SIZE_KEY[mode], text.trim() === '' ? 0 : Number(text))
  }
  const typeLength = (text: string) => {
    setLengthText(text)
    if (lengthProblem(text) === null) set('transform.atrPeriod', Number(text))
  }
  const preset = (p: number) => {
    setValues((prev) => ({ ...prev, 'transform.mode': 'percent', 'transform.percent': p }))
    setSizeText(String(p))
  }

  /** Send only what changed, the way the chart settings dialog does. */
  const apply = () => {
    if (sizeError || lengthError) {
      document.getElementById(sizeError ? `${id}-size` : `${id}-length`)?.focus()
      return
    }
    const patch: Record<string, Value> = {}
    for (const [k, v] of Object.entries(values)) {
      if (req.values[k] !== v) patch[k] = v
    }
    if (Object.keys(patch).length) onApply(patch)
    onClose()
  }

  // Reset goes back to this terminal's baseline for the keys this dialog owns:
  // the box the terminal sized for the instrument, and the theme's colours.
  const ownKeys = (key: string) =>
    key.startsWith('transform.') ||
    colorRows.some((r) => [r.up.key, r.down.key, r.enabled?.key].includes(key))
  const defaults = Object.fromEntries(Object.entries(req.defaults).filter(([k]) => ownKeys(k)))
  const deviates = Object.entries(defaults).some(
    ([k, v]) => values[k] !== undefined && values[k] !== v
  )
  const reset = () => {
    const next = { ...values, ...defaults }
    setValues(next)
    const m = asMode(next['transform.mode'])
    const size = next[SIZE_KEY[m]]
    setSizeText(m === 'fixed' && size === 0 ? '' : asText(size))
    setLengthText(asText(next['transform.atrPeriod'] ?? 14))
  }

  const heading = (text: string) => (
    <div className="col-span-2 pt-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
      {text}
    </div>
  )
  const error = (fieldId: string, message: string | null) =>
    message && (
      <p
        id={`${fieldId}-error`}
        aria-live="polite"
        className="col-span-2 -mt-2 text-[11px] text-destructive"
      >
        {message}
      </p>
    )
  const unit = mode === 'percent' || mode === 'atrPercent' ? '%' : mode === 'atr' ? 'x ATR' : ''
  const reversal = Number(values['transform.reversal'] ?? 3)

  return (
    <div
      className="absolute inset-0 z-40 flex items-center justify-center bg-black/50"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
      role="presentation"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        tabIndex={-1}
        onKeyDown={keepFocus}
        className="flex max-h-[92%] w-[380px] flex-col rounded-lg border bg-popover shadow-2xl outline-none"
      >
        <div className="flex shrink-0 items-center justify-between px-4 pb-2 pt-3">
          <h3 id={`${id}-title`} className="text-[15px] font-semibold tracking-tight">
            {TITLE[type]}
          </h3>
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

        <div className="min-h-0 flex-1 overflow-y-auto border-t px-4 py-3">
          <div className="grid grid-cols-[minmax(0,1fr)_170px] items-center gap-x-5 gap-y-3">
            {colorRows.length > 0 && heading('Colors')}
            {colorRows.map((row) => (
              <ColorPairRow key={row.key} field={row} values={values} onChange={set} />
            ))}

            {heading(type === 'renko' ? 'Brick size' : 'Box size')}
            <fieldset
              className="col-span-2 m-0 flex min-w-0 flex-wrap gap-1.5 border-0 p-0"
              aria-label="Percent presets"
            >
              {PRESETS[type].map((p) => {
                const on = mode === 'percent' && values['transform.percent'] === p && !sizeError
                return (
                  <button
                    key={p}
                    type="button"
                    aria-pressed={on}
                    onClick={() => preset(p)}
                    className={cn(
                      'h-6 rounded border px-2 text-[12px] tabular-nums transition-colors',
                      on
                        ? 'border-primary bg-primary/15 text-foreground'
                        : 'border-border text-muted-foreground hover:border-foreground/40 hover:text-foreground'
                    )}
                  >
                    {presetText(p)}
                  </button>
                )
              })}
            </fieldset>

            <label htmlFor={`${id}-size`} className="text-[13px] text-muted-foreground">
              Size
            </label>
            <div className="flex min-w-0 items-center gap-1.5">
              <input
                id={`${id}-size`}
                type="text"
                inputMode="decimal"
                value={sizeText}
                placeholder={mode === 'fixed' ? 'Auto' : ''}
                title={mode === 'fixed' ? 'Blank or 0 sizes it from the loaded history' : undefined}
                onChange={(e) => typeSize(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && apply()}
                aria-invalid={sizeError ? true : undefined}
                aria-describedby={sizeError ? `${id}-size-error` : undefined}
                className={cn(
                  CONTROL,
                  'w-full min-w-0 tabular-nums',
                  sizeError && 'border-destructive'
                )}
              />
              {unit && <span className="shrink-0 text-[12px] text-muted-foreground">{unit}</span>}
            </div>
            {error(`${id}-size`, sizeError)}

            <label htmlFor={`${id}-mode`} className="text-[13px] text-muted-foreground">
              Measured as
            </label>
            <Select id={`${id}-mode`} value={mode} onChange={(v) => chooseMode(v as Mode)}>
              {MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </Select>

            {usesAtr(mode) && (
              <>
                <label htmlFor={`${id}-length`} className="text-[13px] text-muted-foreground">
                  ATR length
                </label>
                <input
                  id={`${id}-length`}
                  type="text"
                  inputMode="numeric"
                  value={lengthText}
                  onChange={(e) => typeLength(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && apply()}
                  aria-invalid={lengthError ? true : undefined}
                  aria-describedby={lengthError ? `${id}-length-error` : undefined}
                  className={cn(
                    CONTROL,
                    'w-full min-w-0 tabular-nums',
                    lengthError && 'border-destructive'
                  )}
                />
                {error(`${id}-length`, lengthError)}
              </>
            )}

            {heading('Construction')}
            {type === 'point-figure' && (
              <>
                <label htmlFor={`${id}-reversal`} className="text-[13px] text-muted-foreground">
                  Reversal
                </label>
                <Select
                  id={`${id}-reversal`}
                  value={String(reversal)}
                  onChange={(v) => set('transform.reversal', Number(v))}
                >
                  {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => (
                    <option key={n} value={n}>
                      {n === 1 ? '1 box' : `${n} boxes`}
                    </option>
                  ))}
                </Select>
              </>
            )}
            <span className="text-[13px] text-muted-foreground" id={`${id}-prices`}>
              Prices
            </span>
            <div className="flex flex-col gap-1" role="radiogroup" aria-labelledby={`${id}-prices`}>
              {(
                [
                  ['close', 'Close only'],
                  ['hl', 'High and low'],
                ] as const
              ).map(([value, label]) => (
                <label key={value} className="flex items-center gap-2 text-[13px]">
                  <input
                    type="radio"
                    name={`${id}-method`}
                    value={value}
                    checked={values['transform.method'] === value}
                    onChange={() => set('transform.method', value)}
                    className="accent-primary"
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>
        </div>

        <div className="flex shrink-0 items-center justify-between gap-2 border-t px-4 py-2.5">
          <button
            type="button"
            disabled={!deviates}
            onClick={reset}
            title={
              deviates
                ? 'Restore the size, construction and colours to their defaults'
                : 'Already at the defaults'
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

/** A select in the dialog's control chrome, with the shared chevron rather than the native one. */
function Select({
  id,
  value,
  onChange,
  children,
}: {
  id: string
  value: string
  onChange(v: string): void
  children: ReactNode
}) {
  return (
    <div className="relative w-full">
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(CONTROL, 'w-full appearance-none pr-7')}
      >
        {children}
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
