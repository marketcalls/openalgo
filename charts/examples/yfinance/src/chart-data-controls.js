import { utcSecondsToZonedParts, zonedWallClockToUtcSeconds } from '/dist/openalgo-charts.mjs';
import { chartDataFile, chartDataUnavailableReason, downloadChartData } from './chart-data.js';
import { capturePaneTarget } from './pane-target.js';
import { el, openOverlay, closeOverlay, toast, studyNames } from './ui.js';

let closeCurrent = null;

// The bounds are a date and a time on the chart's clock, as the axis reads,
// never epoch seconds: nobody reads or types 1759201500. The export itself
// takes UTC seconds, so the fields convert at the edge.
const pad = n => String(n).padStart(2, '0');
const WALL = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/;

/** `time` as a datetime field reads it on `zone`'s clock, to the second. */
function wallText(time, zone) {
  const p = utcSecondsToZonedParts(time, zone);
  return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
}

/**
 * UTC seconds for a date and time typed on `zone`'s clock, or null when it
 * does not read (a date the calendar lacks included). A To written to the
 * minute takes the whole minute, so every bar that opens inside it is in.
 * A year before 100 does not read: the calendar maths takes it as 19xx, so
 * 0026, a two-digit year in the field, would quietly stand for 1926.
 */
function wallSeconds(text, zone, end) {
  const m = WALL.exec(text);
  if (!m) return null;
  const [year, month, day, hour, minute] = m.slice(1, 6).map(Number);
  if (year < 100) return null;
  const second = m[6] !== undefined ? Number(m[6]) : end ? 59 : 0;
  const probe = new Date(Date.UTC(year, month - 1, day));
  if (probe.getUTCMonth() !== month - 1 || probe.getUTCDate() !== day || hour > 23 || minute > 59 || second > 59) return null;
  const out = zonedWallClockToUtcSeconds(year, month, day, hour, minute, second, zone);
  return Number.isFinite(out) ? out : null;
}

function visibleBounds(chart) {
  const view = chart.getVisibleLogicalRange(), axis = chart.dataLayer;
  const first = Math.max(0, Math.ceil(view.from)), last = Math.min(axis.length - 1, Math.floor(view.to));
  const tail = chart.primaryBars().at(-1)?.time;
  if (first > last || tail === undefined) return null;
  const from = axis.indexToTime(first), to = Math.min(axis.indexToTime(last), tail);
  return Number.isFinite(from) && Number.isFinite(to) && from <= to ? { from, to } : null;
}

/** The dialog retains its chart, study IDs and visible bounds until it closes. */
export function openChartDataControls(app, target = capturePaneTarget(app)) {
  const reason = chartDataUnavailableReason(app, target);
  if (reason) { el('status').textContent = reason; toast('error', reason); return false; }
  closeCurrent?.();
  const modal = el('chartdatamodal');
  const primary = target.chart.primarySeries();
  const context = target.chart.getDataContext();
  const renderer = target.chart.primarySeriesInfo()?.type;
  const type = target.pane === 2 ? app.p2.chartType : app.chartType;
  const bounds = visibleBounds(target.chart);
  const zone = target.chart.timezone();
  let closed = false;
  const listeners = [];
  const listen = (node, type, handler) => {
    node.addEventListener(type, handler); listeners.push(() => node.removeEventListener(type, handler));
  };
  const close = () => {
    if (closed) return;
    closed = true; listeners.splice(0).forEach(remove => remove());
    if (closeCurrent === close) { modal.hidden = true; closeCurrent = null; closeOverlay(modal); }
  };
  closeCurrent = close;
  const current = () => !closed && closeCurrent === close;
  const error = message => { el('csv-error').textContent = message; el('csv-error').hidden = false; };
  const clearError = () => { el('csv-error').textContent = ''; el('csv-error').hidden = true; };
  const assertCurrent = () => {
    const currentType = target.pane === 2 ? app.p2.chartType : app.chartType;
    if (!target.current() || target.chart.primarySeries() !== primary || currentType !== type
      || target.chart.getDataContext() !== context || target.chart.primarySeriesInfo()?.type !== renderer) {
      throw new Error('The chart changed; reopen the download controls');
    }
  };
  const names = studyNames(target.chart);
  const studies = target.chart.indicators().map(study => ({ id: study.id, name: names.get(study.id) }));
  if (!current()) return false;
  el('csv-source').textContent = `Chart ${target.pane}: ${target.request.symbol}, ${target.request.interval}`;
  el('csv-from').value = ''; el('csv-to').value = '';
  el('csv-zone').textContent = `Times are on the chart clock, ${zone}.`;
  el('csv-alignment').value = 'source'; el('csv-comparisons').checked = true;
  clearError();
  const boxes = studies.map(study => {
    const label = document.createElement('label'); label.className = 'csv-study';
    const input = document.createElement('input'); input.type = 'checkbox'; input.checked = true;
    const title = document.createElement('span'); title.textContent = study.name;
    label.appendChild(input); label.appendChild(title);
    return { id: study.id, input, label };
  });
  el('csv-studies').replaceChildren(...boxes.map(item => item.label));
  if (!boxes.length) el('csv-studies').textContent = 'No studies on this chart';
  listen(el('csv-close'), 'click', close); listen(el('csv-cancel'), 'click', close);
  listen(modal, 'pointerdown', event => event.stopPropagation());
  listen(modal, 'click', event => { if (event.target === modal) close(); });
  listen(el('csv-all-studies'), 'click', () => { boxes.forEach(item => { item.input.checked = true; }); clearError(); });
  listen(el('csv-no-studies'), 'click', () => { boxes.forEach(item => { item.input.checked = false; }); clearError(); });
  el('csv-visible').disabled = !bounds;
  listen(el('csv-visible'), 'click', () => {
    if (!bounds) return;
    el('csv-from').value = wallText(bounds.from, zone); el('csv-to').value = wallText(bounds.to, zone); clearError();
  });
  listen(el('csv-all-rows'), 'click', () => { el('csv-from').value = ''; el('csv-to').value = ''; clearError(); });
  listen(el('csv-download'), 'click', () => {
    if (!current()) return;
    try {
      assertCurrent();
      const range = {};
      for (const bound of ['from', 'to']) {
        const text = el(`csv-${bound}`).value.trim();
        if (text !== '') {
          const value = wallSeconds(text, zone, bound === 'to');
          if (value === null) throw new Error('Enter a date and a time on the chart clock, or leave a bound empty');
          range[bound] = value;
        }
      }
      if (range.from !== undefined && range.to !== undefined && range.from > range.to) throw new Error('From must be no later than To');
      const options = { indicators: boxes.filter(item => item.input.checked).map(item => item.id),
        range, alignment: el('csv-alignment').value };
      if (!el('csv-comparisons').checked) options.comparisons = [];
      // Validation and serialization happen once, before any browser file action.
      const file = chartDataFile(app, target, options);
      if (!current()) return;
      assertCurrent();
      if (downloadChartData(app, target, options, file)) close();
      else error(el('status').textContent);
    } catch (failure) { if (current()) error(String(failure?.message || failure)); }
  });
  modal.hidden = false;
  openOverlay(modal, { initialFocus: el('csv-from'), close });
  return true;
}
