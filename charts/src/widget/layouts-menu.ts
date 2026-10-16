/**
 * The Layouts menu: the saved layouts a `LayoutsController` holds, in a panel
 * under the top bar's Layouts button, or centred on a phone. It saves, saves
 * under a new name, renames and deletes the held layout, opens a recent one,
 * turns autosave on and off with what autosave is doing, and settles a layout
 * another window changed. It holds no layout state itself: every paint reads
 * the controller, so two menus on one controller never disagree.
 *
 * Three decisions worth recording:
 *
 * - **Nothing unsaved is dropped without asking.** Before opening another
 *   layout the menu flushes the controller, since a change is judged only
 *   once changes settle, and asks when the held layout still differs from
 *   the chart: save it first, open without saving, or stay.
 * - **A conflict is the user's call.** When another window changed the held
 *   layout, the menu says so and offers the three ways out the controller
 *   has: read the list again, keep this chart as a copy, or overwrite.
 * - **Rename and Delete act on the held layout.** A row opens its layout; the
 *   actions name the one the chart shows, so no row carries a destructive
 *   control a stray tap could reach.
 *
 * It loads on first use (lazy.ts): `openLayoutsMenu` in layouts-widget.ts is
 * the door, and the status sentence the top bar shares lives there too.
 */
import type { WorkspaceDocument } from 'openalgo-charts/workspace';
import type { WidgetContext } from './context';
import { button, dialogFrame, el, openPanel, type PanelHandle } from './form';
import { errorText, widgetText } from './localization';
import type { LayoutsController, LayoutsState } from './layouts';
import { layoutStatusText, layoutText } from './layouts-widget';
import { addWidgetStyles } from './styles';

/** Most recent layouts listed first, as the catalog keeps them. */
const RECENT_LAYOUTS = 10;

type Action = 'save' | 'open' | 'rename' | 'delete' | 'reload' | 'overwrite' | 'autosave';

/** What a failed operation says, by what the user asked for. */
const FAILURES: Readonly<Record<Action, string>> = {
  save: 'The layout could not be saved: {error}',
  open: 'The layout could not be opened: {error}',
  rename: 'The layout could not be renamed: {error}',
  delete: 'The layout could not be deleted: {error}',
  reload: 'The saved layouts could not be read: {error}',
  overwrite: 'The layout could not be overwritten: {error}',
  autosave: 'Autosave could not be changed: {error}',
};

let sequence = 0;

const nameOf = (state: LayoutsState): string | null =>
  state.layoutId === null ? null : state.catalog?.workspaces.find(doc => doc.id === state.layoutId)?.name ?? null;

/**
 * When a layout was last saved, on the chart's clock: the time alone for
 * today, the date as well before that.
 */
function savedAtText(ctx: WidgetContext, at: number, now = Date.now()): string {
  const zone = ctx.chart.timezone();
  const day = (t: number): string => new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(t);
  const options: Intl.DateTimeFormatOptions = day(at) === day(now)
    ? { timeZone: zone, hour: '2-digit', minute: '2-digit' }
    : { timeZone: zone, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' };
  try { return new Intl.DateTimeFormat(ctx.locale, options).format(at); } catch { return new Intl.DateTimeFormat('en-US', options).format(at); }
}

type FormMode = 'save-as' | 'rename' | 'copy';

/**
 * Open the Layouts menu for `controller`: under `anchor`, or centred as a
 * dialog without one and on a phone layout. Returns its handle.
 */
export function mountLayoutsMenu(ctx: WidgetContext, controller: LayoutsController, anchor?: HTMLElement): PanelHandle {
  const doc = ctx.document;
  addWidgetStyles(doc, LAYOUTS_MENU_CSS);
  const text = layoutText(ctx);
  const title = text('title', 'Layouts');
  const frame = dialogFrame(doc, { translate: ctx.translate, title, className: 'oac-layouts', onClose: () => handle.close() });

  // ── the held layout ──────────────────────────────────────────────────
  const current = el(doc, 'div', 'oac-layouts__current');
  const heading = el(doc, 'div', 'oac-layouts__heading');
  const name = el(doc, 'strong', 'oac-layouts__name');
  const tools = el(doc, 'div', 'oac-layouts__tools');
  const rename = button(doc, { label: text('rename', 'Rename'), icon: 'rename', onClick: () => showForm('rename', rename) });
  rename.dataset.action = 'rename';
  const remove = button(doc, { label: text('delete', 'Delete'), icon: 'trash', onClick: () => askDelete() });
  remove.dataset.action = 'delete';
  remove.classList.add('oac-btn--danger');
  tools.append(rename, remove);
  heading.append(name, tools);
  const line = el(doc, 'div', 'oac-layouts__line');
  line.setAttribute('role', 'status');
  line.setAttribute('aria-live', 'polite');
  current.append(heading, line);

  // ── a name, for save as, rename and a copy ───────────────────────────
  const form = el(doc, 'form', 'oac-layouts__form');
  form.hidden = true;
  const formLabel = el(doc, 'label', 'oac-layouts__label');
  const input = el(doc, 'input', 'oac-layouts__input');
  input.type = 'text';
  input.maxLength = 120;
  input.autocomplete = 'off';
  input.id = `oac-layouts-name-${++sequence}`;
  formLabel.htmlFor = input.id;
  const formError = el(doc, 'p', 'oac-input-error');
  formError.setAttribute('role', 'alert');
  formError.hidden = true;
  const formRow = el(doc, 'div', 'oac-layouts__row-controls');
  const cancelForm = button(doc, { label: widgetText(ctx, 'Cancel'), onClick: () => hideForms() });
  const submitForm = button(doc, { label: widgetText(ctx, 'Save'), variant: 'primary', onClick: () => { void submit(); } });
  cancelForm.dataset.action = 'cancel-name';
  submitForm.dataset.action = 'submit-name';
  formRow.append(input, cancelForm, submitForm);
  form.append(formLabel, formRow, formError);

  // ── a question: delete, or open over unsaved changes ─────────────────
  const confirm = el(doc, 'div', 'oac-layouts__confirm');
  confirm.hidden = true;
  confirm.setAttribute('role', 'alertdialog');
  const confirmText = el(doc, 'p', 'oac-layouts__confirm-text');
  confirmText.id = `oac-layouts-confirm-${sequence}`;
  confirm.setAttribute('aria-describedby', confirmText.id);
  const confirmActions = el(doc, 'div', 'oac-layouts__row-controls');
  confirm.append(confirmText, confirmActions);

  // ── another window changed the held layout ───────────────────────────
  const conflict = el(doc, 'div', 'oac-layouts__conflict');
  conflict.hidden = true;
  conflict.setAttribute('role', 'alert');
  const conflictText = el(doc, 'p', 'oac-layouts__conflict-text');
  const conflictActions = el(doc, 'div', 'oac-layouts__row-controls');
  const reloadList = button(doc, { label: text('reload', 'Reload list'), icon: 'refresh', onClick: () => { void run('reload', () => controller.reload()); } });
  reloadList.dataset.action = 'reload';
  const saveCopy = button(doc, { label: text('copy', 'Save as a copy'), onClick: () => showForm('copy', saveCopy) });
  saveCopy.dataset.action = 'copy';
  const overwrite = button(doc, { label: text('overwrite', 'Overwrite'), variant: 'danger', onClick: () => { void run('overwrite', () => controller.overwrite()); } });
  overwrite.dataset.action = 'overwrite';
  conflictActions.append(reloadList, saveCopy, overwrite);
  conflict.append(conflictText, conflictActions);

  const error = el(doc, 'p', 'oac-layouts__error');
  error.setAttribute('role', 'alert');
  error.hidden = true;

  // ── the lists ────────────────────────────────────────────────────────
  const lists = el(doc, 'div', 'oac-layouts__lists');
  frame.body.append(current, form, confirm, conflict, error, lists);

  // ── the footer: autosave on the left, saving on the right ────────────
  const autosave = el(doc, 'button', 'oac-layouts__switch');
  autosave.type = 'button';
  autosave.setAttribute('role', 'switch');
  autosave.dataset.action = 'autosave';
  const autosaveLabel = el(doc, 'span', 'oac-layouts__switch-label', text('autosave', 'Autosave'));
  const autosaveValue = el(doc, 'span', 'oac-layouts__switch-value');
  autosave.append(el(doc, 'span', 'oac-layouts__track'), autosaveLabel, autosaveValue);
  autosave.addEventListener('click', () => {
    if (autosave.getAttribute('aria-disabled') === 'true') return;
    const on = controller.state().catalog?.autosave === true;
    void run('autosave', () => controller.setAutosave(!on));
  });
  const autosaveState = el(doc, 'span', 'oac-layouts__autosave-state');
  autosaveState.setAttribute('aria-live', 'polite');
  frame.lead.append(autosave, autosaveState);
  const saveAs = button(doc, { label: text('saveAs', 'Save as...'), icon: 'save-as', onClick: () => showForm('save-as', saveAs) });
  saveAs.dataset.action = 'save-as';
  const save = button(doc, { label: widgetText(ctx, 'Save'), variant: 'primary', onClick: () => {
    if (save.getAttribute('aria-disabled') === 'true') return;
    // Nothing held yet: Save names the chart first, as Save as does.
    if (controller.state().layoutId === null) showForm('save-as', save);
    else void run('save', () => controller.save());
  } });
  save.dataset.action = 'save';
  frame.actions.append(saveAs, save);

  let formMode: FormMode | null = null;
  let closed = false;
  /** The last failed operation's message, until another operation starts. */
  let failure: string | null = null;
  /** The control a form or a question came from, read when it closes: a row is painted afresh. */
  let back: (() => HTMLElement | null) | null = null;

  const setOff = (b: HTMLElement, off: boolean, why?: string): void => {
    b.setAttribute('aria-disabled', String(off));
    if (off && why !== undefined) b.title = why; else b.removeAttribute('title');
  };
  const reason = (thrown: unknown): string => errorText(ctx, thrown);
  const rowFor = (id: string): HTMLElement | null =>
    Array.from(lists.querySelectorAll<HTMLElement>('.oac-layouts__row')).find(b => b.dataset.layoutId === id) ?? null;
  /**
   * Show or hide a part of the menu, and say whether the focus was in it as it
   * hid. A hidden control keeps the focus in one engine and drops it to the
   * page in another; either way a keyboard user is lost, so the caller moves it.
   */
  const reveal = (part: HTMLElement, shown: boolean): boolean => {
    const had = !shown && !part.hidden && part.contains(doc.activeElement);
    part.hidden = !shown;
    return had;
  };
  /** Focus where the closed form or question came from, else Save. */
  const refocus = (): void => {
    if (closed) return;
    const target = back?.() ?? null;
    (target !== null && !(conflict.hidden && conflict.contains(target)) ? target : save).focus();
  };

  /** Run one controller operation from a control, reporting a failure in the panel. */
  async function run(what: Action, task: () => Promise<unknown>): Promise<boolean> {
    failure = null;
    try {
      await task();
      return true;
    } catch (thrown) {
      failure = text(`failed.${what}`, FAILURES[what], { error: reason(thrown) });
      return false;
    } finally { paint(); }
  }

  function hideForms(): void {
    formMode = null;
    const lost = [reveal(form, false), reveal(confirm, false)].includes(true);
    formError.hidden = true;
    input.removeAttribute('aria-invalid');
    paint();
    if (lost) refocus();
    back = null;
  }

  function showForm(mode: FormMode, from: HTMLElement): void {
    const state = controller.state();
    if (state.busy) return;
    if (mode === 'rename' && state.layoutId === null) return;
    hideForms();
    formMode = mode;
    back = () => from;
    const held = nameOf(state);
    const where = ctx.symbol();
    formLabel.textContent = mode === 'rename' ? text('renameLabel', 'New name for {name}', { name: held ?? '' })
      : mode === 'copy' ? text('copyLabel', 'Name for the copy') : text('nameLabel', 'Layout name');
    input.value = mode === 'rename' ? held ?? ''
      : mode === 'copy' ? text('copyName', '{name} copy', { name: held ?? title })
        : [where.symbol, ctx.interval()].filter(part => part !== '').join(' ');
    submitForm.textContent = mode === 'rename' ? text('renameSubmit', 'Rename') : widgetText(ctx, 'Save');
    form.hidden = false;
    input.focus();
    input.select();
  }

  async function submit(): Promise<void> {
    const mode = formMode;
    const value = input.value.trim();
    if (mode === null || controller.state().busy) return;
    if (value === '') {
      formError.textContent = widgetText(ctx, 'Enter a name');
      formError.hidden = false;
      input.setAttribute('aria-invalid', 'true');
      input.focus();
      return;
    }
    const id = controller.state().layoutId;
    const done = await run(mode === 'rename' ? 'rename' : 'save', () => mode === 'rename' && id !== null
      ? controller.rename(id, value) : controller.saveAs(value));
    if (done && !closed) {
      back = () => save;
      hideForms();
    }
  }

  function ask(words: string, choices: Array<{ label: string; action: string; variant?: 'primary' | 'danger'; run: () => void }>,
    from: () => HTMLElement | null): void {
    hideForms();
    back = from;
    confirmText.textContent = words;
    confirmActions.textContent = '';
    for (const choice of choices) {
      const b = button(doc, { label: choice.label, variant: choice.variant, onClick: choice.run });
      b.dataset.action = choice.action;
      confirmActions.appendChild(b);
    }
    confirm.hidden = false;
    (confirmActions.querySelector('button') as HTMLButtonElement | null)?.focus();
  }

  function askDelete(): void {
    const state = controller.state();
    const id = state.layoutId;
    if (id === null || state.busy) return;
    ask(text('deleteQuestion', 'Delete {name}? The chart stays as it is.', { name: nameOf(state) ?? '' }), [
      { label: widgetText(ctx, 'Cancel'), action: 'keep', run: () => hideForms() },
      { label: text('delete', 'Delete'), action: 'confirm-delete', variant: 'danger', run: () => {
        back = () => save;
        hideForms();
        void run('delete', () => controller.remove(id)).then(() => { if (!closed) save.focus(); });
      } },
    ], () => remove);
  }

  /**
   * Open a layout, asking first when the held one has changes that would be
   * lost. The controller is flushed first: a change is judged only once
   * changes settle, and an autosave due now is written before anything is
   * asked.
   */
  async function openLayout(id: string): Promise<void> {
    if (controller.state().busy || controller.state().suspended) return;
    failure = null;
    // A failed autosave shows on the status line; the question below covers the change it left.
    await controller.flush();
    if (closed) return;
    const state = controller.state();
    if (state.layoutId !== null && state.dirty) {
      const held = nameOf(state) ?? '';
      const choices: Array<{ label: string; action: string; variant?: 'primary' | 'danger'; run: () => void }> = [
        { label: widgetText(ctx, 'Cancel'), action: 'stay', run: () => hideForms() },
        { label: text('discard', 'Open without saving'), action: 'discard', variant: 'danger', run: () => { void go(id); } },
      ];
      // A conflicting layout refuses a save until the user settles it.
      if (!state.conflict) choices.push({ label: text('saveAndOpen', 'Save and open'), action: 'save-and-open', variant: 'primary', run: () => {
        void run('save', () => controller.save()).then(done => { if (done) void go(id); });
      } });
      ask(id === state.layoutId
        ? text('revertQuestion', '{name} has unsaved changes. Open the saved version?', { name: held })
        : text('discardQuestion', '{name} has unsaved changes. Save them before opening {target}?',
          { name: held, target: state.catalog?.workspaces.find(item => item.id === id)?.name ?? '' }), choices, () => rowFor(id));
      return;
    }
    await go(id);
  }

  async function go(id: string): Promise<void> {
    if (reveal(confirm, false)) refocus();
    let applied = false;
    const done = await run('open', async () => {
      const report = await controller.open(id);
      applied = report.applied;
      if (!report.applied) throw new Error(report.reason ?? text('notShown', 'the layout cannot show here'));
    });
    if (done && applied) handle.close();
  }

  // ── painting ─────────────────────────────────────────────────────────
  function row(layout: WorkspaceDocument, state: LayoutsState, list: HTMLElement): void {
    const b = el(doc, 'button', 'oac-layouts__row');
    b.type = 'button';
    b.dataset.layoutId = layout.id;
    const held = layout.id === state.layoutId;
    if (held) b.setAttribute('aria-current', 'true');
    b.append(el(doc, 'span', 'oac-layouts__row-name', layout.name));
    b.append(el(doc, 'span', 'oac-layouts__row-meta', held ? text('current', 'on the chart') : savedAtText(ctx, layout.updatedAt)));
    setOff(b, state.busy || state.suspended, state.suspended ? text('suspendedOpen', 'Stop the replay to open a layout') : undefined);
    b.addEventListener('click', () => { if (b.getAttribute('aria-disabled') !== 'true') void openLayout(layout.id); });
    const item = el(doc, 'li', 'oac-layouts__item');
    item.appendChild(b);
    list.appendChild(item);
  }

  function section(heading_: string, docs: WorkspaceDocument[], state: LayoutsState, key: string): void {
    if (docs.length === 0) return;
    const head = el(doc, 'div', 'oac-head', heading_);
    head.id = `oac-layouts-${key}-${sequence}`;
    const list = el(doc, 'ul', 'oac-layouts__list');
    list.setAttribute('aria-labelledby', head.id);
    list.dataset.list = key;
    for (const item of docs) row(item, state, list);
    lists.append(head, list);
  }

  function paint(): void {
    if (closed) return;
    const state = controller.state();
    const focused = doc.activeElement as HTMLElement | null;
    const focusId = focused?.dataset.layoutId;
    const held = nameOf(state);
    name.textContent = held ?? text('none', 'No layout open');
    name.classList.toggle('is-none', held === null);
    // The autosave switch says what autosave is doing; this line says where the layout stands.
    const doc_ = state.catalog?.workspaces.find(item => item.id === state.layoutId);
    line.textContent = doc_ !== undefined && !state.conflict && !state.dirty && state.autosave !== 'failed' && state.autosave !== 'saving'
      ? text('savedAt', 'Saved {time}', { time: savedAtText(ctx, doc_.updatedAt) }) : layoutStatusText(ctx, state);
    line.dataset.state = state.conflict ? 'conflict' : state.autosave === 'failed' ? 'failed' : state.dirty ? 'dirty' : 'clean';
    setOff(rename, state.layoutId === null || state.busy);
    setOff(remove, state.layoutId === null || state.busy);
    setOff(save, state.busy || state.conflict || (state.layoutId !== null && !state.dirty && state.autosave !== 'failed'),
      state.conflict ? text('conflictSave', 'Choose how to settle the change from the other window') : undefined);
    setOff(saveAs, state.busy);
    const on = state.catalog?.autosave === true;
    autosave.setAttribute('aria-checked', String(on));
    autosaveValue.textContent = on ? text('on', 'On') : text('off', 'Off');
    setOff(autosave, state.busy || state.catalog === null);
    autosaveState.textContent = on && state.layoutId !== null && !state.conflict ? layoutStatusText(ctx, state) : '';
    autosaveState.dataset.state = state.autosave;
    // Settled (an overwrite, a copy, a reload that found the layout as it was): the focus stays in the menu.
    if (reveal(conflict, state.conflict)) save.focus();
    conflictText.textContent = text('conflictText', '{name} was changed in another window. This chart is not saved over it.', { name: held ?? '' });
    for (const b of [reloadList, saveCopy, overwrite]) setOff(b, state.busy);
    // An operation's own failure first; else why autosave stopped, which no control reported.
    const shown = failure ?? (state.autosave === 'failed' && state.error !== null && !state.conflict
      ? text('failed.autosaveWrite', 'Autosave could not save the layout: {error}', { error: reason(state.error) }) : null);
    error.hidden = shown === null;
    error.textContent = shown ?? '';
    lists.textContent = '';
    const all = state.catalog?.workspaces ?? [];
    // A read that failed says so on the error line; the list does not go on saying it is loading.
    if (state.catalog === null) { if (state.busy) lists.appendChild(el(doc, 'p', 'oac-empty', text('loading', 'Loading layouts'))); }
    else if (all.length === 0) lists.appendChild(el(doc, 'p', 'oac-empty', text('empty', 'No saved layouts yet. Save this chart to start one.')));
    const recent = (state.catalog?.recentWorkspaceIds ?? []).slice(0, RECENT_LAYOUTS)
      .map(id => all.find(item => item.id === id)).filter((item): item is WorkspaceDocument => item !== undefined);
    const others = all.filter(item => !recent.includes(item)).sort((a, b) => a.name.localeCompare(b.name));
    section(text('recent', 'Recent'), recent, state, 'recent');
    section(recent.length > 0 ? text('others', 'Other layouts') : text('all', 'Layouts'), others, state, 'others');
    if (focusId !== undefined) {
      (Array.from(lists.querySelectorAll<HTMLElement>('.oac-layouts__row')).find(b => b.dataset.layoutId === focusId))?.focus();
    }
  }

  // Arrow keys walk the rows, as in any list of choices.
  lists.addEventListener('keydown', event => {
    const key = (event as KeyboardEvent).key;
    if (key !== 'ArrowDown' && key !== 'ArrowUp') return;
    const rows = Array.from(lists.querySelectorAll<HTMLElement>('.oac-layouts__row'));
    const at = rows.indexOf(doc.activeElement as HTMLElement);
    if (rows.length === 0) return;
    event.preventDefault();
    rows[(at + (key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length]!.focus(); // wrapped into a non-empty list
  });
  form.addEventListener('submit', event => { event.preventDefault(); void submit(); });
  input.addEventListener('input', () => { formError.hidden = true; input.removeAttribute('aria-invalid'); });

  const offState = controller.subscribe(() => paint());
  paint();
  const phone = ctx.root.classList.contains('is-mobile');
  const panel = openPanel(ctx, frame.el, anchor === undefined || phone
    ? { placement: 'center', modal: true, initialFocus: save }
    : { anchor, placement: 'below', initialFocus: save }, () => finish());
  function finish(): void {
    if (closed) return;
    closed = true;
    offState();
  }
  const handle: PanelHandle = {
    el: panel.el, isOpen: panel.isOpen,
    close: () => { if (!panel.isOpen()) return; finish(); panel.close(); },
  };
  // The list as another window left it, and the chart compared with its
  // layout now rather than when changes next settle, so Save is enabled
  // exactly when there is something to save. A failed read shows like any other.
  void run('reload', async () => { await controller.reload(); await controller.flush(); });
  return handle;
}

/** The Layouts menu's rules, added to the widget sheet when the menu first opens. */
const LAYOUTS_MENU_CSS = `
.oac-widget .oac-layouts { width: 380px; }
.oac-widget .oac-layouts .oac-dialog__body { display: flex; flex-direction: column; gap: 8px; padding-top: 2px; }
.oac-widget .oac-layouts__current { display: grid; gap: 2px; padding: 8px 10px; border: 1px solid var(--oac-bd-soft); border-radius: 8px; background: var(--oac-elev); }
.oac-widget .oac-layouts__heading { display: flex; align-items: center; gap: 6px; min-width: 0; }
.oac-widget .oac-layouts__name { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--oac-tx-strong); font-size: 13px; }
.oac-widget .oac-layouts__name.is-none { color: var(--oac-mut); font-weight: 500; }
.oac-widget .oac-layouts__tools { display: flex; gap: 2px; flex: none; }
.oac-widget .oac-layouts__tools .oac-btn { height: 24px; padding: 0 6px; font-size: 11.5px; }
.oac-widget .oac-layouts__line { color: var(--oac-mut); font-size: 11px; }
.oac-widget .oac-layouts__line[data-state="dirty"] { color: var(--oac-amber); }
.oac-widget .oac-layouts__line[data-state="failed"], .oac-widget .oac-layouts__line[data-state="conflict"] { color: var(--oac-danger); }
.oac-widget .oac-layouts__form, .oac-widget .oac-layouts__confirm, .oac-widget .oac-layouts__conflict { display: grid; gap: 6px; padding: 8px 10px;
  border: 1px solid var(--oac-bd-soft); border-radius: 8px; }
.oac-widget .oac-layouts__conflict { border-color: var(--oac-danger); }
.oac-widget .oac-layouts__label { color: var(--oac-mut); font-size: 11px; }
.oac-widget .oac-layouts__row-controls { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 6px; min-width: 0; }
.oac-widget .oac-layouts__row-controls .oac-btn:not(.oac-btn--primary) { border-color: var(--oac-bd-soft); }
/* Nothing to save: the primary button steps back rather than show faint text on the accent, and a
   disabled Delete takes no danger colour from a hover or a tap. */
.oac-widget .oac-layouts .oac-btn--primary[aria-disabled="true"] { background: var(--oac-elev); color: var(--oac-faint); }
.oac-widget .oac-layouts .oac-btn[aria-disabled="true"]:hover { color: var(--oac-faint); }
.oac-widget .oac-layouts__input { flex: 1 1 160px; min-width: 0; }
.oac-widget .oac-layouts__confirm-text, .oac-widget .oac-layouts__conflict-text { margin: 0; line-height: 1.45; overflow-wrap: anywhere; }
.oac-widget .oac-layouts__error { margin: 0; color: var(--oac-danger); font-size: 11px; overflow-wrap: anywhere; }
.oac-widget .oac-layouts__lists { display: flex; flex-direction: column; min-height: 0; }
.oac-widget .oac-layouts__lists > .oac-head { padding: 6px 2px 3px; }
.oac-widget .oac-layouts__list { list-style: none; margin: 0; padding: 0; display: grid; gap: 1px; }
.oac-widget .oac-layouts__row { display: flex; align-items: center; gap: 8px; width: 100%; min-height: 30px; padding: 5px 8px; border: 0; border-radius: 6px;
  background: transparent; color: var(--oac-tx); text-align: left; }
.oac-widget .oac-layouts__row:hover, .oac-widget .oac-layouts__row:focus-visible { background: var(--oac-elev-2); outline: none; }
.oac-widget .oac-layouts__row[aria-current="true"] { color: var(--oac-acc-2); box-shadow: inset 2px 0 0 var(--oac-acc); }
.oac-widget .oac-layouts__row[aria-disabled="true"] { color: var(--oac-faint); cursor: default; background: transparent; }
.oac-widget .oac-layouts__row-name { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.oac-widget .oac-layouts__row-meta { flex: none; color: var(--oac-mut); font-size: 11px; }
.oac-widget .oac-layouts__switch { display: inline-flex; align-items: center; gap: 7px; height: var(--oac-ctl-h); padding: 0 8px 0 4px; border: 1px solid transparent;
  border-radius: var(--oac-radius); background: transparent; color: var(--oac-tx); }
.oac-widget .oac-layouts__switch:hover { background: var(--oac-elev); border-color: var(--oac-bd-soft); }
.oac-widget .oac-layouts__switch[aria-disabled="true"] { color: var(--oac-faint); cursor: default; background: transparent; border-color: transparent; }
.oac-widget .oac-layouts__track { position: relative; width: 26px; height: 15px; flex: none; border-radius: 999px; background: var(--oac-elev-3);
  border: 1px solid var(--oac-bd); transition: background .12s, border-color .12s; }
.oac-widget .oac-layouts__track::after { content: ''; position: absolute; top: 2px; left: 2px; width: 9px; height: 9px; border-radius: 50%;
  background: var(--oac-mut); transition: transform .12s, background .12s; }
.oac-widget .oac-layouts__switch[aria-checked="true"] .oac-layouts__track { background: var(--oac-acc); border-color: var(--oac-acc); }
.oac-widget .oac-layouts__switch[aria-checked="true"] .oac-layouts__track::after { transform: translateX(11px); background: var(--oac-bg); }
.oac-widget .oac-layouts__switch-value { color: var(--oac-mut); font-size: 11px; }
.oac-widget .oac-layouts__autosave-state { color: var(--oac-mut); font-size: 11px; }
.oac-widget .oac-layouts__autosave-state[data-state="failed"] { color: var(--oac-danger); }
.oac-widget.is-mobile .oac-layouts { width: 100%; }
.oac-widget.is-mobile .oac-layouts__row { min-height: 44px; }
.oac-widget.is-mobile .oac-layouts .oac-btn, .oac-widget.is-mobile .oac-layouts__switch { min-height: 40px; }
@media (prefers-reduced-motion: reduce) {
  .oac-widget .oac-layouts__track, .oac-widget .oac-layouts__track::after { transition: none; }
}
`;
