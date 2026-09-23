/**
 * The choices an OpenScript `kind = "interval"` input offers in the settings
 * dialog.
 *
 * The terminal fills every interval input with the broker's own codes and an
 * empty "Chart interval" entry. That is right for a JavaScript indicator, which
 * the chart runs: the chart reads an empty value as its own interval and `D` as
 * a day. OpenScript reads neither. A timeframe in the language is a count and a
 * unit, `"5m"`, `"1h"`, `"1D"`, `"1W"`, `"1M"`, or a bare number of minutes
 * (`stdlib.md` 15.2), and an interval setting is stored as exactly that string
 * (`host-interface.md` 8.1). So choosing `D` or "Chart interval" for a study
 * that folds bars stopped it at load with OS6001, "D is not a timeframe", on a
 * value the dialog itself had offered.
 *
 * **"Chart interval" becomes the chart's own interval, spelled the language's
 * way.** The language has no word for "whatever the chart is on" in a setting;
 * a script that wants that writes `chart.interval`. What the engine does take
 * is a request at the chart's own timeframe, which folds one bar into one bar.
 * That is what the choice stores, and its label says which interval it is,
 * because the stored value is that interval: moving the chart to another one
 * afterwards does not move the setting with it.
 *
 * **Only what the engine would run on this chart is offered.** Besides the
 * spelling, the engine refuses a request finer than the chart (OS6002, folding
 * cannot invent bars that were never loaded) and an intraday request that is
 * not a whole multiple of an intraday chart (OS6015). The tests hold every
 * choice made here to the installed engine's own answer, so if the language
 * changes a rule this file has to change with it.
 */

/** Minutes in one unit, as the engine orders two timeframes. A month is thirty days. */
const UNIT_MINUTES: Readonly<Record<string, number>> = {
  m: 1,
  h: 60,
  D: 1440,
  W: 10_080,
  M: 43_200,
}

/** The language's grammar: a count and an optional unit, a bare count being minutes. */
const WRITTEN = /^([0-9]+)(m|h|D|W|M)?$/

/**
 * A broker's interval code in the language's spelling, or null where the
 * language has no spelling for it.
 *
 * Seconds have none: the smallest unit the language knows is a minute, so a
 * `30s` choice is left out rather than turned into something else.
 */
export function languageInterval(code: string): string | null {
  const text = code.trim()
  if (WRITTEN.test(text)) return Number.parseInt(text, 10) >= 1 ? text : null

  const found = /^([0-9]*)([a-zA-Z])$/.exec(text)
  if (found === null) return null
  const count = found[1] === '' ? 1 : Number.parseInt(found[1], 10)
  if (!Number.isInteger(count) || count < 1) return null

  // Case matters for one letter only, and in both vocabularies: `M` is a
  // month and `m` a minute. Every other unit is accepted either way round,
  // because brokers write a day as `D`, `d` and `1d`.
  switch (found[2]) {
    case 'm':
      return found[1] === '' ? null : `${count}m`
    case 'M':
      return `${count}M`
    case 'h':
    case 'H':
      return found[1] === '' ? null : `${count}h`
    case 'd':
    case 'D':
      return `${count}D`
    case 'w':
    case 'W':
      return `${count}W`
    default:
      return null
  }
}

/** Minutes one bar of a language timeframe covers, and whether it is counted rather than dated. */
function measure(timeframe: string): { minutes: number; intraday: boolean } | null {
  const found = WRITTEN.exec(timeframe)
  if (found === null) return null
  const unit = found[2] ?? 'm'
  return {
    minutes: Number.parseInt(found[1], 10) * UNIT_MINUTES[unit],
    intraday: unit === 'm' || unit === 'h',
  }
}

/**
 * Whether the engine would fold a chart's bars into the requested ones.
 *
 * Both in the language's spelling. A chart interval the language cannot read
 * refuses nothing, which is also what the engine does: with no chart timeframe
 * to compare against, it skips both comparisons.
 */
export function foldsOnto(requested: string, chart: string | null): boolean {
  const wanted = measure(requested)
  if (wanted === null) return false
  const have = chart === null ? null : measure(chart)
  if (have === null) return true
  if (wanted.minutes < have.minutes) return false
  if (wanted.intraday && have.intraday) return wanted.minutes % have.minutes === 0
  return true
}

export interface IntervalChoice {
  label: string
  value: string
}

/**
 * The choices to show and the value to show them at.
 *
 * `offered` is what the terminal filled the input with, `chartInterval` the
 * chart's own code as the terminal holds it, and `current` the stored value.
 *
 * The stored value is normalised the same way: an empty one, which is what
 * "Chart interval" used to store, becomes the chart's interval, and `D` becomes
 * `1D`. A value that still is not a choice, a stored `1m` on what is now a
 * `5m` chart, is kept as its own entry rather than dropped, so the control
 * never shows one interval while the study is set to another.
 */
export function scriptIntervalChoices(
  offered: readonly { label: string; value: unknown }[] | undefined,
  chartInterval: string | undefined,
  current: unknown
): { choices: IntervalChoice[]; value: string } {
  const chart = chartInterval === undefined ? null : languageInterval(chartInterval)
  const choices: IntervalChoice[] = []
  if (chart !== null) choices.push({ label: `Chart interval (${chartInterval})`, value: chart })

  for (const one of offered ?? []) {
    const code = String(one.value ?? '')
    const value = code === '' ? null : languageInterval(code)
    if (value === null || !foldsOnto(value, chart)) continue
    if (choices.some((held) => held.value === value)) continue
    choices.push({ label: one.label || code, value })
  }

  const stored = typeof current === 'string' ? current.trim() : ''
  const value = stored === '' ? (choices[0]?.value ?? '') : (languageInterval(stored) ?? stored)
  if (value !== '' && !choices.some((held) => held.value === value)) {
    choices.push({ label: value, value })
  }
  return { choices, value }
}
