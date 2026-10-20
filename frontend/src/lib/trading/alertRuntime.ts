import { type Alert, type AlertsDocument, parseAlertsDocument } from 'openalgo-charts'

function definition(alert: Alert): string {
  const source = alert.source
  const anchor =
    source.kind === 'price'
      ? [source.kind, source.price, source.upperPrice]
      : source.kind === 'indicator'
        ? [source.kind, source.instanceId, source.plotKey, source.value, source.upperValue]
        : source.kind === 'drawing'
          ? [
              source.kind,
              source.drawingId,
              source.level,
              source.input?.instanceId,
              source.input?.plotKey,
            ]
          : [source.kind, source.id]
  return JSON.stringify([
    anchor,
    alert.condition,
    alert.policy,
    alert.repeat,
    alert.scope.symbol,
    alert.scope.exchange,
    alert.scope.interval,
    alert.cooldownSeconds,
    alert.expiresAt,
    alert.state === 'disabled',
  ])
}

/** Runtime advances independently of layout autosave, but never replaces definitions. */
export function mergeAlertRuntime(saved: AlertsDocument, input: unknown): AlertsDocument {
  const document = parseAlertsDocument(saved)
  const runtime = new Map(parseAlertsDocument(input).alerts.map((alert) => [alert.id, alert]))
  for (const alert of document.alerts) {
    const previous = runtime.get(alert.id)
    if (!previous || definition(previous) !== definition(alert)) continue
    alert.state = previous.state
    for (const key of [
      'lastTriggeredAt',
      'lastTriggeredTime',
      'lastClosedTime',
      'lastTouchedTime',
    ] as const) {
      if (previous[key] === undefined) delete alert[key]
      else alert[key] = previous[key]
    }
  }
  return document
}

function workspacePrefix(account: string, workspace: string): string {
  return `oa-trading-alert-runtime:${encodeURIComponent(account)}:${encodeURIComponent(workspace)}:`
}

export function alertRuntimeKey(account: string, workspace: string, pane: string): string {
  return workspacePrefix(account, workspace) + encodeURIComponent(pane)
}

export function removeWorkspaceAlertRuntime(
  storage: Storage,
  account: string,
  workspace: string
): void {
  const prefix = workspacePrefix(account, workspace)
  for (let index = storage.length - 1; index >= 0; index--) {
    const key = storage.key(index)
    if (key?.startsWith(prefix)) storage.removeItem(key)
  }
}
