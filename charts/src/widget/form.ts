/**
 * The one control renderer behind every generated dialog in the widget.
 *
 * Three schema vocabularies reach the widget: the chart-settings inputs
 * (`ChartSettingsInput`, which is `IndicatorInput` plus the paired colour
 * row), the indicator descriptors' own `IndicatorInput` lists, and the draw
 * tier's `SettingsField` dot paths. Each dialog would otherwise grow its own
 * switch over control kinds, and three switches drift: one forgets the
 * disabled state, another draws a colour as a 140px block. So the three are
 * folded into one `FormControl` shape here and drawn by one function, and the
 * rules in CLAUDE.md's UI standard are applied in exactly one place: a colour
 * is a small square swatch, a bullish/bearish pair is one row, a control with
 * a reason it cannot act is drawn disabled with its state still readable.
 *
 * A descriptor's `activeWhen` and `visibleWhen` are read here too, against
 * the values the form holds, after every edit and every `sync`. An inactive
 * control goes through the same disabled path as one the host says is
 * unavailable, and a hidden one keeps its draft for when it comes back.
 *
 * DOM-building only. Nothing here knows what a key means or where a value is
 * written: the dialog hands in the values and gets `onChange(key, value)` back
 * with the value already in the type the schema declared.
 */
import { INDICATOR_SOURCES, registeredIntervals, parseSessionSpec } from 'openalgo-charts';
import type { ChartSettingsInput, IndicatorInputPresentation } from 'openalgo-charts';
import { chromeIconSvg, CHROME_ICON_STROKE } from 'openalgo-charts/draw';
import type { SettingsField } from 'openalgo-charts/draw';
import { boxIn, glyph, h, type OverlayOptions } from './context';
import { widgetText, type WidgetTranslationOptions } from './localization';
import { createColorPicker, type ColorPickerOptions } from './color-picker';
import { inputStates } from './input-conditions';

// ── the unified control model ─────────────────────────────────────────────

export type FormKind =
  | 'boolean' | 'number' | 'color' | 'text' | 'multiline' | 'select' | 'opacity' | 'colorPair' | 'custom'
  | 'symbol' | 'session' | 'price' | 'timestamp';

/**
 * One row of a generated form, whatever schema it came from. The presentation
 * fields come from the input: `activeWhen` and `visibleWhen` are re-read on
 * every change, and consecutive controls sharing `inline` share one row. A
 * `colorPair`, a `custom` body and a `multiline` box always take a row of
 * their own, whatever `inline` they carry.
 */
export interface FormControl extends IndicatorInputPresentation {
  /** The flat key `onChange` reports. A `colorPair` reports its halves' keys instead. */
  key: string;
  kind: FormKind;
  label: string;
  /** Sub-heading the row sits under; consecutive rows with one group share a header. */
  group?: string | undefined;
  /** Help text; rendered as a hover affordance beside the label. */
  tooltip?: string | undefined;
  min?: number | undefined;
  max?: number | undefined;
  step?: number | undefined;
  /** `select` only. Absent means free-form: the control becomes a text box. */
  options?: readonly { label: string; value: string }[] | undefined;
  /** `colorPair` only: the switch (optional) and the two swatches. */
  pair?: {
    enabled?: { key: string } | undefined;
    up: { key: string; label: string };
    down: { key: string; label: string };
  } | undefined;
  /** `custom` only: what the dialog renders in the control column. */
  custom?: string | undefined;
}

type FormValues = Readonly<Record<string, unknown>>;

export interface FormOptions extends WidgetTranslationOptions {
  values: FormValues;
  /** Shared overlay owner for nested colour pickers. */
  openOverlay?: ColorPickerOptions['openOverlay'];
  /** Every edit, with the value in the control's declared type. */
  onChange(key: string, value: unknown): void;
  /**
   * Why a control, or one option of a select, cannot act right now, or null
   * when it can. Drawn disabled with the reason as its title, never hidden: a
   * greyed row is information, an absent one is a mystery. Asked again after
   * every edit and every `sync`, beside the control's `activeWhen`, and its
   * reason wins where both apply because the host knows the context.
   */
  unavailable?(key: string, option?: string): string | null;
  /** Prefix for element ids, so two forms in one document never share one. */
  idPrefix: string;
  /**
   * Emit colour and slider edits on `input` as well as `change`, for a dialog
   * that previews live. Off, a colour is one edit when the picker closes and a
   * slider one edit on release, which is what a per-edit undo history wants.
   */
  live?: boolean;
  /** Keep an invalid numeric draft visible for validation when a form is saved. */
  preserveInvalidNumbers?: boolean;
  /** Renders the control column of a `custom` row. Null skips the row. */
  custom?(control: FormControl, row: HTMLElement): HTMLElement | null;
}

export interface FormHandle {
  el: HTMLElement;
  /**
   * Re-read `values` into every control the user is not currently in, hidden
   * ones included, then re-read which controls are shown and editable.
   */
  sync(values: FormValues): void;
  /** Every control's current value, keyed the way `onChange` reports it; a hidden draft included. */
  values(): Record<string, unknown>;
  /**
   * Validate typed drafts without replacing them or committing settings. A
   * hidden or disabled control is skipped: it cannot be corrected from where
   * the user is, so its draft never blocks a save, and it is never written.
   */
  validate(): boolean;
  /** Attach a rejected native write to its field; null clears that error. */
  setError(key: string, message: string | null): void;
  /** Focus the first enabled control. */
  focusFirst(): boolean;
  /** Dispose nested controls and any open overlays before removing the form. */
  destroy(): void;
}

/**
 * The built-in interval tokens, which resolve without being registered and so
 * never appear in `registeredIntervals()`. Listed here in the order a picker
 * reads naturally; a host that registers its own codes sees them appended.
 */
const BUILTIN_INTERVAL_CODES: readonly string[] = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '1d', '1w'];

function intervalOptions(served?: readonly string[]): { label: string; value: string }[] {
  const seen = new Set<string>();
  const out: { label: string; value: string }[] = [{ label: 'Chart', value: '' }];
  for (const code of served ?? [...BUILTIN_INTERVAL_CODES, ...registeredIntervals().map((d) => d.code)]) {
    const key = code.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ label: code, value: code });
  }
  return out;
}

// ── converters from the three schema vocabularies ─────────────────────────

/**
 * Chart-settings and indicator inputs. `source` becomes a select over the
 * canonical price sources; a `colorPair` keeps its two or three keys.
 * `intervals`, the codes the host serves, fills an `interval` select in their
 * order; without it the select offers the built-in tokens and every
 * registered code.
 */
export function controlsFromInputs(
  inputs: readonly ChartSettingsInput[], translation?: FormTranslationOptions, intervals?: readonly string[],
): FormControl[] {
  const out: FormControl[] = [];
  for (const input of inputs) {
    const before = out.length;
    switch (input.type) {
      case 'colorPair':
        out.push({
          key: input.key, kind: 'colorPair', label: input.label, group: input.group,
          pair: {
            enabled: input.enabled === undefined ? undefined : { key: input.enabled.key },
            up: { key: input.up.key, label: input.up.label },
            down: { key: input.down.key, label: input.down.label },
          },
        });
        break;
      case 'number':
        out.push({
          key: input.key, kind: 'number', label: input.label, group: input.group,
          min: input.min, max: input.max, step: input.step,
        });
        break;
      case 'price':
      case 'timestamp':
        out.push({ key: input.key, kind: input.type, label: input.label, group: input.group,
          min: input.min, max: input.max, step: input.step });
        break;
      case 'select':
        out.push({ key: input.key, kind: 'select', label: input.label, group: input.group, options: input.options });
        break;
      case 'source':
        out.push({ key: input.key, kind: 'select', label: input.label, group: input.group, options: INDICATOR_SOURCES });
        break;
      case 'interval':
        // Codes the engine can bucket by and nothing else: the host's own list,
        // or the built-in tokens (which the registry does not list) and
        // whatever the host registered. The empty entry is the chart's own.
        out.push({
          key: input.key, kind: 'select', label: input.label, group: input.group,
          options: intervalOptions(intervals),
        });
        break;
      case 'time':
        // A wall-clock string in the chart's zone; see the input's own note.
        out.push({ key: input.key, kind: 'text', label: input.label, group: input.group });
        break;
      case 'boolean':
      case 'color':
      case 'text':
      case 'symbol':
      case 'session':
      case 'multiline':
        out.push({ key: input.key, kind: input.type, label: input.label, group: input.group });
        break;
    }
    // Set once here rather than in seven branches: every variant carries the
    // field, and a branch that forgot it would drop the help text silently.
    if (out.length > before) {
      const control = out[before]!; // the length test just above says this branch pushed it
      if (input.tooltip !== undefined) control.tooltip = input.tooltip;
      if (input.activeWhen !== undefined) control.activeWhen = input.activeWhen;
      if (input.visibleWhen !== undefined) control.visibleWhen = input.visibleWhen;
      if (input.type !== 'colorPair' && input.inline !== undefined) control.inline = input.inline;
    }
  }
  return localizeControls(out, translation);
}

export interface FormTranslationOptions extends WidgetTranslationOptions {
  /** Stable descriptor scope, for example settings or indicator.ema. */
  scope: string;
}

function localizeControls(controls: FormControl[], translation?: FormTranslationOptions): FormControl[] {
  if (translation?.translate === undefined) return controls;
  const label = (key: string, fallback: string): string => widgetText(translation, `schema.${translation.scope}.${key}`, {}, fallback);
  return controls.map(control => ({
    ...control,
    label: label(`${control.key}.label`, control.label),
    group: control.group === undefined ? undefined : label(`group.${control.group}`, control.group),
    tooltip: control.tooltip === undefined ? undefined : label(`${control.key}.tooltip`, control.tooltip),
    options: control.options?.map(option => ({ ...option, label: option.label === option.value ? option.label : label(`${control.key}.option.${option.value}`, option.label) })),
    pair: control.pair === undefined ? undefined : {
      ...control.pair,
      up: { ...control.pair.up, label: label(`${control.pair.up.key}.label`, control.pair.up.label) },
      down: { ...control.pair.down, label: label(`${control.pair.down.key}.label`, control.pair.down.label) },
    },
  }));
}

/** Our words for the draw tier's group ids. */
const DRAWING_GROUP_LABELS: Readonly<Record<string, string>> = {
  line: 'Line', fill: 'Fill', text: 'Text', levels: 'Levels', behavior: 'Behavior',
};

/**
 * Draw-tier fields. `lineStyle` is a select with a fixed option list, an
 * `opacity` is a slider read in percent, `levels` is left to the dialog (the
 * level editor is its own surface), and the text tool's content is the one
 * multi-line box.
 */
export function controlsFromFields(fields: readonly SettingsField[], translation?: FormTranslationOptions): FormControl[] {
  const out: FormControl[] = [];
  for (const f of fields) {
    const group = f.group === undefined ? undefined : (DRAWING_GROUP_LABELS[f.group] ?? f.group);
    const base = { key: f.path, label: f.label, group };
    switch (f.kind) {
      case 'color':
        out.push({ ...base, kind: 'color' });
        break;
      case 'number':
        out.push({ ...base, kind: 'number', min: f.min, max: f.max, step: f.step });
        break;
      case 'opacity':
        out.push({ ...base, kind: 'opacity' });
        break;
      case 'boolean':
        out.push({ ...base, kind: 'boolean' });
        break;
      case 'select':
      case 'lineStyle':
        out.push(f.options === undefined ? { ...base, kind: 'text' } : { ...base, kind: 'select', options: f.options });
        break;
      case 'text':
        out.push({ ...base, kind: f.path === 'text.value' ? 'multiline' : 'text' });
        break;
      case 'levels':
        out.push({ ...base, kind: 'custom', custom: 'levels' });
        break;
    }
  }
  return localizeControls(out, translation);
}

// ── value helpers ─────────────────────────────────────────────────────────

/** Print a number without float noise: 1.5 stays 1.5, 2.0000000000000004 prints 2. */
export function formatNumber(n: number): string {
  return Number.isInteger(n) ? String(n) : String(Math.round(n * 1000) / 1000);
}

// ── small DOM kit shared by the dialogs ───────────────────────────────────

/** `h` with the text most dialog calls want in place of attributes: one element factory, two call shapes. */
export function el<K extends keyof HTMLElementTagNameMap>(
  doc: Document, tag: K, className?: string, text?: string,
): HTMLElementTagNameMap[K] {
  const node = h(doc, tag, className);
  if (text !== undefined) node.textContent = text;
  return node;
}

const XMLNS = 'http://www.w3.org/2000/svg';

/**
 * Chrome-grid path data the registry derives rather than lists (a layout
 * picker's tile), in the frame `chromeIconSvg` draws, so it sits beside the
 * listed glyphs at one weight. Every picture the widget shows is registry
 * data: a glyph drawn here instead would escape the registry's checks.
 */
export function glyphSvg(path: string): string {
  return `<svg xmlns="${XMLNS}" viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor"`
    + ` stroke-width="${CHROME_ICON_STROKE}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${path}"/></svg>`;
}

/** A chrome glyph wrapped for the stylesheet's `.oac-glyph--chrome` sizing. */
export function chromeGlyph(doc: Document, id: string): HTMLElement {
  return glyph(doc, chromeIconSvg(id), 'chrome');
}

type ButtonVariant = 'ghost' | 'primary' | 'danger';

export interface ButtonSpec {
  label: string;
  /** Chrome icon id. With `iconOnly` the label becomes the accessible name. */
  icon?: string;
  iconOnly?: boolean;
  variant?: ButtonVariant | undefined;
  onClick?: (e: MouseEvent) => void;
  /** Chord hint for the title, as `Ctrl+D`. */
  chord?: string | undefined;
}

/** A flat `.oac-btn`. Icon-only buttons carry their label as `aria-label` and `title`. */
export function button(doc: Document, spec: ButtonSpec): HTMLButtonElement {
  const b = el(doc, 'button');
  b.type = 'button';
  const classes = ['oac-btn'];
  if (spec.iconOnly === true) classes.push('oac-btn--icon');
  if (spec.variant === 'primary') classes.push('oac-btn--primary');
  if (spec.variant === 'danger') classes.push('oac-btn--danger');
  b.className = classes.join(' ');
  if (spec.icon !== undefined) b.appendChild(chromeGlyph(doc, spec.icon));
  if (spec.iconOnly === true) {
    b.setAttribute('aria-label', spec.label);
    b.title = spec.chord === undefined ? spec.label : `${spec.label} (${spec.chord})`;
  } else {
    b.appendChild(doc.createTextNode(spec.label));
    if (spec.chord !== undefined) b.title = spec.chord;
  }
  if (spec.onClick !== undefined) {
    const onClick = spec.onClick;
    b.addEventListener('click', (e) => { e.stopPropagation(); onClick(e as MouseEvent); });
  }
  return b;
}

/** A select wrapped for the stylesheet's custom chevron. */
export function selectBox(doc: Document): { wrap: HTMLElement; select: HTMLSelectElement } {
  const wrap = el(doc, 'span', 'oac-select');
  const select = el(doc, 'select');
  wrap.appendChild(select);
  const chev = el(doc, 'span', 'oac-chev');
  chev.innerHTML = chromeIconSvg('chevron-down');
  wrap.appendChild(chev);
  return { wrap, select };
}

/**
 * Keys typed inside a dialog are the dialog's. The widget's chords (Delete
 * for a drawing, a letter arming a tool) live on the root and must not read a
 * Backspace in a number box as a delete. Escape and Tab still travel: the
 * shell's overlay stack owns closing and the focus trap.
 */
export function stopOwnKeys(node: HTMLElement): void {
  node.addEventListener('keydown', (e) => {
    const k = (e as KeyboardEvent).key;
    if (k !== 'Escape' && k !== 'Tab') e.stopPropagation();
  });
  // A press inside a panel is never a pan on the chart underneath: the chart
  // captures the pointer on pointerdown, so the event has to stop here.
  node.addEventListener('pointerdown', (e) => { e.stopPropagation(); });
}

// ── dialog furniture ──────────────────────────────────────────────────────

interface DialogFrame {
  /** The card (`role="dialog"`), handed to `openOverlay` as is. */
  el: HTMLElement;
  head: HTMLElement;
  body: HTMLElement;
  foot: HTMLElement;
  /** Left slot of the footer, for a secondary control. */
  lead: HTMLElement;
  /** Right slot of the footer; the confirming action goes last. */
  actions: HTMLElement;
  closeButton: HTMLButtonElement;
  setTitle(title: string): void;
}

interface DialogFrameSpec extends WidgetTranslationOptions {
  title: string;
  /** Extra class on the card. */
  className?: string;
  /** The close affordance top right. Escape and the scrim are the overlay stack's. */
  onClose(): void;
  /**
   * The close as the word rather than the icon, for a compact list panel whose
   * rows act through words too and which carries no glyph (the objects panel,
   * the alerts list). Default: the icon every form dialog shows.
   */
  closeText?: boolean;
}

let frameSeq = 0;

/**
 * The furniture every dialog shares: title left, close top right, a
 * scrolling body, and a footer with a lead slot on the left and the actions
 * on the right. The card is `.oac-panel`; the overlay stack adds `.oac-dialog`
 * (centred, over a scrim) or `.oac-pop` (anchored) when it opens the card,
 * so one frame serves a modal and a popover.
 */
export function dialogFrame(doc: Document, spec: DialogFrameSpec): DialogFrame {
  const card = el(doc, 'div', 'oac-panel' + (spec.className === undefined ? '' : ' ' + spec.className));
  card.setAttribute('role', 'dialog');
  card.tabIndex = -1;
  const titleId = `oac-dlg-title-${++frameSeq}`;
  card.setAttribute('aria-labelledby', titleId);

  const head = el(doc, 'div', 'oac-dialog__head');
  const title = el(doc, 'span', 'oac-dialog__title', spec.title);
  title.id = titleId;
  const closeButton = button(doc, { label: widgetText(spec, 'Close'), ...(spec.closeText === true ? {} : { icon: 'close', iconOnly: true }), onClick: () => spec.onClose() });
  head.appendChild(title);
  head.appendChild(closeButton);

  const body = el(doc, 'div', 'oac-dialog__body');
  const foot = el(doc, 'div', 'oac-dialog__foot');
  const lead = el(doc, 'div', 'oac-dialog__lead');
  const spacer = el(doc, 'div', 'oac-spacer');
  const actions = el(doc, 'div', 'oac-dialog__actions');
  foot.appendChild(lead);
  foot.appendChild(spacer);
  foot.appendChild(actions);

  card.appendChild(head);
  card.appendChild(body);
  card.appendChild(foot);
  stopOwnKeys(card);

  return {
    el: card, head, body, foot, lead, actions, closeButton,
    setTitle: (t) => { title.textContent = t; },
  };
}

// ── the overlay session ───────────────────────────────────────────────────

/** What every mount function returns: the shell's `DialogHandle` plus the node and a liveness probe. */
export interface PanelHandle {
  el: HTMLElement;
  close(): void;
  isOpen(): boolean;
}

/** The slice of the widget context a panel needs to show itself. */
interface PanelHost {
  openOverlay(el: HTMLElement, opts?: OverlayOptions): () => void;
}

/**
 * A dialog that cannot open says why in a toast, and hands back a handle that
 * is already closed, so the caller treats it like any other.
 */
export function declinedPanel(ctx: { readonly document: Document; toast(message: string, kind?: 'info'): unknown }, why: string): PanelHandle {
  ctx.toast(why, 'info');
  return { el: ctx.document.createElement('div'), close: () => {}, isOpen: () => false };
}

/**
 * Put `panel` on the shell's overlay stack and return the handle.
 *
 * The stack owns focus, Escape, the outside press and the node's removal, and
 * reports each through `onClose`; the dialog owns what closing means (a
 * settings dialog reverts, a text editor cancels). The two meet here so that
 * whichever side closes first, the other runs exactly once: a dialog closing
 * itself must not have the stack call it back into a second close, and the
 * stack closing the dialog must not have the dialog ask the stack again.
 */
export function openPanel(host: PanelHost, panel: HTMLElement, opts: OverlayOptions, onDismiss: () => void): PanelHandle {
  let closed = false;
  let byShell = false;
  let resize: ResizeObserver | undefined;
  const closer = host.openOverlay(panel, {
    ...opts,
    onClose: () => {
      opts.onClose?.();
      if (closed) return;
      byShell = true;
      onDismiss();
      finish();
    },
  });
  // CSS follows the host container, so keyboard semantics must follow it too.
  const root = panel.closest('.oac-widget');
  const rails = panel.querySelectorAll('.oac-tabs--rail');
  if (root !== null && rails.length > 0) {
    const orient = (): void => {
      const orientation = root.getBoundingClientRect().width <= 720 ? 'horizontal' : 'vertical';
      rails.forEach(nav => nav.setAttribute('aria-orientation', orientation));
    };
    orient();
    const Observer = panel.ownerDocument.defaultView?.ResizeObserver;
    if (Observer !== undefined) {
      resize = new Observer(orient);
      resize.observe(root);
    }
  }
  function finish(): void {
    if (closed) return;
    closed = true;
    resize?.disconnect();
    if (!byShell) closer();
    panel.remove();
  }
  return { el: panel, close: finish, isOpen: () => !closed };
}


/** The slice of a chart a popover needs to sit beside a drawing. */
interface AnchorChart {
  timeToCoordinate(time: number): number;
  priceToCoordinate(price: number, paneIndex?: number): number | null;
  panes(): ReadonlyArray<{ element: HTMLElement }>;
}

/**
 * Where a popover about `drawings` goes, in root px: just below the lowest
 * anchor of the selection, or a little way in from the corner when no anchor
 * is on screen. Chart coordinates are container-relative, and the container
 * sits to the right of the rail, so its offset inside the root is added.
 * `screenOf` places a drawing the chart's time and price maps cannot, one
 * pinned to the viewport; the controller's `screenPoints` is the one to pass.
 */
export function selectionPoint(
  root: HTMLElement, chart: AnchorChart,
  drawings: ReadonlyArray<{ id?: string; paneIndex: number; points: ReadonlyArray<{ time: number; price: number }> }>,
  screenOf?: (id: string) => ReadonlyArray<{ x: number; y: number }> | null,
): { x: number; y: number } {
  const container = chart.panes()[0]?.element.parentElement ?? null;
  const off = container === null ? { left: 0, top: 0 } : boxIn(root, container);
  let x0 = Infinity;
  let y1 = -Infinity;
  for (const d of drawings) {
    const known = screenOf !== undefined && d.id !== undefined ? screenOf(d.id) : null;
    const at = known ?? d.points.map((p) => ({ x: chart.timeToCoordinate(p.time), y: chart.priceToCoordinate(p.price, d.paneIndex) }));
    for (const { x: cx, y: cy } of at) {
      if (!Number.isFinite(cx) || cy === null || !Number.isFinite(cy)) continue;
      x0 = Math.min(x0, cx);
      y1 = Math.max(y1, cy);
    }
  }
  if (!Number.isFinite(x0) || !Number.isFinite(y1)) return { x: off.left + 60, y: off.top + 60 };
  return { x: off.left + x0, y: off.top + y1 + 12 };
}

interface TabSpec {
  id: string;
  label: string;
  /** Chrome icon id for the glyph beside the label. */
  icon?: string;
}

interface TabListHandle {
  el: HTMLElement;
  /** Mark `id` as the selected tab. The buttons stay put, so a focused one keeps its focus. */
  setActive(id: string): void;
}

/**
 * A tab list, as a vertical rail (`rail`) or a row. Every tab carries its
 * glyph, per the UI standard; `onPick` runs on click and on arrow keys, and
 * the list marks the pick itself.
 */
export function tabList(
  doc: Document, tabs: readonly TabSpec[], active: string, layout: 'rail' | 'row', onPick: (id: string) => void,
): TabListHandle {
  const nav = el(doc, 'div', `oac-tabs oac-tabs--${layout}`);
  nav.setAttribute('role', 'tablist');
  nav.setAttribute('aria-orientation', layout === 'rail' ? 'vertical' : 'horizontal');
  const buttons: HTMLButtonElement[] = [];
  const setActive = (id: string): void => {
    // One button per tab, every one built before anything can call this.
    tabs.forEach((t, i) => {
      const on = t.id === id;
      buttons[i]!.setAttribute('aria-selected', on ? 'true' : 'false');
      buttons[i]!.tabIndex = on ? 0 : -1;
    });
  };
  const pick = (id: string): void => { setActive(id); onPick(id); };
  tabs.forEach((t, i) => {
    const b = el(doc, 'button', 'oac-tab');
    b.type = 'button';
    b.setAttribute('role', 'tab');
    b.dataset.tab = t.id;
    if (t.icon !== undefined) b.appendChild(chromeGlyph(doc, t.icon));
    b.appendChild(el(doc, 'span', 'oac-tab__label', t.label));
    b.addEventListener('click', (e) => { e.stopPropagation(); pick(t.id); });
    b.addEventListener('keydown', (e) => {
      const k = (e as KeyboardEvent).key;
      const vertical = nav.getAttribute('aria-orientation') === 'vertical';
      const fwd = vertical ? 'ArrowDown' : 'ArrowRight';
      const back = vertical ? 'ArrowUp' : 'ArrowLeft';
      let next = -1;
      if (k === fwd) next = (i + 1) % tabs.length;
      else if (k === back) next = (i - 1 + tabs.length) % tabs.length;
      else if (k === 'Home') next = 0;
      else if (k === 'End') next = tabs.length - 1;
      if (next < 0) return;
      e.preventDefault();
      // Every branch above leaves next inside the tab list, and a key needs a built button.
      buttons[next]!.focus();
      buttons[next]!.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
      pick(tabs[next]!.id);
    });
    buttons.push(b);
    nav.appendChild(b);
  });
  setActive(active);
  return { el: nav, setActive };
}

// ── placement ─────────────────────────────────────────────────────────────

interface PlaceAt {
  /** Below this control, left edges aligned; above it when the bottom has no room. */
  anchor?: HTMLElement;
  /** At this point, in root px (a context menu at the pointer). */
  point?: { x: number; y: number };
}

/**
 * Position an absolutely placed panel inside `root`. Measured after the
 * panel is in the document, so it has a size; clamped so it never runs past
 * the widget's edge, which on a right-hand price axis is the usual case.
 */
export function placePanel(root: HTMLElement, panel: HTMLElement, at: PlaceAt): void {
  const rr = root.getBoundingClientRect();
  const w = panel.offsetWidth || 200;
  const h = panel.offsetHeight || 100;
  const pad = 4;
  let x = pad;
  let y = pad;
  if (at.anchor !== undefined) {
    const ar = at.anchor.getBoundingClientRect();
    x = ar.left - rr.left;
    y = ar.bottom - rr.top + 6;
    if (y + h > rr.height - pad) y = Math.max(pad, ar.top - rr.top - h - 6);
  } else if (at.point !== undefined) {
    x = at.point.x;
    y = at.point.y;
    if (y + h > rr.height - pad) y = Math.max(pad, rr.height - h - pad);
  }
  x = Math.max(pad, Math.min(x, rr.width - w - pad));
  y = Math.max(pad, Math.min(y, rr.height - h - pad));
  panel.style.left = `${Math.round(x)}px`;
  panel.style.top = `${Math.round(y)}px`;
}

// ── the renderer ──────────────────────────────────────────────────────────

interface Bound {
  key: string;
  read(): unknown;
  /** Show `value`; `undefined` shows the control's empty state. */
  write(value: unknown): void;
  control: HTMLElement;
  focus?: HTMLElement;
  /** The title the control carries for a reason it cannot act, or for none. */
  title(why: string | null): string;
  /** The control this value belongs to, once its row is built. */
  member?: Member;
}

/**
 * What the state pass needs to know about one control's place on the page.
 * Most controls own a whole row; a member of an inline row owns only its part
 * of one, so hiding it must not hide its neighbours.
 */
interface Member {
  control: FormControl;
  fields: Bound[];
  /** Hidden together when the control is. */
  parts: HTMLElement[];
  /** The values whose reasons decide whether the whole control reads as off. */
  offKeys: string[];
  /** Carries the dimmed class, and `offClass` names it. */
  offEl: HTMLElement | null;
  offClass: string;
  /** Carry the reason where a pointer lands, since a disabled input takes none. */
  titles: HTMLElement[];
  row: HTMLElement;
  head: HTMLElement | undefined;
  /** What the last pass applied, so the next one can say what changed. */
  shown: boolean;
  enabled: boolean;
}

const activeForms = new WeakMap<HTMLElement, () => void>();

/**
 * Render `controls` into `host` (emptied first). Rows sit under small
 * uppercase group headers; a boolean sits in the switch column in front of its
 * label; everything else sits in the control column on the right.
 */
export function renderForm(host: HTMLElement, controls: readonly FormControl[], opts: FormOptions): FormHandle {
  activeForms.get(host)?.();
  let destroyed = false;
  const disposers: (() => void)[] = [];
  const doc = host.ownerDocument;
  host.innerHTML = '';
  host.classList.add('oac-form');
  const bound: Bound[] = [];
  const members: Member[] = [];
  const unavailable = opts.unavailable ?? ((): null => null);
  const idFor = (key: string): string => `${opts.idPrefix}-${key.replace(/[^A-Za-z0-9_-]/g, '-')}`;
  // The last value each control reported, so a `change` after a live `input`
  // of the same value is not a second edit.
  const last = new Map<string, unknown>();
  const errors = new Map<string, string>();
  const rows = new Map<string, { control: HTMLElement; error: HTMLElement; member?: Member }>();
  // What the conditions read: the values handed in, then every edit and sync.
  // Written with defineProperty so an own `__proto__` setting stays a setting.
  const current: Record<string, unknown> = { ...opts.values };
  const put = (key: string, value: unknown): void => {
    Object.defineProperty(current, key, { value, writable: true, enumerable: true, configurable: true });
  };
  const conditional = controls.some(c => c.activeWhen !== undefined || c.visibleWhen !== undefined);
  // The control whose edit is being reported, so focus lost to that edit can
  // go back to it rather than to the top of the form.
  let editing: string | undefined;
  let live: HTMLElement | null = null;
  const errorShown = (key: string): boolean => errors.has(key) && rows.get(key)?.member?.shown !== false;
  const setError = (key: string, message: string | null): void => {
    const row = rows.get(key);
    if (message === null) errors.delete(key);
    else { errors.set(key, message); last.delete(key); }
    if (!row) return;
    row.control.setAttribute('aria-invalid', String(message !== null));
    row.error.textContent = message ?? '';
    row.error.hidden = !errorShown(key);
  };
  const validate = (key: string, value: unknown): string | null => {
    const spec = controls.find(control => control.key === key);
    if (spec?.kind === 'price' || spec?.kind === 'timestamp') {
      if (typeof value !== 'number' || !Number.isFinite(value)) return widgetText(opts, 'Enter a finite number');
      if (spec.min !== undefined && value < spec.min) return widgetText(opts, 'Minimum: {value}', { value: spec.min });
      if (spec.max !== undefined && value > spec.max) return widgetText(opts, 'Maximum: {value}', { value: spec.max });
    }
    if (spec?.kind === 'session' && (typeof value !== 'string' || parseSessionSpec(value) === null)) {
      return widgetText(opts, 'Use HHMM-HHMM with optional :days (1 to 7)');
    }
    return null;
  };
  const emit = (key: string, value: unknown): void => {
    if (destroyed) return;
    const error = validate(key, value);
    setError(key, error);
    if (error !== null) return;
    if (last.has(key) && Object.is(last.get(key), value)) return;
    last.set(key, value);
    put(key, value);
    editing = key;
    try { opts.onChange(key, value); }
    finally { editing = undefined; }
    // A dialog that syncs from onChange has already re-read the states; one
    // that does not still needs them re-read, and a rebuilt form needs nothing.
    if (!destroyed) applyState(key);
  };

  /** One input of the kinds a single value covers. */
  function field(key: string, kind: FormKind, spec: FormControl, value: unknown): { ctl: HTMLElement; b: Bound } {
    const plain = (why: string | null): string => why ?? '';
    let ctl: HTMLElement;
    let b: Bound;
    switch (kind) {
      case 'price':
      case 'timestamp': {
        const input = el(doc, 'input', 'oac-input--num');
        // Text retains incomplete exponents and out-of-range drafts. String
        // round-trips the number without the legacy number control's rounding.
        input.type = 'text'; input.inputMode = 'decimal';
        if (spec.min !== undefined) input.min = String(spec.min);
        if (spec.max !== undefined) input.max = String(spec.max);
        if (spec.step !== undefined) input.step = String(spec.step);
        const show = (v: unknown): void => { input.value = typeof v === 'number' ? String(v) : ''; };
        const read = (): number | undefined => input.value.trim() === '' ? undefined : Number(input.value);
        show(value);
        input.addEventListener('change', () => emit(key, read()));
        ctl = input; b = { key, control: input, read, write: show, title: plain };
        break;
      }
      case 'boolean': {
        const input = el(doc, 'input');
        input.type = 'checkbox';
        input.checked = value === true;
        input.addEventListener('change', () => emit(key, input.checked));
        ctl = input;
        b = { key, control: input, read: () => input.checked, write: (v) => { input.checked = v === true; }, title: plain };
        break;
      }
      case 'number': {
        const input = el(doc, 'input', 'oac-input--num');
        input.type = 'number';
        if (spec.min !== undefined) input.min = String(spec.min);
        if (spec.max !== undefined) input.max = String(spec.max);
        if (spec.step !== undefined) input.step = String(spec.step);
        const show = (v: unknown): void => { input.value = typeof v === 'number' && Number.isFinite(v) ? formatNumber(v) : ''; };
        show(value);
        input.addEventListener('change', () => {
          const raw = input.value.trim();
          const n = raw === '' ? NaN : Number(raw);
          // A blank or unparseable box is not an edit; the last good value comes back.
          if (!Number.isFinite(n)) {
            if (opts.preserveInvalidNumbers) emit(key, undefined);
            else show(last.has(key) ? last.get(key) : value);
            return;
          }
          const lo = spec.min ?? -Infinity;
          const hi = spec.max ?? Infinity;
          const clamped = Math.min(hi, Math.max(lo, n));
          if (clamped !== n) show(clamped);
          emit(key, clamped);
        });
        ctl = input;
        b = {
          key, control: input,
          read: () => { const n = Number(input.value); return input.value.trim() === '' || !Number.isFinite(n) ? undefined : n; },
          write: show, title: plain,
        };
        break;
      }
      case 'color': {
        const picker = createColorPicker(doc, {
          id: idFor(key), label: spec.label, value, live: opts.live, translate: opts.translate,
          openOverlay: opts.openOverlay, onChange: next => emit(key, next),
        });
        disposers.push(picker.destroy);
        ctl = picker.el;
        // Unlike a text box a swatch says nothing about itself, so its name
        // stays on it while it can act.
        b = { key, control: picker.input, focus: picker.trigger, read: picker.read, write: picker.write, title: why => why ?? spec.label };
        return { ctl, b };
      }
      case 'opacity': {
        const range = el(doc, 'input', 'oac-range');
        range.type = 'range';
        range.min = '0'; range.max = '100'; range.step = '1';
        const out = el(doc, 'output', 'oac-out');
        const pct = (v: unknown): number => Math.round((typeof v === 'number' ? Math.min(1, Math.max(0, v)) : 0) * 100);
        const show = (v: unknown): void => { range.value = String(pct(v)); out.textContent = `${pct(v)}%`; };
        show(value);
        range.addEventListener('input', () => {
          out.textContent = `${range.value}%`;
          if (opts.live === true) emit(key, Number(range.value) / 100);
        });
        range.addEventListener('change', () => emit(key, Number(range.value) / 100));
        const wrap = el(doc, 'span', 'oac-opacity');
        wrap.appendChild(range);
        wrap.appendChild(out);
        ctl = wrap;
        b = { key, control: range, read: () => Number(range.value) / 100, write: show, title: plain };
        return { ctl, b };
      }
      case 'select': {
        const { wrap, select } = selectBox(doc);
        const options = spec.options ?? [];
        const fill = (v: unknown): void => {
          select.innerHTML = '';
          const list = options.slice();
          const cur = typeof v === 'string' ? v : v === undefined ? undefined : String(v);
          // A value outside the list (a font stack the user typed) stays
          // selectable as its own entry rather than snapping to the first.
          if (cur !== undefined && cur !== '' && !list.some((o) => o.value === cur)) list.push({ value: cur, label: widgetText(opts, 'Custom') });
          for (const o of list) {
            const opt = el(doc, 'option', undefined, o.label);
            opt.value = o.value;
            const reason = unavailable(key, o.value);
            if (reason !== null) { opt.disabled = true; opt.title = reason; }
            select.appendChild(opt);
          }
          select.value = cur === undefined || cur === '' ? (list[0]?.value ?? '') : cur;
        };
        fill(value);
        select.addEventListener('change', () => emit(key, select.value));
        ctl = wrap;
        b = { key, control: select, read: () => select.value, write: fill, title: plain };
        return { ctl, b };
      }
      case 'multiline': {
        const area = el(doc, 'textarea', 'oac-input--multi');
        area.rows = 3;
        area.setAttribute('spellcheck', 'false');
        const show = (v: unknown): void => { area.value = v === undefined || v === null ? '' : String(v); };
        show(value);
        area.addEventListener('change', () => emit(key, area.value));
        ctl = area;
        b = { key, control: area, read: () => area.value, write: show, title: plain };
        break;
      }
      case 'text':
      default: {
        const input = el(doc, 'input');
        input.type = 'text';
        input.setAttribute('spellcheck', 'false');
        const show = (v: unknown): void => { input.value = v === undefined || v === null ? '' : String(v); };
        show(value);
        input.addEventListener('change', () => emit(key, input.value));
        ctl = input;
        b = { key, control: input, read: () => input.value, write: show, title: plain };
        break;
      }
    }
    return { ctl, b };
  }

  const labelFor = (c: FormControl, className: string): HTMLLabelElement => {
    const label = el(doc, 'label', className, c.kind === 'timestamp'
      ? widgetText(opts, '{label} (UTC seconds)', { label: c.label }) : c.label);
    // The mark rides inside the label so it lands the same way in all three row
    // shapes below. It is for the pointer: inside the label its text would be
    // read as part of the control's name, so the control carries it as its
    // description instead (bindLabel).
    if (c.tooltip !== undefined && c.tooltip !== '') {
      const help = el(doc, 'span', 'oac-help', '?');
      help.title = c.tooltip;
      help.setAttribute('aria-hidden', 'true');
      label.appendChild(help);
    }
    return label;
  };
  const bindLabel = (label: HTMLLabelElement, control: HTMLElement, c: FormControl): void => {
    label.htmlFor = control.id;
    if (c.tooltip !== undefined && c.tooltip !== '') control.setAttribute('aria-description', c.tooltip);
  };
  const member = (c: FormControl, row: HTMLElement, head: HTMLElement | undefined, fields: Bound[], parts: HTMLElement[]): Member => {
    const m: Member = { control: c, fields, parts, offKeys: fields.map(f => f.key), offEl: row, offClass: 'oac-row--off',
      titles: [row], row, head, shown: true, enabled: true };
    for (const f of fields) f.member = m;
    members.push(m);
    return m;
  };
  /** The error line under a control's row, and the control's link to it. */
  const errorLine = (key: string, b: Bound, row: HTMLElement): HTMLElement => {
    const error = el(doc, 'div', 'oac-input-error');
    error.id = `${idFor(key)}-error`; error.hidden = true;
    error.setAttribute('role', 'status');
    b.control.setAttribute('aria-describedby', error.id);
    row.appendChild(error);
    rows.set(key, { control: b.control, error });
    return error;
  };
  // Inline rows take the single-value kinds only: a pair is already a row of
  // its own, a custom body is the dialog's, and a multi-line box needs the width.
  const inlinable = (c: FormControl): boolean =>
    c.inline !== undefined && c.kind !== 'custom' && c.kind !== 'colorPair' && c.kind !== 'multiline';

  let lastGroup: string | undefined;
  let head: HTMLElement | undefined;
  // Where rows go: the form, or the group of the heading above them.
  let box = host;
  let inline: { id: string; row: HTMLElement; ctl: HTMLElement } | null = null;
  for (const c of controls) {
    if (c.group !== undefined && c.group !== lastGroup) {
      head = el(doc, 'div', 'oac-head', c.group);
      host.appendChild(head);
      // The rows under a heading are a group it names, so a second Color says
      // whose. The box takes no layout (display: contents), the rows stay the grid's.
      head.id = idFor(`group-${members.length}`);
      box = el(doc, 'div', 'oac-form__group');
      box.setAttribute('role', 'group');
      box.setAttribute('aria-labelledby', head.id);
      host.appendChild(box);
      inline = null;
    }
    lastGroup = c.group ?? lastGroup;
    if (inline !== null && (!inlinable(c) || c.inline !== inline.id)) inline = null;

    if (inline !== null) {
      // A later member of an inline row: its own label and control, grouped so
      // they hide and dim together without touching the members beside them.
      const f = field(c.key, c.kind, c, opts.values[c.key]);
      f.b.control.id = idFor(c.key);
      const label = labelFor(c, 'oac-inline__label');
      bindLabel(label, f.b.focus ?? f.b.control, c);
      bound.push(f.b);
      const item = el(doc, 'span', 'oac-inline__item');
      item.dataset.key = c.key;
      if (c.kind === 'boolean') { item.appendChild(f.ctl); item.appendChild(label); }
      else { item.appendChild(label); item.appendChild(f.ctl); }
      inline.ctl.appendChild(item);
      errorLine(c.key, f.b, inline.row);
      const m = member(c, inline.row, head, [f.b], [item]);
      m.offEl = item; m.offClass = 'oac-inline__item--off'; m.titles = [item];
      rows.get(c.key)!.member = m;
      continue;
    }

    const row = el(doc, 'div', 'oac-row');
    row.dataset.key = c.key;
    const label = labelFor(c, 'oac-row__label');

    if (c.kind === 'custom') {
      const body = opts.custom === undefined ? null : opts.custom(c, row);
      if (body === null) continue;
      row.appendChild(el(doc, 'span', 'oac-row__sw'));
      row.appendChild(label);
      const ctl = el(doc, 'div', 'oac-row__ctl');
      ctl.appendChild(body);
      row.appendChild(ctl);
      box.appendChild(row);
      // The body is the dialog's own markup, so there is nothing here to
      // disable: a condition can only show or hide it.
      member(c, row, head, [], [row]).offEl = null;
      continue;
    }

    if (c.kind === 'colorPair' && c.pair !== undefined) {
      const pair = c.pair;
      const fields: Bound[] = [];
      if (pair.enabled !== undefined) {
        const sw = field(pair.enabled.key, 'boolean', c, opts.values[pair.enabled.key]);
        sw.ctl.classList.add('oac-row__sw');
        sw.ctl.id = idFor(pair.enabled.key);
        bindLabel(label, sw.ctl, c);
        bound.push(sw.b);
        fields.push(sw.b);
        row.appendChild(sw.ctl);
      } else {
        row.appendChild(el(doc, 'span', 'oac-row__sw'));
      }
      row.appendChild(label);
      const ctl = el(doc, 'div', 'oac-row__ctl');
      let first: HTMLElement | undefined;
      for (const half of [pair.up, pair.down]) {
        const f = field(half.key, 'color', c, opts.values[half.key]);
        first ??= f.b.focus ?? f.b.control;
        f.b.control.id = idFor(half.key);
        // Which swatch is which is not obvious at 26px, and the row is too
        // tight for two more labels, so the name rides on the control.
        f.b.title = why => why === null ? half.label : `${half.label}: ${why}`;
        f.b.control.setAttribute('aria-label', `${c.label} ${half.label}`);
        f.b.focus?.setAttribute('aria-label', `${c.label} ${half.label}`);
        bound.push(f.b);
        fields.push(f.b);
        ctl.appendChild(f.ctl);
      }
      if (pair.enabled === undefined && first !== undefined) bindLabel(label, first, c);
      row.appendChild(ctl);
      box.appendChild(row);
      // Inert only when both halves are: one live half keeps the row live and
      // dims the swatch with nothing to paint.
      member(c, row, head, fields, [row]).offKeys = [pair.up.key, pair.down.key];
      continue;
    }

    const f = field(c.key, c.kind, c, opts.values[c.key]);
    f.b.control.id = idFor(c.key);
    bindLabel(label, f.b.focus ?? f.b.control, c);
    bound.push(f.b);
    let parts: HTMLElement[] = [row];
    let titles: HTMLElement[] = [row];
    if (c.kind === 'boolean') {
      f.ctl.classList.add('oac-row__sw');
      row.appendChild(f.ctl);
      row.appendChild(label);
      if (inlinable(c)) {
        row.appendChild(el(doc, 'div', 'oac-row__ctl'));
        parts = [f.ctl, label]; titles = [label];
      }
    } else if (c.kind === 'multiline') {
      row.classList.add('oac-row--block');
      row.appendChild(label);
      row.appendChild(f.ctl);
    } else {
      row.appendChild(el(doc, 'span', 'oac-row__sw'));
      row.appendChild(label);
      const ctl = el(doc, 'div', 'oac-row__ctl');
      if (inlinable(c)) {
        // The leading member keeps the row's label, and its control sits in an
        // item like the others so an action button beside it goes with it.
        const item = el(doc, 'span', 'oac-inline__item');
        item.dataset.key = c.key;
        item.appendChild(f.ctl);
        ctl.appendChild(item);
        parts = [label, item]; titles = [label, item];
      } else {
        ctl.appendChild(f.ctl);
      }
      row.appendChild(ctl);
    }
    if (inlinable(c)) {
      row.classList.add('oac-row--inline');
      row.dataset.inline = c.inline;
      inline = { id: c.inline as string, row, ctl: row.lastChild as HTMLElement };
    }
    errorLine(c.key, f.b, row);
    box.appendChild(row);
    const m = member(c, row, head, [f.b], parts);
    m.titles = titles;
    rows.get(c.key)!.member = m;
  }

  if (conditional) {
    // Polite, and inside the dialog, so the change is read after the edit
    // that caused it without moving focus to say so.
    live = el(doc, 'div', 'oac-sr');
    live.setAttribute('role', 'status');
    live.setAttribute('aria-live', 'polite');
    host.appendChild(live);
  }

  // A pair's switch and swatches are named by the pair, as the reader counts them.
  const labelOf = (key: string): string | undefined =>
    controls.find(c => c.key === key || [c.pair?.enabled, c.pair?.up, c.pair?.down].some(part => part?.key === key))?.label;
  const usable = (b: Bound): boolean => b.member?.shown !== false && !(b.control as HTMLInputElement).disabled;
  const focusFirst = (): boolean => {
    if (destroyed) return false;
    for (const b of bound) {
      if (!usable(b)) continue;
      (b.focus ?? b.control).focus();
      return true;
    }
    return false;
  };

  /**
   * Show, hide, enable and disable every control from the values held now.
   * It runs after the first paint, after each edit and after each sync, and
   * says in the live region what appeared, left, or changed its availability.
   */
  function applyState(cause = editing, announce = true): void {
    const before = doc.activeElement as HTMLElement | null;
    const states = conditional ? inputStates(controls, current) : null;
    const said: Record<'shown' | 'hidden' | 'on' | 'off', string[]> = { shown: [], hidden: [], on: [], off: [] };
    for (const m of members) {
      const state = states?.get(m.control.key);
      const visible = state?.visible ?? true;
      let reason: string | null = null;
      if (state !== undefined && !state.active) {
        const names = state.dependsOn.map(labelOf).filter((name): name is string => name !== undefined);
        reason = names.length > 0 ? widgetText(opts, 'Depends on {inputs}', { inputs: names.join(', ') })
          : widgetText(opts, 'Not used with the current settings');
      }
      for (const part of m.parts) part.hidden = !visible;
      const why = new Map<string, string | null>();
      for (const b of m.fields) {
        const r = unavailable(b.key) ?? reason;
        why.set(b.key, r);
        for (const node of [b.control, b.focus]) {
          if (node === undefined) continue;
          (node as HTMLInputElement).disabled = r !== null;
          node.title = b.title(r);
        }
      }
      const off = m.fields.length > 0 && m.offKeys.every(key => why.get(key) !== null);
      if (m.offEl !== null) {
        m.offEl.classList.toggle(m.offClass, off);
        const lead = why.get(m.offKeys[0]!) ?? null; // only a custom row has no keys, and its offEl is null
        for (const node of m.titles) node.title = off ? lead ?? '' : '';
      }
      const name = m.control.label;
      if (m.shown !== visible) said[visible ? 'shown' : 'hidden'].push(name);
      else if (visible && m.enabled === off) said[off ? 'off' : 'on'].push(name);
      m.shown = visible;
      m.enabled = !off;
    }
    // A row whose every member left goes too, and a head with nothing under it.
    for (const outer of [(m: Member): HTMLElement => m.row, (m: Member): HTMLElement | undefined => m.head]) {
      const groups = new Map<HTMLElement, boolean>();
      for (const m of members) {
        const node = outer(m);
        if (node !== undefined) groups.set(node, (groups.get(node) ?? false) || m.shown);
      }
      for (const [node, any] of groups) node.hidden = !any;
    }
    for (const [key, row] of rows) row.error.hidden = !errorShown(key);

    // Focus inside a control that just left, or just turned off, would fall to
    // the page and out of the dialog's trap: hand it to the control whose edit
    // caused this, or to the first control still usable.
    if (before !== null && host.contains(before)
      && (members.some(m => !m.shown && m.parts.some(part => part.contains(before))) || (before as HTMLInputElement).disabled)) {
      const back = cause === undefined ? undefined : bound.find(b => b.key === cause);
      if (back !== undefined && usable(back)) (back.focus ?? back.control).focus();
      else focusFirst();
    }

    if (!announce || live === null) return;
    const lines: string[] = [];
    if (said.shown.length > 0) lines.push(widgetText(opts, 'Shown: {inputs}', { inputs: said.shown.join(', ') }));
    if (said.hidden.length > 0) lines.push(widgetText(opts, 'Hidden: {inputs}', { inputs: said.hidden.join(', ') }));
    if (said.on.length > 0) lines.push(widgetText(opts, 'Available: {inputs}', { inputs: said.on.join(', ') }));
    if (said.off.length > 0) lines.push(widgetText(opts, 'Unavailable: {inputs}', { inputs: said.off.join(', ') }));
    if (lines.length === 0) return;
    const message = lines.join('. ');
    // A screen reader reads a live region when its text changes, so the same
    // words twice in a row are told apart by a trailing space it does not read.
    live.textContent = live.textContent === message ? `${message}\u00a0` : message;
  }
  applyState(undefined, false);

  const destroy = (): void => {
    if (destroyed) return;
    destroyed = true;
    for (const dispose of disposers.splice(0)) dispose();
    if (activeForms.get(host) === destroy) activeForms.delete(host);
  };
  activeForms.set(host, destroy);
  return {
    el: host, destroy, setError,
    validate: () => {
      const skipped = new Set(bound.filter(b => !usable(b)).map(b => b.key));
      for (const b of bound) {
        if (skipped.has(b.key)) continue;
        const error = validate(b.key, b.read());
        if (error !== null || !errors.has(b.key)) setError(b.key, error);
      }
      return [...errors.keys()].every(key => skipped.has(key));
    },
    sync: (values) => {
      if (destroyed) return;
      for (const key of Object.keys(values)) put(key, values[key]);
      const active = doc.activeElement;
      for (const b of bound) {
        if (b.control === active) continue;
        if (errors.has(b.key)) continue;
        if (!(b.key in values)) continue;
        b.write(values[b.key]);
        // What the control shows now is what it last reported: a value the
        // model refused and wrote back over must be choosable again.
        if (last.has(b.key)) last.set(b.key, b.read());
      }
      applyState();
    },
    values: () => {
      const out: Record<string, unknown> = {};
      for (const b of bound) out[b.key] = b.read();
      return out;
    },
    focusFirst,
  };
}
