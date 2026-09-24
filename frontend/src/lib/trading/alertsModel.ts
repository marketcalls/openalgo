/**
 * What an alert dialog needs to know, without knowing it is a dialog.
 *
 * The chart engine ships an alert *engine* and, separately, an alert *UI*. The
 * engine is the part worth having: it decides what a source is worth right now,
 * when a condition has been met, and what a cooldown or an expiry means. The UI
 * is a settings table, a label on the left and a control on the right for every
 * field in a schema, which is the wrong shape for this: an alert is a sentence
 * about an instrument, and a form that asks for its words one row at a time
 * never reads back as one.
 *
 * So this page renders its own, in the app's own controls, the way it already
 * renders its own indicator settings. Everything here is the part of that job
 * which is not React: enumerating what can be watched, turning a draft into the
 * engine's input, and saying in a trader's words why a draft will not do. It
 * takes a plain `AlertChart` rather than the terminal so it can be tested
 * without a canvas, a broker or a socket.
 */

import {
  type Alert,
  type AlertInput,
  type AlertSource,
  utcSecondsToZonedParts,
  zonedWallClockToUtcSeconds,
} from 'openalgo-charts'
import { type AlertDelivery, DEFAULT_DELIVERY, deliveryOf } from './alertDelivery'
import { snapTick } from './format'

/**
 * The instrument's tick, and a price to sanity-check it against.
 *
 * Carried together because `snapTick` needs both: a tick larger than about one
 * percent of the price is a unit mismatch rather than a real instrument, and
 * the reference price is how that is caught.
 */
export interface AlertTick {
  tick: number | undefined
  refPrice: number
}

/**
 * A price on the instrument's tick.
 *
 * Every price this dialog stores goes through here. A price picked off the
 * chart comes from a pixel, and a pixel maps to a price with fifteen decimals
 * behind it: right-clicking at 1,293.63 produced an alert armed at
 * 1293.6305656934308, a price the instrument cannot trade at and a box nobody
 * can read. The snapping belongs here rather than at each place a price is
 * picked up, because there are four of them and a new one is one line away.
 *
 * Only a price. A study threshold is in the plot's own units, and an
 * oscillator that runs nought to a hundred has nothing to do with the
 * instrument's tick.
 */
export function snapPrice(price: number, at: AlertTick | undefined): number {
  if (!Number.isFinite(price) || at === undefined) return price
  return snapTick(price, at.tick, at.refPrice)
}

/** The slice of the chart this module reads. Narrow on purpose: it is the mock. */
export interface AlertChart {
  indicators(): readonly {
    id: string
    name: string
    indicatorId: string
    paneIndex: number
    values(): Record<string, readonly (number | null)[]>
    series(plotKey: string): unknown
  }[]
  primaryBars(): readonly { close: number }[]
  timezone(): string
}

/** The drawing tier, when it is loaded. Alerts on drawings are optional. */
export interface AlertDrawings {
  drawings(): readonly { id: string; tool: string }[]
  alertInfo(id: string): { available: boolean; levels: readonly { id: string; title: string }[] }
}

export type AlertKind = 'price' | 'indicator' | 'drawing' | 'barCondition'

export type AlertConditionId =
  | 'crossing'
  | 'crossingUp'
  | 'crossingDown'
  | 'greaterThan'
  | 'lessThan'
  | 'enteringRange'
  | 'leavingRange'

/** One choice in one of the dialog's selects. */
export interface AlertChoice {
  value: string
  label: string
}

/** What the trader is building, before it is an alert. */
export interface AlertDraft {
  kind: AlertKind
  condition: AlertConditionId
  /** The threshold, and the second one a range condition needs. */
  value: string
  upperValue: string
  instanceId: string
  plotKey: string
  drawingId: string
  level: string
  barConditionId: string
  policy: 'onBarClose' | 'onTouch'
  repeat: 'once' | 'everyTime'
  cooldownSeconds: string
  /** Empty means no expiry; the dialog's checkbox is what empties it. */
  expiresAt: string
  title: string
  message: string
  enabled: boolean
  /**
   * How the trader asked to be told when it fires.
   *
   * Part of the draft rather than a terminal-wide setting, because a price
   * somebody is waiting on all week and a level they are watching for the next
   * ten minutes do not deserve the same interruption.
   */
  deliver: AlertDelivery
}

/**
 * The conditions, in the order a person reads them.
 *
 * Crossing first because it is what most alerts are, then the one-sided
 * comparisons, then the two-sided ones. The engine's own ordering is the order
 * the type happens to list them in, which puts "entering range" third.
 */
export const ALERT_CONDITIONS: readonly { value: AlertConditionId; label: string }[] = [
  { value: 'crossing', label: 'Crossing' },
  { value: 'crossingUp', label: 'Crossing up' },
  { value: 'crossingDown', label: 'Crossing down' },
  { value: 'greaterThan', label: 'Greater than' },
  { value: 'lessThan', label: 'Less than' },
  { value: 'enteringRange', label: 'Entering channel' },
  { value: 'leavingRange', label: 'Leaving channel' },
]

/** Whether this condition is the two-sided kind, which needs a second number. */
export function isRangeCondition(condition: AlertConditionId): boolean {
  return condition === 'enteringRange' || condition === 'leavingRange'
}

/**
 * Whether this source is a number the trader types, or a thing they pick.
 *
 * A drawing level and a candle condition carry their own value: a trend line is
 * already at a price on every bar, and "inside bar" is either true or it is not.
 * Asking for a threshold beside them is asking for a number that means nothing.
 */
export function needsThreshold(kind: AlertKind): boolean {
  return kind === 'price' || kind === 'indicator'
}

export const ALERT_KINDS: readonly { value: AlertKind; label: string }[] = [
  { value: 'price', label: 'Price' },
  { value: 'indicator', label: 'Study plot' },
  { value: 'drawing', label: 'Drawing level' },
  { value: 'barCondition', label: 'Candle condition' },
]

/** The studies on the chart, numbered the way the legend numbers them. */
export function studyChoices(chart: AlertChart): AlertChoice[] {
  return chart.indicators().map((one, index) => ({
    value: one.id,
    label: `${index + 1}: ${one.name}`,
  }))
}

/**
 * The plots of one study.
 *
 * Read from the live instance rather than from the registry, so a study whose
 * plots depend on its settings offers what it is actually drawing.
 */
export function plotChoices(chart: AlertChart, instanceId: string): AlertChoice[] {
  const instance = chart.indicators().find((one) => one.id === instanceId)
  if (!instance) return []
  return Object.keys(instance.values()).map((key) => ({ value: key, label: key }))
}

export function drawingChoices(drawings: AlertDrawings | null): AlertChoice[] {
  if (!drawings) return []
  return drawings.drawings().map((one, index) => ({
    value: one.id,
    label: `${one.tool} (${index + 1})`,
  }))
}

export function levelChoices(drawings: AlertDrawings | null, drawingId: string): AlertChoice[] {
  if (!drawings || !drawingId) return []
  try {
    return drawings.alertInfo(drawingId).levels.map((one) => ({ value: one.id, label: one.title }))
  } catch {
    // A drawing removed between the menu opening and this read has no levels,
    // which the caller draws as an empty select rather than as a crash.
    return []
  }
}

/** The last value a study plot produced, for seeding the threshold. */
export function plotValueAt(chart: AlertChart, instanceId: string, plotKey: string): number | null {
  const instance = chart.indicators().find((one) => one.id === instanceId)
  const column = instance?.values()[plotKey]
  if (!column || column.length === 0) return null
  for (let at = column.length - 1; at >= 0; at--) {
    const value = column[at]
    if (typeof value === 'number' && Number.isFinite(value)) return value
  }
  return null
}

/** The instrument's latest close, for seeding a price threshold. */
export function lastClose(chart: AlertChart): number | null {
  const bars = chart.primaryBars()
  const last = bars[bars.length - 1]?.close
  return typeof last === 'number' && Number.isFinite(last) ? last : null
}

/**
 * Why this draft cannot be saved, in a sentence a trader can act on, or null.
 *
 * Checked here rather than left to the engine because the engine's refusals are
 * about its own contract. "Enter a price to watch" is what somebody who left a
 * box empty needs; a thrown type error is not.
 */
export function draftProblem(
  draft: AlertDraft,
  chart: AlertChart,
  drawings: AlertDrawings | null
): string | null {
  if (needsThreshold(draft.kind)) {
    const value = Number(draft.value)
    if (draft.value.trim() === '' || !Number.isFinite(value)) {
      return draft.kind === 'price' ? 'Enter a price to watch.' : 'Enter a value to watch.'
    }
    if (isRangeCondition(draft.condition)) {
      const upper = Number(draft.upperValue)
      if (draft.upperValue.trim() === '' || !Number.isFinite(upper)) {
        return 'A channel needs both of its bounds.'
      }
      if (upper === value) return 'A channel needs two different bounds.'
    }
  }
  if (draft.kind === 'indicator') {
    const instance = chart.indicators().find((one) => one.id === draft.instanceId)
    if (!instance) return 'Choose a study. This chart has none, or the one chosen has been removed.'
    if (!instance.series(draft.plotKey)) return 'Choose a plot from that study.'
  }
  if (draft.kind === 'drawing') {
    if (!drawings) return 'Drawings are still loading. Try again in a moment.'
    if (!draft.drawingId) return 'Draw something on the chart first, then alert on its level.'
    if (!draft.level) return 'Choose which level of that drawing to watch.'
  }
  if (draft.kind === 'barCondition' && !draft.barConditionId) {
    return 'Choose a candle condition.'
  }
  const cooldown = Number(draft.cooldownSeconds)
  if (draft.cooldownSeconds.trim() !== '' && (!Number.isFinite(cooldown) || cooldown < 0)) {
    return 'A cooldown is a number of seconds, or nothing at all.'
  }
  if (draft.expiresAt !== '' && !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(draft.expiresAt)) {
    return 'Enter an expiry date and time, or switch the expiry off.'
  }
  return null
}

/**
 * An instant as the chart's own clock reads it, shaped for a datetime input.
 *
 * The chart's zone rather than the browser's: an alert is set against candles
 * the chart has already labelled, so an expiry in another zone asks the reader
 * to do the arithmetic and be hours out when they do not.
 */
export function expiryText(seconds: number | undefined, zone: string): string {
  if (seconds === undefined || !Number.isFinite(seconds)) return ''
  const p = utcSecondsToZonedParts(seconds, zone)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}`
}

/**
 * The instant a wall-clock reading names on that clock.
 *
 * Handed to the engine's own helper rather than worked out here, because a zone
 * that changes offset during the year needs the offset in force at the answer
 * and not at the reading, and that is a thing to get right once.
 */
export function expirySeconds(text: string, zone: string): number | undefined {
  if (text === '') return undefined
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(text)
  if (!match) return undefined
  const [, year, month, day, hour, minute] = match.map(Number)
  const seconds = zonedWallClockToUtcSeconds(year, month, day, hour, minute, 0, zone)
  return Number.isFinite(seconds) ? seconds : undefined
}

/** How long a new alert runs before it expires. */
export const DEFAULT_EXPIRY_MONTHS = 2

/**
 * The expiry a new alert opens with.
 *
 * An alert with no expiry never stops asking, and one that expires this week is
 * gone before the setup it was watching for arrives. Two months is a season of
 * trading. It is a default and the field is right there.
 */
export function defaultExpiry(zone: string, now = new Date()): string {
  const then = new Date(now.getTime())
  // Through the calendar rather than by adding days: two months from the 31st
  // has to land on a date that exists, and `setMonth` already knows that.
  then.setMonth(then.getMonth() + DEFAULT_EXPIRY_MONTHS)
  return expiryText(Math.floor(then.getTime() / 60000) * 60, zone)
}

/**
 * What the alert is called, when the trader has not said.
 *
 * Written as the sentence the alert actually means, so a list of them reads
 * without opening any. "Chart alert" was the engine's default, and a list of
 * six of those tells you nothing about any of them.
 */
export function titleFor(
  draft: AlertDraft,
  chart: AlertChart,
  symbol: string,
  at?: AlertTick
): string {
  return nameFrom(
    {
      kind: draft.kind,
      condition: draft.condition,
      instanceId: draft.instanceId,
      barConditionId: draft.barConditionId,
      value: draft.value,
      upperValue: draft.upperValue,
    },
    chart,
    symbol,
    at
  )
}

/** The parts of an alert a generated name is made of, from either side of it. */
interface Named {
  kind: AlertKind
  condition: AlertConditionId
  instanceId: string
  barConditionId: string
  /** Numbers as text, because a draft holds what was typed and may hold ''. */
  value: string
  upperValue: string
}

function nameFrom(one: Named, chart: AlertChart, symbol: string, at?: AlertTick): string {
  const condition = ALERT_CONDITIONS.find((choice) => choice.value === one.condition)?.label ?? ''
  const subject =
    one.kind === 'indicator'
      ? (chart.indicators().find((study) => study.id === one.instanceId)?.name ?? 'Study')
      : one.kind === 'drawing'
        ? 'Drawing'
        : symbol
  if (one.kind === 'barCondition') return `${symbol} ${one.barConditionId}`
  if (!needsThreshold(one.kind)) return `${subject} ${condition.toLowerCase()}`
  // Named after the price it will be armed at, not the one under the pointer.
  const shown = (text: string): string => {
    const n = Number(text)
    if (one.kind !== 'price' || !Number.isFinite(n)) return text
    return String(snapPrice(n, at))
  }
  const bounds = isRangeCondition(one.condition)
    ? `${shown(one.value)} and ${shown(one.upperValue)}`
    : shown(one.value)
  return `${subject} ${condition.toLowerCase()} ${bounds}`
}

/**
 * What an alert that already exists should be called.
 *
 * The same sentence `titleFor` writes, from the stored alert rather than from
 * the form. Dragging an alert's line moves its price without touching its name,
 * so a machine-written name would go on advertising the price the alert was
 * created at while the line sat somewhere else. This is what it is renamed to.
 */
export function alertTitleFor(
  alert: Alert,
  chart: AlertChart,
  symbol: string,
  at?: AlertTick
): string {
  const source = alert.source as {
    kind: AlertKind
    instanceId?: string
    id?: string
    price?: number
    value?: number
    upperPrice?: number
    upperValue?: number
  }
  const lower = source.price ?? source.value
  const upper = source.upperPrice ?? source.upperValue
  return nameFrom(
    {
      kind: source.kind,
      condition: alert.condition as AlertConditionId,
      instanceId: source.instanceId ?? '',
      barConditionId: source.id ?? '',
      value: lower === undefined ? '' : String(lower),
      upperValue: upper === undefined ? '' : String(upper),
    },
    chart,
    symbol,
    at
  )
}

/**
 * Everything this host keeps on an alert, in the engine's opaque field.
 *
 * `payload` is the engine's own place for host data it never interprets, and it
 * is written whole rather than merged, so both members are stated together:
 * writing one and leaving the other to a later patch is how a delivery choice
 * disappears the first time a name is regenerated.
 */
export interface AlertPayload {
  /** A name we wrote and may rewrite when the price moves under a drag. */
  readonly autoTitle?: true
  readonly deliver?: AlertDelivery
}

/**
 * The mark that says a name was written by us and may be rewritten.
 *
 * `payload` is the engine's own field for host data it never interprets, and
 * this is the one thing this host keeps there. A name the trader typed is
 * theirs and is never touched; one generated because they left the field blank
 * describes the price, so it has to follow the price when the line is dragged.
 */
export const AUTO_TITLE_PAYLOAD = { autoTitle: true } as const

/** Whether this alert's name is ours to rewrite. */
export function hasAutoTitle(alert: Alert): boolean {
  return (alert.payload as { autoTitle?: unknown } | undefined)?.autoTitle === true
}

/**
 * The draft an editor opens with, and the alert a right-click makes.
 *
 * **One function, because the two have to agree.** Right-clicking a price
 * creates an alert there and then, with no form in between; the toolbar opens
 * the form on the same thing. If the alert the gesture makes were seeded
 * separately from the alert the form proposes, the two would drift, and the
 * drift would show up as a right-click quietly producing a different alert from
 * the one the form said it would.
 *
 * `existing` is an alert being edited. Without it this is a new one, seeded from
 * whatever was clicked: a price from the pointer, a study's own reading at that
 * plot, a drawing's level, or the last close when nothing was clicked at all.
 */
export function draftFor(options: {
  readonly chart: AlertChart
  readonly drawings: AlertDrawings | null
  readonly zone: string
  readonly source?: AlertSource
  readonly existing?: Alert
  readonly at?: AlertTick
}): AlertDraft {
  const { chart, drawings: tier, zone, existing, at } = options
  const source = existing?.source ?? options.source
  const kind = (source?.kind ?? 'price') as AlertKind
  const studies = studyChoices(chart)
  const instanceId = source?.kind === 'indicator' ? source.instanceId : (studies[0]?.value ?? '')
  const plots = plotChoices(chart, instanceId)
  const plotKey = source?.kind === 'indicator' ? source.plotKey : (plots[0]?.value ?? '')
  const drawings = drawingChoices(tier)
  const drawingId = source?.kind === 'drawing' ? source.drawingId : (drawings[0]?.value ?? '')
  const levels = levelChoices(tier, drawingId)
  const seeded =
    source?.kind === 'price'
      ? source.price
      : source?.kind === 'indicator'
        ? source.value
        : kind === 'indicator'
          ? plotValueAt(chart, instanceId, plotKey)
          : lastClose(chart)
  // Seeded on the tick. The value may have come from a pixel, and a pixel maps
  // to a price with fifteen decimals behind it.
  const onTick = (n: number): number => (kind === 'price' ? snapPrice(n, at) : n)
  return {
    kind,
    condition: (existing?.condition ?? 'crossing') as AlertConditionId,
    value: seeded === null || seeded === undefined ? '' : String(onTick(seeded)),
    upperValue:
      source?.kind === 'price' && source.upperPrice !== undefined
        ? String(onTick(source.upperPrice))
        : source?.kind === 'indicator' && source.upperValue !== undefined
          ? String(source.upperValue)
          : '',
    instanceId,
    plotKey,
    drawingId,
    level: source?.kind === 'drawing' ? (source.level ?? '') : (levels[0]?.value ?? ''),
    barConditionId: source?.kind === 'barCondition' ? (source.id ?? '') : '',
    // Intrabar, because an alert is about a price being reached and that is
    // the moment it is reached. Waiting for the candle to close means a level
    // touched at 13:15 on an hourly chart is reported at 14:15, by which time
    // the trader has either seen it themselves or missed the move; on a daily
    // chart it is the next session. It reads as an alert that does not work,
    // and it was reported as one.
    //
    // The cost is real and is the reason the other policy exists: intrabar
    // fires on a wick that the finished candle does not keep, so a level
    // brushed once and rejected still sends the message. That is the right
    // trade for a price a trader is watching for, and Bar close is one field
    // away in the form for anybody who wants the confirmation instead.
    policy: existing?.policy ?? 'onTouch',
    repeat: existing?.repeat ?? 'once',
    cooldownSeconds: String(existing?.cooldownSeconds ?? 0),
    expiresAt: existing ? expiryText(existing.expiresAt, zone) : defaultExpiry(zone),
    // Blank when we named it, so the field keeps showing the generated name as
    // its placeholder and the alert keeps the mark that lets a drag rewrite it.
    // Opening the editor and pressing Save should not be what quietly freezes a
    // name to a price the line has since left.
    title: existing && !hasAutoTitle(existing) ? existing.title : '',
    message: existing?.message ?? '',
    enabled: existing ? existing.state !== 'disabled' : true,
    // An alert stored before delivery was a choice reads as the default, which
    // is the behaviour it already had plus the sound.
    deliver: deliveryOf(existing?.payload),
  }
}

/**
 * The draft as the engine's input, or null when it is not ready.
 *
 * Returns null rather than throwing: `draftProblem` is what says why, in words
 * for a trader, and a caller that has already asked should not have to catch an
 * exception to find out the same thing in the engine's words.
 */
export function toAlertInput(
  draft: AlertDraft,
  chart: AlertChart,
  drawings: AlertDrawings | null,
  symbol: string,
  at?: AlertTick
): AlertInput | null {
  if (draftProblem(draft, chart, drawings) !== null) return null
  const onTick = draft.kind === 'price'
  const value = onTick ? snapPrice(Number(draft.value), at) : Number(draft.value)
  const rawUpper = isRangeCondition(draft.condition) ? Number(draft.upperValue) : undefined
  const upper = rawUpper === undefined ? undefined : onTick ? snapPrice(rawUpper, at) : rawUpper
  const source: AlertSource =
    draft.kind === 'price'
      ? { kind: 'price', price: value, ...(upper === undefined ? {} : { upperPrice: upper }) }
      : draft.kind === 'indicator'
        ? {
            kind: 'indicator',
            instanceId: draft.instanceId,
            plotKey: draft.plotKey,
            value,
            upperValue: upper,
          }
        : draft.kind === 'drawing'
          ? { kind: 'drawing', drawingId: draft.drawingId, level: draft.level }
          : { kind: 'barCondition', id: draft.barConditionId }
  const cooldown = Number(draft.cooldownSeconds)
  return {
    source,
    condition: draft.condition,
    policy: draft.policy,
    repeat: draft.repeat,
    state: draft.enabled ? 'armed' : 'disabled',
    title: draft.title.trim() || titleFor(draft, chart, symbol, at),
    // Marked when we named it, so a drag can rename it and a name the trader
    // typed is left exactly as they typed it.
    payload: {
      // Marked when we named it, so a drag can rename it and a name the trader
      // typed is left exactly as they typed it.
      ...(draft.title.trim() === '' ? AUTO_TITLE_PAYLOAD : {}),
      // Defaulted rather than written through. The engine validates a payload
      // as JSON, and a member holding undefined is not JSON: a draft built
      // before this field existed would write one and be refused at `add`.
      deliver: draft.deliver ?? DEFAULT_DELIVERY,
    } satisfies AlertPayload,
    message: draft.message.trim() || undefined,
    cooldownSeconds:
      draft.cooldownSeconds.trim() === '' || !Number.isFinite(cooldown) ? 0 : cooldown,
    expiresAt: expirySeconds(draft.expiresAt, chart.timezone()),
  }
}
