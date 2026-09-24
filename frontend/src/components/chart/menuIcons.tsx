/**
 * The glyphs a chart's own menus use.
 *
 * Hand-drawn rather than taken from the icon set, because these name chart
 * concepts the set has no word for: a price grid, a volume histogram, the
 * drawing tools. They started inside the trading pane and live here because a
 * second chart surface now draws the same menu, and two copies of an icon
 * drift in stroke weight long before anyone notices.
 */

/** Shared stroke, so the set reads as one hand at 16px. */
const glyph = {
  fill: 'none' as const,
  stroke: 'currentColor',
  strokeWidth: 1.7,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

/** The drawing tools. */
export function PencilIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" {...glyph} className={className} aria-hidden="true">
      <path d="M4 20.5h4L20 8.5a2.4 2.4 0 0 0-3.4-3.4L4.5 17z" />
      <path d="M15.5 6.5 18.5 9.5" />
    </svg>
  )
}

/** Three bars of a volume histogram. */
export function VolumeIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M5 20v-6M12 20V8M19 20v-9" />
    </svg>
  )
}

/** The price grid. */
export function GridIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" {...glyph} className={className} aria-hidden="true">
      <path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
    </svg>
  )
}
