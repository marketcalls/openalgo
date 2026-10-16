import type { BarCondition } from './types';

let conditions: Map<string, Readonly<BarCondition>> | undefined;

function registry(): Map<string, Readonly<BarCondition>> {
  if (!conditions) {
    // The controller hands a condition the bars through `index`, so `bars[index]`
    // is there, and so is `bars[index - 1]` once `index > 0`.
    const builtins: BarCondition[] = [
      { id: 'bullish', title: 'Bullish bar', when: ({ bars, index }) => bars[index]!.close > bars[index]!.open },
      { id: 'bearish', title: 'Bearish bar', when: ({ bars, index }) => bars[index]!.close < bars[index]!.open },
      { id: 'inside', title: 'Inside bar', when: ({ bars, index }) => index > 0
        && bars[index]!.high < bars[index - 1]!.high && bars[index]!.low > bars[index - 1]!.low },
      { id: 'outside', title: 'Outside bar', when: ({ bars, index }) => index > 0
        && bars[index]!.high > bars[index - 1]!.high && bars[index]!.low < bars[index - 1]!.low },
      { id: 'gap-up', title: 'Gap up', when: ({ bars, index }) => index > 0 && bars[index]!.low > bars[index - 1]!.high },
      { id: 'gap-down', title: 'Gap down', when: ({ bars, index }) => index > 0 && bars[index]!.high < bars[index - 1]!.low },
    ];
    conditions = new Map(builtins.map(condition => [condition.id, Object.freeze(condition)]));
  }
  return conditions;
}

/** Register runtime code by stable id; persisted alerts store only that id. */
export function registerBarCondition(condition: BarCondition): void {
  if (typeof condition.id !== 'string' || !condition.id.trim() || typeof condition.title !== 'string'
    || !condition.title.trim() || typeof condition.when !== 'function') throw new Error('Invalid bar condition');
  if (registry().has(condition.id)) throw new Error(`Bar condition id already registered: ${condition.id}`);
  registry().set(condition.id, Object.freeze({ ...condition }));
}

export function unregisterBarCondition(id: string): boolean { return registry().delete(id); }
export function getBarCondition(id: string): Readonly<BarCondition> | undefined { return registry().get(id); }
export function registeredBarConditions(): readonly Readonly<BarCondition>[] { return [...registry().values()]; }
