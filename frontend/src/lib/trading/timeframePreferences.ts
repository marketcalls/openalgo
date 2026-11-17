import { createTimeframePreferences, type TimeframePreferences } from 'openalgo-charts/widget'

let shared: TimeframePreferences | undefined
/** Shared choices, separate from each pane's selected interval and layout. */
export function chartTimeframePreferences(): TimeframePreferences {
  if (!shared) {
    let storage: Storage | null = null
    try {
      storage = localStorage
    } catch {
      /* Private browsing can block storage. */
    }
    shared = createTimeframePreferences({
      storage,
      key: 'openalgo-chart-timeframes',
      defaults: ['1m', '5m', '15m', '1h', 'D'],
    })
  }
  return shared
}
