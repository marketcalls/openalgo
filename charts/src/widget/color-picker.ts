import type { WidgetContext } from './context';
import { widgetText, type WidgetTranslationOptions } from './localization';

const PALETTE = ['#4f8cff', '#26a69a', '#ef5350', '#f4b740', '#ab79df', '#22a8bd', '#e88555', '#9aa6b2', '#ffffff', '#000000'];
const RECENT_LIMIT = 6;
const recent: string[] = [];

type ColorFormat = 'hex' | 'hexAlpha' | 'rgba';

function parse(value: unknown): { hex: string; alpha: number; format: ColorFormat } | null {
  // Host values may be untrusted; colour literals need only a short, bounded scan.
  if (typeof value !== 'string' || value.length > 256) return null;
  const literal = value.trim();
  const hex = /^#([\da-f]{3}|[\da-f]{4}|[\da-f]{6}|[\da-f]{8})$/i.exec(literal);
  if (hex !== null) {
    let digits = hex[1]!.toLowerCase(); // the group is not optional, so any match fills it
    if (digits.length <= 4) digits = digits.split('').map(c => c + c).join('');
    const alpha = digits.length === 8 ? parseInt(digits.slice(6), 16) / 255 : 1;
    return { hex: `#${digits.slice(0, 6)}`, alpha, format: digits.length === 8 ? 'hexAlpha' : 'hex' };
  }
  const lower = literal.toLowerCase();
  const start = lower.startsWith('rgba(') ? 5 : lower.startsWith('rgb(') ? 4 : 0;
  if (start === 0 || !literal.endsWith(')')) return null;
  const body = literal.slice(start, -1);
  let components: string[];
  let alphaToken: string | undefined;
  if (body.includes(',')) {
    const parts = body.split(',').map(part => part.trim());
    if (parts.length !== 3 && parts.length !== 4) return null;
    components = parts.slice(0, 3);
    alphaToken = parts[3];
  } else {
    const parts = body.split('/');
    if (parts.length > 2) return null;
    components = parts[0]!.trim().split(/\s+/); // a split always returns at least one part
    alphaToken = parts[1]?.trim();
  }
  if (components.length !== 3 || components.some(part => !/^\d{1,3}$/.test(part))) return null;
  const channels = components.map(Number);
  if (channels.some(n => n > 255)) return null;
  if (alphaToken !== undefined) {
    const decimal = alphaToken.split('.');
    if (decimal.length > 2 || decimal.every(part => part === '') || decimal.some(part => /\D/.test(part))) return null;
  }
  const alpha = alphaToken === undefined ? 1 : Number(alphaToken);
  if (!Number.isFinite(alpha) || alpha < 0 || alpha > 1) return null;
  return {
    hex: `#${channels.map(n => n.toString(16).padStart(2, '0')).join('')}`,
    alpha, format: alphaToken === undefined ? 'hex' : 'rgba',
  };
}

function compose(hex: string, alpha: number, format: ColorFormat): string {
  if (format === 'hex') return hex;
  if (format === 'hexAlpha') return `${hex}${Math.round(alpha * 255).toString(16).padStart(2, '0')}`;
  const parts = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
  return `rgba(${parts.join(',')},${Number(alpha.toFixed(3))})`;
}

function remember(hex: string): void {
  const old = recent.indexOf(hex);
  if (old >= 0) recent.splice(old, 1);
  recent.unshift(hex);
  recent.length = Math.min(recent.length, RECENT_LIMIT);
}

export interface ColorPickerOptions extends WidgetTranslationOptions {
  id: string;
  label: string;
  value: unknown;
  disabledReason?: string | null;
  live?: boolean | undefined;
  /** Use the host's overlay stack to escape scrolling ancestors and share focus/Escape ownership. */
  openOverlay?: WidgetContext['openOverlay'] | undefined;
  onChange(value: string): void;
}

export interface ColorPickerHandle {
  el: HTMLElement;
  input: HTMLInputElement;
  trigger: HTMLButtonElement;
  read(): unknown;
  write(value: unknown): void;
  destroy(): void;
}

/** A compact colour swatch with an optional alpha channel retained in its original format. */
export function createColorPicker(doc: Document, options: ColorPickerOptions): ColorPickerHandle {
  const make = <K extends keyof HTMLElementTagNameMap>(tag: K, className: string): HTMLElementTagNameMap[K] => {
    const node = doc.createElement(tag);
    node.className = className;
    return node;
  };
  const text = (name: string): string => widgetText(options, `schema.ui.colorPicker.${name}`, {}, name);
  const wrap = make('span', 'oac-color');
  const input = make('input', 'oac-swatch-input');
  input.type = 'color';
  input.id = options.id;
  input.tabIndex = -1;
  input.setAttribute('aria-hidden', 'true');
  input.setAttribute('aria-label', options.label);
  const trigger = make('button', 'oac-color__trigger');
  trigger.type = 'button';
  trigger.id = `${options.id}-trigger`;
  trigger.setAttribute('aria-label', options.label);
  trigger.setAttribute('aria-haspopup', 'dialog');
  trigger.setAttribute('aria-expanded', 'false');
  if (options.disabledReason !== null && options.disabledReason !== undefined) {
    trigger.disabled = true;
    input.disabled = true;
    trigger.title = options.disabledReason;
    input.title = options.disabledReason;
  } else {
    trigger.title = options.label;
    input.title = options.label;
  }
  wrap.appendChild(input);
  wrap.appendChild(trigger);
  const popup = make('div', 'oac-color__popover');
  popup.hidden = true;
  popup.setAttribute('role', 'dialog');
  popup.setAttribute('aria-label', text('Color'));
  const palette = make('div', 'oac-color__palette');
  palette.setAttribute('aria-label', text('Palette'));
  const recentRow = make('div', 'oac-color__recent');
  recentRow.setAttribute('aria-label', text('Recent'));
  const custom = make('button', 'oac-color__custom');
  custom.type = 'button';
  custom.textContent = text('Custom');
  custom.addEventListener('click', () => { if (!destroyed) input.click(); });
  popup.appendChild(palette);
  popup.appendChild(recentRow);
  popup.appendChild(custom);
  wrap.appendChild(popup);

  let raw: unknown = options.value;
  let parsed = parse(raw);
  let alpha = parsed?.alpha ?? 1;
  let open = false;
  let destroyed = false;
  let closeOverlay: (() => void) | undefined;
  let opacity: HTMLInputElement | undefined;
  let opacityOut: HTMLOutputElement | undefined;

  const paint = (): void => {
    input.value = parsed?.hex ?? '#000000';
    // Some engines expose color inputs as text fields, so the button owns its swatch.
    trigger.style.backgroundColor = parsed === null ? '#000000' : compose(parsed.hex, alpha, parsed.format);
    if (opacity !== undefined) {
      opacity.value = String(Math.round(alpha * 100));
      if (opacityOut !== undefined) opacityOut.textContent = `${opacity.value}%`;
    }
  };
  const commit = (hex: string, a = alpha): void => {
    if (destroyed || trigger.disabled || !/^#[\da-f]{6}$/i.test(hex)) return;
    const format = parsed?.format ?? 'hex';
    raw = compose(hex.toLowerCase(), a, format);
    parsed = { hex: hex.toLowerCase(), alpha: a, format };
    alpha = a;
    paint();
    remember(parsed.hex);
    options.onChange(raw as string);
  };
  const choices = (container: HTMLElement, colors: readonly string[]): void => {
    container.innerHTML = '';
    for (const color of colors) {
      const choice = make('button', 'oac-color__choice');
      choice.type = 'button';
      choice.setAttribute('aria-label', color);
      choice.title = color;
      choice.style.backgroundColor = color;
      choice.addEventListener('click', () => { commit(color); close(); trigger.focus(); });
      container.appendChild(choice);
    }
  };
  const onOutside = (event: Event): void => {
    if (!wrap.contains(event.target as Node) && !popup.contains(event.target as Node)) close();
  };
  const finish = (): void => {
    if (!open) return;
    closeOverlay = undefined;
    open = false;
    popup.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
    doc.removeEventListener('pointerdown', onOutside, true);
    parsed = parse(raw);
    alpha = parsed?.alpha ?? 1;
    paint();
    if (!destroyed && popup.parentNode !== wrap) wrap.appendChild(popup);
  };
  const close = (): void => {
    const release = closeOverlay;
    closeOverlay = undefined;
    release?.();
    finish();
  };
  const show = (): void => {
    if (destroyed || open || trigger.disabled) return;
    open = true;
    ensureOpacity();
    paint();
    choices(palette, PALETTE);
    choices(recentRow, recent);
    recentRow.hidden = recent.length === 0;
    popup.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    if (options.openOverlay) {
      popup.classList.remove('oac-color__popover--above');
      trigger.focus();
      const release = options.openOverlay(popup, {
        anchor: trigger, placement: 'below', modal: false,
        initialFocus: palette.querySelector('button'), onClose: finish,
      });
      if (open) closeOverlay = release;
      else release();
    } else {
      const root = wrap.closest('.oac-widget');
      if (root !== null) {
        const edge = root.getBoundingClientRect().bottom;
        popup.classList.toggle('oac-color__popover--above', trigger.getBoundingClientRect().bottom + popup.offsetHeight > edge);
      }
      doc.addEventListener('pointerdown', onOutside, true);
      (palette.querySelector('button') as HTMLButtonElement | null)?.focus();
    }
  };
  trigger.addEventListener('click', () => open ? close() : show());
  const onKey = (event: KeyboardEvent): void => {
    if (event.key !== 'Escape' || !open) return;
    event.preventDefault();
    event.stopPropagation();
    close();
    trigger.focus();
  };
  wrap.addEventListener('keydown', onKey);
  popup.addEventListener('keydown', onKey);
  popup.addEventListener('pointerdown', event => event.stopPropagation());
  input.addEventListener('input', () => { if (options.live) commit(input.value); });
  input.addEventListener('change', () => commit(input.value));
  function ensureOpacity(): void {
    if (opacity !== undefined || parsed === null || parsed.format === 'hex') return;
    const line = make('label', 'oac-color__opacity');
    line.appendChild(doc.createTextNode(text('Opacity')));
    opacity = make('input', 'oac-color__range');
    opacity.type = 'range';
    opacity.min = '0'; opacity.max = '100'; opacity.step = '1';
    opacityOut = make('output', 'oac-color__percent');
    const range = opacity;
    const out = opacityOut;
    range.addEventListener('input', () => {
      alpha = Number(range.value) / 100;
      out.textContent = `${range.value}%`;
      if (options.live) commit(input.value, alpha);
    });
    range.addEventListener('change', () => commit(input.value, Number(range.value) / 100));
    line.appendChild(range);
    line.appendChild(out);
    popup.appendChild(line);
  }
  paint();
  return {
    el: wrap, input, trigger,
    read: () => raw,
    write: value => { raw = value; parsed = parse(value); alpha = parsed?.alpha ?? 1; paint(); },
    destroy: () => {
      if (destroyed) return;
      destroyed = true;
      close();
      popup.remove();
      wrap.removeEventListener('keydown', onKey);
      popup.removeEventListener('keydown', onKey);
    },
  };
}

/** Include this string beside the widget stylesheet to support strict style CSP. */
export const COLOR_PICKER_CSS = `
.oac-widget .oac-color { position: relative; display: inline-flex; width: 27px; height: 27px; flex: 0 0 27px; }
.oac-widget .oac-color > .oac-swatch-input { position: absolute; inset: 0; width: 27px; height: 27px; padding: 0; opacity: 0; pointer-events: none; }
.oac-widget .oac-color__trigger { position: absolute; inset: 0; width: 27px; height: 27px; border: 1px solid var(--oac-bd); border-radius: 5px; background: transparent; cursor: pointer; }
.oac-widget .oac-color__trigger:focus-visible { outline: 2px solid var(--oac-ring); outline-offset: 2px; }
.oac-widget .oac-color__trigger:disabled { cursor: not-allowed; opacity: .5; }
.oac-widget .oac-color__popover { position: absolute; z-index: 80; top: 30px; right: 0; width: 188px; padding: 9px; border: 1px solid var(--oac-bd); border-radius: 7px; background: var(--oac-elev); color: var(--oac-tx); box-shadow: var(--oac-shadow); }
.oac-widget .oac-color__popover--above { top: auto; bottom: 30px; }
.oac-widget .oac-color__popover.oac-pop { right: auto; bottom: auto; min-width: 0; max-width: calc(100% - 16px); max-height: calc(100% - 16px); overflow: auto; }
.oac-widget .oac-color__popover[hidden], .oac-widget .oac-color__recent[hidden] { display: none; }
.oac-widget .oac-color__palette, .oac-widget .oac-color__recent { display: grid; grid-template-columns: repeat(5, 1fr); gap: 5px; margin-bottom: 7px; }
.oac-widget .oac-color__choice { width: 28px; height: 28px; padding: 0; border: 1px solid var(--oac-bd); border-radius: 5px; background: transparent; overflow: hidden; cursor: pointer; }
.oac-widget .oac-color__custom { width: 100%; padding: 5px; border: 1px solid var(--oac-bd); border-radius: 4px; background: transparent; color: inherit; cursor: pointer; }
.oac-widget .oac-color__opacity { display: flex; align-items: center; gap: 5px; margin-top: 7px; font-size: 11px; }
.oac-widget .oac-color__range { min-width: 0; flex: 1; }
.oac-widget .oac-color__percent { min-width: 30px; text-align: right; }
`;
