import { useEffect, useRef } from 'react'
import { applyChartDialogMetrics, buildChartTheme, isLightTheme } from '@/lib/trading/chartTheme'
import type { BottomBarPane, TradingBottomBar } from '@/lib/trading/bottomBar'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

/**
 * The library's strip height (`BOTTOMBAR_HEIGHT`). The page keeps this much
 * clear under the grid from the first render, before the bar's code arrives.
 */
export const BOTTOM_BAR_PX = 28

export interface BottomBarControl {
  paneLoaded(pane: BottomBarPane): void
}

/**
 * One bottom bar for the whole grid, acting on the focused pane.
 *
 * The bar fills the strip the page keeps clear once the widget tier has
 * loaded, so the chart neither waits for it nor jumps when it arrives. Its
 * root spans the grid column, so Go to and the timezone menu open over the
 * charts rather than clipped inside 28px; only the strip and those popovers
 * take the pointer.
 */
export function ChartBottomBar({
  pane,
  panes,
  focusKey,
  control,
}: {
  /** The focused pane, read at every use. */
  pane(): BottomBarPane | null
  /** Every pane that is up, for putting saved ranges back once the bar loads. */
  panes(): BottomBarPane[]
  /** Changes when focus moves, so the bar re-reads at once rather than on its next tick. */
  focusKey: string
  control: React.MutableRefObject<BottomBarControl | null>
}) {
  const rootRef = useRef<HTMLDivElement>(null)
  const barRef = useRef<TradingBottomBar | null>(null)
  const paneRef = useRef(pane)
  paneRef.current = pane
  const panesRef = useRef(panes)
  panesRef.current = panes
  const { mode, appMode } = useThemeStore()

  useEffect(() => {
    let alive = true
    const root = rootRef.current
    if (!root) return
    import('@/lib/trading/bottomBar')
      .then(({ mountTradingBottomBar }) => {
        if (!alive) return
        const bar = mountTradingBottomBar(root, {
          pane: () => paneRef.current(),
          notify: (text, kind) => (kind === 'error' ? showToast.error(text) : showToast.info(text)),
        })
        const { mode: m, appMode: a } = useThemeStore.getState()
        bar.setTheme(buildChartTheme(m, a), isLightTheme(m, a) ? 'light' : 'dark')
        applyChartDialogMetrics(root)
        barRef.current = bar
        control.current = { paneLoaded: (p) => bar.paneLoaded(p) }
        for (const p of panesRef.current()) bar.paneLoaded(p)
      })
      .catch(() => {
        // Without the bar the charts work exactly as before; the strip stays empty.
      })
    return () => {
      alive = false
      control.current = null
      barRef.current?.destroy()
      barRef.current = null
    }
  }, [control])

  // biome-ignore lint/correctness/useExhaustiveDependencies: focusKey is the trigger
  useEffect(() => {
    barRef.current?.refresh()
  }, [focusKey])

  useEffect(() => {
    const bar = barRef.current
    const root = rootRef.current
    if (!bar || !root) return
    // After the app has switched its tokens, as the panes do.
    const frame = requestAnimationFrame(() => {
      bar.setTheme(buildChartTheme(mode, appMode), isLightTheme(mode, appMode) ? 'light' : 'dark')
      applyChartDialogMetrics(root)
    })
    return () => cancelAnimationFrame(frame)
  }, [mode, appMode])

  return (
    <div ref={rootRef} className="pointer-events-none absolute inset-0" data-trading-bottombar />
  )
}
