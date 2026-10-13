/**
 * Chart construction options for a trader whose operating system asks for
 * less motion: a wheel zoom lands in one frame instead of gliding, and the
 * price range snaps rather than easing. Kinetic pan after a flick is the
 * trader's own gesture continuing, so it stays.
 *
 * Read at every chart build, so a change to the system setting reaches each
 * pane the next time it loads a symbol, an interval or a theme.
 */
export function chartMotionOptions(
  view: Pick<Window, 'matchMedia'> | undefined = globalThis.window
): { animZoom?: false; animAutoscale?: false } {
  if (!view || typeof view.matchMedia !== 'function') return {}
  try {
    return view.matchMedia('(prefers-reduced-motion: reduce)').matches
      ? { animZoom: false, animAutoscale: false }
      : {}
  } catch {
    return {}
  }
}
