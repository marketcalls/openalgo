/**
 * The shortcuts panel, which is also where a user changes them.
 *
 * Every row the keymap lists shows its chord; a row whose command may move
 * carries Change, which records the next chord pressed (Escape cancels), and
 * Reset once it differs from its default. A chord another binding holds is
 * not taken silently: the row says who has it and offers to replace, and a
 * chord held by a fixed binding or kept by the browser is refused with the
 * reason, while the panel keeps listening for another. Changes apply at once;
 * the shell saves them, so the panel has no Save.
 *
 * It loads on first use (lazy.ts): a widget whose user never presses `?`
 * never fetches it. `openShortcutsPanel` in keymap.ts is the door, and the
 * capture, which has to see a key before the dialog's own Escape does, lives
 * next to the only control that needs it.
 */
import { eventToCombo } from 'openalgo-charts';
import { chromeIconSvg } from 'openalgo-charts/draw';
import { h, type WidgetContext } from './context';
import { widgetText } from './localization';
import { eventKeyCombo, type KeyChordUse, type KeyEventLike, type KeyRebindResult, type KeymapRow } from './keymap';
import { addWidgetStyles } from './styles';

/** What the panel waits on: a chord to be pressed, or a choice about one another binding holds. */
type Pending =
  | { kind: 'capture'; command: string }
  | { kind: 'conflict'; command: string; combo: string; chord: string; holders: readonly KeyChordUse[]; reset: boolean };

/** Keys that name no character a chord could be read back as. */
const UNREADABLE = /(^|\+)(Dead|Process|Compose)$/;

/** A list of names in the reader's language, where the runtime can join one. */
function joinNames(names: readonly string[], locale: string | undefined): string {
  const LF = (Intl as unknown as { ListFormat?: new (l?: string, o?: { type: string }) => { format(v: readonly string[]): string } }).ListFormat;
  if (LF === undefined) return names.join(', ');
  try { return new LF(locale, { type: 'conjunction' }).format(names); } catch { return names.join(', '); }
}

/**
 * The shortcuts panel: every group from `keymap.describe()`, two columns,
 * closed by Escape or its button, with the editing controls when `edit`.
 * Returns the closer.
 */
export function mountShortcutsPanel(ctx: WidgetContext, edit: boolean): () => void {
  const doc = ctx.document;
  const km = ctx.keymap;
  addWidgetStyles(doc, KEYMAP_EDITOR_CSS);
  const el = h(doc, 'div', 'oac-keys-dialog', { 'aria-label': widgetText(ctx, 'Keyboard shortcuts') });
  const head = h(doc, 'div', 'oac-dialog__head');
  const title = h(doc, 'div', 'oac-dialog__title');
  title.textContent = widgetText(ctx, 'Keyboard shortcuts');
  const x = h(doc, 'button', 'oac-btn oac-btn--icon', { type: 'button', 'aria-label': widgetText(ctx, 'Close') });
  x.innerHTML = chromeIconSvg('close');
  head.appendChild(title);
  head.appendChild(x);
  const body = h(doc, 'div', 'oac-dialog__body');
  const cols = h(doc, 'div', 'oac-keys');
  const note = h(doc, 'div', 'oac-keys__note');
  body.appendChild(cols);
  body.appendChild(note);
  el.appendChild(head);
  el.appendChild(body);

  // The footer carries Reset all, the live message and the closing action.
  const foot = h(doc, 'div', 'oac-dialog__foot');
  const resetAll = h(doc, 'button', 'oac-btn oac-keys__reset-all', { type: 'button' });
  const status = h(doc, 'div', 'oac-keys__status', { role: 'status', 'aria-live': 'polite' });
  const confirmNo = h(doc, 'button', 'oac-btn', { type: 'button' });
  const confirmYes = h(doc, 'button', 'oac-btn oac-btn--primary', { type: 'button' });
  const done = h(doc, 'button', 'oac-btn', { type: 'button' });
  confirmNo.textContent = widgetText(ctx, 'Cancel');
  confirmYes.textContent = widgetText(ctx, 'Reset all');
  done.textContent = widgetText(ctx, 'Close');
  if (edit) {
    for (const part of [resetAll, status, confirmNo, confirmYes, done]) foot.appendChild(part);
    el.appendChild(foot);
  }

  let pending: Pending | null = null;
  let confirming = false;
  /** Set while the panel itself changes the keymap. */
  let own = false;
  let release: (() => void) | null = null;
  let message = '';
  /** Translated labels by command, for naming the holders of a chord. */
  const names = new Map<string, string>();
  /** The controls of the rows just drawn, so focus can find its way back after a redraw. */
  const controls = new Map<string, { change?: HTMLButtonElement; reset?: HTMLButtonElement; replace?: HTMLButtonElement }>();

  const nameOf = (u: KeyChordUse): string => (u.command !== null ? names.get(u.command) : undefined) ?? u.label;
  const say = (text: string): void => { message = text; status.textContent = text; };
  const stopCapture = (): void => {
    release?.();
    release = null;
    if (pending?.kind === 'capture') pending = null;
  };

  const rowLabel = (group: string, r: KeymapRow): string =>
    widgetText(ctx, `schema.shortcuts.${group}.${r.defaultCombo ?? r.combo}`, {}, r.label);

  const draw = (focus?: { command: string; part: 'change' | 'reset' | 'replace' }): void => {
    cols.textContent = '';
    controls.clear();
    names.clear();
    let shadowed = 0;
    const groups = km.describe();
    for (const g of groups) for (const r of g.rows) if (r.command !== undefined) names.set(r.command, rowLabel(g.group, r));
    for (const g of groups) {
      const box = h(doc, 'div', 'oac-keys__group');
      const gh = h(doc, 'div', 'oac-head');
      // The widget's own group keeps its id for hosts that register into it; a reader sees General.
      gh.textContent = widgetText(ctx, `schema.shortcuts.group.${g.group}`, {}, g.group === 'Widget' ? 'General' : g.group);
      box.appendChild(gh);
      for (const r of g.rows) {
        const name = rowLabel(g.group, r);
        const row = h(doc, 'div', 'oac-keys__row');
        const label = h(doc, 'span');
        label.textContent = name;
        const kbd = h(doc, 'kbd');
        const listening = pending?.kind === 'capture' && pending.command === r.command;
        kbd.textContent = listening ? widgetText(ctx, 'Press keys') : r.display !== '' ? r.display : widgetText(ctx, 'Not set');
        kbd.classList.toggle('is-empty', !listening && r.display === '');
        row.appendChild(label);
        row.appendChild(kbd);
        if (r.shadowedBy !== undefined) {
          row.classList.add('is-shadowed');
          row.title = widgetText(ctx, 'Claimed by {name}', { name: r.shadowedBy });
          shadowed++;
        }
        const command = r.command;
        if (command !== undefined) {
          row.dataset.command = command;
          row.classList.toggle('is-changed', r.changed === true);
        }
        row.classList.toggle('is-listening', listening);
        box.appendChild(row);
        if (!edit) continue;
        // Every row keeps the same action column, so the chords line up
        // whether or not a row can change.
        const acts = h(doc, 'div', 'oac-keys__acts');
        row.appendChild(acts);
        if (command === undefined || r.rebindable !== true) continue;
        const change = h(doc, 'button', 'oac-btn oac-keys__change', { type: 'button' });
        change.textContent = listening ? widgetText(ctx, 'Cancel') : widgetText(ctx, 'Change');
        change.setAttribute('aria-label', listening ? widgetText(ctx, 'Cancel changing {name}', { name }) : widgetText(ctx, 'Change {name}', { name }));
        change.addEventListener('click', () => {
          if (listening) { stopCapture(); say(''); draw({ command, part: 'change' }); } else capture(command);
        });
        const reset = h(doc, 'button', 'oac-btn oac-keys__reset', { type: 'button' });
        reset.textContent = widgetText(ctx, 'Reset');
        const back = r.defaultCombo === undefined || r.defaultCombo === '' ? widgetText(ctx, 'Not set') : km.format(r.defaultCombo);
        reset.setAttribute('aria-label', widgetText(ctx, 'Reset {name} to {chord}', { name, chord: back }));
        // Kept in the row so the chords line up; hidden from pointer, focus
        // and reader alike while there is nothing to reset.
        reset.disabled = r.changed !== true;
        reset.classList.toggle('is-idle', r.changed !== true);
        reset.addEventListener('click', () => { attempt(command, null, back, true, false); });
        acts.appendChild(change);
        acts.appendChild(reset);
        controls.set(command, { change, reset });
        if (pending?.kind === 'conflict' && pending.command === command) box.appendChild(conflictNotice(pending));
      }
      cols.appendChild(box);
    }
    note.textContent = shadowed === 0 ? '' : widgetText(ctx, shadowed === 1
      ? '{count} chart shortcut struck through: another shortcut uses the same chord here and takes precedence.'
      : '{count} chart shortcuts struck through: another shortcut uses the same chord here and takes precedence.', { count: shadowed });
    note.hidden = shadowed === 0;
    drawFoot();
    if (focus !== undefined) {
      // A Reset with nothing left to reset cannot hold the focus; its row's Change can.
      const c = controls.get(focus.command);
      const want = c?.[focus.part];
      (want !== undefined && !want.disabled ? want : c?.change)?.focus();
    }
  };

  const conflictNotice = (p: Extract<Pending, { kind: 'conflict' }>): HTMLElement => {
    const box = h(doc, 'div', 'oac-keys__conflict', { role: 'group' });
    const text = h(doc, 'span');
    text.textContent = widgetText(ctx, '{chord} is used by {names}.', { chord: p.chord, names: joinNames(p.holders.map(nameOf), ctx.locale) });
    const cancel = h(doc, 'button', 'oac-btn', { type: 'button' });
    cancel.textContent = widgetText(ctx, 'Cancel');
    const replace = h(doc, 'button', 'oac-btn oac-btn--primary', { type: 'button' });
    replace.textContent = widgetText(ctx, 'Replace');
    box.setAttribute('aria-label', text.textContent);
    cancel.addEventListener('click', () => { pending = null; say(''); draw({ command: p.command, part: 'change' }); });
    replace.addEventListener('click', () => { attempt(p.command, p.combo, p.chord, p.reset, true); });
    box.appendChild(text);
    box.appendChild(cancel);
    box.appendChild(replace);
    const row = controls.get(p.command);
    if (row !== undefined) row.replace = replace;
    return box;
  };

  const drawFoot = (): void => {
    const changed = Object.keys(km.overrides()).length > 0;
    resetAll.textContent = widgetText(ctx, 'Reset all');
    resetAll.disabled = !changed;
    resetAll.hidden = confirming;
    confirmNo.hidden = !confirming;
    confirmYes.hidden = !confirming;
    done.hidden = confirming;
    status.textContent = confirming ? widgetText(ctx, 'Put every shortcut back to its default?') : message;
  };

  /**
   * Run a rebind or a reset and draw what came of it; a chord another
   * rebindable binding holds becomes a choice on the row.
   */
  const attempt = (command: string, combo: string | null, chord: string, reset: boolean, replace: boolean): void => {
    own = true;
    let r: KeyRebindResult;
    try { r = reset ? km.reset(command, { replace }) : km.rebind(command, combo, { replace }); } finally { own = false; }
    const holders = joinNames(r.conflicts.map(nameOf), ctx.locale);
    if (r.ok) {
      stopCapture();
      pending = null;
      const name = names.get(command) ?? command;
      say((reset ? widgetText(ctx, '{name} is back to {chord}.', { name, chord }) : widgetText(ctx, '{name} is now {chord}.', { name, chord }))
        + (r.conflicts.length > 0 ? ' ' + widgetText(ctx, 'Taken from {names}.', { names: holders }) : ''));
      draw({ command, part: 'change' });
    } else if (r.reason === 'taken' && r.conflicts.every((u) => u.rebindable)) {
      stopCapture();
      pending = { kind: 'conflict', command, combo: combo ?? '', chord, holders: r.conflicts, reset };
      // The notice on the row says it, and names the group the focus lands in.
      say('');
      draw({ command, part: 'replace' });
    } else if (r.reason === 'taken') {
      const fixed = r.conflicts.filter((u) => !u.rebindable).map(nameOf);
      say(widgetText(ctx, '{chord} belongs to {names}, which cannot change. Press another.', { chord, names: joinNames(fixed, ctx.locale) }));
    } else if (r.reason === 'reserved') {
      say(widgetText(ctx, '{chord} belongs to the browser. Press another.', { chord }));
    } else {
      say(widgetText(ctx, 'That key cannot be used here. Press another.'));
    }
  };

  const onKey = (command: string) => (e: KeyEventLike): boolean | void => {
    const mods = e.ctrlKey === true || e.metaKey === true || e.altKey === true || e.shiftKey === true;
    if (e.key === 'Tab') {
      // Leaving the row by keyboard ends the recording. The focus goes back to
      // the row first, so the Tab itself moves on from there.
      stopCapture();
      say('');
      draw({ command, part: 'change' });
      return false;
    }
    if (e.key === 'Escape' && !mods) {
      stopCapture();
      say(widgetText(ctx, 'Nothing changed.'));
      draw({ command, part: 'change' });
      return;
    }
    const combo = eventKeyCombo(e);
    // A modifier on its own is the start of a chord, not one.
    if (combo === '') return;
    if (UNREADABLE.test(combo)) { say(widgetText(ctx, 'That key cannot be used here. Press another.')); return; }
    const chord = km.format(combo);
    // Letters and digits alone start typing a symbol or an interval on the
    // chart, and Space alone presses the focused button: a binding there
    // would run in place of every control in the widget.
    const mod = km.isMac ? 'Cmd' : 'Ctrl';
    const alt = km.isMac ? 'Opt' : 'Alt';
    if (/^(Shift\+)?[a-z0-9]$/.test(combo)) { say(widgetText(ctx, '{chord} types into the chart. Add {mod} or {alt}.', { chord, mod, alt })); return; }
    if (/^(Shift\+)?Space$/.test(combo)) { say(widgetText(ctx, '{chord} presses the focused control. Add {mod} or {alt}.', { chord, mod, alt })); return; }
    const chart = command.startsWith('chart:');
    // The row shows the chord in this keymap's grammar, which folds Control
    // and Cmd into Mod; the engine keeps them apart on macOS (and Windows
    // keeps Meta), so fold them here too or Control+G is stored and Cmd+G shown.
    const held = e.ctrlKey || e.metaKey;
    const code = chart ? eventToCombo({ code: e.code, key: e.key, altKey: e.altKey, shiftKey: e.shiftKey, ctrlKey: !km.isMac && held, metaKey: km.isMac && held }, km.isMac) : '';
    if (chart && code === '') { say(widgetText(ctx, 'That key cannot be used here. Press another.')); return; }
    attempt(command, chart ? code : combo, chord, false, false);
  };

  const capture = (command: string): void => {
    stopCapture();
    confirming = false;
    pending = { kind: 'capture', command };
    release = km.capture(onKey(command));
    say(widgetText(ctx, 'Press the new shortcut for {name}. Esc cancels.', { name: names.get(command) ?? command }));
    draw({ command, part: 'change' });
  };

  resetAll.addEventListener('click', () => {
    stopCapture();
    pending = null;
    confirming = true;
    draw();
    confirmNo.focus();
  });
  confirmNo.addEventListener('click', () => { confirming = false; drawFoot(); resetAll.focus(); });
  confirmYes.addEventListener('click', () => {
    confirming = false;
    own = true;
    try { km.resetAll(); } finally { own = false; }
    say(widgetText(ctx, 'Every shortcut is back to its default.'));
    draw();
    done.focus();
  });

  // A change made elsewhere (another chart in a grid, the host) redraws the
  // rows; the panel's own changes redraw with the focus placed, so they skip
  // it. The redraw replaces the focused control, so the focus follows it to
  // the new one rather than dropping out of the dialog.
  const focused = (): { command: string; part: 'change' | 'reset' | 'replace' } | undefined => {
    const at = doc.activeElement;
    for (const [command, c] of controls) {
      for (const part of ['change', 'reset', 'replace'] as const) if (c[part] !== undefined && c[part] === at) return { command, part };
    }
    return undefined;
  };
  const offChange = km.onChange(() => { if (!own) draw(focused()); });

  draw();
  const close = ctx.openOverlay(el, {
    placement: 'center',
    dismissOnOutside: true,
    // The first control is a Change halfway down the list, and focusing it
    // would scroll the first groups out of sight: the panel itself takes the
    // focus, so it opens at the top and a reader hears its name, and Tab
    // walks the controls from there.
    initialFocus: edit ? el : undefined,
    onClose: () => { stopCapture(); offChange(); },
  });
  x.addEventListener('click', close);
  done.addEventListener('click', close);
  return close;
}

/** The editor's rules, added to the widget sheet when the panel first opens. */
const KEYMAP_EDITOR_CSS: string = `
.oac-widget .oac-keys-dialog { width: 880px; }
.oac-widget .oac-keys { columns: 2; column-gap: 28px; min-width: 0; }
.oac-widget .oac-keys__group { margin-bottom: 0; padding-bottom: 8px; }
.oac-widget .oac-keys__row { min-height: 30px; padding: 2px 0; }
.oac-widget .oac-keys__row > kbd { min-width: 44px; text-align: center; }
.oac-widget .oac-keys__row.is-changed > kbd { color: var(--oac-acc-2); border-color: var(--oac-on-bd); background: var(--oac-on-bg); }
.oac-widget .oac-keys__row > kbd.is-empty { border-style: dashed; font-family: inherit; }
.oac-widget .oac-keys__row:not(.is-changed) > kbd.is-empty { background: transparent; color: var(--oac-faint); }
.oac-widget .oac-keys__acts { flex: none; display: flex; align-items: center; gap: 2px; min-width: 118px; }
.oac-widget .oac-keys__row.is-listening > kbd { color: var(--oac-acc-2); border-color: var(--oac-acc); border-style: solid; font-family: inherit; }
.oac-widget .oac-keys__change, .oac-widget .oac-keys__reset { flex: none; height: 24px; padding: 0 8px; font-size: 11.5px; color: var(--oac-mut); }
.oac-widget .oac-keys__change:hover, .oac-widget .oac-keys__reset:hover { color: var(--oac-tx); }
.oac-widget .oac-keys__row.is-listening .oac-keys__change { color: var(--oac-acc-2); border-color: var(--oac-on-bd); }
.oac-widget .oac-keys__reset.is-idle { visibility: hidden; }
.oac-widget .oac-keys__conflict { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 2px 0 6px; padding: 6px 8px;
  border: 1px solid var(--oac-bd-soft); border-left: 3px solid var(--oac-amber); border-radius: 6px; background: var(--oac-elev); break-inside: avoid; }
.oac-widget .oac-keys__conflict > span { flex: 1 1 180px; min-width: 0; color: var(--oac-tx); font-size: 12px; overflow-wrap: anywhere; }
.oac-widget .oac-keys__conflict > .oac-btn { height: 24px; font-size: 11.5px; }
.oac-widget .oac-keys__status { flex: 1 1 200px; min-width: 0; color: var(--oac-mut); font-size: 12px; overflow-wrap: anywhere; }
.oac-widget .oac-keys__note:empty { display: none; }
@container oac-widget (max-width: 920px) {
  .oac-widget .oac-keys { columns: 1; }
}
`;
