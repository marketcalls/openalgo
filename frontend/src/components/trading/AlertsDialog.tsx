/**
 * Creating and managing chart alerts, in the app's own controls.
 *
 * The engine ships an alert UI of its own, and this replaces it on this page
 * for the same reason the indicator settings dialog is ours: the engine is
 * canvas-only, its dialog is generated from a schema as a settings table, and
 * an alert is not a table of settings. It is a sentence. "RELIANCE, crossing,
 * 1243.40" reads as one when the three controls are stacked and full width, and
 * reads as a form when each is a row with a label on its left.
 *
 * So the shape here is sections rather than rows: what to watch, when to fire,
 * when to stop, and what to call it. The engine is still the one that decides
 * whether a condition has been met; everything below is how it is asked.
 *
 * **This is the editor and nothing else.** The list of alerts lives on the rail
 * in `AlertsPanel`, because a list is something you keep open beside the chart
 * rather than something that covers it. A modal is good at one job, which is
 * filling in a form, and this is that form however it was opened: from the
 * toolbar, from a right-click on the chart, or from a row in that list.
 */

import { Loader2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { type AlertDelivery, readySound } from '@/lib/trading/alertDelivery'
import { ALERT_PLACEHOLDERS } from '@/lib/trading/alertMessage'
import { askToNotify } from '@/lib/trading/alertNotify'
import {
  ALERT_CONDITIONS,
  ALERT_KINDS,
  type AlertConditionId,
  type AlertDraft,
  type AlertKind,
  defaultExpiry,
  draftFor,
  draftProblem,
  drawingChoices,
  isRangeCondition,
  lastClose,
  levelChoices,
  needsThreshold,
  plotChoices,
  plotValueAt,
  snapPrice,
  studyChoices,
  titleFor,
  toAlertInput,
} from '@/lib/trading/alertsModel'
import type { AlertsHandle } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'

/** A section heading. The four of them are what makes this read as a sentence. */
function Section({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
      {children}
    </div>
  )
}

/** Every select in this dialog, so none of them can drift from the others. */
function Choice({
  value,
  onChange,
  options,
  label,
  disabled,
}: {
  value: string
  onChange: (next: string) => void
  options: readonly { value: string; label: string }[]
  label: string
  disabled?: boolean
}) {
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger className="h-9 w-full text-sm" aria-label={label}>
        <SelectValue placeholder={label} />
      </SelectTrigger>
      <SelectContent>
        {options.length === 0 && (
          <div className="px-2 py-1.5 text-xs text-muted-foreground">Nothing to choose yet.</div>
        )}
        {options.map((one) => (
          <SelectItem key={one.value} value={one.value} className="text-sm">
            {one.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

/** The four ways to be told, in the order the dialog draws them. */
const DELIVERY_CHOICES: readonly {
  readonly key: keyof AlertDelivery
  readonly label: string
  readonly means: string
}[] = [
  { key: 'sound', label: 'Sound', means: 'A short tone from this tab' },
  { key: 'notify', label: 'Desktop notification', means: 'Shown only while this tab is hidden' },
  { key: 'telegram', label: 'Telegram', means: 'Needs the bot running and your account linked' },
  { key: 'whatsapp', label: 'WhatsApp', means: 'Needs a paired device' },
]

interface Props {
  handle: AlertsHandle | null
  onClose: () => void
}

export function AlertsDialog({ handle, onClose }: Props) {
  const [draft, setDraft] = useState<AlertDraft | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  const zone = handle?.chart.timezone() ?? 'UTC'
  /** The alert being edited, or undefined when this is a new one. */
  const editing = handle?.editAlertId

  /** A draft seeded from what the chart is showing, or from an existing alert. */
  /** The draft the form opens with, seeded exactly as a right-click seeds one. */
  const seed = useCallback(
    (alertId?: string): AlertDraft => {
      const existing = alertId ? handle?.alerts.list().find((one) => one.id === alertId) : undefined
      if (!handle) {
        // No chart yet. The effect below only runs with a handle, so this is
        // unreachable in practice and typed rather than asserted.
        return draftFor({
          chart: { indicators: () => [], primaryBars: () => [], timezone: () => zone },
          drawings: null,
          zone,
        })
      }
      return draftFor({
        chart: handle.chart,
        drawings: handle.drawings,
        zone,
        ...(handle.source ? { source: handle.source } : {}),
        ...(existing ? { existing } : {}),
        ...(handle.at ? { at: handle.at } : {}),
      })
    },
    [handle, zone]
  )

  /**
   * Seed the form each time the dialog is opened.
   *
   * A new handle is a new opening, whether it came from the toolbar, from a
   * right-click on a study's plot, or from a row in the rail's list. The three
   * differ only in what the draft starts as, which `seed` already knows.
   */
  useEffect(() => {
    if (!handle) return
    setDraft(seed(handle.editAlertId))
    setProblem(null)
  }, [handle, seed])

  const patch = (next: Partial<AlertDraft>) =>
    setDraft((previous) => (previous === null ? previous : { ...previous, ...next }))

  const save = () => {
    if (!handle || draft === null) return
    const fault = draftProblem(draft, handle.chart, handle.drawings)
    if (fault !== null) {
      setProblem(fault)
      return
    }
    const input = toAlertInput(draft, handle.chart, handle.drawings, handle.symbol, handle.at)
    if (input === null) return
    try {
      if (editing) handle.alerts.update(editing, input)
      else handle.alerts.add(input)
      // Asked here and nowhere else. This is a click the trader has just made
      // for the express purpose of being told about a price, which is the one
      // moment a request to notify them explains itself; on page load it is a
      // prompt people dismiss without reading, and a dismissed prompt is the
      // permanent answer. Nothing waits on it: a refusal costs the desktop
      // notification and the alert still fires and still toasts.
      // Asked from the click that armed it, which is the only gesture a
      // browser lets either of these start from.
      if (draft.enabled && draft.deliver.notify) void askToNotify()
      if (draft.enabled && draft.deliver.sound) readySound()
      setProblem(null)
      onClose()
    } catch (error) {
      // The engine refuses in its own terms. Shown as-is rather than swallowed:
      // a Save that does nothing and says nothing is the worse failure.
      setProblem(error instanceof Error ? error.message : String(error))
    }
  }

  const studies = handle ? studyChoices(handle.chart) : []
  const plots = handle && draft ? plotChoices(handle.chart, draft.instanceId) : []
  const drawings = drawingChoices(handle?.drawings ?? null)
  const levels = handle && draft ? levelChoices(handle.drawings, draft.drawingId) : []

  return (
    <Dialog open={handle !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[88dvh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="text-base">{editing ? 'Edit alert' : 'Create alert'}</DialogTitle>
          <DialogDescription className="text-xs">
            {handle?.symbol ? `${handle.symbol} on this chart` : 'This chart'}
          </DialogDescription>
        </DialogHeader>

        {draft === null ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" strokeWidth={1.5} />
          </div>
        ) : (
          <div className="space-y-4">
            {/* What to watch. Stacked and full width, so the three controls read
                as one sentence instead of as three settings. */}
            <div className="space-y-2">
              <Section>Condition</Section>
              <Choice
                label="What to watch"
                value={draft.kind}
                options={ALERT_KINDS}
                onChange={(next) => {
                  const kind = next as AlertKind
                  const seededValue =
                    kind === 'indicator' && handle
                      ? plotValueAt(handle.chart, draft.instanceId, draft.plotKey)
                      : kind === 'price' && handle
                        ? lastClose(handle.chart)
                        : null
                  patch({
                    kind,
                    value:
                      seededValue === null
                        ? draft.value
                        : String(
                            kind === 'price' ? snapPrice(seededValue, handle?.at) : seededValue
                          ),
                  })
                }}
              />
              {draft.kind === 'indicator' && (
                <>
                  <Choice
                    label="Study"
                    value={draft.instanceId}
                    options={studies}
                    onChange={(instanceId) => {
                      const next = handle ? plotChoices(handle.chart, instanceId) : []
                      const plotKey = next[0]?.value ?? ''
                      const seeded = handle ? plotValueAt(handle.chart, instanceId, plotKey) : null
                      patch({
                        instanceId,
                        plotKey,
                        value: seeded === null ? draft.value : String(seeded),
                      })
                    }}
                  />
                  <Choice
                    label="Plot"
                    value={draft.plotKey}
                    options={plots}
                    onChange={(plotKey) => {
                      const seeded = handle
                        ? plotValueAt(handle.chart, draft.instanceId, plotKey)
                        : null
                      patch({ plotKey, value: seeded === null ? draft.value : String(seeded) })
                    }}
                  />
                </>
              )}
              {draft.kind === 'drawing' && (
                <>
                  <Choice
                    label="Drawing"
                    value={draft.drawingId}
                    options={drawings}
                    onChange={(drawingId) => {
                      const next = levelChoices(handle?.drawings ?? null, drawingId)
                      patch({ drawingId, level: next[0]?.value ?? '' })
                    }}
                  />
                  <Choice
                    label="Level"
                    value={draft.level}
                    options={levels}
                    onChange={(level) => patch({ level })}
                  />
                </>
              )}
              <Choice
                label="Condition"
                value={draft.condition}
                options={ALERT_CONDITIONS}
                onChange={(condition) => patch({ condition: condition as AlertConditionId })}
              />
              {needsThreshold(draft.kind) && (
                <div
                  className={cn('grid gap-2', isRangeCondition(draft.condition) && 'grid-cols-2')}
                >
                  <Input
                    inputMode="decimal"
                    value={draft.value}
                    onChange={(event) => patch({ value: event.target.value })}
                    aria-label={isRangeCondition(draft.condition) ? 'Lower bound' : 'Value'}
                    placeholder={isRangeCondition(draft.condition) ? 'Lower' : 'Value'}
                    className="h-9 text-sm"
                  />
                  {isRangeCondition(draft.condition) && (
                    <Input
                      inputMode="decimal"
                      value={draft.upperValue}
                      onChange={(event) => patch({ upperValue: event.target.value })}
                      aria-label="Upper bound"
                      placeholder="Upper"
                      className="h-9 text-sm"
                    />
                  )}
                </div>
              )}
            </div>

            {/* When it fires. Two questions, both of which change what the alert
                does rather than how it looks, so they are not buried. */}
            <div className="space-y-2">
              <Section>Trigger</Section>
              <div className="grid grid-cols-2 gap-2">
                <Choice
                  label="Repeat"
                  value={draft.repeat}
                  options={[
                    { value: 'once', label: 'Only once' },
                    { value: 'everyTime', label: 'Every time' },
                  ]}
                  onChange={(repeat) => patch({ repeat: repeat as AlertDraft['repeat'] })}
                />
                <Choice
                  label="Evaluate"
                  value={draft.policy}
                  options={[
                    { value: 'onBarClose', label: 'On bar close' },
                    { value: 'onTouch', label: 'Intrabar touch' },
                  ]}
                  onChange={(policy) => patch({ policy: policy as AlertDraft['policy'] })}
                />
              </div>
              <p className="text-[11px] leading-snug text-muted-foreground">
                {draft.policy === 'onBarClose'
                  ? 'Fires on a confirmed bar. A wick that is later revised will not fire it.'
                  : 'Fires the moment price touches, including on a wick that final history may not keep.'}
              </p>
            </div>

            {/* When it stops. The checkbox is the switch, so an open-ended alert
                is a deliberate choice rather than an empty field. */}
            <div className="space-y-2">
              <Section>Expiration</Section>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="alert-expires"
                  checked={draft.expiresAt !== ''}
                  onCheckedChange={(checked) =>
                    patch({ expiresAt: checked === true ? defaultExpiry(zone) : '' })
                  }
                />
                <Label htmlFor="alert-expires" className="text-xs font-normal">
                  Expires
                </Label>
                <Input
                  type="datetime-local"
                  step={60}
                  value={draft.expiresAt}
                  disabled={draft.expiresAt === ''}
                  onChange={(event) => patch({ expiresAt: event.target.value })}
                  aria-label={`Expiry, ${zone}`}
                  className="h-9 flex-1 text-sm"
                />
              </div>
              <p className="text-[11px] text-muted-foreground">
                {draft.expiresAt === ''
                  ? 'Open-ended: this alert keeps watching until you remove it.'
                  : `Times are ${zone}, the same clock as the chart's axis.`}
              </p>
            </div>

            {/* What to call it, and what it says. Last, because both have a
                sensible answer already and neither stops anyone saving. */}
            <div className="space-y-2">
              <Section>Alert name</Section>
              <Input
                value={draft.title}
                onChange={(event) => patch({ title: event.target.value })}
                placeholder={handle ? titleFor(draft, handle.chart, handle.symbol, handle.at) : ''}
                aria-label="Alert name"
                className="h-9 text-sm"
              />
              <Input
                value={draft.message}
                onChange={(event) => patch({ message: event.target.value })}
                placeholder="Message (optional)"
                aria-label="Message"
                className="h-9 text-sm"
              />
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                A message can carry values filled in when it fires:{' '}
                {ALERT_PLACEHOLDERS.slice(0, 5).map((one, index) => (
                  <span key={one.name}>
                    {index > 0 && ', '}
                    <button
                      type="button"
                      title={one.means}
                      onClick={() => patch({ message: `${draft.message}{{${one.name}}}` })}
                      className="rounded bg-muted px-1 font-mono text-[10px] hover:bg-accent hover:text-foreground"
                    >
                      {`{{${one.name}}}`}
                    </button>
                  </span>
                ))}
                {' and '}
                {ALERT_PLACEHOLDERS.length - 5} more. One spelled wrong is left as you typed it
                rather than blanked.
              </p>
              <div className="flex items-center gap-2 pt-1">
                <Checkbox
                  id="alert-enabled"
                  checked={draft.enabled}
                  onCheckedChange={(checked) => patch({ enabled: checked === true })}
                />
                <Label htmlFor="alert-enabled" className="text-xs font-normal">
                  Active as soon as it is saved
                </Label>
              </div>
            </div>

            {/* How to be told. Last, because every one of them has an answer
                already and none of them stops anyone saving. */}
            <div className="space-y-2">
              <Section>When it fires</Section>
              <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                {DELIVERY_CHOICES.map((choice) => (
                  <div key={choice.key} className="flex items-center gap-2">
                    <Checkbox
                      id={`alert-deliver-${choice.key}`}
                      checked={draft.deliver[choice.key]}
                      onCheckedChange={(checked) =>
                        patch({ deliver: { ...draft.deliver, [choice.key]: checked === true } })
                      }
                    />
                    <Label
                      htmlFor={`alert-deliver-${choice.key}`}
                      className="text-xs font-normal"
                      title={choice.means}
                    >
                      {choice.label}
                    </Label>
                  </div>
                ))}
              </div>
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                Sound and the desktop notification reach you with the tab behind another window and
                never leave this machine. Telegram and WhatsApp send the message out, and each needs
                to be set up on its own page first.
              </p>
            </div>

            {problem !== null && (
              <p role="alert" className="text-xs text-destructive">
                {problem}
              </p>
            )}

            <DialogFooter className="gap-2 pt-1">
              <Button variant="outline" size="sm" onClick={onClose}>
                Cancel
              </Button>
              <Button size="sm" onClick={save}>
                {editing ? 'Save' : 'Create'}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
