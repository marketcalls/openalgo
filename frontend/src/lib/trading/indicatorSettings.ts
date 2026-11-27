import type { IndicatorBarSource, IndicatorInputCondition, SeriesApi } from 'openalgo-charts'
import { isKnownInterval } from 'openalgo-charts'
import { isScriptInstance } from './openscriptFiles'
import type { IndicatorField, IndicatorSettingsRequest } from './terminal'

export function toField(f: {
  key: string
  type: string
  label?: string
  group?: string
}): IndicatorField {
  return {
    key: f.key,
    type: f.type,
    label: f.label ?? f.key,
    group: f.group,
    tooltip: (f as { tooltip?: string }).tooltip,
    options: (f as { options?: { label: string; value: unknown }[] }).options,
    min: (f as { min?: number }).min,
    max: (f as { max?: number }).max,
    step: (f as { step?: number }).step,
    visibleWhen: (f as { visibleWhen?: IndicatorInputCondition }).visibleWhen,
    ...((f as { timeKey?: string }).timeKey
      ? { timeKey: (f as { timeKey?: string }).timeKey }
      : {}),
    ...((f as { pick?: IndicatorField['pick'] }).pick !== undefined
      ? { pick: (f as { pick?: IndicatorField['pick'] }).pick }
      : {}),
  }
}

export interface ChartWithIndicators {
  indicators(): readonly {
    id: string
    name: string
    indicatorId: string
    settings(): Record<string, unknown>
    barSource(): IndicatorBarSource
    setSettings?(patch: Record<string, unknown>): void
    setBarSource?(source: IndicatorBarSource): void
  }[]
  primarySeries?(): SeriesApi | null
  seriesTransform?(s: SeriesApi): unknown
}

export async function buildIndicatorSettingsRequest(
  chart: ChartWithIndicators,
  instanceId: string,
  availableIntervals: readonly string[] = []
): Promise<IndicatorSettingsRequest | null> {
  const inst = chart.indicators().find((i) => i.id === instanceId)
  if (!inst) return null

  const { registeredIndicators: getRegisteredIndicators, indicatorStyleInputs: getStyleInputs } =
    await import('openalgo-charts')
  const descriptor = getRegisteredIndicators().find((d) => d.id === inst.indicatorId)
  if (!descriptor) return null

  const primary = chart.primarySeries?.() ?? null
  const isTransformed = primary !== null && (chart.seriesTransform?.(primary) ?? null) !== null

  const isScript = isScriptInstance(instanceId)
  const inputs: IndicatorField[] = descriptor.inputs.map(toField).map((f) => {
    if (f.type !== 'interval' || f.options !== undefined) return f
    const offered = !isScript
      ? availableIntervals.filter((code) => isKnownInterval(code))
      : availableIntervals
    const options = [
      { label: 'Chart interval', value: '' as unknown },
      ...offered.map((code) => ({ label: code, value: code as unknown })),
    ]
    const current = (inst.settings() as Record<string, unknown>)[f.key]
    if (typeof current === 'string' && current !== '' && !offered.includes(current)) {
      options.push({ label: current, value: current })
    }
    return { ...f, options }
  })

  const styleInputs: IndicatorField[] = getStyleInputs(descriptor).map(toField)

  return {
    instanceId,
    name: inst.name,
    ...(isTransformed ? { barSource: inst.barSource() } : {}),
    values: { ...inst.settings() },
    inputs,
    styleInputs,
  }
}

export async function indicatorDefaultsFor(
  chart: ChartWithIndicators,
  instanceId: string
): Promise<Record<string, unknown> | null> {
  const inst = chart.indicators().find((i) => i.id === instanceId)
  if (!inst) return null
  const { registeredIndicators: getRegisteredIndicators, indicatorDefaults: getDefaults } =
    await import('openalgo-charts')
  const descriptor = getRegisteredIndicators().find((d) => d.id === inst.indicatorId)
  return descriptor ? { ...getDefaults(descriptor) } : null
}

export function applyIndicatorSettings(
  chart: ChartWithIndicators,
  instanceId: string,
  patch: Record<string, unknown>,
  barSource?: IndicatorBarSource
): void {
  const inst = chart.indicators().find((i) => i.id === instanceId)
  if (!inst) return
  if (barSource !== undefined && barSource !== inst.barSource()) {
    inst.setBarSource?.(barSource)
  }
  inst.setSettings?.(patch)
}
