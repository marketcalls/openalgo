import { parseSessionSpec } from '/dist/openalgo-charts.mjs';
import { mountIndicatorInputControls, createOverlayStack, applyTokens, widgetTokens } from '/dist/openalgo-charts.widget.mjs';
import { referenceSymbolSearch } from './symbol-search.js';
import { closeOverlay, openOverlay, chartTheme, currentTheme } from './ui.js';

const specs = new WeakMap();

/** Keep draft parsing separate from native validation of the final patch. */
export function typedFieldValue(field) {
  return field.dataset.kind === 'price' || field.dataset.kind === 'timestamp'
    ? field.value.trim() === '' ? undefined : Number(field.value) : field.value;
}

function errorFor(input, value) {
  if (input.type === 'price' || input.type === 'timestamp') {
    if (typeof value !== 'number' || !Number.isFinite(value)) return 'Enter a finite number';
    if (input.min !== undefined && value < input.min) return `Minimum: ${input.min}`;
    if (input.max !== undefined && value > input.max) return `Maximum: ${input.max}`;
  }
  if (input.type === 'session' && !parseSessionSpec(value)) return 'Use HHMM-HHMM with optional :days (1 to 7)';
  return null;
}

/** The reason a typed field's draft cannot be saved, or null; null for any other field. */
export function typedFieldProblem(field) {
  const input = specs.get(field)?.input;
  return input ? errorFor(input, typedFieldValue(field)) : null;
}

/**
 * Whether a field is out of the user's reach: disabled, or inside a row a
 * condition hid. Read through the `hidden` property, which is what the form
 * sets, rather than a selector.
 */
export function outOfPlay(field, host) {
  if (field.disabled) return true;
  for (let node = field; node && node !== host; node = node.parentElement) if (node.hidden) return true;
  return false;
}

export function typedFieldError(field, message) {
  const info = specs.get(field);
  if (!info) return;
  field.setAttribute('aria-invalid', message ? 'true' : 'false');
  info.error.textContent = message || '';
  info.error.hidden = !message;
}

export function bindTypedField(field, input, row) {
  if (!['symbol', 'session', 'multiline', 'price', 'timestamp'].includes(input.type)) return;
  const error = field.ownerDocument.createElement('div');
  error.className = 'set-input-error'; error.id = field.id + '-error'; error.hidden = true;
  error.setAttribute('role', 'status'); field.setAttribute('aria-describedby', error.id);
  row.appendChild(error); specs.set(field, { input, error }); field._error = error;
  field.addEventListener('input', () => typedFieldError(field, errorFor(input, typedFieldValue(field))));
}

/** Mark every reachable typed draft; one out of reach never blocks Apply. */
export function validateTypedRows(host) {
  let valid = true;
  for (const field of host.querySelectorAll('[data-key]')) {
    const input = specs.get(field)?.input;
    if (!input || outOfPlay(field, host)) continue;
    const error = errorFor(input, typedFieldValue(field));
    typedFieldError(field, error);
    if (error) valid = false;
  }
  return valid;
}

/** The reference dialog stages values until Apply, including one symbol pair. */
export function mountReferenceInputControls(app, target, instance, inputs, host, panel, onPatch, current) {
  const suffix = target.pane === 2 ? '2' : '';
  const context = app['inspection' + target.pane]?.context ?? app['alertUi' + suffix]?.context;
  if (!context || context.chart !== target.chart) return null;
  // Chart-local overlays sit below the reference modal and may be clipped by
  // a pane. This short-lived layer shares controls, not that stacking context.
  const root = document.createElement('div'); root.className = 'oac-widget host-input-actions';
  const theme = () => applyTokens(root, widgetTokens(chartTheme(), currentTheme()));
  theme(); document.addEventListener('oac:theme', theme); document.body.appendChild(root);
  const overlays = createOverlayStack(root, document);
  const ctx = { ...context, root, overlays, symbolSearch: context.symbolSearch ?? referenceSymbolSearch,
    openOverlay: (node, options) => {
      const close = overlays.open(node, { ...options, onClose: () => { closeOverlay(node); options?.onClose?.(); } });
      openOverlay(node, { close, initialFocus: options?.anchor });
      return close;
    },
  };
  const controls = mountIndicatorInputControls(ctx, {
    instance, inputs, panel, current,
    field: key => [...host.querySelectorAll('[data-key]')].find(field => field.dataset.key === key) ?? null,
    onPatch,
    suspend: () => {
      const focus = document.activeElement;
      panel.hidden = true;
      // Remove the reference shell's trap immediately, before its observer runs.
      closeOverlay(panel);
      let resumed = false;
      return () => {
        if (resumed) return;
        resumed = true;
        if (!current()) return;
        panel.hidden = false; openOverlay(panel);
        if (focus?.isConnected && panel.contains(focus)) focus.focus();
      };
    },
  });
  return { ...controls, destroy: () => {
    controls.destroy(); overlays.destroy(); document.removeEventListener('oac:theme', theme); root.remove();
  } };
}
