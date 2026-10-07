/**
 * The price scale's own right-click menu.
 *
 * Opened by a right-click on the price axis, where the chart menu with its
 * order rows used to open. Everything here acts on what the scale shows: how
 * it fits, which way up it reads, its mode, its side, and the levels tagged on
 * it. Every choice goes through the pane's chart settings, so it is kept.
 *
 * A level with no data is greyed and says so rather than being hidden: "no
 * previous session loaded" and "no order book" are information. One that is
 * already on can still be switched off, so a level turned on yesterday is never
 * stuck on a morning with no book yet.
 *
 * The level switches keep the menu open, since a trader usually sets more than
 * one; every other row closes it.
 */
import type { PriceAxisCommand, PriceAxisMenu } from '@/lib/trading/priceAxis'
import { AXIS_CHORDS, SCALE_MODES } from '@/lib/trading/priceAxis'
import { cn } from '@/lib/utils'

interface Props {
  menu: PriceAxisMenu
  x: number
  y: number
  /** Run a command. `keepOpen` is set for the level switches. */
  onCommand(command: PriceAxisCommand, keepOpen: boolean): void
  /** Open Chart settings on its Axes tab. */
  onSettings(): void
}

const row =
  'flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left text-[13px] hover:bg-accent hover:text-accent-foreground'

function Chord({ text }: { text?: string }) {
  if (!text) return null
  return <span className="ml-auto pl-3 text-[11px] text-muted-foreground">{text}</span>
}

/** A drawn checkbox or radio mark, so the state reads without a glyph. */
function Mark({ on, radio }: { on: boolean; radio?: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'flex h-3 w-3 shrink-0 items-center justify-center border',
        radio ? 'rounded-full' : 'rounded-sm',
        on ? 'border-primary' : 'border-muted-foreground/50',
        on && !radio && 'bg-primary'
      )}
    >
      {on && radio && <span className="h-1.5 w-1.5 rounded-full bg-primary" />}
    </span>
  )
}

function Heading({ children }: { children: string }) {
  return (
    <div className="px-2 pb-0.5 pt-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
      {children}
    </div>
  )
}

const Separator = () => <div className="my-1 h-px bg-border" />

export function PriceScaleMenu({ menu, x, y, onCommand, onSettings }: Props) {
  const run = (command: PriceAxisCommand) => onCommand(command, false)
  const toggle = (label: string, on: boolean, command: PriceAxisCommand, chord?: string) => (
    <button
      type="button"
      role="menuitemcheckbox"
      aria-checked={on}
      className={row}
      onClick={() => run(command)}
    >
      <Mark on={on} />
      {label}
      <Chord text={chord} />
    </button>
  )
  const other = menu.side === 'right' ? 'left' : 'right'

  return (
    <div
      role="menu"
      aria-label="Price scale"
      className="fixed z-50 max-h-[calc(100vh-8px)] w-60 overflow-y-auto rounded-md border bg-popover p-1 shadow-lg"
      style={{ left: x, top: y }}
    >
      {toggle('Auto-fit to the data', menu.autoFit, { type: 'autoFit' }, AXIS_CHORDS.autoFit)}
      {toggle('Fit to primary prices only', menu.priceOnly, { type: 'priceOnly' })}
      {toggle('Invert scale', menu.inverted, { type: 'invert' }, AXIS_CHORDS.invert)}
      <button type="button" role="menuitem" className={row} onClick={() => run({ type: 'reset' })}>
        <span className="w-3 shrink-0" />
        Reset price scale
        <Chord text={AXIS_CHORDS.reset} />
      </button>

      <Separator />
      <Heading>Scale</Heading>
      {SCALE_MODES.map((mode) => (
        <button
          type="button"
          key={mode.value}
          role="menuitemradio"
          aria-checked={menu.mode === mode.value}
          className={row}
          onClick={() => run({ type: 'mode', mode: mode.value })}
        >
          <Mark on={menu.mode === mode.value} radio />
          {mode.label}
          <Chord text={mode.chord} />
        </button>
      ))}

      <Separator />
      <button
        type="button"
        role="menuitem"
        className={row}
        onClick={() => run({ type: 'side', side: other })}
      >
        <span className="w-3 shrink-0" />
        {other === 'left' ? 'Move scale to the left' : 'Move scale to the right'}
      </button>

      <Separator />
      <Heading>Price levels</Heading>
      {menu.levels.map((level) => (
        <div key={level.kind} className="flex items-center gap-2 px-2 py-0.5 text-[13px]">
          <span className={cn('min-w-0 flex-1 truncate', !level.available && 'opacity-50')}>
            {level.label}
            {!level.available && (
              <span className="ml-1.5 text-[11px] text-muted-foreground">no data</span>
            )}
          </span>
          {(['line', 'tag'] as const).map((half) => {
            const on = half === 'line' ? level.line : level.tag
            // Off with nothing to draw stays off; on can always be switched off.
            const disabled = !level.available && !on
            return (
              <button
                type="button"
                key={half}
                aria-pressed={on}
                aria-label={`${level.label} ${half === 'line' ? 'line' : 'axis tag'}`}
                disabled={disabled}
                title={disabled ? `No ${level.label.toLowerCase()} to show yet` : undefined}
                className={cn(
                  'rounded border px-1.5 py-px text-[11px] transition-colors',
                  on
                    ? 'border-primary/60 bg-primary/15 text-foreground'
                    : 'border-border text-muted-foreground hover:bg-accent hover:text-foreground',
                  disabled && 'cursor-not-allowed opacity-40 hover:bg-transparent'
                )}
                onClick={(e) => {
                  // The menu closes on any window click; this one keeps it.
                  e.stopPropagation()
                  onCommand({ type: 'level', kind: level.kind, half, on: !on }, true)
                }}
              >
                {half === 'line' ? 'Line' : 'Tag'}
              </button>
            )
          })}
        </div>
      ))}

      <Separator />
      <button type="button" role="menuitem" className={row} onClick={onSettings}>
        <span className="w-3 shrink-0" />
        Chart settings...
      </button>
    </div>
  )
}
