import { parseSessionSpec } from '../feed/time';
import type { IndicatorInput, IndicatorSettings } from './indicator-registry';
import { IndicatorInputError } from './indicator-input-error';
import { isPriceScaleId } from './price-axis-layout';
import { isPlainObject } from '../helpers/validate';

/** Validate new native kinds without changing established descriptor contracts. */
export function validateIndicatorInputs(inputs: readonly IndicatorInput[], settings: Readonly<IndicatorSettings>): void {
  for (const input of inputs) {
    if (!['symbol', 'session', 'multiline', 'price', 'timestamp'].includes(input.type)) continue;
    const fail = (reason: string): never => { throw new IndicatorInputError(`Invalid study input "${input.key}": ${reason}`); };
    const property = Object.getOwnPropertyDescriptor(settings, input.key);
    if (property && !('value' in property)) fail('expected a data property');
    const value: unknown = property ? property.value : input.default;
    if (input.type === 'price' || input.type === 'timestamp') {
      const { min, max, step } = input;
      if ((min !== undefined && !Number.isFinite(min)) || (max !== undefined && !Number.isFinite(max))
        || (min !== undefined && max !== undefined && min > max)
        || (step !== undefined && (!Number.isFinite(step) || step <= 0))) fail('invalid numeric constraints');
      const valid = (number: unknown): boolean => typeof number === 'number' && Number.isFinite(number)
        && (min === undefined || number >= min) && (max === undefined || number <= max);
      if (!valid(input.default) || !valid(value)) fail('expected a finite number within the declared bounds');
      const pick = input.pick;
      if (pick !== undefined && typeof pick !== 'boolean') {
        if (input.type !== 'price' || pick === null || typeof pick !== 'object') fail('invalid pick target');
        const target = pick as { paneIndex?: number; priceScaleId?: string };
        if (!isPlainObject(target)) fail('invalid pick target');
        const properties = Object.getOwnPropertyDescriptors(target);
        if (Object.values(properties).some(item => !('value' in item))) fail('invalid pick target');
        const paneIndex = properties.paneIndex?.value as number | undefined;
        const priceScaleId = properties.priceScaleId?.value as string | undefined;
        if (paneIndex !== undefined && (!Number.isSafeInteger(paneIndex) || paneIndex < 0)) fail('invalid pick pane');
        if (priceScaleId !== undefined && !isPriceScaleId(priceScaleId)) fail('invalid pick scale');
      }
      if (input.type === 'price') {
        // A pair is one point: its time must be a declared absolute instant,
        // and one instant cannot be the time of two different prices.
        const { timeKey, anchor } = input;
        if (timeKey !== undefined && (typeof timeKey !== 'string' || timeKey === input.key
          || inputs.find(item => item.key === timeKey)?.type !== 'timestamp'
          || inputs.some(item => item !== input && item.type === 'price' && item.timeKey === timeKey))) {
          fail('timeKey must name a declared timestamp input no other price pairs with');
        }
        if (anchor !== undefined && (typeof anchor !== 'boolean' || (anchor && timeKey === undefined))) fail('an anchor needs a boolean and a timeKey');
      }
    } else {
      if (typeof input.default !== 'string' || typeof value !== 'string') fail('expected text');
      if (input.type === 'session' && (!parseSessionSpec(input.default) || !parseSessionSpec(value as string))) fail('expected a session such as 0930-1600:23456');
      if (input.type === 'symbol' && input.exchangeKey !== undefined) {
        if (typeof input.exchangeKey !== 'string' || !input.exchangeKey || input.exchangeKey === input.key) fail('invalid exchange field');
        const exchange = Object.getOwnPropertyDescriptor(settings, input.exchangeKey);
        if (exchange && (!('value' in exchange) || typeof exchange.value !== 'string')) fail(`expected text in "${input.exchangeKey}"`);
        const declared = inputs.find(item => item.key === input.exchangeKey);
        if (declared && typeof declared.default !== 'string') fail('exchange field must default to text');
      }
    }
  }
}
