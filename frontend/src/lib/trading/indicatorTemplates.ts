import { parseIndicatorStates, WorkspaceDocumentError } from 'openalgo-charts/workspace'

export { type IndicatorTemplateMode, planIndicatorTemplate } from 'openalgo-charts/workspace'

export interface StoredIndicatorRecord {
  instanceId?: string
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
