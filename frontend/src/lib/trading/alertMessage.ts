/**
 * Placeholders in an alert's message, filled in at the moment it fires.
 *
 * **A message written when the alert is armed is read when it fires**, and the
 * useful part is usually the number nobody knew yet. "RELIANCE crossed" is a
 * sentence a trader has to go and look something up after; "RELIANCE crossed
 * 1264.70, close 1266.10 on 1h" is one they can act on from a notification on a
 * locked phone. So the message may carry placeholders, and they are substituted
 * against the bar that fired it.
 *
 * **An unknown placeholder is left exactly as written.** A trader who typed
 * `{{closs}}` has made a spelling mistake, and replacing it with nothing turns
 * their message into a sentence with a hole in it that reads like a bug in the
 * alert rather than a typo in the text. Left standing, it says what happened.
 * The same rule covers a value the chart does not have: a bar with no volume
 * prints the placeholder rather than claiming zero, because zero volume is a
 * real reading and this is not it.
 *
 * Substitution is one pass over the text and never re-scans what it wrote, so a
 * price that happened to contain braces cannot become a placeholder itself.
 */

/** What the chart knew when the alert fired. */
export interface AlertFacts {
  readonly ticker?: string
  readonly exchange?: string
  readonly interval?: string
  readonly open?: number | null
  readonly high?: number | null
  readonly low?: number | null
  readonly close?: number | null
  readonly volume?: number | null
  /** The value that met the condition, which is not always the close. */
  readonly price?: number | null
  /** The fired bar's time, in UTC seconds. */
  readonly time?: number | null
  /** How many decimals this instrument's prices are written with. */
  readonly digits?: number
}

/**
 * The placeholders a trader may use, and what each one prints.
 *
 * Listed here rather than inferred, because this doubles as the list the editor
 * shows: a placeholder nobody can discover is a feature nobody uses.
 */
export const ALERT_PLACEHOLDERS: readonly { readonly name: string; readonly means: string }[] = [
  { name: 'ticker', means: 'The instrument, as the chart names it' },
  { name: 'exchange', means: 'The exchange it trades on' },
  { name: 'interval', means: "The chart's timeframe" },
  { name: 'price', means: 'The value that met the condition' },
  { name: 'close', means: "The fired bar's close" },
  { name: 'open', means: "The fired bar's open" },
  { name: 'high', means: "The fired bar's high" },
  { name: 'low', means: "The fired bar's low" },
  { name: 'volume', means: "The fired bar's volume" },
  { name: 'time', means: 'The bar the alert fired on' },
  { name: 'timenow', means: 'The moment it was delivered' },
]

/** `{{name}}`, with whatever spacing the trader left inside the braces. */
const PLACEHOLDER = /\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g

/**
 * The message with its placeholders filled in.
 *
 * `now` is a parameter rather than a call to the clock, so the same message and
 * the same facts produce the same text in a test as they do in a terminal.
 */
export function fillAlertMessage(
  text: string,
  facts: AlertFacts,
  now: number = Date.now()
): string {
  if (text === '' || !text.includes('{{')) return text
  return text.replace(PLACEHOLDER, (whole, name: string) => {
    const filled = placeholderValue(name.toLowerCase(), facts, now)
    // Unknown, or known and absent: the placeholder stands. A hole in the
    // sentence reads as a fault in the alert; the text as typed reads as a typo,
    // which is what it is.
    return filled ?? whole
  })
}

function placeholderValue(name: string, facts: AlertFacts, now: number): string | null {
  switch (name) {
    case 'ticker':
    case 'symbol':
      return facts.ticker || null
    case 'exchange':
      return facts.exchange || null
    case 'interval':
    case 'timeframe':
      return facts.interval || null
    case 'price':
      return priceText(facts.price, facts.digits)
    case 'close':
      return priceText(facts.close, facts.digits)
    case 'open':
      return priceText(facts.open, facts.digits)
    case 'high':
      return priceText(facts.high, facts.digits)
    case 'low':
      return priceText(facts.low, facts.digits)
    case 'volume':
      // Whole units and no price rounding: a volume is a count, and printing it
      // to two decimals says it was measured more finely than it was.
      return typeof facts.volume === 'number' && Number.isFinite(facts.volume)
        ? String(Math.round(facts.volume))
        : null
    case 'time':
      return instant(facts.time === null || facts.time === undefined ? null : facts.time * 1000)
    case 'timenow':
      return instant(now)
    default:
      return null
  }
}

/**
 * A price at the instrument's own precision.
 *
 * The instrument's digits rather than the number's: a close that happens to be
 * 1264.7 is written 1264.70 beside one written 1266.10, because a column of
 * prices that disagree about their decimals reads as two different instruments.
 */
function priceText(value: number | null | undefined, digits: number | undefined): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  const places = typeof digits === 'number' && digits >= 0 && digits <= 8 ? digits : undefined
  return places === undefined ? String(value) : value.toFixed(places)
}

/** An instant, written the way the rest of the terminal writes one. */
function instant(ms: number | null): string | null {
  if (ms === null || !Number.isFinite(ms)) return null
  const when = new Date(ms)
  if (Number.isNaN(when.getTime())) return null
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())} ` +
    `${pad(when.getHours())}:${pad(when.getMinutes())}`
  )
}
