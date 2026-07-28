/**
 * One plot's row in an indicator's Style tab: an enable checkbox, the plot
 * title, and a combined colour + line preview button that opens the full
 * appearance popover (palette, opacity, thickness, line style).
 *
 * The style inputs the registry generates are flat (`<plot>:color`,
 * `<plot>:opacity`, ...) but each carries the plot title as its `group`, so the
 * form can present them per plot the way a charting package does.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { IndicatorField } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'

/** 10x10 palette: a greyscale row, then hue columns light→dark. */
const HUES = [
  '#f23645', '#ff9800', '#ffd700', '#4caf50', '#00bcd4',
  '#2196f3', '#3f51b5', '#673ab7', '#9c27b0', '#e91e63',
]
const GREYS = [
  '#ffffff', '#e0e0e0', '#c7c7c7', '#adadad', '#949494',
  '#7a7a7a', '#616161', '#474747', '#2e2e2e', '#000000',
]
/** Mix a hue toward white (t<0) or black (t>0). */
function shade(hex: string, t: number): string {
  const n = Number.parseInt(hex.slice(1), 16)
  const to = t >= 0 ? 0 : 255
  const k = Math.abs(t)
  const ch = (v: number) => Math.round(v + (to - v) * k)
  const r = ch((n >> 16) & 255)
  const g = ch((n >> 8) & 255)
  const b = ch(n & 255)
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`
}
const TINTS = [-0.7, -0.45, -0.2, 0, 0.2, 0.4, 0.55, 0.7]
const WIDTHS = [1, 2, 3, 4]
const DASHES: { value: string; dash: string }[] = [
  { value: 'solid', dash: '' },
  { value: 'dashed', dash: '6 4' },
  { value: 'dotted', dash: '1.5 4' },
]

interface Props {
  title: string
  fields: IndicatorField[]
  values: Record<string, unknown>
  onChange(key: string, v: unknown): void
}

export function PlotStyleRow({ title, fields, values, onChange }: Props) {
  const [open, setOpen] = useState(false)
  const [at, setAt] = useState<{ top: number; left: number }>({ top: 0, left: 0 })
  const ref = useRef<HTMLDivElement>(null)
  const btnRef = useRef<HTMLButtonElement>(null)

  /**
   * The dialog body scrolls, and an absolutely-positioned popover inside it
   * gets clipped — which is also what was forcing a scrollbar to appear. A
   * fixed popover is positioned against the viewport instead, so no ancestor's
   * overflow can touch it; flip it above the button when it would run off the
   * bottom.
   */
  const place = useCallback(() => {
    const r = btnRef.current?.getBoundingClientRect()
    if (!r) return
    const H = 380
    const W = 248
    const below = r.bottom + 6
    const top = below + H > window.innerHeight ? Math.max(8, r.top - H - 6) : below
    setAt({ top, left: Math.max(8, Math.min(r.right - W, window.innerWidth - W - 8)) })
  }, [])

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    // Re-place rather than drift: the popover is fixed, so a scroll or resize
    // would otherwise leave it detached from its button.
    const reposition = () => place()
    window.addEventListener('mousedown', close)
    window.addEventListener('resize', reposition)
    window.addEventListener('scroll', reposition, true)
    return () => {
      window.removeEventListener('mousedown', close)
      window.removeEventListener('resize', reposition)
      window.removeEventListener('scroll', reposition, true)
    }
  }, [open, place])

  const find = (t: string, label?: string) =>
    fields.find((f) => (label ? f.label === label : f.type === t))
  const colorF = fields.find((f) => f.type === 'color')
  const opacityF = find('number', 'Opacity')
  const widthF = find('number', 'Thickness')
  const dashF = find('select', 'Line style')

  const color = (colorF && (values[colorF.key] as string)) || '#4f8cff'
  const opacity = opacityF ? Number(values[opacityF.key] ?? 100) : 100
  const width = widthF ? Number(values[widthF.key] ?? 1.5) : 1.5
  const dash = dashF ? String(values[dashF.key] ?? 'solid') : 'solid'
  const dashArray = DASHES.find((d) => d.value === dash)?.dash ?? ''

  /** Choosing a swatch is a decision, so it commits and dismisses. */
  const pickColor = (c: string) => {
    if (colorF) onChange(colorF.key, c)
    setOpen(false)
  }

  // The checkbox is opacity-driven: the registry generates no per-plot visible
  // flag, and zero opacity is exactly "drawn but invisible".
  const enabled = opacity > 0
  const toggle = () => opacityF && onChange(opacityF.key, enabled ? 0 : 100)

  return (
    <div className="flex items-center gap-2.5" ref={ref}>
      <input
        type="checkbox"
        checked={enabled}
        onChange={toggle}
        aria-label={`${title} visible`}
        className="h-3.5 w-3.5 accent-[hsl(var(--primary))]"
      />
      <span className="flex-1 truncate text-[13px]">{title}</span>

      <div className="relative">
        <button
          type="button"
          ref={btnRef}
          onClick={() => {
            place()
            setOpen((v) => !v)
          }}
          aria-label={`${title} appearance`}
          className={cn(
            'flex h-7 w-[76px] items-center gap-1.5 rounded border px-1.5 transition-colors',
            open ? 'border-primary' : 'border-border hover:border-muted-foreground'
          )}
        >
          <span
            className="h-4 w-4 shrink-0 rounded-sm"
            style={{ background: color, opacity: Math.max(0.15, opacity / 100) }}
          />
          <svg viewBox="0 0 40 12" className="h-3 flex-1" aria-hidden="true">
            <line
              x1="1" y1="6" x2="39" y2="6"
              stroke={color}
              strokeWidth={Math.min(4, width)}
              strokeDasharray={dashArray}
              opacity={Math.max(0.15, opacity / 100)}
            />
          </svg>
        </button>

        {open && (
          <div
            className="fixed z-[60] w-[248px] rounded-md border bg-popover p-2.5 shadow-2xl"
            style={{ top: at.top, left: at.left }}
          >
            {/* Palette */}
            <div className="grid grid-cols-10 gap-1">
              {GREYS.map((c) => (
                <Swatch key={c} c={c} on={c === color} pick={() => pickColor(c)} />
              ))}
              {TINTS.map((t) =>
                HUES.map((h) => {
                  const c = shade(h, t)
                  return (
                    <Swatch key={`${h}${t}`} c={c} on={c === color} pick={() => pickColor(c)} />
                  )
                })
              )}
            </div>

            {/* Custom colour */}
            <label className="mt-2 flex w-fit cursor-pointer items-center gap-1 text-muted-foreground hover:text-foreground">
              <span className="text-lg leading-none">+</span>
              <input
                type="color"
                value={color}
                onChange={(e) => colorF && onChange(colorF.key, e.target.value)}
                aria-label="Custom colour"
                className="h-0 w-0 opacity-0"
              />
            </label>

            {opacityF && (
              <>
                <p className="mt-2 text-[11px] text-muted-foreground">Opacity</p>
                <div className="mt-1 flex items-center gap-2">
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={opacity}
                    onChange={(e) => onChange(opacityF.key, Number(e.target.value))}
                    aria-label="Opacity"
                    className="h-1 flex-1 accent-[hsl(var(--primary))]"
                    style={{
                      background: `linear-gradient(to right, transparent, ${color})`,
                      borderRadius: 999,
                    }}
                  />
                  <span className="w-11 rounded border border-border px-1 text-center text-[12px]">
                    {opacity}%
                  </span>
                </div>
              </>
            )}

            {widthF && (
              <>
                <p className="mt-2.5 text-[11px] text-muted-foreground">Thickness</p>
                <div className="mt-1 grid grid-cols-4 gap-1">
                  {WIDTHS.map((w) => (
                    <button
                      type="button"
                      key={w}
                      onClick={() => onChange(widthF.key, w)}
                      aria-label={`${w} px`}
                      className={cn(
                        'flex h-7 items-center justify-center rounded border',
                        Math.round(width) === w ? 'border-primary' : 'border-border hover:bg-accent'
                      )}
                    >
                      <span className="w-6 rounded bg-foreground" style={{ height: w }} />
                    </button>
                  ))}
                </div>
              </>
            )}

            {dashF && (
              <>
                <p className="mt-2.5 text-[11px] text-muted-foreground">Line style</p>
                <div className="mt-1 grid grid-cols-3 gap-1">
                  {DASHES.map((d) => (
                    <button
                      type="button"
                      key={d.value}
                      onClick={() => onChange(dashF.key, d.value)}
                      aria-label={d.value}
                      className={cn(
                        'flex h-7 items-center justify-center rounded border',
                        dash === d.value ? 'border-primary' : 'border-border hover:bg-accent'
                      )}
                    >
                      <svg viewBox="0 0 40 8" className="h-2 w-9" aria-hidden="true">
                        <line
                          x1="1" y1="4" x2="39" y2="4"
                          stroke="currentColor" strokeWidth={2} strokeDasharray={d.dash}
                        />
                      </svg>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function Swatch({ c, on, pick }: { c: string; on: boolean; pick(): void }) {
  return (
    <button
      type="button"
      onClick={pick}
      aria-label={c}
      style={{ background: c }}
      className={cn('h-4 w-4 rounded-[3px]', on ? 'ring-2 ring-primary ring-offset-1 ring-offset-popover' : '')}
    />
  )
}
