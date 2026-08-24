/**
 * The one checkbox every terminal panel uses.
 *
 * It exists because there were three of them. The chart and indicator dialogs
 * each carried their own copy of a masked-tick control, the plot-style row and
 * the drawing text dialog fell back to `accent-color` on a native box, and the
 * three did not look alike in the same panel. Parity here is structural: there
 * is one control, so there is nothing to keep in sync.
 *
 * Why the whole control is drawn rather than tinted: `accent-color` only tints
 * the CHECKED state. A native unchecked box stays white and reads as a hole
 * punched in a dark panel, which is the tell the UI standard calls out.
 *
 * Why the tick is a real `<svg>` and not a CSS mask. The previous copies drew
 * it with `checked:after:[mask:url("data:image/svg+xml,...")]`, and TWO
 * separate faults meant nothing ever appeared:
 *
 *  1. The tick was painted `bg-[hsl(var(--primary-foreground))]`. This app
 *     carries two token systems -- an early `@layer base` block defining HSL
 *     channel triplets, and a later `:root` / `.dark` pair redefining the same
 *     names as complete `oklch(...)` colours. The later block wins, so that
 *     expands to `hsl(oklch(...))`, which is not a colour, and the declaration
 *     is dropped. Tailwind v4's `@theme` maps `--color-primary-foreground` to
 *     whichever value is live, so the plain `bg-primary-foreground` /
 *     `text-primary-foreground` utilities are correct under both systems. Do
 *     not reintroduce an `hsl(var(--x))` anywhere in this file.
 *  2. The arbitrary `[mask:url(...)]` utility was never emitted at all --
 *     confirmed in the browser, where the pseudo-element's computed
 *     `mask-image` came back `none`. With the colour fixed but the mask still
 *     missing, the tick would have become a solid filled square covering the
 *     whole box, which is worse than the blank one it replaced.
 *
 * An inline SVG toggled by `peer-checked` has neither failure mode: it is an
 * element that either renders or does not, it inherits its colour through
 * `currentColor`, and it needs no icon font.
 */
import { cn } from '@/lib/utils'

interface Props {
  checked: boolean
  onChange(next: boolean): void
  /** Omit only when a wrapping `<label>` already names the control. */
  label?: string
  id?: string
  disabled?: boolean
  /** Applied to the wrapper, so callers can adjust spacing, not the box. */
  className?: string
}

export function TickBox({ checked, onChange, label, id, disabled, className }: Props) {
  return (
    <span
      className={cn('relative inline-flex h-4 w-4 shrink-0 items-center justify-center', className)}
    >
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        aria-label={label}
        className={cn(
          'peer h-4 w-4 cursor-pointer appearance-none rounded-[4px] border border-border bg-background',
          'transition-colors hover:border-muted-foreground',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background',
          'disabled:cursor-not-allowed disabled:opacity-40',
          'checked:border-primary checked:bg-primary'
        )}
      />
      <svg
        viewBox="0 0 16 16"
        className="pointer-events-none absolute h-3 w-3 text-primary-foreground opacity-0 peer-checked:opacity-100"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M3.5 8.5l3 3 6-6" />
      </svg>
    </span>
  )
}
