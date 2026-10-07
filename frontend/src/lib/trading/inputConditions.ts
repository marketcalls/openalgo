import type { IndicatorInputCondition, IndicatorInputConditionValue } from 'openalgo-charts'

const asList = (
  value: IndicatorInputConditionValue | readonly IndicatorInputConditionValue[]
): readonly IndicatorInputConditionValue[] =>
  Array.isArray(value) ? value : [value as IndicatorInputConditionValue]

/**
 * Whether an input's `visibleWhen` holds against the values a form is showing.
 *
 * The engine describes a control that only means something beside another
 * one (a point and figure box size read only in fixed mode, an ATR length only
 * in ATR mode) with a condition over the form's own keys. A form that ignores it
 * shows every control at once, and a trader sets a percent the transform never
 * reads. Hiding a control keeps its value, as the engine does.
 */
export function conditionHolds(
  condition: IndicatorInputCondition,
  values: Readonly<Record<string, unknown>>
): boolean {
  if ('all' in condition) return condition.all.every((one) => conditionHolds(one, values))
  if ('any' in condition) return condition.any.some((one) => conditionHolds(one, values))
  const value = values[condition.key] as IndicatorInputConditionValue
  if ('is' in condition) return asList(condition.is).includes(value)
  return !asList(condition.isNot).includes(value)
}
