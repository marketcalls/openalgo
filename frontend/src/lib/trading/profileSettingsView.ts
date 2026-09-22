import { isProfileKind, profileDefaults, profileFields, profileValues } from './profileSettings'
import type { ChartSettingsRequest } from './terminal'

/** Replace only the series-specific section of the existing Price tab. */
export function profileSettingsView(
  request: ChartSettingsRequest,
  chartType: string,
  saved: Record<string, unknown>
): ChartSettingsRequest {
  if (!isProfileKind(chartType)) return request
  const tabs = request.tabs.map((tab) =>
    tab.id === 'price'
      ? {
          ...tab,
          description:
            chartType === 'session-volume-profile'
              ? 'Volume is estimated from the loaded OHLCV bars. Up/Down volume follows candle direction.'
              : 'Each letter represents a time block at a price. Profiles use the loaded intraday history.',
          inputs: [
            ...profileFields(chartType),
            ...tab.inputs.filter((input) => input.group === 'Values'),
          ],
        }
      : tab
  )
  const keys = new Set(
    tabs.flatMap((tab) =>
      tab.inputs.flatMap((field) => {
        if (field.type === 'colorPair' && 'up' in field) {
          return [field.up.key, field.down.key, ...(field.enabled ? [field.enabled.key] : [])]
        }
        return [field.key]
      })
    )
  )
  const visible = (values: ChartSettingsRequest['values']) =>
    Object.fromEntries(Object.entries(values).filter(([key]) => keys.has(key)))
  return {
    tabs,
    values: visible({ ...request.values, ...profileValues(chartType, saved) }),
    defaults: visible({ ...request.defaults, ...profileDefaults(chartType) }),
  }
}
