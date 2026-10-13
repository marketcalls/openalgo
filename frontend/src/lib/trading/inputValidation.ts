/**
 * What is wrong with a number typed into a study's settings, in a trader's
 * words, or null when nothing is.
 *
 * The engine refuses a value outside an input's bounds when the form is
 * applied, and the study then keeps its old setting with nothing on screen to
 * say why. Saying it under the box, as it is typed, is the difference between
 * a form that explains itself and one that seems to ignore the trader.
 */

/** The input types the form draws as a number box. */
const NUMBER_TYPES = new Set(['number', 'price', 'timestamp'])

export interface NumberRule {
  type: string
  min?: number
  max?: number
  step?: number
}

export function numberProblem(field: NumberRule, value: unknown): string | null {
  if (!NUMBER_TYPES.has(field.type)) return null
  if (value === '' || value === null || value === undefined) return 'Enter a number'
  const number = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(number)) return 'Enter a number'
  if (field.min !== undefined && number < field.min) return `The lowest allowed is ${field.min}`
  if (field.max !== undefined && number > field.max) return `The highest allowed is ${field.max}`
  // A whole step is a count (a length, a period), which a fraction cannot be.
  if (
    field.type === 'number' &&
    field.step !== undefined &&
    Number.isInteger(field.step) &&
    field.step >= 1 &&
    !Number.isInteger(number)
  )
    return 'Use a whole number'
  return null
}

/** A picked price, kept to the digits that mean something at its size. */
export function pickedPrice(price: number): number {
  if (!Number.isFinite(price)) return price
  const abs = Math.abs(price)
  return abs >= 1 ? Math.round(price * 100) / 100 : Number(price.toPrecision(6))
}
