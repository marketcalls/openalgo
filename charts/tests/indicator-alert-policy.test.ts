import { describe, expect, it } from 'vitest';
import { IndicatorAlertPolicy, type IndicatorAlertPolicyPass } from '../src/model/indicator-alert-policy';
import type { IndicatorAlertFrequency, IndicatorAlertSpec, IndicatorExecutionContext, IndicatorValues } from '../src/model/indicator-registry';
import type { AlertEventPayload } from '../src/alerts/types';

function pass(times: number[], revision: number, patch: Partial<IndicatorExecutionContext> = {}, options: {
  confirmed?: boolean; refresh?: boolean; tailOnly?: boolean; values?: IndicatorValues; current?: () => boolean; legacy?: boolean;
  from?: number;
} = {}): IndicatorAlertPolicyPass {
  return {
    bars: times.map(time => ({ time, open: 1, high: 1, low: 1, close: 1 })),
    values: options.values ?? { v: times.map(() => 1) }, settings: { factor: 2 },
    calculation: {
      execution: options.legacy ? undefined : {
        sourceId: 1, revision, historyRevision: 1, provenance: revision === 1 ? 'history' : 'live',
        change: revision === 1 ? 'initial' : 'replace', confirmationSource: 'provider', ...patch,
      },
      barState: { isNew: patch.change === 'append', isConfirmed: options.confirmed ?? false, isRealtime: revision !== 1, lastIndex: times.length - 1 },
      timezone: 'Etc/UTC', now: () => 1_000, interval: '100t',
    },
    tailOnly: options.tailOnly ?? revision !== 1, refresh: options.refresh ?? false, current: options.current ?? (() => true),
    from: options.from ?? times.length,
  };
}

const spec = (frequency: IndicatorAlertFrequency, patch: Partial<IndicatorAlertSpec> = {}): IndicatorAlertSpec => ({
  id: frequency, title: frequency, frequency, when: () => true, ...patch,
});

function policy(specs: readonly IndicatorAlertSpec[]) {
  const scheduler = new IndicatorAlertPolicy(specs), events: AlertEventPayload[] = [];
  return { scheduler, events, run: (value: IndicatorAlertPolicyPass) => scheduler.evaluate(value, event => events.push(event)) };
}

describe('explicit alert policy selection', () => {
  it('ignores omitted frequencies and validates only explicit identities and frequencies', () => {
    const ignored = policy([{ id: '', title: 'Legacy', when: () => { throw new Error('Legacy evaluated'); } }]);
    ignored.run(pass([0], 1)); ignored.run(pass([0], 2)); expect(ignored.events).toEqual([]);
    expect(() => new IndicatorAlertPolicy([spec('once', { id: ' ' })])).toThrow(/id/i);
    expect(() => new IndicatorAlertPolicy([spec('once'), spec('once')])).toThrow(/unique|duplicate/i);
    expect(() => new IndicatorAlertPolicy([spec('bad' as IndicatorAlertFrequency)])).toThrow(/frequency/i);
  });

  it('seeds loaded history and observes each changed live revision only once', () => {
    const h = policy([spec('everyUpdate')]);
    h.run(pass([0, 60], 1)); expect(h.events).toEqual([]);
    h.run(pass([0, 60], 2)); h.run(pass([0, 60], 2)); h.run(pass([0, 60], 3));
    expect(h.events.map(event => event.time)).toEqual([60, 60]);
    expect(h.events[0]).toEqual({ alertId: 'everyUpdate', title: 'everyUpdate', message: 'everyUpdate', time: 60, index: 1 });
  });

  it('waits for the first matching live value within a bar', () => {
    const h = policy([spec('oncePerBar', { when: ctx => ctx.values.v[ctx.index] === 2 })]);
    h.run(pass([0], 1)); h.run(pass([0], 2));
    h.run(pass([0], 3, {}, { values: { v: [2] } }));
    h.run(pass([0], 4, {}, { values: { v: [2] } }));
    h.run(pass([0, 60], 5, { change: 'append' }, { values: { v: [2, 2] } }));
    expect(h.events.map(event => event.time)).toEqual([0, 60]);
  });

  it('does not treat a completed loaded bar as a new once-per-bar opportunity', () => {
    const h = policy([spec('oncePerBar')]); h.run(pass([0, 60], 1, {}, { confirmed: true }));
    h.run(pass([0, 60], 2, {}, { confirmed: true })); expect(h.events).toEqual([]);
    h.run(pass([0, 60, 120], 3, { change: 'append' })); expect(h.events.map(event => event.time)).toEqual([120]);
  });

  it('keeps once spent across bars, source replacements, history resets and replay', () => {
    const h = policy([spec('once')]); h.run(pass([0], 1)); h.run(pass([0], 2));
    h.run(pass([0, 60], 3, { change: 'append' }));
    h.run(pass([100], 1, { sourceId: 2 })); h.run(pass([100], 2, { sourceId: 2 }));
    h.run(pass([100], 3, { sourceId: 2, historyRevision: 2, provenance: 'history', change: 'reset' }));
    h.run(pass([100], 4, { sourceId: 2, historyRevision: 3, provenance: 'replay', change: 'reset' }));
    h.run(pass([100], 5, { sourceId: 2, historyRevision: 4, provenance: 'history', change: 'reset' }));
    h.run(pass([100], 6, { sourceId: 2, historyRevision: 4 }));
    expect(h.events).toHaveLength(1);
    const other = policy([spec('once')]); other.run(pass([0], 1)); other.run(pass([0], 2)); expect(other.events).toHaveLength(1);
  });

  it('does not spend a once latch during loaded, refreshed or replay calculations', () => {
    const h = policy([spec('once')]); h.run(pass([0], 1));
    h.run(pass([0], 2, {}, { refresh: true })); h.run(pass([0], 2));
    h.run(pass([0], 3, { provenance: 'replay', historyRevision: 2 }));
    h.run(pass([0], 4, { provenance: 'history', historyRevision: 3, change: 'reset' }));
    expect(h.events).toEqual([]);
    h.run(pass([0], 5, { historyRevision: 3 })); expect(h.events).toHaveLength(1);
  });

  it('seeds a correction followed by a coalesced append despite final live provenance', () => {
    const h = policy([spec('everyUpdate'), spec('oncePerBar'), spec('onBarClose')]);
    h.run(pass([0], 1));
    h.run(pass([0, 60, 120], 3, { historyRevision: 2, change: 'append' }, { confirmed: false, tailOnly: false }));
    expect(h.events).toEqual([]);
    h.run(pass([0, 60, 120], 4, { historyRevision: 2 }, { confirmed: true }));
    expect(h.events.map(event => [event.alertId, event.time])).toEqual([['everyUpdate', 120], ['oncePerBar', 120], ['onBarClose', 120]]);
  });

  it.each(['everyUpdate', 'oncePerBar', 'once'] as const)('judges each bar a pass appended for %s, in order, on the bars through it', frequency => {
    const judged: number[][] = [];
    const h = policy([spec(frequency, { when: ctx => { judged.push([ctx.index, ctx.bars.length, ctx.values.v.length]); return ctx.index === 2; } })]);
    h.run(pass([0, 60], 1));
    h.run(pass([0, 60, 120, 180], 2, { change: 'append' }, { from: 2 }));
    // A spent once alert judges nothing after its delivery.
    expect(judged).toEqual(frequency === 'once' ? [[2, 3, 3]] : [[2, 3, 3], [3, 4, 4]]);
    expect(h.events.map(event => [event.time, event.index])).toEqual([[120, 2]]);
    // A tick on the newest bar appends nothing, so only it is judged.
    judged.length = 0;
    h.run(pass([0, 60, 120, 180], 3));
    expect(judged).toEqual(frequency === 'once' ? [] : [[3, 4, 4]]);
  });

  it('supports empty history and first live observations without invented close events', () => {
    const h = policy([spec('everyUpdate'), spec('onBarClose')]);
    h.run(pass([], 1, {}, { confirmed: true }));
    h.run(pass([0], 2, { change: 'append' }));
    expect(h.events.map(event => event.alertId)).toEqual(['everyUpdate']);
  });
});

describe('explicit close policy', () => {
  it('evaluates prior and coalesced completed bars with causal prefixes', () => {
    const seen: [number, number[], (number | null)[]][] = [];
    const h = policy([spec('onBarClose', {
      when: ctx => { seen.push([ctx.index, ctx.bars.map(bar => bar.time), [...ctx.values.v]]); return true; },
      message: ctx => `Closed ${ctx.bars[ctx.bars.length - 1].time}: ${ctx.values.v[ctx.index]}`,
    })]);
    h.run(pass([0], 1));
    h.run(pass([0, 60, 600, 660], 4, { change: 'append' }, { values: { v: [10, 20, 30, 40] }, tailOnly: false }));
    expect(seen).toEqual([[0, [0], [10]], [1, [0, 60], [10, 20]], [2, [0, 60, 600], [10, 20, 30]]]);
    expect(h.events.map(event => event.message)).toEqual(['Closed 0: 10', 'Closed 60: 20', 'Closed 600: 30']);
  });

  it('honors explicit confirmation at the same timestamp and never judges that close again', () => {
    let matched = false;
    const h = policy([spec('onBarClose', { when: () => matched })]);
    h.run(pass([0], 1)); h.run(pass([0], 2, {}, { confirmed: true }));
    matched = true; h.run(pass([0], 3, {}, { confirmed: true }));
    h.run(pass([0, 60], 4, { change: 'append' })); expect(h.events).toEqual([]);
    h.run(pass([0, 60], 5, {}, { confirmed: true })); expect(h.events.map(event => event.time)).toEqual([60]);
  });

  it('seeds confirmed historical tails but lets a forming historical tail close later', () => {
    const closed = policy([spec('onBarClose')]); closed.run(pass([0, 60], 1, {}, { confirmed: true }));
    closed.run(pass([0, 60], 2, {}, { confirmed: true })); expect(closed.events).toEqual([]);
    const forming = policy([spec('onBarClose')]); forming.run(pass([0, 60], 1));
    forming.run(pass([0, 60], 2, {}, { confirmed: true })); expect(forming.events.map(event => event.time)).toEqual([60]);
  });

  it('waits for a live execution after refresh-only clock closure', () => {
    const h = policy([spec('onBarClose')]); h.run(pass([0], 1));
    h.run(pass([0], 1, { provenance: 'history', change: 'refresh', confirmationSource: 'clock' }, { confirmed: true, refresh: true }));
    expect(h.events).toEqual([]);
    h.run(pass([0], 2, { confirmationSource: 'clock' }, { confirmed: true })); expect(h.events).toHaveLength(1);
  });

  it('suppresses a newly observed refresh revision without consuming the pending close', () => {
    const h = policy([spec('onBarClose')]); h.run(pass([0], 1));
    h.run(pass([0], 2, {}, { refresh: true, confirmed: true }));
    h.run(pass([0], 2, {}, { confirmed: true })); expect(h.events).toEqual([]);
    h.run(pass([0], 3, {}, { confirmed: true })); expect(h.events.map(event => event.time)).toEqual([0]);
  });

  it('does not infer confirmation from wall time, interval or the latest provider override for prior bars', () => {
    const h = policy([spec('onBarClose')]); h.run(pass([0], 1));
    h.run(pass([0], 2)); expect(h.events).toEqual([]);
    h.run(pass([0, 86_400], 3, { change: 'append', confirmationSource: 'provider' }));
    expect(h.events.map(event => event.time)).toEqual([0]);
  });

  it('retries a thrown close on the next live revision without repeating completed siblings', () => {
    let fail = true;
    const failure = new Error('Condition failed');
    const h = policy([
      spec('onBarClose', { id: 'a', when: () => { if (fail) throw failure; return true; } }),
      spec('onBarClose', { id: 'b' }),
    ]);
    h.run(pass([0], 1));
    expect(() => h.run(pass([0, 60], 2, { change: 'append' }))).toThrow(failure);
    expect(h.events.map(event => event.alertId)).toEqual(['b']);
    expect(() => h.run(pass([0, 60], 2, { change: 'append' }))).not.toThrow();
    fail = false; h.run(pass([0, 60], 3));
    expect(h.events.map(event => [event.alertId, event.time])).toEqual([['b', 0], ['a', 0]]);
  });

  it('retains a failed close behind later successful close checkpoints', () => {
    let fail = true;
    const h = policy([spec('onBarClose', { when: ctx => { if (ctx.index === 0 && fail) throw new Error('First'); return true; } })]);
    h.run(pass([0], 1)); expect(() => h.run(pass([0, 60, 120], 3, { change: 'append' }))).toThrow('First');
    expect(h.events.map(event => event.time)).toEqual([60]);
    fail = false; h.run(pass([0, 60, 120], 4)); expect(h.events.map(event => event.time)).toEqual([60, 0]);
  });

  it('retries a close message failure only while the same source observation remains available', () => {
    let fail = true;
    const h = policy([spec('onBarClose', { message: () => { if (fail) throw new Error('Message'); return 'Closed'; } })]);
    h.run(pass([0], 1)); expect(() => h.run(pass([0, 60], 2, { change: 'append' }))).toThrow('Message');
    fail = false;
    h.run(pass([60, 120], 3, { historyRevision: 2, provenance: 'history', change: 'reset' }));
    h.run(pass([60, 120], 4, { historyRevision: 2 }, { confirmed: true }));
    expect(h.events.map(event => event.time)).toEqual([120]);
  });
});

describe('explicit alert callback ownership', () => {
  it('leaves once unspent after predicate or message errors and tries siblings', () => {
    let fail = true;
    const h = policy([
      spec('once', { id: 'a', when: () => { if (fail) throw new Error('First error'); return true; } }),
      spec('once', { id: 'b', message: () => { if (fail) throw new Error('Second error'); return 'Recovered'; } }),
      spec('once', { id: 'c' }),
    ]);
    h.run(pass([0], 1)); expect(() => h.run(pass([0], 2))).toThrow('First error');
    expect(h.events.map(event => event.alertId)).toEqual(['c']);
    h.run(pass([0], 2)); fail = false; h.run(pass([0], 3));
    expect(h.events.map(event => event.alertId)).toEqual(['c', 'a', 'b']);
  });

  it('commits delivery before emitting even if a subscriber throws', () => {
    const scheduler = new IndicatorAlertPolicy([spec('once'), spec('oncePerBar')]);
    scheduler.evaluate(pass([0], 1), () => {});
    const events: string[] = [];
    expect(() => scheduler.evaluate(pass([0], 2), event => { events.push(event.alertId); throw new Error('Subscriber'); })).toThrow('Subscriber');
    scheduler.evaluate(pass([0], 3), event => events.push(event.alertId));
    expect(events).toEqual(['once', 'oncePerBar']);
  });

  it('keeps once spent when its subscriber synchronously replaces the source', () => {
    const h = policy([spec('once')]); h.run(pass([0], 1));
    h.scheduler.evaluate(pass([0], 2), event => { h.events.push(event); h.run(pass([600], 1, { sourceId: 2 })); });
    h.run(pass([600], 2, { sourceId: 2 })); expect(h.events).toHaveLength(1);
  });

  it.each(['predicate', 'message', 'emit'] as const)('abandons stale continuation after %s changes current ownership', stage => {
    let current = true;
    const h = policy([
      spec('once', {
        id: 'a', when: () => { if (stage === 'predicate') current = false; return true; },
        message: () => { if (stage === 'message') current = false; return 'A'; },
      }), spec('once', { id: 'b' }),
    ]);
    h.run(pass([0], 1));
    h.scheduler.evaluate(pass([0], 2, {}, { current: () => current }), event => { h.events.push(event); if (stage === 'emit') current = false; });
    expect(h.events.map(event => event.alertId)).toEqual(stage === 'emit' ? ['a'] : []);
  });

  it('reserves the current revision against repeated evaluation inside predicates and events', () => {
    const scheduler = new IndicatorAlertPolicy([spec('everyUpdate', { when: () => { scheduler.evaluate(live, emit); return true; } })]);
    const events: AlertEventPayload[] = [];
    const live = pass([0], 2);
    const emit = (event: AlertEventPayload): void => { events.push(event); scheduler.evaluate(live, emit); };
    scheduler.evaluate(pass([0], 1), emit); scheduler.evaluate(live, emit);
    expect(events).toHaveLength(1);
  });

  it('reserves an in-progress close and abandons the older pass when a newer revision reenters', () => {
    let reenter = true;
    const events: AlertEventPayload[] = [];
    const scheduler = new IndicatorAlertPolicy([spec('onBarClose', { when: () => {
      if (reenter) { reenter = false; scheduler.evaluate(pass([0, 60], 3), event => events.push(event)); }
      return true;
    } })]);
    scheduler.evaluate(pass([0], 1), event => events.push(event));
    scheduler.evaluate(pass([0, 60], 2, { change: 'append' }), event => events.push(event));
    expect(events).toEqual([]);
    scheduler.evaluate(pass([0, 60], 4), event => events.push(event)); expect(events.map(event => event.time)).toEqual([0]);
  });

  it('copies pass inputs before callbacks can mutate the original arrays', () => {
    const input = pass([0], 2);
    const h = policy([spec('everyUpdate', {
      when: ctx => {
        input.bars[0].time = 999; (input.values.v as number[])[0] = 999; (input.settings as Record<string, unknown>).factor = 999;
        expect(Object.isFrozen(ctx.bars)).toBe(true); expect(Object.isFrozen(ctx.values.v)).toBe(true);
        return true;
      },
      message: ctx => `${ctx.bars[0].time}:${ctx.values.v[0]}:${ctx.settings.factor}`,
    })]);
    h.run(pass([0], 1)); h.run(input);
    expect(h.events[0]).toMatchObject({ time: 0, message: '0:1:2' });
  });
});

describe('explicit alerts on legacy hosts', () => {
  it('uses tailOnly eligibility and suppresses refreshes without native execution metadata', () => {
    const h = policy([spec('everyUpdate'), spec('onBarClose')]);
    h.run(pass([0], 1, {}, { legacy: true }));
    h.run(pass([0], 2, {}, { legacy: true, refresh: true, confirmed: true }));
    h.run(pass([0], 3, {}, { legacy: true, confirmed: true }));
    expect(h.events.map(event => event.alertId)).toEqual(['everyUpdate', 'onBarClose']);
    h.run(pass([0, 60], 4, {}, { legacy: true, tailOnly: false }));
    expect(h.events).toHaveLength(2);
  });

  it('reserves a legacy calculation object against callback reentry', () => {
    const h = policy([spec('everyUpdate')]); const live = pass([0], 2, {}, { legacy: true });
    h.run(pass([0], 1, {}, { legacy: true }));
    h.scheduler.evaluate(live, event => { h.events.push(event); h.scheduler.evaluate(live, nested => h.events.push(nested)); });
    expect(h.events).toHaveLength(1);
  });
});
