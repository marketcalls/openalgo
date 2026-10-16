import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createWidget, type Widget, type WidgetOptions } from '../src/widget/widget';
import { ReplayController } from '../src/replay/controller';
import { fakeWidgetDocument, fakeContainer, fire, fireKey, ensureWindowGlobal, type FakeElement } from './helpers/fake-dom-widget';
import '../src/indicators/index';

const widgets: Widget[] = [];
const downloads: Blob[] = [];
// Four one-minute bars from 09:15 IST on 28 September 2026: the dialog's
// bounds are typed on the chart's clock, which is IST by default.
const T0 = Date.UTC(2026, 8, 28, 3, 45) / 1000;
const rows = [1, 3, 5, 7].map((close, index) => ({ time: T0 + index * 60, open: close, high: close + 1, low: close - 1, close }));
const at = (index: number): number => T0 + index * 60;
beforeEach(() => {
  ensureWindowGlobal();
  downloads.length = 0;
  vi.spyOn(URL, 'createObjectURL').mockImplementation(blob => { downloads.push(blob as Blob); return 'blob:csv-test'; });
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
});
afterEach(() => { widgets.splice(0).forEach(widget => widget.destroy()); vi.restoreAllMocks(); });
function make(options: WidgetOptions = {}) {
  const doc = fakeWidgetDocument();
  const widget = createWidget(fakeContainer(doc) as unknown as HTMLElement, {
    document: doc as unknown as Document, symbol: 'SAMPLE', interval: '1m', shortcuts: false,
    pixelRatio: () => 1, raf: { schedule: () => 0, cancel: () => {} }, ...options,
  });
  widgets.push(widget);
  widget.chart.applySize(800, 500);
  widget.series.setData(rows);
  const root = widget.root as unknown as FakeElement;
  root.rect = { left: 0, top: 0, width: 800, height: 500 };
  return { widget, root, doc };
}
function open(root: FakeElement): FakeElement {
  root.querySelector('[aria-label="Capture chart"]')!.click();
  root.querySelectorAll('.oac-menu__row').find(row => row.textContent === 'Download chart data (CSV)')!.click();
  const dialog = root.querySelector('.oac-csv');
  expect(dialog).not.toBeNull();
  return dialog!;
}
const field = (dialog: FakeElement, key: string): FakeElement => dialog.querySelector(`[data-key="${key}"] input`)!;
function edit(dialog: FakeElement, key: string, value: string): void {
  const input = field(dialog, key); input.value = value; fire(input, 'input'); fire(input, 'change');
}
const action = (dialog: FakeElement, name: string): FakeElement => dialog.querySelector(`[data-action="${name}"]`)!;

describe('widget chart data download options', () => {
  it('opens a modal without downloading and captures hidden repeated instances separately', () => {
    const { widget, root } = make();
    const first = widget.chart.addIndicator('sma', { length: 1 });
    const hidden = widget.chart.addIndicator('sma', { length: 2 }); hidden.setVisible(false);
    const dialog = open(root);
    expect(downloads).toHaveLength(0);
    expect(dialog.getAttribute('role')).toBe('dialog');
    expect(field(dialog, 'study-0').checked).toBe(true);
    expect(field(dialog, 'study-1').checked).toBe(true);
    // Repeated instances are told apart by their place among their name, not by an internal id.
    const label = (key: string): string => dialog.querySelector(`[data-key="${key}"] label`)!.textContent;
    expect(label('study-0')).toBe(`${first.name} (1)`);
    expect(label('study-1')).toBe(`${hidden.name} (2), hidden`);
    expect(dialog.textContent).not.toContain(first.id);
    widget.chart.addIndicator('ema', { length: 1 });
    expect(dialog.querySelectorAll('input[type="checkbox"]')).toHaveLength(2);
  });

  it('numbers only listed studies, so a host study the list never shows moves no number', () => {
    const { widget, root } = make();
    const host = widget.chart.addIndicator('sma', { length: 4 }, { policy: { listed: false } });
    const first = widget.chart.addIndicator('sma', { length: 1 });
    const second = widget.chart.addIndicator('sma', { length: 2 });
    const lone = widget.chart.addIndicator('ema', { length: 1 });
    const dialog = open(root);
    const labels = dialog.querySelectorAll('[data-key]').filter(node => node.getAttribute('data-key')!.startsWith('study-'))
      .map(node => node.querySelector('label')!.textContent);
    // The chart's order is host, first, second, lone; the host study counts after the listed two.
    expect(labels).toEqual([`${host.name} (3)`, `${first.name} (1)`, `${second.name} (2)`, lone.name]);
  });

  it('asks for the bounds as dates and times on the chart clock, not as epoch seconds', () => {
    const { root } = make(); const dialog = open(root);
    for (const key of ['from', 'to']) expect(field(dialog, key).type).toBe('datetime-local');
    expect(dialog.querySelector('[data-key="from"] label')!.textContent).toBe('From');
    expect(dialog.querySelector('[data-key="to"] label')!.textContent).toBe('To');
    expect(dialog.textContent).toContain('Times are on the chart clock, Asia/Kolkata.');
    expect(dialog.textContent).not.toContain('UTC seconds');
  });

  it('downloads only captured checked IDs and custom inclusive bounds after full warmup', async () => {
    const { widget, root } = make();
    const first = widget.chart.addIndicator('sma', { length: 1 });
    const second = widget.chart.addIndicator('sma', { length: 3 });
    const dialog = open(root);
    field(dialog, 'study-0').checked = false;
    // A To written to the minute takes in every bar that opens inside it.
    edit(dialog, 'from', '2026-09-28T09:17'); edit(dialog, 'to', '2026-09-28T09:18');
    widget.chart.addIndicator('ema', { length: 1 });
    action(dialog, 'download-csv').click();
    expect(downloads).toHaveLength(1);
    expect(await downloads[0].text()).toBe(`time,open,high,low,close,volume,oi,indicator:${second.id}:ma\r\n${at(2)},5,6,4,5,,,3\r\n${at(3)},7,8,6,7,,,5\r\n`);
    expect(await downloads[0].text()).not.toContain(first.id);
    expect(root.querySelector('.oac-csv')).toBeNull();
  });

  it('fills the captured visible bounds even after navigation, and clears back to all loaded', async () => {
    const { widget, root } = make();
    // A one-bar viewport must fit below the native maximum spacing.
    widget.chart.applySize(120, 500);
    widget.chart.setVisibleLogicalRange({ from: 1, to: 2 });
    expect(widget.chart.getVisibleLogicalRange()).toEqual({ from: 1, to: 2 });
    const dialog = open(root);
    widget.chart.fitContent();
    action(dialog, 'csv-visible').click();
    expect(field(dialog, 'from').value).toBe('2026-09-28T09:16:00');
    expect(field(dialog, 'to').value).toBe('2026-09-28T09:17:00');
    action(dialog, 'csv-all').click();
    expect(field(dialog, 'from').value).toBe('');
    expect(field(dialog, 'to').value).toBe('');
    action(dialog, 'download-csv').click();
    expect((await downloads[0].text()).trim().split('\r\n')).toHaveLength(5);
  });

  it.each(['bad', '2026-02-30T09:15', '2026-09-28T25:00', String(T0)])('retains the invalid draft %s without downloading', draft => {
    const { root } = make(); const dialog = open(root);
    edit(dialog, 'from', draft); action(dialog, 'download-csv').click();
    expect(field(dialog, 'from').value).toBe(draft);
    expect(field(dialog, 'from').getAttribute('aria-invalid')).toBe('true');
    expect(downloads).toHaveLength(0);
    expect(root.querySelector('.oac-csv')).toBe(dialog);
  });

  it('rejects reversed bounds and allows a corrected draft', async () => {
    const { root } = make(); const dialog = open(root);
    edit(dialog, 'from', '2026-09-28T09:18'); edit(dialog, 'to', '2026-09-28T09:17'); action(dialog, 'download-csv').click();
    expect(downloads).toHaveLength(0);
    expect(dialog.querySelector('.oac-csv__error')?.textContent).toMatch(/before|range|bound/i);
    edit(dialog, 'from', '2026-09-28T09:15'); edit(dialog, 'to', '2026-09-28T09:15'); action(dialog, 'download-csv').click();
    expect((await downloads[0].text()).trim().split('\r\n')).toHaveLength(2);
  });

  it('surfaces a selected removed instance instead of silently substituting another study', () => {
    const { widget, root } = make(); const study = widget.chart.addIndicator('sma', { length: 1 });
    const dialog = open(root); study.remove(); widget.chart.addIndicator('sma', { length: 1 });
    action(dialog, 'download-csv').click();
    expect(downloads).toHaveLength(0);
    expect(dialog.querySelector('.oac-csv__error')?.textContent).toContain(study.id);
  });

  it('rejects replacement of the native primary even when the widget source labels remain unchanged', () => {
    const { widget, root } = make(); const dialog = open(root);
    widget.series.remove(); widget.chart.addSeries('candlestick').setData(rows);
    action(dialog, 'download-csv').click();
    expect(downloads).toHaveLength(0);
    expect(dialog.querySelector('.oac-csv__error')?.textContent).toMatch(/changed|source/i);
  });

  it('rechecks native source context before final download', () => {
    const { widget, root } = make(); const dialog = open(root);
    widget.chart.setDataContext({ symbol: 'OTHER', interval: '1m' });
    action(dialog, 'download-csv').click();
    expect(downloads).toHaveLength(0);
    expect(dialog.querySelector('.oac-csv__error')?.textContent).toMatch(/changed|source/i);
  });

  it('does not revive captured ownership after a source changes away and back', () => {
    const { widget, root } = make(); const before = widget.chart.getDataContext();
    const dialog = open(root);
    widget.chart.setDataContext({ symbol: 'OTHER', interval: '1m' });
    widget.chart.setDataContext(before);
    action(dialog, 'download-csv').click();
    expect(downloads).toHaveLength(0);
    expect(dialog.querySelector('.oac-csv__error')?.textContent).toMatch(/changed|source/i);
  });

  it('rechecks managed loading at final download even with retained source rows', async () => {
    let pending = false;
    const { widget, root } = make({ feed: { getBars: () => pending ? new Promise(() => {}) : Promise.resolve(rows) } });
    await widget.reload();
    const dialog = open(root);
    pending = true; void widget.reload();
    action(dialog, 'download-csv').click();
    expect(downloads).toHaveLength(0);
    expect(dialog.querySelector('.oac-csv__error')?.textContent).toMatch(/loading/i);
  });

  it('supports an empty study selection and disables an unavailable visible range', async () => {
    const { widget, root } = make(); widget.chart.addIndicator('sma', { length: 1 });
    widget.chart.setVisibleLogicalRange({ from: 100, to: 150 });
    const dialog = open(root);
    expect(action(dialog, 'csv-visible').disabled).toBe(true);
    field(dialog, 'study-0').checked = false;
    action(dialog, 'download-csv').click();
    expect((await downloads[0].text()).split('\r\n')[0]).toBe('time,open,high,low,close,volume,oi');
  });

  it('exports the current revealed replay prefix and display alignment when selected', async () => {
    const { widget, root } = make();
    const study = widget.chart.addIndicator('sma', { length: 1 });
    study.series('ma')!.applyOptions({ barOffset: 1 });
    const replay = new ReplayController(widget.chart, { series: widget.series, bars: rows, startIndex: 2 });
    const dialog = open(root);
    const select = dialog.querySelector('[data-key="alignment"] select')!;
    select.value = 'display'; fire(select, 'change'); action(dialog, 'download-csv').click();
    const csv = await downloads[0].text();
    expect(csv).toBe(`time,logical_index,time_origin,open,high,low,close,volume,oi,indicator:${study.id}:ma\r\n`
      + `${at(0)},0,axis,1,2,0,1,,,\r\n${at(1)},1,axis,3,4,2,3,,,1\r\n${at(2)},2,axis,5,6,4,5,,,3\r\n`
      + `${at(3)},3,projected,,,,,,,5\r\n`);
    // The offset projects an accepted value; the unrevealed source row is absent.
    expect(csv).not.toContain(',7,8,6,7,'); replay.stop();
  });

  it('cancels with Escape and closes safely when the widget is destroyed', () => {
    const { widget, root, doc } = make(); open(root);
    fireKey(doc.activeElement!, 'Escape');
    expect(root.querySelector('.oac-csv')).toBeNull(); expect(downloads).toHaveLength(0);
    const dialog = open(root); widget.destroy(); action(dialog, 'download-csv').click();
    expect(downloads).toHaveLength(0);
  });
});
