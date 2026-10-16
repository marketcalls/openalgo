import type { IndicatorInput } from '../model/indicator-registry';
import type { AlertCondition, AlertSource } from './types';

const labels: Record<AlertCondition, string> = {
  crossing: 'Crossing', crossingUp: 'Crossing up', crossingDown: 'Crossing down',
  greaterThan: 'Above', lessThan: 'Below', enteringRange: 'Entering range',
  leavingRange: 'Leaving range', matches: 'Matches',
};
const numeric: AlertCondition[] = ['crossing', 'crossingUp', 'crossingDown', 'greaterThan', 'lessThan'];
const ranges: AlertCondition[] = ['enteringRange', 'leavingRange'];

/** Shared editor fields in source units. Drawing bands own their bounds. */
export function alertSettingsSchema(source: AlertSource, condition?: AlertCondition): readonly IndicatorInput[] {
  const conditions = source.kind === 'barCondition' ? ['matches' as const]
    : source.kind === 'drawing' ? source.level === 'band' ? ranges : numeric : [...numeric, ...ranges];
  const selected = condition && conditions.includes(condition) ? condition : conditions[0]!; // no list above is empty
  const range = ranges.includes(selected);
  const fields: IndicatorInput[] = [
    { key: 'title', type: 'text', label: 'Name', default: 'Chart alert' },
    { key: 'condition', type: 'select', label: 'Condition', default: selected,
      options: conditions.map(value => ({ value, label: labels[value] })) },
  ];
  if (source.kind === 'price' || source.kind === 'indicator') {
    const price = source.kind === 'price';
    fields.push({ key: price ? 'price' : 'value', type: 'number', label: range ? 'Lower bound' : 'Threshold',
      default: price ? source.price : source.value, step: 0.01 });
    if (range) fields.push({ key: price ? 'upperPrice' : 'upperValue', type: 'number', label: 'Upper bound',
      default: price ? source.upperPrice ?? source.price : source.upperValue ?? source.value, step: 0.01 });
  }
  fields.push(
    { key: 'policy', type: 'select', label: 'Evaluate', default: 'onBarClose', options: [
      { value: 'onBarClose', label: 'Bar close' }, { value: 'onTouch', label: 'Intrabar touch' },
    ] },
    { key: 'repeat', type: 'select', label: 'Repeat', default: 'once', options: [
      { value: 'once', label: 'Once' }, { value: 'everyTime', label: 'Every match' },
    ] },
    { key: 'cooldownSeconds', type: 'number', label: 'Cooldown (seconds)', default: 0, min: 0, step: 1 },
    // The zone belongs to the chart, so the editor appends it. A fixed one
    // here was UTC, while every candle the alert is set against is labelled in
    // the chart's own.
    { key: 'expiresAt', type: 'text', label: 'Expires', default: '', tooltip: 'Leave empty for no expiry.' },
    { key: 'message', type: 'text', label: 'Message', default: '' },
    { key: 'enabled', type: 'boolean', label: 'Enabled', default: true },
  );
  return fields;
}
