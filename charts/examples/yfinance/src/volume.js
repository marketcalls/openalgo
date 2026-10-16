import { el, fmt, fmtVol, UP, DOWN } from './ui.js';
import { nameOf, exchangeOf } from './status.js';
import { setCompareLegends } from './compare.js';
import { autosave } from './persist.js';
import { PaneLegend } from '/dist/openalgo-charts.mjs';
import { selectedPane } from './pane-target.js';
import { intervalLabel } from './intervals.js';

let app;
export function initVolume(a) {
  app = a;
  document.addEventListener?.('oac:theme', () => { refreshVolume(1); refreshVolume(2); });
}

export const VOLUME_DEFAULTS = {
  'volume.visible': true, 'volume.colorByDirection': true,
  'volume.showMA': false, 'volume.maPeriod': 20, 'volume.maColor': '#e6b53c',
  'volume.maWidth': 1.5, 'volume.maStyle': 'solid',
};

export const VOLUME_TAB = { id: 'volume', label: 'Volume', inputs: [
  { key: 'volume.visible', type: 'boolean', label: 'Show volume', group: 'Histogram' },
  { key: 'volume.colorByDirection', type: 'boolean', label: 'Match candle colors', group: 'Histogram' },
  { key: 'volume.showMA', type: 'boolean', label: 'Show moving average', group: 'Moving average' },
  { key: 'volume.maPeriod', type: 'number', label: 'Period', min: 1, max: 500, step: 1, group: 'Moving average' },
  { key: 'volume.maColor', type: 'color', label: 'Color', group: 'Moving average' },
  { key: 'volume.maWidth', type: 'number', label: 'Thickness', min: 1, max: 5, step: 0.5, group: 'Moving average' },
  { key: 'volume.maStyle', type: 'select', label: 'Line style', group: 'Moving average',
    options: ['solid', 'dashed', 'dotted'].map(value => ({ value, label: value[0].toUpperCase() + value.slice(1) })) },
].map(input => ({ ...input, default: VOLUME_DEFAULTS[input.key] })) };

export function volumeValues(saved = {}) {
  const values = { ...VOLUME_DEFAULTS };
  for (const key of Object.keys(values)) {
    const value = saved[key];
    if (typeof value !== typeof values[key]) continue;
    if (typeof value === 'number') {
      if (!Number.isFinite(value)) continue;
      values[key] = key === 'volume.maPeriod' ? Math.max(1, Math.min(500, Math.round(value))) : Math.max(1, Math.min(5, value));
    } else if (key === 'volume.maStyle') {
      if (['solid', 'dashed', 'dotted'].includes(value)) values[key] = value;
    } else if (typeof value !== 'string' || /^#[0-9a-f]{6}$/i.test(value)) values[key] = value;
  }
  return values;
}

const suffixFor = pane => pane === 2 ? '2' : '';
export function volumeSettings(pane = selectedPane(app)) {
  return volumeValues({ 'volume.visible': pane === 1 ? el('volshow').checked : true,
    ...app['volumeSettings' + suffixFor(pane)] });
}

export function applyVolumeSettings(pane, patch) {
  const values = volumeValues({ ...volumeSettings(pane), ...patch });
  app['volumeSettings' + suffixFor(pane)] = values;
  if (pane === 1) el('volshow').checked = values['volume.visible'];
  refreshVolume(pane);
}

/** Match the displayed candle, including explicit per-bar colour overrides. */
export function volumePoint(bar, previousClose, style, direction) {
  const reference = style.colorByPreviousClose && Number.isFinite(previousClose) ? previousClose : bar.open;
  const color = direction ? bar.color || (bar.close >= reference ? style.upColor : style.downColor) : undefined;
  const value = Number.isFinite(bar.volume) ? bar.volume : NaN;
  return { time: bar.time, open: 0, high: value, low: 0, close: value, ...(color ? { color } : {}) };
}

export function volumeAveragePoint(bars, index, period) {
  let total = NaN;
  if (index + 1 >= period) {
    total = 0;
    for (let at = index - period + 1; at <= index; at++) total += bars[at].close;
    total /= period;
  }
  return { time: bars[index].time, open: total, high: total, low: total, close: total };
}

export function volumeAverage(bars, period) {
  let total = 0, count = 0;
  return bars.map((bar, index) => {
    if (Number.isFinite(bar.close)) { total += bar.close; count++; }
    if (index >= period && Number.isFinite(bars[index - period].close)) { total -= bars[index - period].close; count--; }
    const value = count === period ? total / period : NaN;
    return { time: bar.time, open: value, high: value, low: value, close: value };
  });
}

export function attachVolume(pane = 1, enabled = true) {
  const suffix = suffixFor(pane), chart = app['chart' + suffix];
  app['volume' + suffix] = null;
  app['volumeMA' + suffix] = null;
  app['volLegend' + suffix] = null;
  app['volumeReadings' + suffix] = new Map();
  if (!enabled) return;
  const histogram = chart.addSeries('histogram', {
    priceScaleId: '', priceFormat: { type: 'volume' },
    style: { color: '#33415e', base: 0, priceLineVisible: false, lastValueVisible: false },
  });
  histogram.priceScale().setOptions({ marginTop: 0.82, marginBottom: 0 });
  app['volume' + suffix] = histogram;
  app['volumeMA' + suffix] = chart.addSeries('line', {
    priceScaleId: '', priceFormat: { type: 'volume' },
    style: { priceLineVisible: false, lastValueVisible: false },
  });
  const legend = new PaneLegend({ id: 'volume', title: 'Vol', actions: ['hide'] });
  app['volLegend' + suffix] = legend;
  chart.addPrimitive(legend);
  chart.subscribeClick(id => { if (id === 'volume::hide') setVolumeShown(!volumeShown(pane), pane); });
  chart.on('data:update', change => {
    if (app['chart' + suffix] === chart) refreshVolume(pane, change);
  });
  refreshVolume(pane);
}

export function refreshVolume(pane = 1, change) {
  const suffix = suffixFor(pane), chart = app?.['chart' + suffix];
  const histogram = app?.['volume' + suffix], average = app?.['volumeMA' + suffix];
  if (!chart || !histogram || !average) return;
  const settings = volumeSettings(pane), bars = chart.primaryBars();
  const style = { upColor: chart.theme().upColor, downColor: chart.theme().downColor, ...chart.primarySeriesInfo()?.style };
  const direction = settings['volume.colorByDirection'], period = settings['volume.maPeriod'];
  histogram.applyOptions({ visible: settings['volume.visible'] });
  average.applyOptions({ visible: settings['volume.visible'] && settings['volume.showMA'],
    color: settings['volume.maColor'], lineWidth: settings['volume.maWidth'], lineStyle: settings['volume.maStyle'] });
  if (change?.kind === 'update' && bars.length) {
    histogram.update(volumePoint(bars.at(-1), bars.at(-2)?.close, style, direction));
    if (settings['volume.showMA']) {
      const window = bars.slice(-period).map(bar => ({ time: bar.time, close: bar.volume ?? NaN }));
      const point = volumeAveragePoint(window, window.length - 1, period);
      average.update(point);
      app['volumeReadings' + suffix].set(point.time, point.close);
    }
  } else {
    const points = bars.map((bar, index) => volumePoint(bar, bars[index - 1]?.close, style, direction));
    histogram.setData(points);
    const averages = settings['volume.showMA'] ? volumeAverage(points, period) : [];
    average.setData(averages);
    app['volumeReadings' + suffix] = new Map(averages.map(point => [point.time, point.close]));
  }
  app['volLegend' + suffix]?.setOptions({ hidden: !settings['volume.visible'],
    params: settings['volume.showMA'] ? 'MA ' + period : '' });
  setVolumeLegend(bars.at(-1), pane);
}

export function setVolumeLegend(bar, pane = 1) {
  const suffix = suffixFor(pane), legend = app['volLegend' + suffix];
  if (!legend) return;
  const average = app['volumeReadings' + suffix]?.get(bar?.time);
  legend.setValues([
    ...(Number.isFinite(bar?.volume) ? [{ text: fmtVol(bar.volume), color: bar.close >= bar.open ? UP : DOWN, field: 'volume' }] : []),
    ...(Number.isFinite(average) ? [{ label: 'MA', text: fmtVol(average), color: volumeSettings(pane)['volume.maColor'], field: 'volume' }] : []),
  ]);
}

// ── volume visibility ──────────────────────────────────────────────────
// The primary legacy checkbox mirrors its own saved settings. Secondary
// visibility belongs to that chart and must not write the primary control.
export const volumeShown = (pane = selectedPane(app)) => volumeSettings(pane)['volume.visible'];

/**
 * Show or hide one chart's volume. Hidden, never removed:
 * the series keeps its data and its overlay price scale, so coming back is
 * a repaint rather than a rebuild, and the legend row stays on the pane
 * (dimmed, eye struck through) so there is something left to click.
 */
export function setVolumeShown(on, pane = selectedPane(app)) {
  applyVolumeSettings(pane, { 'volume.visible': on });
  el('status').textContent = on ? 'volume shown' : 'volume hidden';
  autosave();
}

export function setLegend(bar) {
  if (!app.symbolLegend) return;
  app.symbolLegend.setOptions({
    title: nameOf(app.req.symbol || ''),
    params: `${intervalLabel(app.req.interval || '')} · ${exchangeOf(app.req.symbol || '')}`,
  });
  setCompareLegends(bar);
  if (!bar) { app.symbolLegend.setValues([]); app.volLegend && app.volLegend.setValues([]); return; }
  const displayed = app.chart.primaryBars();
  const i = displayed.findIndex(item => item.time === bar.time);
  const prevClose = i > 0 ? displayed[i - 1].close : bar.open;
  const chg = bar.close - prevClose;
  const pct = prevClose ? (chg / prevClose) * 100 : 0;
  const sign = chg >= 0 ? '+' : '';
  const col = bar.close >= bar.open ? UP : DOWN;
  // Dimmed O/H/L/C labels with colored numbers, one segment each. Each
  // reading names the status-line group that owns it: the settings dialog's
  // "Chart values", "Bar change values" and "Volume" switches hide readings
  // by their `field` tag, so an untagged number falls under "Indicator
  // values" instead and none of the three switches can reach it.
  app.symbolLegend.setValues([
    { label: 'O', text: fmt(bar.open), color: col, field: 'ohlc' },
    { label: 'H', text: fmt(bar.high), color: col, field: 'ohlc' },
    { label: 'L', text: fmt(bar.low), color: col, field: 'ohlc' },
    { label: 'C', text: fmt(bar.close), color: col, field: 'ohlc', priority: 10 },
    { text: `${sign}${fmt(chg)} (${sign}${pct.toFixed(2)}%)`, color: chg >= 0 ? UP : DOWN, field: 'change' },
    ...(app.chart?.hasOpenInterest !== false && Number.isFinite(bar.oi)
      ? [{ label: 'OI', text: fmtVol(bar.oi), color: col, field: 'openInterest' }] : []),
  ]);
  // Volume gets its own row, the way a volume study would.
  setVolumeLegend(bar);
}
