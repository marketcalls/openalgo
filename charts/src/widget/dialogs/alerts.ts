import { widgetText } from '../localization';
import { alertSettingsSchema, dataVariantKey, getBarCondition, utcSecondsToZonedParts, zoneOffsetSeconds, type Alert, type AlertCondition, type AlertInput, type AlertPatch, type AlertPolicy, type AlertRepeat, type AlertSource, type DataVariant } from 'openalgo-charts';
import { dataVariantLabel } from '../data-status';
import type { WidgetContext } from '../context';
import { button, controlsFromInputs, dialogFrame, el, openPanel, renderForm, type FormControl, type FormHandle, type PanelHandle } from '../form';
import { alertSourceFields } from './alert-source';
import { formatWallClock, parseWallClock } from '../wall-clock';

export interface AlertEditorOptions {
  /** Edit this record; omit to create a new alert. */
  alertId?: string;
  /** Seed a draft from a plot, clicked price or drawing anchor. */
  source?: AlertSource;
  onClose?(): void;
}

export interface AlertsPanelOptions {
  onClose?(): void;
}

let editorSequence = 0;

/** The shape a `datetime-local` input reads and writes. */
const EXPIRY_SHAPE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

/**
 * An instant as the wall clock reads it on the chart's own time axis.
 *
 * Not UTC, which is what this used to be. An alert is set against candles the
 * chart has already labelled in its timezone, so an expiry written in another
 * one asks the reader to do the arithmetic themselves, and be five and a half
 * hours out when they do not. The zone comes from the chart rather than from
 * the browser for the same reason: the axis is what the number is compared to.
 */
function expiryText(value: number | undefined, zone: string): string {
  if (value === undefined) return '';
  const wall = formatWallClock(value, zone, false);
  return `${wall.date}T${wall.time}`;
}

/**
 * The instant a wall-clock reading names in that zone.
 *
 * The shared wall-clock reader (wall-clock.ts) owns this, and an expiry
 * refuses a reading a spring-forward skipped rather than move it. Unchanged
 * existing readings skip parsing, preserving either occurrence of an overlap
 * and its seconds.
 */
function expiryValue(ctx: WidgetContext, value: unknown, zone: string): number | undefined {
  if (value === '') return undefined;
  const wrong = widgetText(ctx, 'Enter an expiry date and time');
  if (typeof value !== 'string' || !EXPIRY_SHAPE.test(value)) throw new Error(wrong);
  // EXPIRY_SHAPE has matched, so both parts are there.
  const [date, time] = value.split('T');
  const seconds = parseWallClock(date!, time!, zone, { rejectSkipped: true });
  if (seconds === null) throw new Error(wrong);
  return seconds;
}

/**
 * How long a new alert runs for before it expires, in months.
 *
 * An alert with no expiry never stops asking, and one that expires this week is
 * gone before the setup it was watching for arrives. Two months is a season of
 * trading: long enough that nobody is renewing alerts as a chore, short enough
 * that a chart does not accumulate a year of alerts nobody remembers setting.
 * It is a default, and the field is right there.
 */
const DEFAULT_EXPIRY_MONTHS = 2;

/** That default as a wall-clock reading, or empty when editing an alert. */
function defaultExpiry(existing: Alert | undefined, zone: string): string {
  if (existing) return expiryText(existing.expiresAt, zone);
  const now = utcSecondsToZonedParts(Math.floor(Date.now() / 1000), zone);
  const month = now.month - 1 + DEFAULT_EXPIRY_MONTHS;
  const day = Math.min(now.day, new Date(Date.UTC(now.year, month + 1, 0)).getUTCDate());
  // UTC arithmetic here represents the chart's calendar, independent of the
  // browser zone. Clamp the day before converting that wall time to an instant.
  const wall = Date.UTC(now.year, month, day, now.hour, now.minute) / 1000;
  const first = wall - zoneOffsetSeconds(wall, zone);
  const second = wall - zoneOffsetSeconds(first, zone);
  // A default inside a spring gap advances across it so it can be saved.
  // Manually entered skipped times are still refused by expiryValue.
  const seconds = second + zoneOffsetSeconds(second, zone) === wall ? second : Math.max(first, second);
  return expiryText(seconds, zone);
}

/** A series key that cannot throw inside a listener; a malformed variant never matches a readable one. */
const variantKey = (variant: DataVariant | undefined): string => { try { return dataVariantKey(variant); } catch { return 'invalid'; } };

/** Draft edits never arm an alert until Save. Closing always discards the draft. */
export function mountAlertEditor(ctx: WidgetContext, anchor?: HTMLElement, opts: AlertEditorOptions = {}): PanelHandle {
  const alerts = ctx.alerts;
  const existing = alerts?.list().find(alert => alert.id === opts.alertId);
  // Keep the labelled reading stable if a host changes the chart's zone while editing.
  const expiryZone = ctx.chart.timezone();
  const initialContext = ctx.chart.getDataContext();
  // The variant is part of the series an alert is set on, like the interval.
  const scope = (value: { symbol?: string; exchange?: string; interval?: string; variant?: DataVariant } | undefined): string =>
    JSON.stringify([value?.symbol, value?.exchange, value?.interval, variantKey(value?.variant)]);
  const initialScope = scope(initialContext);
  const bars = ctx.chart.primaryBars();
  const source = existing?.source ?? opts.source ?? { kind: 'price', price: bars[bars.length - 1]?.close };
  let form: FormHandle;
  let closed = false;
  let enabledChanged = false;
  const formId = `oac-alert-${++editorSequence}`;
  const off: (() => void)[] = [];
  let draft: Record<string, unknown> = {
    ...existing, ...source,
    ...(source.kind === 'drawing' ? { inputInstanceId: source.input?.instanceId, inputPlotKey: source.input?.plotKey } : {}),
    ...(source.kind === 'barCondition' ? { barConditionId: source.id } : {}),
    enabled: existing ? existing.state === 'armed' : true,
    expiresAt: defaultExpiry(existing, expiryZone),
  };
  function close(): void {
    if (closed) return;
    closed = true;
    for (const dispose of off.splice(0)) dispose();
    form?.destroy();
    panel?.close();
    opts.onClose?.();
  }
  const frame = dialogFrame(ctx.document, { translate: ctx.translate, title: existing ? widgetText(ctx, 'Edit alert') : widgetText(ctx, 'Create alert'), className: 'oac-alert-editor', onClose: close });
  const context = el(ctx.document, 'p', 'oac-alert-context', [initialContext?.symbol, initialContext?.exchange, initialContext?.interval].filter(Boolean).join(' / '));
  const fields = el(ctx.document, 'div');
  const availability = el(ctx.document, 'p', 'oac-alert-help');
  const timing = el(ctx.document, 'p', 'oac-alert-help', widgetText(ctx, 'Bar close evaluates confirmed values. Intrabar touch can fire on a wick that is absent from final history.'));
  const error = el(ctx.document, 'p', 'oac-alert-error');
  error.setAttribute('role', 'status');
  frame.body.append(context, fields, availability, timing, error);
  const save = button(ctx.document, { label: widgetText(ctx, 'Save'), variant: 'primary', onClick: commit });
  save.dataset.action = 'save-alert';
  const cancel = button(ctx.document, { label: widgetText(ctx, 'Cancel'), onClick: close });
  cancel.dataset.action = 'cancel-alert';
  frame.actions.append(cancel, save);

  function unavailable(): string | undefined {
    if (!alerts) return widgetText(ctx, 'Alerts are unavailable in this host');
    if (opts.alertId && !alerts.list().some(alert => alert.id === opts.alertId)) return widgetText(ctx, 'This alert was removed');
    if (scope(ctx.chart.getDataContext()) !== initialScope || (existing && scope(existing.scope) !== initialScope)) return widgetText(ctx, 'The instrument context changed. Reopen the editor for the intended instrument.');
    return alertSourceFields(ctx, draft).reason;
  }
  function refreshAvailability(): void {
    const reason = unavailable();
    error.textContent = reason ?? '';
    save.disabled = reason !== undefined;
    availability.textContent = alertSourceFields(ctx, draft).hint ?? '';
  }
  function render(): void {
    form?.destroy();
    const selection = alertSourceFields(ctx, draft);
    const schema = alertSettingsSchema(selection.source, draft.condition as AlertCondition | undefined);
    for (const field of schema) if (!(field.key in draft)) draft[field.key] = field.default;
    draft.condition = schema.find(field => field.key === 'condition')!.default;
    const controls = controlsFromInputs(schema, { translate: ctx.translate, scope: 'alert' });
    const expiryControl = controls.find(control => control.key === 'expiresAt');
    // Keep the host's schema translation and help while naming the draft's zone.
    if (expiryControl) expiryControl.label += ` (${expiryZone})`;
    form = renderForm(fields, [...selection.controls, ...controls], {
      idPrefix: formId, values: draft, translate: ctx.translate, openOverlay: ctx.openOverlay, preserveInvalidNumbers: true,
      onChange: (key, value) => {
        draft = { ...draft, ...form.values(), [key]: value };
        if (key === 'enabled') enabledChanged = true;
        const changedSource = ['kind', 'instanceId', 'plotKey', 'drawingId', 'level', 'inputInstanceId'].includes(key);
        if (key === 'kind') {
          for (const name of ['price', 'value', 'upperPrice', 'upperValue', 'condition']) delete draft[name];
        }
        if (key === 'instanceId') { delete draft.plotKey; delete draft.value; delete draft.upperValue; }
        if (key === 'plotKey') { delete draft.value; delete draft.upperValue; }
        if (key === 'drawingId') { delete draft.level; delete draft.inputInstanceId; delete draft.inputPlotKey; }
        if (key === 'inputInstanceId') delete draft.inputPlotKey;
        if (key === 'condition' || changedSource) {
          const focused = ctx.document.activeElement !== null && fields.contains(ctx.document.activeElement);
          render();
          if (focused) fields.querySelector<HTMLElement>(`[data-key="${key}"] select`)?.focus();
        }
        refreshAvailability();
      },
    });
    const expiry = fields.querySelector<HTMLInputElement>('[data-key="expiresAt"] input');
    if (expiry) { expiry.type = 'datetime-local'; expiry.step = '60'; }
  }
  function commit(): void {
    if (closed) return;
    try {
      const reason = unavailable();
      if (reason) throw new Error(reason);
      draft = { ...draft, ...form.values() };
      // A blank name leaves the trigger toast, the row and its buttons saying nothing.
      const title = String(draft.title ?? '').trim();
      if (title === '') throw new Error(widgetText(ctx, 'Enter a name'));
      const condition = draft.condition as AlertCondition;
      const range = condition === 'enteringRange' || condition === 'leavingRange';
      const selected = alertSourceFields(ctx, draft).source;
      const nextSource: AlertSource = selected.kind === 'price'
        ? { kind: 'price', price: draft.price as number, ...(range ? { upperPrice: draft.upperPrice as number } : {}) }
        : selected.kind === 'indicator'
          ? { ...selected, value: draft.value as number, upperValue: range ? draft.upperValue as number : undefined }
          : selected;
      const patch: AlertPatch = {
        source: nextSource, condition, title, message: String(draft.message ?? '') || undefined,
        // The schema seeds both into the draft, and a stored alert always has them.
        policy: draft.policy as AlertPolicy, repeat: draft.repeat as AlertRepeat,
        cooldownSeconds: draft.cooldownSeconds as number,
      };
      if (!existing || draft.expiresAt !== expiryText(existing.expiresAt, expiryZone)) patch.expiresAt = expiryValue(ctx, draft.expiresAt, expiryZone);
      if (!existing || enabledChanged) patch.state = draft.enabled ? 'armed' : 'disabled';
      if (existing) alerts!.update(existing.id, patch);
      else alerts!.add(patch as AlertInput);
      close();
    } catch (cause) { error.textContent = cause instanceof Error ? cause.message : widgetText(ctx, 'Could not save this alert'); }
  }
  render();
  refreshAvailability();
  for (const event of ['data:context', 'data:update', 'objects:change', 'alert:removed', 'alerts:restored'] as const) off.push(ctx.chart.on(event, refreshAvailability));
  off.push(ctx.chart.on('destroy', close));
  const panel = openPanel(ctx, frame.el, { anchor, modal: true, placement: 'center' }, close);
  return { el: frame.el, close, isOpen: () => !closed && panel.isOpen() };
}

/** All lifecycle states remain visible until explicitly deleted. */
export function mountAlertsPanel(ctx: WidgetContext, anchor?: HTMLElement, opts: AlertsPanelOptions = {}): PanelHandle {
  const alerts = ctx.alerts;
  let closed = false;
  let rendering = false;
  const off: (() => void)[] = [];
  const rows = new Map<string, { el: HTMLElement; summary: HTMLElement; status: HTMLElement; toggle: HTMLButtonElement }>();
  function close(): void {
    if (closed) return;
    closed = true;
    for (const dispose of off.splice(0)) dispose();
    panel?.close();
    opts.onClose?.();
  }
  const frame = dialogFrame(ctx.document, { translate: ctx.translate, title: widgetText(ctx, 'Alerts'), className: 'oac-alerts', onClose: close, closeText: true });
  const list = el(ctx.document, 'div', 'oac-alerts__list');
  list.setAttribute('role', 'list');
  list.setAttribute('aria-label', widgetText(ctx, 'Chart alerts'));
  const empty = el(ctx.document, 'p', 'oac-empty', alerts ? widgetText(ctx, 'No alerts. Create an alert for this chart.') : widgetText(ctx, 'Alerts are unavailable in this host'));
  const count = el(ctx.document, 'span', 'oac-alert-context');
  count.setAttribute('role', 'status');
  const create = button(ctx.document, { label: widgetText(ctx, 'Create alert'), variant: 'primary', onClick: () => { mountAlertEditor(ctx); } });
  create.dataset.action = 'create-alert';
  create.disabled = !alerts;
  frame.body.append(list, empty);
  frame.lead.appendChild(count);
  frame.actions.appendChild(create);
  const stateNames = { armed: widgetText(ctx, 'Active'), triggered: widgetText(ctx, 'Triggered'), expired: widgetText(ctx, 'Expired'), disabled: widgetText(ctx, 'Disabled') };
  /** What the editor lists for a source id: a drawing, its level, a study plot. */
  const listed = (controls: readonly FormControl[], key: string, value: unknown): string | undefined =>
    controls.find(control => control.key === key)?.options?.find(option => option.value === value)?.label;
  function sourceText(alert: Alert): string {
    const source = alert.source;
    if (source.kind === 'price') {
      // As the pane's axis prints it, the way the menu that set it did.
      const price = (value: number): string => ctx.chart.panes()[ctx.chart.primaryPaneIndex()]?.readoutScale().format(value) ?? String(value);
      return source.upperPrice === undefined ? widgetText(ctx, 'Price {price}', { price: price(source.price) }) : widgetText(ctx, 'Price {price} to {upper}', { price: price(source.price), upper: price(source.upperPrice) });
    }
    if (source.kind === 'barCondition') return getBarCondition(source.id)?.title ?? widgetText(ctx, 'Unavailable candle condition');
    if (source.kind === 'drawing') {
      const { controls } = alertSourceFields(ctx, { ...source, inputInstanceId: source.input?.instanceId, inputPlotKey: source.input?.plotKey });
      return `${listed(controls, 'drawingId', source.drawingId) ?? widgetText(ctx, 'Unavailable drawing')} / ${listed(controls, 'level', source.level) ?? source.level ?? widgetText(ctx, 'Default level')}`;
    }
    const instance = ctx.chart.indicators().find(item => item.id === source.instanceId);
    const { controls } = alertSourceFields(ctx, { kind: 'indicator', instanceId: source.instanceId, plotKey: source.plotKey, value: source.value });
    const plot = listed(controls, 'plotKey', source.plotKey) ?? source.plotKey;
    // On the study's own scale, as the price branch prints on the pane's.
    const scale = instance?.series(source.plotKey)?.priceScale();
    const value = (v: number): string => scale?.format(v) ?? String(v);
    return widgetText(ctx, source.upperValue === undefined ? '{name} / {plot}: {value}' : '{name} / {plot}: {value} to {upper}', {
      name: listed(controls, 'instanceId', source.instanceId) ?? widgetText(ctx, 'Unavailable study'), plot,
      value: value(source.value), upper: source.upperValue === undefined ? '' : value(source.upperValue) });
  }
  function render(): void {
    if (closed || rendering) return;
    rendering = true;
    try {
      const records = alerts?.list() ?? [];
      const ids = new Set(records.map(alert => alert.id));
      for (const [id, row] of rows) if (!ids.has(id)) { row.el.remove(); rows.delete(id); }
      for (const alert of records) {
        let row = rows.get(alert.id);
        if (!row) {
          const node = el(ctx.document, 'div', 'oac-alerts__row');
          node.dataset.alertId = alert.id;
          node.setAttribute('role', 'listitem');
          const summary = el(ctx.document, 'div', 'oac-alerts__summary');
          const status = el(ctx.document, 'div', 'oac-alerts__status');
          const actions = el(ctx.document, 'div', 'oac-alerts__actions');
          const edit = button(ctx.document, { label: widgetText(ctx, 'Edit'), onClick: () => { mountAlertEditor(ctx, undefined, { alertId: alert.id }); } });
          edit.dataset.action = 'edit-alert';
          const toggle = button(ctx.document, { label: widgetText(ctx, 'Disable'), onClick: () => {
            const current = alerts?.list().find(item => item.id === alert.id);
            if (current?.state === 'armed') alerts?.disable(alert.id);
            else alerts?.enable(alert.id);
          } });
          toggle.dataset.action = 'toggle-alert';
          const remove = button(ctx.document, { label: widgetText(ctx, 'Delete'), onClick: () => { alerts?.remove(alert.id); } });
          remove.dataset.action = 'delete-alert';
          actions.append(edit, toggle, remove);
          node.append(summary, status, actions);
          list.appendChild(node);
          row = { el: node, summary, status, toggle };
          rows.set(alert.id, row);
        }
        const scope = [alert.scope.symbol, alert.scope.exchange, alert.scope.interval, dataVariantLabel(ctx, alert.scope.variant)]
          .filter(Boolean).join(' / ');
        row.summary.textContent = `${alert.title}\n${scope}\n${sourceText(alert)}`;
        row.el.dataset.state = alert.state;
        const available = alerts!.availability(alert.id);
        row.status.textContent = [stateNames[alert.state], alert.policy === 'onBarClose' ? widgetText(ctx, 'Bar close') : widgetText(ctx, 'Intrabar touch'),
          alert.repeat === 'once' ? widgetText(ctx, 'Once') : widgetText(ctx, 'Every match'),
          alert.cooldownSeconds ? widgetText(ctx, '{seconds}s cooldown', { seconds: alert.cooldownSeconds }) : '',
          alert.expiresAt === undefined ? '' : widgetText(ctx, 'Expires {time}', { time: expiryText(alert.expiresAt, ctx.chart.timezone()).replace('T', ' ') }),
          alert.lastTriggeredAt === undefined ? '' : widgetText(ctx, 'Last fired {time}', { time: expiryText(alert.lastTriggeredAt, ctx.chart.timezone()).replace('T', ' ') }),
          available.available ? '' : available.reason,
        ].filter(Boolean).join(' / ');
        row.toggle.textContent = alert.state === 'armed' ? widgetText(ctx, 'Disable') : widgetText(ctx, 'Enable');
        row.toggle.setAttribute('aria-label', widgetText(ctx, alert.state === 'armed' ? 'Disable {name}' : 'Enable {name}', { name: alert.title }));
        row.toggle.disabled = alert.state !== 'armed' && alert.expiresAt !== undefined && alert.expiresAt <= Date.now() / 1000;
        row.toggle.title = row.toggle.disabled ? widgetText(ctx, 'Edit the expiry before enabling this alert') : '';
      }
      empty.hidden = records.length > 0;
      count.textContent = widgetText(ctx, records.length === 1 ? '{count} alert' : '{count} alerts', { count: records.length });
    } finally { rendering = false; }
  }
  for (const event of ['alert:created', 'alert:updated', 'alert:removed', 'alert:triggered', 'alert:expired', 'alerts:restored',
    'data:context', 'data:update', 'data:range', 'objects:change', 'replay:start', 'replay:stop'] as const) off.push(ctx.chart.on(event, render));
  off.push(ctx.chart.on('destroy', close));
  render();
  const panel = openPanel(ctx, frame.el, { anchor, modal: true, placement: 'center' }, close);
  return { el: frame.el, close, isOpen: () => !closed && panel.isOpen() };
}
