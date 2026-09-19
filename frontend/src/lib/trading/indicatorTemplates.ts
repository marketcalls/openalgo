import type { IndicatorState } from 'openalgo-charts'
import { parseIndicatorStates, WorkspaceDocumentError } from 'openalgo-charts/workspace'

export type IndicatorTemplateMode = 'replace' | 'append'

export interface StoredIndicatorRecord {
  indicatorId: string
  settings: Record<string, unknown>
  visible?: boolean
  /** Legacy preferences let the descriptor choose its pane. */
  paneIndex?: number
}

/** Heal old race-generated repeats only when reading an unversioned save. */
export function dedupeIndicators<T extends { indicatorId: string; settings: unknown }>(
  records: T[]
): T[] {
  const seen = new Set<string>()
  return records.filter((record) => {
    const key = `${record.indicatorId}:${JSON.stringify(record.settings)}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function properties(input: unknown): PropertyDescriptorMap {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    throw new WorkspaceDocumentError('Saved indicator must be a record')
  }
  const result = Object.getOwnPropertyDescriptors(input)
  if (Object.values(result).some((property) => !('value' in property))) {
    throw new WorkspaceDocumentError('Saved indicator accessors are not allowed')
  }
  return result
}

export function readStoredIndicators(input: unknown): StoredIndicatorRecord[] {
  if (!Array.isArray(input)) {
    const envelope = properties(input)
    if (envelope.version?.value !== 2) {
      throw new WorkspaceDocumentError('Unsupported saved indicator version')
    }
    return parseIndicatorStates(envelope.indicators?.value)
  }
  if (input.length > 256)
    throw new WorkspaceDocumentError('At most 256 saved indicators are supported')
  const legacy: StoredIndicatorRecord[] = []
  for (let index = 0; index < input.length; index++) {
    const slot = Object.getOwnPropertyDescriptor(input, String(index))
    if (!slot || !('value' in slot))
      throw new WorkspaceDocumentError('Invalid saved indicator array')
    const fields = properties(slot.value)
    const paneIndex = fields.paneIndex?.value
    const record: StoredIndicatorRecord = parseIndicatorStates([
      {
        indicatorId: fields.indicatorId?.value,
        settings: fields.settings?.value,
        paneIndex: paneIndex === undefined ? 0 : paneIndex,
        ...(fields.visible?.value === undefined ? {} : { visible: fields.visible.value }),
      },
    ])[0]
    if (paneIndex === undefined) delete record.paneIndex
    legacy.push(record)
  }
  return dedupeIndicators(legacy)
}

/** Plan first so a missing custom study cannot erase the current configuration. */
export function planIndicatorTemplate(
  current: IndicatorState[],
  incoming: IndicatorState[],
  mode: IndicatorTemplateMode,
  available: ReadonlySet<string>,
  nextPaneIndex: number
): IndicatorState[] {
  if (mode !== 'replace' && mode !== 'append') {
    throw new WorkspaceDocumentError('Unsupported indicator template mode')
  }
  const previous = parseIndicatorStates(current)
  const additions = parseIndicatorStates(incoming)
  if (mode === 'append') {
    if (!Number.isInteger(nextPaneIndex) || nextPaneIndex < 1 || nextPaneIndex > 32) {
      throw new WorkspaceDocumentError('Invalid next indicator pane')
    }
    const panes = [
      ...new Set(additions.map((item) => item.paneIndex).filter((index) => index > 0)),
    ].sort((a, b) => a - b)
    for (const item of additions) {
      if (item.paneIndex > 0) item.paneIndex = nextPaneIndex + panes.indexOf(item.paneIndex)
      if (item.paneIndex > 31) throw new WorkspaceDocumentError('Indicator pane limit exceeded')
    }
  }
  const planned = mode === 'replace' ? additions : [...previous, ...additions]
  if (planned.length > 256)
    throw new WorkspaceDocumentError('At most 256 indicator instances are supported')
  const missing = [
    ...new Set(
      planned.filter((item) => !available.has(item.indicatorId)).map((item) => item.indicatorId)
    ),
  ]
  if (missing.length) throw new WorkspaceDocumentError(`Missing indicators: ${missing.join(', ')}`)
  return planned
}
