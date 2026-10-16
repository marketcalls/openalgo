import type { ChartDataCsvOptions } from 'openalgo-charts';
import type { WidgetContext } from './context';
import { button, dialogFrame, el, openPanel, renderForm, type FormControl, type PanelHandle } from './form';
import { errorText, widgetText } from './localization';
import { studyNames } from './objects-panel';
import { formatWallClock, parseWallClock } from './wall-clock';

let sequence = 0;

/**
 * Capture the offered studies and viewport once; the caller guards the source
 * at download. The bounds are a date and a time on the chart's clock, as in
 * the go-to panel: the axis the user reads is labelled in that zone, and the
 * export itself takes UTC seconds, which nobody reads or types.
 */
export function openChartDataExportDialog(
  ctx: WidgetContext, anchor: HTMLElement, onDownload: (options: ChartDataCsvOptions) => void,
): PanelHandle {
  const chart = ctx.chart;
  const names = studyNames(chart);
  const studies = chart.indicators().map(study => ({ id: study.id, name: names.get(study.id)!, hidden: !study.visible() }));
  const viewport = chart.getVisibleLogicalRange();
  const visible = chart.primaryBars().filter(bar => {
    const index = chart.dataLayer.timeToIndex(bar.time);
    return Number.isFinite(bar.time) && index !== undefined && index >= viewport.from && index <= viewport.to;
  });
  const visibleRange = visible.length ? { from: visible[0]!.time, to: visible[visible.length - 1]!.time } : null; // not empty here
  const zone = chart.timezone();
  // The captured range to the second, so it stays exactly the bars in view.
  const wall = (time: number): string => { const w = formatWallClock(time, zone, true); return `${w.date}T${w.time}`; };
  let closed = false;
  let panel: PanelHandle | null = null;
  let offDestroy = (): void => {};
  const frame = dialogFrame(ctx.document, {
    translate: ctx.translate, title: widgetText(ctx, 'Download chart data (CSV)'), className: 'oac-csv', onClose: close,
  });
  const hint = el(ctx.document, 'p', 'oac-csv__hint', widgetText(ctx, 'Only loaded rows are exported. Blank bounds include all loaded times.'));
  const actions = el(ctx.document, 'div', 'oac-csv__ranges');
  const formHost = el(ctx.document, 'div');
  const error = el(ctx.document, 'p', 'oac-csv__error');
  error.setAttribute('role', 'alert');
  const clock = el(ctx.document, 'p', 'oac-csv__hint', widgetText(ctx, 'Times are on the chart clock, {zone}.', { zone }));
  frame.body.append(hint, clock, actions, formHost, error);
  const controls: FormControl[] = [
    { key: 'from', kind: 'text', label: widgetText(ctx, 'From') },
    { key: 'to', kind: 'text', label: widgetText(ctx, 'To') },
    { key: 'alignment', kind: 'select', label: widgetText(ctx, 'Study alignment'), options: [
      { value: 'source', label: widgetText(ctx, 'Source rows') },
      { value: 'display', label: widgetText(ctx, 'Displayed rows') },
    ] },
    ...studies.map((study, index): FormControl => ({
      key: `study-${index}`, kind: 'boolean', group: widgetText(ctx, 'Studies'),
      label: study.hidden ? widgetText(ctx, '{name}, hidden', { name: study.name }) : study.name,
    })),
  ];
  const form = renderForm(formHost, controls, {
    idPrefix: `oac-csv-${++sequence}`, translate: ctx.translate, openOverlay: ctx.openOverlay,
    values: { from: '', to: '', alignment: 'source', ...Object.fromEntries(studies.map((_, index) => [`study-${index}`, true])) },
    onChange: key => { form.setError(key, null); error.textContent = ''; },
  });
  for (const key of ['from', 'to']) {
    const input = formHost.querySelector<HTMLInputElement>(`[data-key="${key}"] input`);
    if (input !== null) { input.type = 'datetime-local'; input.step = '1'; }
  }
  const setBounds = (from: string, to: string): void => {
    form.setError('from', null); form.setError('to', null); error.textContent = '';
    form.sync({ from, to });
  };
  const visibleButton = button(ctx.document, { label: widgetText(ctx, 'Use captured visible range'),
    onClick: () => { if (visibleRange) setBounds(wall(visibleRange.from), wall(visibleRange.to)); } });
  visibleButton.dataset.action = 'csv-visible';
  visibleButton.disabled = visibleRange === null;
  const allButton = button(ctx.document, { label: widgetText(ctx, 'All loaded rows'), onClick: () => setBounds('', '') });
  allButton.dataset.action = 'csv-all';
  actions.append(visibleButton, allButton);
  const cancel = button(ctx.document, { label: widgetText(ctx, 'Cancel'), onClick: close });
  const download = button(ctx.document, { label: widgetText(ctx, 'Download CSV'), variant: 'primary', onClick: commit });
  download.dataset.action = 'download-csv';
  frame.actions.append(cancel, download);
  function close(): void {
    if (closed) return;
    closed = true;
    offDestroy(); form.destroy(); panel?.close();
  }
  function commit(): void {
    if (closed) return;
    const draft = form.values();
    const range: { from?: number; to?: number } = {};
    try {
      for (const key of ['from', 'to'] as const) {
        form.setError(key, null);
        const text = String(draft[key] ?? '').trim();
        if (text === '') continue;
        // A To written to the minute takes in every bar that opens inside it.
        const [date = '', time = ''] = text.split('T');
        const value = parseWallClock(date, time, zone, key === 'to' ? { end: true } : {});
        if (value === null) {
          const message = widgetText(ctx, 'Enter a date and a time on the chart clock');
          form.setError(key, message); throw new Error(message);
        }
        range[key] = value;
      }
      if (range.from !== undefined && range.to !== undefined && range.from > range.to) {
        const message = widgetText(ctx, 'The From bound must be before or equal to the To bound');
        form.setError('to', message); throw new Error(message);
      }
      onDownload({ indicators: studies.filter((_, index) => draft[`study-${index}`] === true).map(study => study.id),
        range, alignment: draft.alignment === 'display' ? 'display' : 'source' });
      close();
    } catch (cause) {
      const message = errorText(ctx, cause);
      error.textContent = message;
      ctx.status(widgetText(ctx, 'Data export failed: {error}', { error: message }), 'error');
    }
  }
  offDestroy = chart.on('destroy', close);
  panel = openPanel(ctx, frame.el, { anchor, modal: true, placement: 'center' }, close);
  if (closed) panel.close();
  return { el: frame.el, close, isOpen: () => !closed && panel!.isOpen() };
}
