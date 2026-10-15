/**
 * The vocabulary of the terminal's toolbar row, written once.
 *
 * The row used to be a run of outlined pills, each control in its own box,
 * which made thirty controls read as thirty separate things. A control here is
 * its glyph and its label on the bar's own surface: a fill appears under the
 * pointer, a soft tint of the mode's accent marks a toggle that is on, and the
 * groups are told apart by hairline dividers rather than by boxes. Every
 * control is 28px tall, so the row reads as one band whatever is in it.
 *
 * ChartPane, the workspace controls on the page and the menus that bring their
 * own trigger (Compare, Workspaces, Templates) all read these, so restyling the
 * row is an edit here rather than a sweep through five files.
 */
import { ChromeIcon } from '@/lib/trading/glyphs'
import { cn } from '@/lib/utils'

/** A toolbar control at rest: label and glyph only, a fill on hover. */
export const TB_BTN =
  'inline-flex h-7 shrink-0 select-none items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-1.5 text-[13px] font-medium leading-none text-foreground/80 outline-none transition-colors duration-100 hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/60 active:bg-accent/70 disabled:pointer-events-none disabled:opacity-35 data-[state=open]:bg-accent data-[state=open]:text-foreground [&_svg]:shrink-0'

/** Layered onto TB_BTN for a square, glyph-only control. */
export const TB_ICON = 'w-7 px-0'

/**
 * Layered onto TB_BTN while a toggle is on or a mode is running: a soft fill
 * in the accent of the current mode. The accent is the app's primary, so it is
 * the operator's neutral or colour in Live and the violet in Analyze.
 */
export const TB_ON =
  'bg-primary/15 text-primary hover:bg-primary/20 hover:text-primary data-[state=open]:bg-primary/20 data-[state=open]:text-primary'

/** A label that gives way to its glyph below 1536px; the button keeps an aria-label. */
export const TB_LABEL_2XL = 'hidden 2xl:inline'

/** A label for the less used controls, shown only where the row has room for all of them. */
export const TB_LABEL_WIDE = 'hidden min-[1800px]:inline'

/** The count chip Indicators and Compare wear. */
export const TB_COUNT =
  'rounded bg-primary/15 px-1 py-0.5 text-[10px] font-semibold leading-none text-primary tabular-nums'

/** A hairline between groups: shorter than the controls, centred on them. */
export function ToolbarDivider({ className }: { className?: string }) {
  return (
    <div aria-hidden="true" className={cn('mx-0.5 h-[18px] w-px shrink-0 bg-border', className)} />
  )
}

/**
 * The small caret after a control that opens a list rather than acting at
 * once, so the two kinds of control can be told apart before either is pressed.
 */
export function MenuChevron() {
  return <ChromeIcon id="chevron-down" size={10} className="-ml-1 opacity-60" />
}
