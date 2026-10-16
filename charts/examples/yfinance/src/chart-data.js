import { exportChartDataCsv } from '/dist/openalgo-charts.mjs';
import { capturePaneTarget } from './pane-target.js';
import { el, toast } from './ui.js';

export function chartDataUnavailableReason(app, target = capturePaneTarget(app)) {
  if (!target?.current() || target.chart.isDestroyed) return 'The chart changed; reopen the download controls';
  if (app.workspaceLoading || app.applyingTemplate || app.chartSettingsEditing || app.replayLoading || app.replayPicking
    || (target.pane === 2 ? app.loading2 || app.loadFailed2 || app.restoringSecondary : app.loading || app.loadFailed)) {
    return 'Finish loading or editing this chart before downloading its data';
  }
  return target.chart.primaryBars().length ? null : 'This chart has no bars to download';
}

export function chartDataFile(app, target = capturePaneTarget(app), options) {
  const reason = chartDataUnavailableReason(app, target);
  if (reason) throw new Error(reason);
  const part = value => String(value || 'chart').replace(/[^A-Za-z0-9._-]/g, '') || 'chart';
  const replay = app.replay && (app.replayScope === 'all'
    ? app.replayTargets?.some(item => item.chart === target.chart) : app.replayTarget?.chart === target.chart);
  const selectedType = target.pane === 2 ? app.p2.chartType : app.chartType;
  const type = selectedType?.replace(/^t:/, '') || target.chart.primarySeriesInfo()?.type;
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
  const filename = [target.request.symbol, target.request.interval, type]
    .map(part).join('-') + (replay ? '-replay' : '') + `-${stamp}.csv`;
  const rows = target.chart.primaryBars().filter(bar => (options?.range?.from === undefined || bar.time >= options.range.from)
    && (options?.range?.to === undefined || bar.time <= options.range.to)).length;
  return { filename, text: exportChartDataCsv(target.chart, options), rows };
}

export function downloadChartData(app, target = capturePaneTarget(app), options, preparedFile) {
  try {
    const reason = chartDataUnavailableReason(app, target);
    if (reason) throw new Error(reason);
    const file = preparedFile ?? chartDataFile(app, target, options), anchor = document.createElement('a');
    const url = URL.createObjectURL(new Blob([file.text], { type: 'text/csv;charset=utf-8' }));
    try {
      anchor.href = url; anchor.download = file.filename; document.body.appendChild(anchor); anchor.click();
    } finally {
      anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 0);
    }
    el('status').textContent = `Chart data download started: ${file.rows} source bars`;
    return true;
  } catch (error) {
    const message = `Data export failed: ${error.message}`;
    el('status').textContent = message; toast('error', message);
    return false;
  }
}
