import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import * as engine from '../src/index';
import * as widget from '../src/widget/index';
import type { AlertSource, ContextMenuEvent } from '../src/index';
import { zoneOffsetSeconds } from '../src/index';
import type { Widget } from '../src/widget/index';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
engine.registerIndicator({
  id: 'widget-alert-study', name: 'Alert study', placement: 'pane', inputs: [],
  plots: [{ key: 'close', title: 'Close reading', type: 'line' }, { key: 'oi', title: 'Open interest', type: 'line' }],
  calc: bars => ({ close: bars.map(bar => bar.close), oi: bars.map(bar => bar.oi ?? null) }),
});
const live: Widget[] = [];
afterEach(() => { for (const w of live.splice(0)) w.destroy(); vi.useRealTimers(); });

function make(options: widget.WidgetOptions = {}): { w: Widget; root: FakeElement } {
  const doc = fakeWidgetDocument();
  const w = widget.createWidget(fakeContainer(doc) as unknown as HTMLElement, {
    document: doc as unknown as Document, persist: false, pixelRatio: () => 1,
    raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
    ...options,
  });
  live.push(w);
  w.chart.applySize(800, 600);
  w.series.setData([{ time: 1000, open: 100, high: 101, low: 99, close: 100 }]);
  const root = w.root as unknown as FakeElement;
  root.rect = { left: 0, top: 0, width: 800, height: 600 };
  root.offsetWidth = 800; root.offsetHeight = 600;
  return { w, root };
}

function field(root: FakeElement, key: string): FakeElement {
  const row = root.querySelector(`[data-key="${key}"]`)!;
  expect(row, `Missing field ${key}`).not.toBeNull();
  return row.querySelector('input') ?? row.querySelector('select') ?? row.querySelector('textarea')!;
}
function change(root: FakeElement, key: string, value: string | boolean): void {
  const input = field(root, key);
  if (typeof value === 'boolean') input.checked = value;
  else input.value = value;
  fire(input, 'change');
}
function click(root: FakeElement, action: string): void {
  const target = root.querySelector(`[data-action="${action}"]`)!;
  expect(target, `Missing action ${action}`).not.toBeNull();
  fire(target, 'click');
}

describe('alert settings schema', () => {
  it('offers only conditions evaluable for each source and exposes range bounds', () => {
    const conditions = (source: AlertSource) => {
      const input = engine.alertSettingsSchema(source).find(input => input.key === 'condition');
      return input?.type === 'select' ? input.options.map(option => option.value) : [];
    };
    expect(conditions({ kind: 'barCondition', id: 'bullish' })).toEqual(['matches']);
    expect(conditions({ kind: 'drawing', drawingId: 'channel', level: 'band' }))
      .toEqual(['enteringRange', 'leavingRange']);
    expect(conditions({ kind: 'drawing', drawingId: 'line' }))
      .toEqual(['crossing', 'crossingUp', 'crossingDown', 'greaterThan', 'lessThan']);
    expect(engine.alertSettingsSchema({ kind: 'price', price: 0 }, 'enteringRange').map(input => input.key))
      .toEqual(expect.arrayContaining(['price', 'upperPrice', 'policy', 'repeat', 'cooldownSeconds', 'expiresAt', 'enabled']));
  });
});

describe('widget alert editor', () => {
  it.each([
    ['UTC', '2030-07-31T12:15:59Z', '2030-09-30T12:15'],
    ['UTC', '2031-12-31T12:15:59Z', '2032-02-29T12:15'],
    ['UTC', '2032-12-31T12:15:59Z', '2033-02-28T12:15'],
    ['Asia/Kolkata', '2030-07-30T20:00:00Z', '2030-09-30T01:30'],
    ['America/New_York', '2030-01-10T17:00:00Z', '2030-03-10T12:00'],
    ['America/New_York', '2030-01-10T07:30:00Z', '2030-03-10T03:30'],
  ])('defaults two chart-calendar months from %s at %s', (zone, now, expected) => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date(now));
    const { w, root } = make();
    w.chart.setTimezone(zone);
    widget.mountAlertEditor(w.context);
    expect(field(root, 'expiresAt').value).toBe(expected);
    click(root, 'save-alert');
    expect(w.alerts.list()).toHaveLength(1);
    const editor = widget.mountAlertEditor(w.context, undefined, { alertId: w.alerts.list()[0].id });
    expect(field(root, 'expiresAt').value).toBe(expected);
    editor.close();
  });

  it.each([false, true])('pins an existing expiry zone across a chart zone change (rerender: %s)', rerender => {
    const { w, root } = make();
    w.chart.setTimezone('UTC');
    const expiresAt = Date.parse('2040-01-15T12:34:25.500Z') / 1000;
    const alert = w.alerts.add({ source: { kind: 'price', price: 105 }, expiresAt });
    widget.mountAlertEditor(w.context, undefined, { alertId: alert.id });
    w.chart.setTimezone('Asia/Kolkata');
    change(root, rerender ? 'condition' : 'title', rerender ? 'greaterThan' : 'Rename only');
    expect(root.querySelector('[data-key="expiresAt"] .oac-row__label')!.textContent).toContain('(UTC)');
    expect(field(root, 'expiresAt').value).toBe('2040-01-15T12:34');
    click(root, 'save-alert');
    expect(w.alerts.list()[0].expiresAt).toBe(expiresAt);
    widget.mountAlertEditor(w.context, undefined, { alertId: alert.id });
    expect(root.querySelector('[data-key="expiresAt"] .oac-row__label')!.textContent).toContain('(Asia/Kolkata)');
    expect(field(root, 'expiresAt').value).toBe('2040-01-15T18:04');
  });

  it('saves a new draft in the labelled zone even if the chart changes zone', () => {
    const { w, root } = make();
    w.chart.setTimezone('UTC');
    widget.mountAlertEditor(w.context);
    change(root, 'expiresAt', '2040-01-15T12:34');
    w.chart.setTimezone('Asia/Kolkata');
    change(root, 'condition', 'greaterThan');
    expect(root.querySelector('[data-key="expiresAt"] .oac-row__label')!.textContent).toContain('(UTC)');
    click(root, 'save-alert');
    expect(w.alerts.list()[0].expiresAt).toBe(Date.parse('2040-01-15T12:34:00Z') / 1000);
  });

  it.each([
    ['America/New_York', '2030-03-10T02:30'],
    ['Europe/Berlin', '2030-03-31T02:30'],
    ['UTC', '2030-02-30T12:00'],
  ])('rejects a nonexistent local expiry in %s: %s', (zone, value) => {
    const { w, root } = make();
    w.chart.setTimezone(zone);
    const editor = widget.mountAlertEditor(w.context);
    change(root, 'expiresAt', value);
    click(root, 'save-alert');
    expect(w.alerts.list()).toHaveLength(0);
    expect(editor.isOpen()).toBe(true);
    expect(root.querySelector('.oac-alert-error')!.textContent).toContain('Enter an expiry date and time');
  });

  it.each([
    ['America/New_York', '2030-11-03T01:30', '2030-11-03T05:30:00Z', '2030-11-03T06:30:25.500Z'],
    ['Europe/Berlin', '2030-10-27T02:30', '2030-10-27T01:30:00Z', '2030-10-27T00:30:25.500Z'],
  ])('resolves a new overlap consistently and preserves either existing instant in %s', (zone, value, expected, other) => {
    const { w, root } = make();
    w.chart.setTimezone(zone);
    widget.mountAlertEditor(w.context);
    change(root, 'expiresAt', value);
    click(root, 'save-alert');
    expect(w.alerts.list()[0].expiresAt).toBe(Date.parse(expected) / 1000);
    const expiresAt = Date.parse(other) / 1000;
    const alert = w.alerts.add({ source: { kind: 'price', price: 105 }, expiresAt });
    widget.mountAlertEditor(w.context, undefined, { alertId: alert.id });
    expect(field(root, 'expiresAt').value).toBe(value);
    change(root, 'title', 'Rename only');
    click(root, 'save-alert');
    expect(w.alerts.list().find(item => item.id === alert.id)!.expiresAt).toBe(expiresAt);
  });

  it('keeps no expiry on existing alerts and accepts clearing the default on new alerts', () => {
    const { w, root } = make();
    const alert = w.alerts.add({ source: { kind: 'price', price: 105 } });
    widget.mountAlertEditor(w.context, undefined, { alertId: alert.id });
    expect(field(root, 'expiresAt').value).toBe('');
    change(root, 'title', 'Rename only');
    click(root, 'save-alert');
    expect(w.alerts.list()[0].expiresAt).toBeUndefined();
    widget.mountAlertEditor(w.context);
    change(root, 'expiresAt', '');
    click(root, 'save-alert');
    expect(w.alerts.list()).toHaveLength(2);
    expect(w.alerts.list()[1].expiresAt).toBeUndefined();
  });

  it('treats a change of data variant under an open editor as a change of context', () => {
    const { w, root } = make({ symbol: 'AAA', exchange: 'X', interval: '1m' });
    widget.mountAlertEditor(w.context);
    expect((root.querySelector('[data-action="save-alert"]') as FakeElement).disabled).toBe(false);
    w.setDataVariant({ session: 'extended' });
    const save = root.querySelector('[data-action="save-alert"]') as FakeElement;
    expect(save.disabled).toBe(true);
    expect(root.textContent).toContain('The instrument context changed');
    click(root, 'save-alert');
    expect(w.alerts.list()).toHaveLength(0);
  });

  it('names the series of an alert set on a non-default variant in the list', () => {
    const { w, root } = make({ symbol: 'AAA', exchange: 'X', interval: '1m', variant: { session: 'extended', currency: 'USD' } });
    w.alerts.add({ source: { kind: 'price', price: 105 }, title: 'Pre-market level' });
    widget.mountAlertsPanel(w.context);
    expect(root.querySelector('.oac-alerts__summary')!.textContent).toContain('AAA / X / 1m / Extended hours USD');
  });

  it('refuses an alert with no name', () => {
    const { w, root } = make();
    const editor = widget.mountAlertEditor(w.context);
    change(root, 'title', '   ');
    click(root, 'save-alert');
    expect(w.alerts.list()).toHaveLength(0);
    expect(editor.isOpen()).toBe(true);
    expect(root.querySelector('.oac-alert-error')!.textContent).toBe('Enter a name');
  });

  it('keeps keyboard focus on a selector when its dependent fields change', () => {
    const { w, root } = make();
    widget.mountAlertEditor(w.context);
    field(root, 'condition').focus();
    change(root, 'condition', 'enteringRange');
    expect(w.context.document.activeElement).toBe(field(root, 'condition'));
    expect(field(root, 'upperPrice')).not.toBeNull();
  });
  it('selects a particular study instance and plot without converting an absent value to zero', () => {
    const { w, root } = make();
    w.chart.addIndicator('widget-alert-study');
    const second = w.chart.addIndicator('widget-alert-study');
    widget.mountAlertEditor(w.context);
    change(root, 'kind', 'indicator');
    change(root, 'instanceId', second.id);
    change(root, 'plotKey', 'oi');
    expect(field(root, 'value').value).toBe('');
    expect(root.textContent).toContain('unavailable');
    change(root, 'value', '0');
    click(root, 'save-alert');
    expect(w.alerts.list()).toMatchObject([{ source: { kind: 'indicator', instanceId: second.id, plotKey: 'oi', value: 0 } }]);
    expect(w.alerts.availability(w.alerts.list()[0].id).available).toBe(false);
  });

  it('offers registered candle predicates and stores their identity', () => {
    const { w, root } = make();
    widget.mountAlertEditor(w.context);
    change(root, 'kind', 'barCondition');
    change(root, 'barConditionId', 'outside');
    click(root, 'save-alert');
    expect(w.alerts.list()).toMatchObject([{ source: { kind: 'barCondition', id: 'outside' }, condition: 'matches' }]);
  });

  it('requires a compatible input plot for a study-pane drawing and stores its explicit level', () => {
    const { w, root } = make();
    const study = w.chart.addIndicator('widget-alert-study');
    const drawing = w.draw.add({ tool: 'horizontal-line', paneIndex: study.paneIndex, style: {}, points: [{ time: 1000, price: 105 }] });
    widget.mountAlertEditor(w.context, undefined, { source: { kind: 'drawing', drawingId: drawing.id } });
    expect(field(root, 'inputInstanceId').value).toBe(study.id);
    change(root, 'inputPlotKey', 'close');
    click(root, 'save-alert');
    expect(w.alerts.list()).toMatchObject([{ source: {
      kind: 'drawing', drawingId: drawing.id, level: 'line', input: { instanceId: study.id, plotKey: 'close' },
    } }]);
  });

  it('changes a channel band to a line condition when selecting a boundary', () => {
    const { w, root } = make();
    const drawing = w.draw.add({ tool: 'parallel-channel', paneIndex: 0, style: {},
      points: [{ time: 900, price: 90 }, { time: 1100, price: 100 }, { time: 1000, price: 110 }] });
    widget.mountAlertEditor(w.context, undefined, { source: { kind: 'drawing', drawingId: drawing.id, level: 'band' } });
    expect(field(root, 'condition').value).toBe('enteringRange');
    change(root, 'level', 'base');
    expect(field(root, 'condition').value).toBe('crossing');
    click(root, 'save-alert');
    expect(w.alerts.list()[0]).toMatchObject({ condition: 'crossing', source: { level: 'base' } });
  });

  it('disables unsupported or removed drawing anchors with an explanation', () => {
    const { w, root } = make();
    const unsupported = w.draw.add({ tool: 'rectangle', paneIndex: 0, style: {}, points: [{ time: 900, price: 90 }, { time: 1100, price: 100 }] });
    const editor = widget.mountAlertEditor(w.context, undefined, { source: { kind: 'drawing', drawingId: unsupported.id } });
    expect(root.querySelector('[data-action="save-alert"]')!.disabled).toBe(true);
    expect(root.querySelector('.oac-alert-error')!.textContent).toContain('numeric');
    editor.close();
    const drawing = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 1000, price: 105 }] });
    widget.mountAlertEditor(w.context, undefined, { source: { kind: 'drawing', drawingId: drawing.id } });
    w.draw.remove(drawing.id);
    expect(root.querySelector('[data-action="save-alert"]')!.disabled).toBe(true);
    click(root, 'save-alert');
    expect(w.alerts.list()).toEqual([]);
  });

  it('owns the evaluator and saves a draft only after explicit confirmation', () => {
    const { w, root } = make();
    expect(w.alerts).toBeInstanceOf(engine.AlertController);
    expect(w.context.alerts).toBe(w.alerts);
    const editor = widget.mountAlertEditor(w.context, undefined, { source: { kind: 'price', price: 105 } });
    expect(root.textContent).toContain('Bar close');
    expect(root.textContent).toContain('final history');
    change(root, 'title', 'My threshold');
    expect(w.alerts.list()).toEqual([]);
    click(root, 'save-alert');
    expect(editor.isOpen()).toBe(false);
    expect(w.alerts.list()).toMatchObject([{ title: 'My threshold', source: { kind: 'price', price: 105 }, policy: 'onBarClose', repeat: 'once' }]);
    expect(w.getState().chart.alerts?.alerts).toHaveLength(1);
  });

  it('cancels without creating an alert or changing an existing alert', () => {
    const { w, root } = make();
    widget.mountAlertEditor(w.context);
    click(root, 'cancel-alert');
    expect(w.alerts.list()).toEqual([]);
    const alert = w.alerts.add({ source: { kind: 'price', price: 105 }, title: 'Original' });
    const editor = widget.mountAlertEditor(w.context, undefined, { alertId: alert.id });
    change(root, 'title', 'Draft');
    editor.close();
    expect(w.alerts.list()[0].title).toBe('Original');
  });

  it('accepts zero bounds, explicit touch timing, cooldown and an expiry on the chart clock', () => {
    const { w, root } = make();
    widget.mountAlertEditor(w.context, undefined, { source: { kind: 'price', price: 0 } });
    change(root, 'condition', 'enteringRange');
    change(root, 'upperPrice', '10');
    change(root, 'policy', 'onTouch');
    change(root, 'repeat', 'everyTime');
    change(root, 'cooldownSeconds', '45');
    change(root, 'expiresAt', '2099-01-02T03:04');
    change(root, 'enabled', false);
    click(root, 'save-alert');
    // The reading is on the CHART's clock, not UTC. An alert is set against
    // candles the chart has already labelled in its timezone, so an expiry
    // read in another one is five and a half hours out on this chart's default
    // and asks the reader to do that arithmetic themselves. The stored instant
    // is therefore the wall clock minus the zone's offset.
    const zone = w.context.chart.timezone();
    const wallClockAsUtc = Date.parse('2099-01-02T03:04:00Z') / 1000;
    expect(w.alerts.list()).toMatchObject([{
      source: { kind: 'price', price: 0, upperPrice: 10 }, condition: 'enteringRange',
      policy: 'onTouch', repeat: 'everyTime', cooldownSeconds: 45, state: 'disabled',
      expiresAt: wallClockAsUtc - zoneOffsetSeconds(wallClockAsUtc, zone),
    }]);
    // And the offset is not zero on the default zone, so the line above is
    // asserting something: written against UTC this test passed either way.
    expect(zoneOffsetSeconds(wallClockAsUtc, zone)).not.toBe(0);
  });

  it('opens a new alert with an expiry two months out, on the chart clock', () => {
    // An alert with no expiry never stops asking and one that expires this
    // week is gone before the setup arrives. The field is prefilled so that
    // neither is the default, and it is prefilled in the zone the field is
    // labelled with.
    const { w, root } = make();
    widget.mountAlertEditor(w.context, undefined, { source: { kind: 'price', price: 100 } });
    const value = field(root, 'expiresAt').value;
    expect(value).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);

    const zone = w.context.chart.timezone();
    const asUtc = Date.parse(`${value}:00Z`) / 1000;
    const instant = asUtc - zoneOffsetSeconds(asUtc, zone);
    const months = (instant - Date.now() / 1000) / (30 * 24 * 3600);
    // Two calendar months is between 59 and 62 days, so the window is wide
    // enough for any starting date and far too narrow for a week or a year.
    expect(months).toBeGreaterThan(1.9);
    expect(months).toBeLessThan(2.1);
  });

  it('labels the expiry field with the zone it is read in', () => {
    // A field reading a time in one zone under a label naming another is
    // worse than an unlabelled one, and the schema's label is a fixed string
    // that cannot know the chart's zone.
    const { w, root } = make();
    widget.mountAlertEditor(w.context, undefined, { source: { kind: 'price', price: 100 } });
    const label = root.querySelector('[data-key="expiresAt"] .oac-row__label');
    expect(label?.textContent).toContain(w.context.chart.timezone());
    expect(label?.textContent).not.toContain('UTC');
  });

  it('rejects an empty threshold instead of retaining a stale numeric draft', () => {
    const { w, root } = make();
    const editor = widget.mountAlertEditor(w.context, undefined, { source: { kind: 'price', price: 105 } });
    field(root, 'price').value = '';
    fire(field(root, 'price'), 'change');
    click(root, 'save-alert');
    expect(editor.isOpen()).toBe(true);
    expect(w.alerts.list()).toEqual([]);
    expect(root.querySelector('.oac-alert-error')!.textContent).not.toBe('');
  });

  it('preserves a triggered once alert when editing its title, then enables it deliberately', () => {
    const { w, root } = make();
    const alert = w.alerts.add({ source: { kind: 'price', price: 105 }, policy: 'onTouch', title: 'Threshold' });
    w.series.update({ time: 1000, open: 100, high: 110, low: 99, close: 110 });
    expect(w.alerts.list()[0].state).toBe('triggered');
    expect(root.querySelector('.oac-toast__msg')!.textContent).toContain('Threshold');
    widget.mountAlertEditor(w.context, undefined, { alertId: alert.id });
    change(root, 'title', 'Already fired');
    click(root, 'save-alert');
    expect(w.alerts.list()[0]).toMatchObject({ state: 'triggered', title: 'Already fired', lastTriggeredTime: 1000 });
    widget.mountAlertEditor(w.context, undefined, { alertId: alert.id });
    change(root, 'enabled', true);
    click(root, 'save-alert');
    expect(w.alerts.list()[0].state).toBe('armed');
  });

  it('prevents a draft from being silently retargeted after an instrument change', () => {
    const { w, root } = make();
    const editor = widget.mountAlertEditor(w.context, undefined, { source: { kind: 'price', price: 105 } });
    w.setSymbol('NEW', 'NSE');
    click(root, 'save-alert');
    expect(editor.isOpen()).toBe(true);
    expect(w.alerts.list()).toEqual([]);
    expect(root.querySelector('.oac-alert-error')!.textContent).toContain('context');
  });

  it('preserves an existing expiry instant when another field is edited', () => {
    const { w, root } = make();
    const expiresAt = Date.parse('2099-01-02T03:04:25Z') / 1000 + 0.5;
    const alert = w.alerts.add({ source: { kind: 'price', price: 105 }, expiresAt });
    widget.mountAlertEditor(w.context, undefined, { alertId: alert.id });
    change(root, 'title', 'Rename only');
    click(root, 'save-alert');
    expect(w.alerts.list()[0].expiresAt).toBe(expiresAt);
  });

  it('keeps labels bound to the correct editor when two drafts are open', () => {
    const { w } = make();
    const one = widget.mountAlertEditor(w.context);
    const two = widget.mountAlertEditor(w.context);
    const first = field(one.el as unknown as FakeElement, 'price');
    const second = field(two.el as unknown as FakeElement, 'price');
    expect(first.id).not.toBe(second.id);
    one.close(); two.close();
  });
});

describe('widget alert list', () => {
  it('names each source the way the editor lists it, and prints a price in the pane format', () => {
    const { w, root } = make();
    const fib = w.draw.add({ tool: 'fib-retracement', paneIndex: 0, style: {}, points: [{ time: 900, price: 90 }, { time: 1100, price: 110 }] });
    const line = w.draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, points: [{ time: 900, price: 90 }, { time: 1100, price: 110 }] });
    const study = w.chart.addIndicator('widget-alert-study');
    const onFib = w.alerts.add({ source: { kind: 'drawing', drawingId: fib.id, level: 'ratio:0.618' } });
    const onLine = w.alerts.add({ source: { kind: 'drawing', drawingId: line.id, level: 'line' } });
    const onStudy = w.alerts.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'close', value: 100 } });
    const onPrice = w.alerts.add({ source: { kind: 'price', price: 22345.6789 } });
    widget.mountAlertsPanel(w.context);
    const summary = (id: string): string => root.querySelector(`[data-alert-id="${id}"] .oac-alerts__summary`)!.textContent;
    // The level the editor lists for ratio 0.618.
    expect(summary(onFib.id)).toContain('/ 61.8%');
    expect(summary(onFib.id)).not.toContain('ratio:');
    expect(summary(onLine.id)).toContain('/ Line');
    expect(summary(onStudy.id)).toContain('Alert study / Close reading: 100');
    const shown = w.chart.panes()[w.chart.primaryPaneIndex()].readoutScale().format(22345.6789);
    expect(summary(onPrice.id)).toContain(`Price ${shown}`);
    expect(summary(onPrice.id)).not.toContain('22345.6789');
  });

  it('prints a study value and its upper bound on the study\'s own scale', () => {
    const { w, root } = make();
    const study = w.chart.addIndicator('widget-alert-study');
    const one = w.alerts.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'close', value: 1.23456789 } });
    const band = w.alerts.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'close', value: 1.23456789, upperValue: 2.98765432 } });
    widget.mountAlertsPanel(w.context);
    const summary = (id: string): string => root.querySelector(`[data-alert-id="${id}"] .oac-alerts__summary`)!.textContent;
    const scale = study.series('close')!.priceScale();
    expect(scale.format(1.23456789)).not.toBe('1.23456789');
    expect(summary(one.id)).toContain(`Alert study / Close reading: ${scale.format(1.23456789)}`);
    expect(summary(band.id)).toContain(`${scale.format(1.23456789)} to ${scale.format(2.98765432)}`);
    expect(summary(band.id)).not.toContain('1.23456789');
  });

  it('gives one object one number in Objects and the alert editor, counting only listed drawings', () => {
    const { w, root } = make();
    const at = [{ time: 900, price: 90 }, { time: 1100, price: 110 }];
    const add = (tool: string, listed = true) => w.draw.add({ tool, paneIndex: 0, style: {}, points: at, ...(listed ? {} : { policy: { listed: false } }) });
    const unlisted = add('trend-line', false), first = add('trend-line'), box = add('rectangle'), second = add('trend-line');
    // Brought to the front, the first line is now the second of its name, on both surfaces.
    w.draw.reorder(first.id, 1); w.draw.reorder(first.id, 1);
    const panel = widget.createObjectsPanelContent(w.context);
    const tree = panel.element as unknown as FakeElement;
    const row = (id: string): string => tree.querySelector(`[data-object-id="drawing:${id}"] .oac-objects__name`)!.textContent;
    expect([row(first.id), row(box.id), row(second.id)]).toEqual(['Trend Line (2)', 'Rectangle', 'Trend Line (1)']);
    widget.mountAlertEditor(w.context, undefined, { source: { kind: 'drawing', drawingId: second.id } });
    const options = new Map(field(root, 'drawingId').querySelectorAll('option').map(option => [option.value, option.textContent]));
    expect([options.get(first.id), options.get(box.id), options.get(second.id)]).toEqual(['Trend Line (2)', 'Rectangle', 'Trend Line (1)']);
    expect(options.has(unlisted.id)).toBe(false);
    // An unlisted drawing an alert already names is listed for it, after the listed ones.
    const onHidden = w.alerts.add({ source: { kind: 'drawing', drawingId: unlisted.id, level: 'line' } });
    widget.mountAlertsPanel(w.context);
    expect(root.querySelector(`[data-alert-id="${onHidden.id}"] .oac-alerts__summary`)!.textContent).toContain('Trend Line (3) / Line');
    panel.destroy();
  });

  it('gives one study one number in Objects, the alert editor and the alert list', () => {
    const { w, root } = make();
    w.chart.addIndicator('widget-alert-study', {}, { policy: { listed: false } });
    const first = w.chart.addIndicator('widget-alert-study');
    const second = w.chart.addIndicator('widget-alert-study');
    const panel = widget.createObjectsPanelContent(w.context);
    const tree = panel.element as unknown as FakeElement;
    const row = (id: string): string => tree.querySelector(`[data-object-id="indicator:${id}"] .oac-objects__name`)!.textContent;
    expect([row(first.id), row(second.id)]).toEqual(['Alert study (1)', 'Alert study (2)']);
    const onSecond = w.alerts.add({ source: { kind: 'indicator', instanceId: second.id, plotKey: 'close', value: 100 } });
    widget.mountAlertEditor(w.context, undefined, { alertId: onSecond.id });
    expect(field(root, 'instanceId').querySelectorAll('option').map(option => option.textContent)).toEqual(['Alert study (1)', 'Alert study (2)']);
    widget.mountAlertsPanel(w.context);
    expect(root.querySelector(`[data-alert-id="${onSecond.id}"] .oac-alerts__summary`)!.textContent).toContain('Alert study (2) / Close reading');
    panel.destroy();
  });

  it('refreshes an open price-only list when the chart timezone changes without changing the expiry instant', () => {
    const { w, root } = make();
    w.chart.setTimezone('UTC');
    expect(w.chart.indicators()).toEqual([]);
    const expiresAt = Date.parse('2099-01-02T03:04:25.500Z') / 1000;
    const record = w.alerts.add({ source: { kind: 'price', price: 105 }, expiresAt });
    w.openAlerts();
    const status = root.querySelector(`[data-alert-id="${record.id}"] .oac-alerts__status`)!;
    expect(status.textContent).toContain('Expires 2099-01-02 03:04');
    w.chart.setTimezone('Asia/Kolkata');
    expect(status.textContent).toContain('Expires 2099-01-02 08:34');
    expect(w.alerts.list()[0].expiresAt).toBe(expiresAt);
  });

  it('saves a consumed touch even when cooldown suppresses its delivery', () => {
    vi.useFakeTimers();
    const store = new Map<string, string>();
    const { w } = make({ persist: true, storage: {
      getItem: key => store.get(key) ?? null,
      setItem: (key, value) => { store.set(key, value); }, removeItem: key => { store.delete(key); },
    } });
    w.alerts.add({ source: { kind: 'price', price: 105 }, condition: 'greaterThan', policy: 'onTouch', repeat: 'everyTime', cooldownSeconds: 60 });
    w.series.update({ time: 1000, open: 100, high: 110, low: 99, close: 110 });
    vi.advanceTimersByTime(300);
    w.series.update({ time: 1060, open: 110, high: 111, low: 110, close: 111 });
    vi.advanceTimersByTime(300);
    const saved = w.context.storage.get(widget.STATE_KEY) as widget.WidgetState;
    expect(saved.chart.alerts?.alerts[0]).toMatchObject({ lastTriggeredTime: 1000, lastTouchedTime: 1060 });
  });
  it('updates and saves an expiry on an idle feed', () => {
    vi.useFakeTimers();
    const store = new Map<string, string>();
    const { w, root } = make({ persist: true, storage: {
      getItem: key => store.get(key) ?? null,
      setItem: (key, value) => { store.set(key, value); }, removeItem: key => { store.delete(key); },
    } });
    const record = w.alerts.add({ source: { kind: 'price', price: 105 }, expiresAt: Date.now() / 1000 + 1 });
    w.openAlerts();
    vi.advanceTimersByTime(1300);
    const row = root.querySelector(`[data-alert-id="${record.id}"]`)!;
    expect(row.textContent).toContain('Expired');
    const saved = w.context.storage.get(widget.STATE_KEY) as widget.WidgetState;
    expect(saved.chart.alerts?.alerts[0].state).toBe('expired');
    expect(row.querySelector('[data-action="toggle-alert"]')!.disabled).toBe(true);
    expect(row.querySelector('[data-action="toggle-alert"]')!.title).toContain('expiry');
  });
  it('opens from desktop and mobile controls and reflects enable, disable and delete immediately', () => {
    const { w, root } = make();
    const record = w.alerts.add({ title: 'Visible alert', source: { kind: 'price', price: 105 } });
    const opener = root.querySelector('.oac-topbar__alerts');
    expect(opener).not.toBeNull();
    fire(opener!, 'click');
    let row = root.querySelector(`[data-alert-id="${record.id}"]`)!;
    expect(row.textContent).toContain('Active');
    click(row, 'toggle-alert');
    expect(w.alerts.list()[0].state).toBe('disabled');
    row = root.querySelector(`[data-alert-id="${record.id}"]`)!;
    expect(row.textContent).toContain('Disabled');
    click(row, 'toggle-alert');
    expect(w.alerts.list()[0].state).toBe('armed');
    click(row, 'delete-alert');
    expect(w.alerts.list()).toEqual([]);
    expect(root.querySelector('.oac-alerts')!.textContent).toContain('No alerts');
    w.context.overlays.closeAll();
    const more = root.querySelector('[data-mobile-action="more"]')!;
    fire(more, 'click');
    fire(root.querySelector('[data-mobile-action="alerts"]')!, 'click');
    expect(root.querySelector('.oac-alerts')).not.toBeNull();
    w.destroy();
    expect(w.openAlerts()).toBe(false);
  });

  it('keeps a triggered once record visible after a widget state restore without a new notification', () => {
    const { w, root } = make();
    w.alerts.add({ title: 'Fired alert', source: { kind: 'price', price: 105 }, policy: 'onTouch' });
    w.series.update({ time: 1000, open: 100, high: 110, low: 99, close: 110 });
    const state = w.getState();
    const restored = make();
    restored.w.restoreState(state);
    expect(restored.root.querySelector('.oac-toast__msg')).toBeNull();
    expect(restored.w.openAlerts()).toBe(true);
    expect(restored.root.querySelector('.oac-alerts')!.textContent).toContain('Triggered');
    expect(restored.root.querySelector('.oac-alerts')!.textContent).toContain('Fired alert');
    expect(root.querySelector('.oac-toast__msg')).not.toBeNull();
  });

  it('reports a nonportable host payload without aborting widget teardown', () => {
    const store = new Map<string, string>();
    const { w } = make({ persist: true, storage: {
      getItem: key => store.get(key) ?? null,
      setItem: (key, value) => { store.set(key, value); }, removeItem: key => { store.delete(key); },
    } });
    const errors: string[] = [];
    w.on('status', event => { if (event.kind === 'error') errors.push(event.text); });
    w.alerts.add({ source: { kind: 'price', price: 105 }, payload: { callback: () => {} } });
    expect(() => w.destroy()).not.toThrow();
    expect(w.isDestroyed).toBe(true);
    expect(errors.join(' ')).toContain('saved');
    expect(w.alerts.list()).toEqual([]);
  });
});

describe('alert context actions', () => {
  it('seeds the clicked plot and bar reading instead of the first plot or latest bar', () => {
    const { w, root } = make();
    w.series.setData([{ time: 1000, open: 100, high: 101, low: 99, close: 100, oi: 0 },
      { time: 1060, open: 110, high: 111, low: 109, close: 110, oi: 20 }]);
    const study = w.chart.addIndicator('widget-alert-study');
    const event: ContextMenuEvent = { paneIndex: study.paneIndex, point: { x: 150, y: 80 },
      price: 0, time: 1000, index: 0,
      target: { kind: 'indicator', id: `indicator:${study.id}`, instanceId: study.id, plotKey: 'oi' },
      preventDefault: () => {} };
    const action = widget.contextMenuEntries(w.context, event)
      .find(entry => 'id' in entry && entry.id === 'alert-indicator') as widget.MenuItem;
    action.run!();
    expect(field(root, 'plotKey').value).toBe('oi');
    expect(field(root, 'value').value).toBe('0');
  });

  it('seeds a price or drawing alert from its actual target, and keeps study-pane units separate', () => {
    const { w, root } = make();
    const event: ContextMenuEvent = { paneIndex: 0, point: { x: 150, y: 80 }, price: 107, time: 1000, index: 0,
      target: { kind: 'empty', id: null }, preventDefault: () => {} };
    const menu = widget.contextMenuEntries(w.context, event);
    const action = menu.find(entry => entry.kind !== 'separator' && entry.kind !== 'header' && entry.id === 'alert-create') as widget.MenuItem;
    expect(action).toBeDefined();
    action.run!();
    expect(field(root, 'price').value).toBe('107');
    w.context.overlays.closeAll();
    expect(widget.contextMenuEntries(w.context, { ...event, paneIndex: 1 }).some(entry => 'id' in entry && entry.id === 'alert-create')).toBe(false);
    const line = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 1000, price: 109 }] });
    const drawingMenu = widget.contextMenuEntries(w.context, { ...event, target: { kind: 'drawing', id: `draw:${line.id}` } });
    const drawingAction = drawingMenu.find(entry => 'id' in entry && entry.id === 'alert-drawing') as widget.MenuItem;
    expect(drawingAction).toBeDefined();
    drawingAction.run!();
    click(root, 'save-alert');
    expect(w.alerts.list()[0].source).toMatchObject({ kind: 'drawing', drawingId: line.id, level: 'line' });
  });
});
