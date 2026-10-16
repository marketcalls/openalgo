import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createWidget, type Widget, type WidgetOptions } from '../src/widget/widget';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fireKey, type FakeElement } from './helpers/fake-dom-widget';

const widgets: Widget[] = [];
const downloads: Blob[] = [];
const bars = [1, 3].map((close, index) => ({ time: index * 60, open: close, high: close + 1, low: close - 1, close }));
beforeEach(() => {
  ensureWindowGlobal();
  downloads.length = 0;
  vi.spyOn(URL, 'createObjectURL').mockImplementation(blob => { downloads.push(blob as Blob); return 'blob:mobile-csv'; });
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
});
afterEach(() => { widgets.splice(0).forEach(widget => widget.destroy()); vi.restoreAllMocks(); });

function make(options: WidgetOptions = {}) {
  const doc = fakeWidgetDocument();
  const widget = createWidget(fakeContainer(doc, 390, 700) as unknown as HTMLElement, {
    document: doc as unknown as Document, symbol: 'SAMPLE', interval: '1m', shortcuts: false,
    pixelRatio: () => 1, raf: { schedule: () => 0, cancel: () => {} }, ...options,
  });
  widgets.push(widget);
  widget.chart.applySize(390, 700);
  widget.series.setData(bars);
  return { widget, doc, root: widget.root as unknown as FakeElement };
}

function capture(root: FakeElement): FakeElement {
  expect(root.classList.contains('is-mobile')).toBe(true);
  const more = root.querySelector('[data-mobile-action="more"]')!;
  more.focus(); more.click();
  const action = root.querySelector('[data-mobile-action="capture"]');
  expect(action).not.toBeNull();
  action!.click();
  expect(root.querySelector('.oac-mobile-sheet')).toBeNull();
  return root.querySelectorAll('.oac-menu__row').find(row => row.textContent === 'Download chart data (CSV)')!;
}

describe('automatic mobile chart data export', () => {
  it('downloads through More and restores focus to its visible control', async () => {
    const { root, doc } = make();
    capture(root).click();
    const dialog = root.querySelector('.oac-csv');
    expect(dialog).not.toBeNull();
    expect(downloads).toHaveLength(0);
    dialog!.querySelector('[data-action="download-csv"]')!.click();
    expect(downloads).toHaveLength(1);
    expect(await downloads[0].text()).toBe('time,open,high,low,close,volume,oi\r\n0,1,2,0,1,,\r\n60,3,4,2,3,,\r\n');
    expect(root.querySelector('.oac-csv')).toBeNull();
    expect(doc.activeElement).toBe(root.querySelector('[data-mobile-action="more"]'));
  });

  it('shares captured source validation and supports Escape on mobile', () => {
    const { widget, root, doc } = make();
    capture(root).click();
    const dialog = root.querySelector('.oac-csv')!;
    widget.chart.setDataContext({ symbol: 'OTHER', interval: '1m' });
    dialog.querySelector('[data-action="download-csv"]')!.click();
    expect(downloads).toHaveLength(0);
    expect(dialog.querySelector('.oac-csv__error')?.textContent).toMatch(/changed|source/i);
    fireKey(doc.activeElement!, 'Escape');
    expect(root.querySelector('.oac-csv')).toBeNull();
    expect(doc.activeElement).toBe(root.querySelector('[data-mobile-action="more"]'));
  });

  it('keeps CSV disabled during a managed reload even with retained bars', async () => {
    let pending = false;
    const { widget, root } = make({ feed: { getBars: () => pending ? new Promise(() => {}) : Promise.resolve(bars) } });
    await widget.reload();
    pending = true; void widget.reload();
    const csv = capture(root);
    expect(csv.getAttribute('aria-disabled')).toBe('true');
    csv.click();
    expect(root.querySelector('.oac-csv')).toBeNull();
    expect(downloads).toHaveLength(0);
  });
});
