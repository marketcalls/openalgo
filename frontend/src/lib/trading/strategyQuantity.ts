/**
 * Where a strategy's order size comes from, and who is allowed to change it.
 *
 * **The rule is the language's, not this panel's: what the code states, runs.**
 * A `strategy()` declaration carries a `qty`, and the compiled program records
 * it one of two ways. A script that wrote a number carries that number, and no
 * host may override it: the author sized the order, and a settings box that
 * quietly traded a different size would be this application deciding how much
 * of somebody's money to spend. A script that wired its quantity to an
 * `input()` carries a reference to that input instead, and the trader sets it
 * in the same form as every other input, because handing it to an input is how
 * an author says "this is yours to choose".
 *
 * So there is no separate quantity box anywhere. There is one question, asked
 * of the program, and two answers:
 *
 * ```
 * strategy("x", qty = 5)              -> stated, 5, fixed
 * q = input(5, "Quantity", min = 1)
 * strategy("x", qty = q)              -> from the input "q", the trader's
 * strategy("x")                       -> stated, 1, the language's default
 * ```
 *
 * **The third line is why this reports the default as such.** A script that
 * says nothing about size gets one unit, and one unit is almost never what
 * somebody meant to trade. It is indistinguishable in the compiled program from
 * a written `qty = 1`, so this cannot silently substitute anything for it, and
 * a trader reading "1 unit" with no idea why is how a strategy runs all day at
 * the wrong size. Naming it, and saying the one line that fixes it, is the
 * whole of what a host can honestly do here.
 */

/** What the program says about the order size. */
export type Quantity =
  | {
      /** The script wrote a number. No host may change it. */
      readonly kind: 'stated'
      readonly units: number
    }
  | {
      /** The script wired it to an input, so the trader owns it. */
      readonly kind: 'input'
      readonly key: string
      /** The input's own default, which is what runs until the trader types. */
      readonly units: number | null
    }
  | {
      /** The program carries no readable declaration at all. */
      readonly kind: 'unknown'
    }

/** The units a declaration states, as the compiled program writes them. */
function numberOf(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  // A constant is also written as a two element array tagged by kind.
  if (Array.isArray(value) && value.length >= 2 && typeof value[1] === 'number') {
    return Number.isFinite(value[1]) ? value[1] : null
  }
  return null
}

/** The key a declaration field refers to, when it refers to an input. */
function referenceOf(value: unknown): string | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
  const key = (value as { input?: unknown }).input
  return typeof key === 'string' && key !== '' ? key : null
}

/**
 * Where this program's order size comes from.
 *
 * Read defensively. The program is JSON from a compiler and a panel that threw
 * on an unexpected shape would take the run down over a label.
 */
export function quantityOf(program: unknown): Quantity {
  const meta = (program as { meta?: { strategy?: unknown } })?.meta?.strategy
  if (typeof meta !== 'object' || meta === null) return { kind: 'unknown' }

  const field = (meta as Record<string, unknown>).qty

  const key = referenceOf(field)
  if (key !== null) {
    return { kind: 'input', key, units: defaultUnitsFor(program, key) }
  }

  const units = numberOf(field)
  if (units === null) return { kind: 'unknown' }
  return { kind: 'stated', units }
}

/** The declared default of the input a quantity refers to, if it can be read. */
function defaultUnitsFor(program: unknown, key: string): number | null {
  const declared = (program as { inputs?: unknown })?.inputs
  if (!Array.isArray(declared)) return null
  for (const one of declared) {
    if (one !== null && typeof one === 'object' && (one as { key?: unknown }).key === key) {
      return numberOf((one as { default?: unknown }).default)
    }
  }
  return null
}

/**
 * The size a run will send per order, given what the trader has typed.
 *
 * `edited` is the panel's own form state, keyed the same way it sends settings.
 * A stated quantity ignores it entirely, which is the point.
 */
export function unitsFor(quantity: Quantity, edited: Readonly<Record<string, string>>): number | null {
  if (quantity.kind === 'stated') return quantity.units
  if (quantity.kind === 'unknown') return null
  const typed = edited[quantity.key]
  if (typed === undefined || typed.trim() === '') return quantity.units
  const value = Number(typed)
  return Number.isFinite(value) ? value : quantity.units
}

/**
 * One sentence saying who owns the size, written for a trader.
 *
 * No status code, no field name from the compiled program, and an action where
 * there is one to take.
 */
export function quantityNote(quantity: Quantity): string {
  if (quantity.kind === 'input') {
    return 'This script takes its size from a setting below, so you choose it.'
  }
  if (quantity.kind === 'unknown') {
    return 'This script does not say what size it trades. Run it once to read its declaration.'
  }
  if (quantity.units === 1) {
    return (
      'The script sets this size, so it cannot be changed here. It trades 1 unit, which is also ' +
      'what a script that says nothing about size trades. To choose it yourself, edit the script ' +
      'to read qty = input(1, "Quantity", min = 1).'
    )
  }
  return 'The script sets this size, so it cannot be changed here. Edit the script to change it.'
}
