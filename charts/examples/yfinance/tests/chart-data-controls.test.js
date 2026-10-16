import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('/dist/openalgo-charts.mjs', () => import('../../../src/index.ts'));
import { Chart, registerIndicator } from '../../../src/index.ts';
import { installDom } from '../../../tests/widget-form.test.ts';
import { openChartDataControls } from '../src/chart-data-controls.js';
import { capturePaneTarget } from '../src/pane-target.js';
import { topOverlay, overlayKeydown } from '../src/ui.js';

let dom, chart, app, downloads, blobs;
const T0 = Date.UTC(2026, 8, 28, 3, 45) / 1000;
beforeEach(() => {
  dom = installDom(); vi.stubGlobal('document', dom.doc); vi.stubGlobal('window', dom.win);
  const node = (tag, id, parent = dom.root) => {
    const element = dom.doc.createElement(tag); element.id = id; parent.appendChild(element); return element;
  };
  node('div', 'status');
  const modal = node('div', 'chartdatamodal'); modal.hidden = true;
  for (const id of ['csv-source', 'csv-error', 'csv-studies', 'csv-zone']) node('div', id, modal);
  const list = dom.doc.getElementById('csv-studies');
  list.replaceChildren = (...children) => { list.textContent = ''; children.forEach(child => list.appendChild(child)); };
  for (const id of ['csv-close', 'csv-cancel', 'csv-download', 'csv-visible', 'csv-all-rows', 'csv-all-studies', 'csv-no-studies']) node('button', id, modal);
  for (const id of ['csv-from', 'csv-to', 'csv-comparisons']) node('input', id, modal);
  const alignment = node('select', 'csv-alignment', modal);
  for (const value of ['source', 'display']) { const option = dom.doc.createElement('option'); option.value = value; alignment.appendChild(option); }
  chart = new Chart(dom.chartEl, { document: dom.doc, shortcuts: false, raf: { schedule: () => 0 } });
  chart.applySize(800, 500);
  // Three one-minute bars from 09:15 IST on 28 September 2026, the chart's default clock.
  chart.addSeries('line').setData([0, 1, 2].map(i => ({ time: T0 + i * 60, value: i + 1 })));
  chart.setVisibleLogicalRange({ from: 1, to: 2 });
  vi.spyOn(chart, 'getVisibleLogicalRange').mockReturnValue({ from: 1, to: 2 });
  registerIndicator({ id: 'csv-controls-study', name: 'Repeated study', placement: 'onchart', inputs: [],
    plots: [{ key: 'value', title: 'Value', type: 'line' }], calc: bars => ({ value: bars.map(bar => bar.close * 2) }) });
  app = { chart, req: { symbol: 'AAA', interval: '1m' }, focusPane: 1, chartType: 'line' };
  downloads = []; blobs = [];
  const create = dom.doc.createElement.bind(dom.doc);
  vi.spyOn(dom.doc, 'createElement').mockImplementation(tag => {
    const element = create(tag);
    if (tag === 'a') element.click = () => downloads.push(element.download);
    return element;
  });
  vi.spyOn(URL, 'createObjectURL').mockImplementation(blob => { blobs.push(blob); return 'blob:csv-controls'; });
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  vi.useFakeTimers();
});
afterEach(() => {
  while (topOverlay()) overlayKeydown({ key: 'Escape', preventDefault() {}, stopImmediatePropagation() {} });
  chart.destroy(); vi.runAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});
const field = id => dom.doc.getElementById(id);

describe('reference chart data controls', () => {
  it('captures study identities and visible bounds while allowing a selected subset', async () => {
    const first = chart.addIndicator('csv-controls-study'), second = chart.addIndicator('csv-controls-study');
    second.setVisible(false);
    expect(openChartDataControls(app)).toBe(true);
    // Repeated instances are told apart by their place among their name, as the widget numbers them, not by an internal id.
    expect(field('csv-studies').textContent).toBe(`${first.name} (1)${second.name} (2)`);
    expect(field('csv-studies').textContent).not.toContain(first.id);
    chart.setVisibleLogicalRange({ from: 0, to: 0 });
    chart.getVisibleLogicalRange.mockReturnValue({ from: 0, to: 0 });
    chart.addIndicator('csv-controls-study');
    field('csv-visible').click();
    expect(field('csv-zone').textContent).toBe('Times are on the chart clock, Asia/Kolkata.');
    expect(field('csv-from').value).toBe('2026-09-28T09:16:00'); expect(field('csv-to').value).toBe('2026-09-28T09:17:00');
    field('csv-studies').querySelectorAll('input')[0].checked = false;
    field('csv-download').click();
    expect(downloads).toHaveLength(1);
    const text = await blobs[0].text();
    expect(text.split('\r\n')[0]).toBe(`time,open,high,low,close,volume,oi,indicator:${second.id}:value`);
    expect(text.split('\r\n').filter(Boolean)).toHaveLength(3);
    expect(text).toContain(`${T0 + 60},2,2,2,2,,,4`);
    expect(field('chartdatamodal').hidden).toBe(true);
  });

  it('keeps unreadable or reversed bounds open without creating a download', () => {
    openChartDataControls(app);
    // A year before 100 would be read as 19xx by the calendar maths: a two-digit
    // year typed for 2026 must not quietly become 1926 and widen the export.
    for (const [from, to] of [[String(T0), ''], ['2026-02-30T09:15', ''], ['word', '2026-09-28T09:17'], ['2026-09-28T09:17', '2026-09-28T09:16'],
      ['0026-09-28T09:15', ''], ['', '0099-12-31T23:59']]) {
      field('csv-from').value = from; field('csv-to').value = to; field('csv-download').click();
      expect(field('csv-error').hidden).toBe(false);
      expect(field('chartdatamodal').hidden).toBe(false);
    }
    expect(blobs).toHaveLength(0);
    field('csv-all-rows').click();
    expect(field('csv-from').value).toBe(''); expect(field('csv-to').value).toBe('');
    field('csv-download').click(); expect(downloads).toHaveLength(1);
  });

  it('retains the captured source and refuses replacement, loading and renderer changes', () => {
    const target = capturePaneTarget(app);
    openChartDataControls(app, target); app.focusPane = 2;
    app.loading = true; field('csv-download').click(); expect(blobs).toHaveLength(0);
    app.loading = false; app.chartType = 'area'; field('csv-download').click(); expect(blobs).toHaveLength(0);
    app.chartType = 'line'; app.req.symbol = 'BBB'; field('csv-download').click(); expect(blobs).toHaveLength(0);
    app.req.symbol = 'AAA'; field('csv-download').click(); expect(downloads[0]).toMatch(/^AAA-1m-line-/);
  });

  it('reports a removed selected study and allows explicit deselection', () => {
    const study = chart.addIndicator('csv-controls-study'); openChartDataControls(app); study.remove();
    field('csv-download').click(); expect(field('csv-error').textContent).toMatch(/Unknown CSV indicator/);
    expect(blobs).toHaveLength(0); field('csv-no-studies').click(); field('csv-download').click();
    expect(downloads).toHaveLength(1);
  });

  it('cancels without a download and disables a viewport without loaded timestamps', () => {
    chart.setVisibleLogicalRange({ from: 20, to: 30 });
    chart.getVisibleLogicalRange.mockReturnValue({ from: 20, to: 30 });
    openChartDataControls(app);
    expect(field('csv-visible').disabled).toBe(true);
    field('csv-cancel').click(); expect(field('chartdatamodal').hidden).toBe(true); expect(blobs).toHaveLength(0);
  });

  it.each(['cancel', 'replace'])('does not deliver after a calculation callback %s', action => {
    let armed = false, calls = 0;
    registerIndicator({ id: 'csv-controls-reentry', name: 'Reentry study', placement: 'onchart', inputs: [],
      plots: [{ key: 'value', title: 'Value', type: 'line' }], calc: bars => {
        calls++;
        if (armed) {
          armed = false;
          if (action === 'cancel') field('csv-cancel').click();
          else openChartDataControls(app);
        }
        return { value: bars.map(bar => bar.close) };
      } });
    chart.addIndicator('csv-controls-reentry'); openChartDataControls(app);
    chart.primarySeries().update({ time: T0 + 120, value: 4 });
    armed = true; const before = calls; field('csv-download').click();
    expect(calls).toBeGreaterThan(before); expect(downloads).toHaveLength(0);
    expect(field('chartdatamodal').hidden).toBe(action === 'cancel');
    if (action === 'replace') {
      overlayKeydown({ key: 'Escape', preventDefault() {}, stopImmediatePropagation() {} });
      expect(field('chartdatamodal').hidden).toBe(true); expect(topOverlay()).toBeNull();
    }
  });
});
