// The point and figure and Renko settings dialogs against a real chart from
// the built library: which chart types open one, what each control writes,
// and that Cancel writes nothing. The rebuild itself is the toolbar's
// changeType, which is stood in for here, so each test reads exactly the type
// the dialog asked for.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createChart } from '/dist/openalgo-charts.mjs';
import { fakeDocument } from '../../../tests/helpers/fake-dom';
import { installDom } from './fake-dom.js';

vi.mock('../src/persist.js', async importOriginal => ({ ...await importOriginal(), autosave: vi.fn() }));
import { initToolbar } from '../src/toolbar.js';
import { chartTypeSeries } from '../src/transforms.js';
import { OVERLAY_CLOSE } from '../src/ui.js';
import { applyBoxSettings, closeBoxSettings, initBoxSettings, openBoxSettings } from '../src/box-settings.js';

const bars = Array.from({ length: 80 }, (_, i) => {
  const close = 100 + 12 * Math.sin(i / 5);
  return { time: 1_700_000_000 + i * 86400, open: close - 1, high: close + 2, low: close - 2, close, volume: 100 };
});

let dom, app, chart, changeType;
const field = id => dom.document.getElementById(id);
const presets = () => field('box-body').querySelectorAll('button').filter(b => b.classList.contains('box-preset'));
const radios = () => field('box-body').querySelectorAll('input').filter(input => input.type === 'radio');
const swatches = () => field('box-body').querySelectorAll('[data-key]');
const choose = (select, value) => { select.value = value; select.fire('change'); };
const typed = (input, value) => { input.value = String(value); input.fire('input'); };
/** The type and options the dialog last asked the toolbar to rebuild with. */
const asked = () => changeType.mock.calls.at(-1);

/** Build the chart as `chartType` with `transforms`, the way main.js does, and make it the shown type. */
function show(chartType, transforms = {}) {
  chart?.destroy();
  chart = createChart(fakeDocument().createElement('div'), {
    document: fakeDocument(), pixelRatio: () => 1, shortcuts: false, timeNavigator: false,
    raf: { schedule: callback => { callback(); return 1; }, cancel: () => {} },
  });
  chart.applySize(900, 600);
  const { type, transform } = chartTypeSeries(chartType, transforms);
  chart.addSeries(type, transform ? { transform } : {}).setData(bars);
  app.chart = chart;
  app.transforms = transforms;
  field('ctype').value = chartType;
}

const target = () => ({ pane: 1, chart: app.chart, request: app.req, current: () => app.chart === chart && !chart.isDestroyed });

beforeEach(() => {
  dom = installDom();
  const node = (tag, id, parent = dom.document.body) => {
    const element = dom.document.createElement(tag); element.id = id; parent.appendChild(element); return element;
  };
  node('div', 'status');
  node('select', 'ctype');
  const modal = node('div', 'boxmodal'); modal.hidden = true;
  node('span', 'box-title', modal); node('div', 'box-body', modal); node('p', 'box-error', modal);
  for (const id of ['box-x', 'box-cancel', 'box-ok']) node('button', id, modal);
  app = { req: { symbol: 'AAPL', interval: '1d', period: '1y' }, transforms: {} };
  initToolbar(app);
  // Stood in for: the rebuild is the toolbar's, and these tests read what was asked of it.
  app.changeType = changeType = vi.fn();
  initBoxSettings(app);
});
afterEach(() => { closeBoxSettings(); chart?.destroy(); chart = null; });

describe('opening the box settings', () => {
  it('opens only while point and figure or Renko is the type drawn', () => {
    for (const type of ['candlestick', 'line', 't:heikin-ashi', 't:kagi', 't:range']) {
      show(type);
      expect(openBoxSettings(target()), type).toBe(false);
      expect(field('boxmodal').hidden).toBe(true);
    }
    show('t:point-figure');
    expect(openBoxSettings(target())).toBe(true);
    expect(field('boxmodal').hidden).toBe(false);
    expect(field('box-title').textContent).toBe('Point and figure settings');
    show('t:renko');
    expect(openBoxSettings(target())).toBe(true);
    expect(field('box-title').textContent).toBe('Renko settings');
  });

  it('waits for history, and closes with Escape through its own close control', () => {
    show('t:renko');
    app.loading = true;
    expect(openBoxSettings(target())).toBe(false);
    expect(field('status').textContent).toBe('load chart history before changing its settings');
    expect(OVERLAY_CLOSE.boxmodal).toBe('#box-x');
  });

  it('shows the options and colours the chart is drawn with', () => {
    show('t:point-figure', { 'point-figure': { mode: 'atr', atrMultiplier: 2, atrPeriod: 20, reversal: 4, method: 'close' } });
    chart.primarySeries().applyOptions({ upColor: '#112233', downColor: '#445566' });
    openBoxSettings(target());
    expect(field('box-method').value).toBe('atr');
    expect(field('box-size').value).toBe('2');
    expect(field('box-reversal').value).toBe('4');
    expect(field('box-hint').textContent).toBe('Multiple of the 20-bar ATR.');
    expect(radios().map(radio => [radio.value, radio.checked])).toEqual([['close', true], ['hl', false]]);
    expect(swatches().map(swatch => swatch._colorPicker.read())).toEqual(['#112233', '#445566']);
    // Nothing touched: OK has nothing to rebuild.
    applyBoxSettings();
    expect(changeType).not.toHaveBeenCalled();
    expect(field('boxmodal').hidden).toBe(true);
  });

  it('starts point and figure on its ATR box and Renko on a fixed brick from history, with the renderer colours', () => {
    show('t:point-figure');
    openBoxSettings(target());
    expect([field('box-method').value, field('box-size').value, field('box-reversal').value]).toEqual(['atr', '1', '3']);
    expect(radios().find(radio => radio.checked).value).toBe('hl');
    expect(swatches().map(swatch => swatch._colorPicker.read())).toEqual(['#26a69a', '#ef5350']);
    show('t:renko');
    openBoxSettings(target());
    expect([field('box-method').value, field('box-size').value]).toEqual(['fixed', '0']);
    expect(field('box-reversal')).toBeNull();
    expect(radios().find(radio => radio.checked).value).toBe('close');
    expect(swatches().map(swatch => swatch._colorPicker.read())).toEqual([chart.theme().upColor, chart.theme().downColor]);
  });
});

describe('what the controls write', () => {
  it('offers each transform its own percent presets, and a preset is the Percent method at that value', () => {
    show('t:point-figure');
    openBoxSettings(target());
    expect(presets().map(b => b.textContent)).toEqual(['0.05%', '0.10%', '0.15%', '0.25%', '0.50%', '1%', '2%', '3%']);
    presets()[3].click();
    expect([field('box-method').value, field('box-size').value]).toEqual(['percent', '0.25']);
    expect(presets().map(b => b.getAttribute('aria-pressed'))).toEqual(['false', 'false', 'false', 'true', 'false', 'false', 'false', 'false']);
    // A size typed to another value is no longer the preset.
    typed(field('box-size'), 0.3);
    expect(presets().some(b => b.classList.contains('is-on'))).toBe(false);
    typed(field('box-size'), 0.25);
    applyBoxSettings();
    expect(asked()[1]).toEqual({ chartType: 't:point-figure',
      transforms: { 'point-figure': { mode: 'percent', percent: 0.25, reversal: 3, method: 'hl' } } });
    expect(asked()[2]).toEqual({ label: 'Point and figure settings' });

    show('t:renko');
    openBoxSettings(target());
    expect(presets().map(b => b.textContent)).toEqual(['0.05%', '0.10%', '0.25%', '0.50%', '1%', '2%', '3%', '5%']);
    presets()[7].click();
    applyBoxSettings();
    expect(asked()[1].transforms).toEqual({ renko: { mode: 'percent', percent: 5, method: 'close' } });
  });

  it.each([
    ['fixed', 12.5, { mode: 'fixed', boxSize: 12.5 }],
    ['fixed', 0, { mode: 'fixed', boxSize: 0 }],
    ['percent', 0.4, { mode: 'percent', percent: 0.4 }],
    ['atr', 1.5, { mode: 'atr', atrMultiplier: 1.5, atrPeriod: 14 }],
    ['atrPercent', 60, { mode: 'atrPercent', percent: 60, atrPeriod: 14 }],
  ])('writes the %s method with size %s as the options the engine reads', (mode, size, options) => {
    // Renko starts from a saved percent brick, so a fixed brick from history is a change there too.
    for (const [type, kind, rest, saved] of [['t:point-figure', 'point-figure', { reversal: 3, method: 'hl' }, {}],
      ['t:renko', 'renko', { method: 'close' }, { renko: { mode: 'percent', percent: 1, method: 'close' } }]]) {
      show(type, saved);
      openBoxSettings(target());
      choose(field('box-method'), mode);
      typed(field('box-size'), size);
      applyBoxSettings();
      expect(asked()[1].transforms[kind], type).toEqual({ ...options, ...rest });
    }
  });

  it('gives a method switched to a size that suits it, and says what the size reads', () => {
    show('t:renko', { renko: { mode: 'percent', percent: 0.75, method: 'close' } });
    openBoxSettings(target());
    const hints = {};
    for (const mode of ['fixed', 'atr', 'atrPercent', 'percent']) {
      choose(field('box-method'), mode);
      hints[mode] = [field('box-size').value, field('box-hint').textContent];
    }
    expect(hints).toEqual({
      fixed: ['0', 'In price. 0 sizes it from the loaded history.'],
      atr: ['1', 'Multiple of the 14-bar ATR.'],
      atrPercent: ['50', 'Percent of the 14-bar ATR.'],
      // Back to the saved method: its saved size, not a stock one.
      percent: ['0.75', 'Percent of price, sized again as each brick forms.'],
    });
  });

  it('writes the reversal and the prices the columns are built from', () => {
    show('t:point-figure');
    openBoxSettings(target());
    expect([...field('box-reversal').children].map(o => o.textContent)).toEqual(['1 box', ...[2, 3, 4, 5, 6, 7, 8, 9, 10].map(n => `${n} boxes`)]);
    field('box-reversal').value = '5';
    radios().find(radio => radio.value === 'close').checked = true;
    radios().find(radio => radio.value === 'hl').checked = false;
    applyBoxSettings();
    expect(asked()[1].transforms['point-figure']).toEqual({ mode: 'atr', atrMultiplier: 1, atrPeriod: 14, reversal: 5, method: 'close' });

    show('t:renko');
    openBoxSettings(target());
    radios().find(radio => radio.value === 'close').checked = false;
    radios().find(radio => radio.value === 'hl').checked = true;
    applyBoxSettings();
    expect(asked()[1].transforms.renko).toEqual({ mode: 'fixed', boxSize: 0, method: 'hl' });
  });

  it('keeps the options of the other transform and an ATR length set elsewhere', () => {
    const renko = { mode: 'atr', atrMultiplier: 2, atrPeriod: 21, method: 'hl' };
    show('t:renko', { renko, 'point-figure': { mode: 'fixed', boxSize: 3, reversal: 2, method: 'hl' } });
    openBoxSettings(target());
    typed(field('box-size'), 3);
    applyBoxSettings();
    expect(asked()[1].transforms).toEqual({ renko: { ...renko, atrMultiplier: 3 }, 'point-figure': { mode: 'fixed', boxSize: 3, reversal: 2, method: 'hl' } });
  });

  it('recolours in place when only the colours change: one step, no rebuild', () => {
    show('t:point-figure');
    openBoxSettings(target());
    const [up, down] = swatches();
    up._colorPicker.write('#2962ff');
    down._colorPicker.write('#ff9800');
    applyBoxSettings();
    expect(changeType).not.toHaveBeenCalled();
    expect(chart.primarySeriesInfo().style).toMatchObject({ upColor: '#2962ff', downColor: '#ff9800' });

    // A brick is a body with a border, so the colour goes on both.
    show('t:renko');
    openBoxSettings(target());
    swatches()[0]._colorPicker.write('#00897b');
    applyBoxSettings();
    expect(chart.primarySeriesInfo().style).toMatchObject({ upColor: '#00897b', borderUpColor: '#00897b', wickUpColor: '#00897b' });
  });

  it('carries new colours with new options, both ways, so one undo puts both back', () => {
    show('t:point-figure');
    openBoxSettings(target());
    swatches()[1]._colorPicker.write('#ab47bc');
    presets()[0].click();
    applyBoxSettings();
    expect(asked()[2]).toEqual({ label: 'Point and figure settings',
      fromColors: { upColor: '#26a69a', downColor: '#ef5350' }, colors: { upColor: '#26a69a', downColor: '#ab47bc' } });
    // The rebuild applies them; the dialog leaves the chart it is about to replace alone.
    expect(chart.primarySeriesInfo().style.downColor).toBeUndefined();
  });
});

describe('leaving without applying', () => {
  it.each(['box-cancel', 'box-x', 'boxmodal'])('writes nothing when closed by %s', id => {
    show('t:point-figure');
    openBoxSettings(target());
    presets()[5].click();
    swatches()[0]._colorPicker.write('#000000');
    field(id).fire('click');
    expect(field('boxmodal').hidden).toBe(true);
    expect(changeType).not.toHaveBeenCalled();
    expect(chart.primarySeriesInfo().style.upColor).toBeUndefined();
    // Opened again, it shows the chart, not the abandoned edits.
    openBoxSettings(target());
    expect(field('box-method').value).toBe('atr');
  });

  it('keeps a size it cannot use open with the reason, and applies nothing', () => {
    show('t:renko');
    openBoxSettings(target());
    for (const [mode, size, error] of [['percent', 0, 'Enter a size above 0'], ['atr', 0, 'Enter a size above 0'],
      ['fixed', -1, 'Enter a size of 0 or more'], ['fixed', '', 'Enter a size of 0 or more']]) {
      choose(field('box-method'), mode);
      typed(field('box-size'), size);
      expect(applyBoxSettings()).toBe(false);
      expect(field('box-error').hidden).toBe(false);
      expect(field('box-error').textContent).toBe(error);
      expect(field('boxmodal').hidden).toBe(false);
    }
    // Editing the size clears the complaint.
    typed(field('box-size'), 2);
    expect(field('box-error').hidden).toBe(true);
    expect(changeType).not.toHaveBeenCalled();
  });

  it('closes when its chart goes away', () => {
    show('t:renko');
    openBoxSettings(target());
    chart.destroy();
    expect(field('boxmodal').hidden).toBe(true);
  });
});
