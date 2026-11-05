/**
 * One line weight for every glyph around the chart.
 *
 * The engine draws its chrome set on a 16 unit grid for 16px and its tool set
 * on a 24 unit grid for 20px, both at about 1.3px of line. A glyph shown at
 * another size keeps that line by scaling its stroke against the size it is
 * shown at, which is what the engine asks of a host. The few glyphs the engine
 * has no picture for come from the app's icon set, and `lineStroke24` gives
 * them the same 1.3px, so the toolbar, both rails and their menus read as one
 * set rather than three.
 */
import type { ReactNode } from 'react'
import {
  CHROME_ICON_ACCENT_PATHS,
  CHROME_ICON_FILLED_IDS,
  CHROME_ICON_PATHS,
  CHROME_ICON_SIZE,
  CHROME_ICON_STROKE,
  TOOL_ICON_ACCENT_PATHS,
  TOOL_ICON_SIZE,
  TOOL_ICON_STROKE,
} from './chromeIcons'

/** The engine's line, in CSS pixels, at the size each set is drawn for. */
const LINE_PX = (CHROME_ICON_STROKE * CHROME_ICON_SIZE) / 16

/** Stroke, in viewBox units, that keeps a chrome glyph at the engine's line when shown at `size`. */
export function chromeStroke(size: number): number {
  return (CHROME_ICON_STROKE * CHROME_ICON_SIZE) / size
}

/** Stroke, in viewBox units, that keeps a tool glyph at the engine's line when shown at `size`. */
export function toolStroke(size: number): number {
  return (TOOL_ICON_STROKE * TOOL_ICON_SIZE) / size
}

/** Stroke for any other glyph on a 24 unit grid (the app's icon set), shown at `size`. */
export function lineStroke24(size: number): number {
  return (LINE_PX * 24) / size
}

/** Whether the engine draws a chrome glyph under this id. */
export function hasChromeIcon(id: string): boolean {
  return id in CHROME_ICON_PATHS
}

/**
 * An engine chrome glyph, stroked in the current text colour. Glyphs the
 * engine marks as solid are filled as well, and its accent marks (a slider's
 * knob, a lens's pupil) are painted over the outline, exactly as its own
 * markup builder does.
 */
export function ChromeIcon({
  id,
  size = CHROME_ICON_SIZE,
  className,
}: {
  id: string
  size?: number
  className?: string
}): ReactNode {
  const d = CHROME_ICON_PATHS[id]
  if (!d) return null
  const accent = CHROME_ICON_ACCENT_PATHS[id]
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      fill={CHROME_ICON_FILLED_IDS.has(id) ? 'currentColor' : 'none'}
      stroke="currentColor"
      strokeWidth={chromeStroke(size)}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      <path d={d} />
      {accent && <path d={accent} fill="currentColor" stroke="none" />}
    </svg>
  )
}

/**
 * A tool-grid glyph from its path data, with the tool's accent marks filled.
 * It carries its own width and height (the rail's 20px unless `size` says
 * otherwise): an SVG with only a viewBox falls back to 300 by 150 wherever a
 * container does not size it, and the cursor glyph sits in a bare button.
 */
export function toolGlyph(
  path: string,
  accentId: string | undefined,
  size: number = TOOL_ICON_SIZE,
  className?: string
): ReactNode {
  const accent = accentId ? TOOL_ICON_ACCENT_PATHS[accentId] : undefined
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={toolStroke(size)}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      <path d={path} />
      {accent && <path d={accent} fill="currentColor" stroke="none" />}
    </svg>
  )
}
