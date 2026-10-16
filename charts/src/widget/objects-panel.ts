import { widgetText } from './localization';
import type { Chart, ChartObjects, ChartObjectSnapshot } from 'openalgo-charts';
import type { WidgetContext } from './context';
import { chromeIconSvg } from 'openalgo-charts/draw';
import { button, dialogFrame, el, openPanel, type PanelHandle } from './form';

export interface ObjectsPanelOptions {
  /** Overrides the widget's inventory for a custom host. The caller owns it. */
  objects?: ChartObjects;
  /** Runs once for either programmatic or overlay dismissal. */
  onClose?: () => void;
}

type Action = 'select' | 'visibility' | 'lock' | 'settings' | 'focus' | 'remove';
interface ObjectRow {
  el: HTMLElement;
  summary: HTMLElement;
  name: HTMLElement;
  meta: HTMLElement;
  status: HTMLElement;
  actions: HTMLElement;
  selectable: boolean;
  buttons: Map<string, HTMLButtonElement>;
  move?: HTMLSelectElement | undefined;
  members?: HTMLElement | undefined;
}

const KINDS = { source: 'Source', indicator: 'Indicator', drawing: 'Drawing', profile: 'Profile', group: 'Group' };
const ACTIONS = ['visibility', 'lock', 'settings', 'focus', 'remove'] as const;
const STATUS = { loading: 'Loading', ready: 'Ready', empty: 'No data', unsupported: 'Unsupported', error: 'Could not load' };
const FAILURES = { select: 'Could not select {name}', visibility: 'Could not change visibility for {name}', lock: 'Could not change lock for {name}', settings: 'Could not open settings for {name}', focus: 'Could not focus {name}', remove: 'Could not remove {name}' } as const;

let rowSequence = 0;

/**
 * Names that tell apart objects of one name, by id: the second listed "Trend
 * Line" is "Trend Line (2)", and a name nothing listed repeats carries no
 * number. Objects, the alert editor, study settings and the data export all
 * number through this, over the chart's own order (drawings back to front,
 * studies as the chart lists them), so one object carries one number wherever
 * it is named. Only listed items count, so a host's unlisted object never
 * moves a number a user has seen; one a list shows anyway is numbered after.
 */
export function numberedNames<T extends { readonly id: string }>(items: readonly T[], name: (item: T) => string,
  listed: (item: T) => boolean = () => true): Map<string, string> {
  const count = (some: readonly T[]): Map<string, number> => {
    const out = new Map<string, number>();
    for (const item of some) out.set(name(item), (out.get(name(item)) ?? 0) + 1);
    return out;
  };
  const shown = items.filter(listed), extra = items.filter(item => !listed(item));
  const repeats = count(shown), everywhere = count(items), seen = new Map<string, number>();
  return new Map([...shown, ...extra].map(item => {
    const base = name(item), n = (seen.get(base) ?? 0) + 1;
    seen.set(base, n);
    return [item.id, ((listed(item) ? repeats : everywhere).get(base) ?? 0) > 1 ? `${base} (${n})` : base];
  }));
}

/** The chart's studies named apart, as `numberedNames` says. */
export const studyNames = (chart: Chart): Map<string, string> => numberedNames(chart.indicators(), study => study.name,
  study => study.policy().listed !== false);

export interface ObjectsPanelContent {
  element: HTMLElement;
  initialFocus: HTMLElement;
  destroy(): void;
}

/** Searchable object tree for a host-owned dock or sheet. */
export function createObjectsPanelContent(ctx: WidgetContext, opts: ObjectsPanelOptions = {}): ObjectsPanelContent {
  const resolved = opts.objects ?? ctx.objects;
  if (resolved === undefined) throw new Error(widgetText(ctx, 'Objects panel requires an object model'));
  const objects = resolved;
  // The price pane is named, not numbered: it can sit below its studies, and
  // "Pane 3" would not tell a trader that is where the candles are.
  const paneName = (pane: number): string => pane === objects.primaryPaneIndex()
    ? widgetText(ctx, 'Price pane') : widgetText(ctx, 'Pane {number}', { number: pane + 1 });
  const paneLabel = (row: ChartObjectSnapshot): string => paneName(row.paneIndex);
  const kindLabel = (row: ChartObjectSnapshot): string => widgetText(ctx, `schema.object.kind.${row.kind}`, {}, KINDS[row.kind]);
  const doc = ctx.document;
  let closed = false;
  let all: readonly ChartObjectSnapshot[] = [];
  const rows = new Map<string, ObjectRow>();

  const content = el(doc, 'div', 'oac-objects-content');
  const stopPointer = (event: Event): void => event.stopPropagation();
  content.addEventListener('pointerdown', stopPointer);
  const sections = new Map<number, { element: HTMLElement; rows: HTMLElement; heading: HTMLElement }>();
  let draggedId: string | null = null;
  const text = (key: string, fallback: string, values: Record<string, string | number> = {}): string =>
    widgetText(ctx, `schema.ui.objects.${key}`, values, fallback);
  const search = el(doc, 'input', 'oac-objects__find');
  search.type = 'search';
  search.placeholder = widgetText(ctx, 'Search name, type or pane');
  search.setAttribute('aria-label', widgetText(ctx, 'Search objects'));
  search.setAttribute('spellcheck', 'false');
  const list = el(doc, 'div', 'oac-objects__list');
  list.setAttribute('role', 'list');
  list.setAttribute('aria-label', widgetText(ctx, 'Chart objects'));
  const empty = el(doc, 'div', 'oac-empty');
  empty.setAttribute('role', 'status');
  const count = el(doc, 'span', 'oac-objects__count');
  count.setAttribute('role', 'status');
  // How the list reads and how to change it, once, rather than on every row.
  const hint = el(doc, 'p', 'oac-objects__hint', text('orderHint', 'Each pane lists back to front. Drag a row, or press Alt with an arrow key, to move it.'));
  content.append(search, hint, list, empty, count);
  const groupName = el(doc, 'input', 'oac-objects__group-name');
  groupName.type = 'text';
  groupName.dataset.action = 'group-name';
  groupName.placeholder = text('groupName', 'Group name');
  groupName.setAttribute('aria-label', text('groupName', 'Group name'));
  const groupButton = button(doc, { label: text('group', 'Group selected'), onClick: () => {
    if (closed) return;
    const ids = all.filter(item => item.kind === 'drawing' && item.selected).map(item => item.id);
    if (objects.createGroup(groupName.value, ids)) groupName.value = '';
    paint();
  } });
  groupButton.dataset.action = 'group';
  if (objects.canGroup()) {
    const grouping = el(doc, 'div', 'oac-objects__grouping');
    grouping.append(groupName, groupButton);
    content.insertBefore(grouping, list);
  }
  const updateGroupButton = (): void => {
    // A read-only drawing's row offers no lock, and grouping leaves it in the
    // group the host gave it, so a selection of only those has nothing to group.
    groupButton.disabled = !groupName.value.trim() || !all.some(item => item.kind === 'drawing' && item.selected && item.capabilities.lock);
  };
  groupName.addEventListener('input', updateGroupButton);

  function moveTo(id: string, paneIndex: number): void {
    if (closed) return;
    if (!objects.move(id, paneIndex)) ctx.toast(text('moveFailed', 'Could not move object'), 'error');
    paint();
  }

  /**
   * Where a drop on `node` puts the dragged row in paint order. The list runs
   * back to front, so the upper half of a row means under it and the lower
   * half over it. A row with no box to measure (no layout yet) takes the
   * dragged row into its place, the way a drop on a row always did.
   */
  function dropSide(node: HTMLElement, event: DragEvent, id: string): 'above' | 'below' {
    const box = node.getBoundingClientRect();
    if (box.height > 0) return event.clientY < box.top + box.height / 2 ? 'below' : 'above';
    const stack = objects.stack(objects.get(id)?.paneIndex ?? -1);
    return stack.findIndex(item => item.id === draggedId) > stack.findIndex(item => item.id === id) ? 'below' : 'above';
  }

  function clearDropMarks(): void {
    for (const row of rows.values()) row.el.classList.remove('is-drop-before', 'is-drop-after');
  }

  /** A drop onto a row of another pane moves the dragged row there first. */
  function dropOn(id: string, where: 'above' | 'below'): void {
    clearDropMarks();
    if (closed || draggedId === null || draggedId === id) return;
    const source = objects.get(draggedId);
    const target = objects.get(id);
    if (!source || !target) return;
    if (source.paneIndex !== target.paneIndex && !(source.capabilities.move && objects.move(source.id, target.paneIndex))) return;
    if (objects.canPlace(source.id, target.id, where)) {
      if (!objects.place(source.id, target.id, where)) ctx.toast(text('reorderFailed', 'Could not reorder object'), 'error');
      return;
    }
    // Rows outside a pane's stack keep their own order among their kind.
    if (source.kind !== target.kind || source.band !== undefined) return;
    // Re-read after every step because model listeners publish synchronously.
    for (let n = 0; n < all.length; n++) {
      const peers = objects.list().filter(item => item.kind === source.kind && item.paneIndex === objects.get(source.id)?.paneIndex);
      const from = peers.findIndex(item => item.id === source.id);
      const to = peers.findIndex(item => item.id === target.id);
      if (from < 0 || to < 0 || from === to || !objects.reorder(source.id, from < to ? 1 : -1)) break;
      if (Math.abs(from - to) === 1) break;
    }
  }

  /**
   * One step through the pane's draw order, as `place` would take it: a
   * drawing over or under the row next to it, a source or study over the
   * next slot or under the previous one, taking what is placed on it along.
   */
  function step(item: ChartObjectSnapshot, direction: -1 | 1): { target: string; where: 'above' | 'below' } | null {
    const stack = objects.stack(item.paneIndex);
    const at = stack.findIndex(row => row.id === item.id);
    if (at < 0) return null;
    if (item.kind === 'drawing') {
      const next = stack[at + direction];
      return next ? { target: next.id, where: direction === 1 ? 'above' : 'below' } : null;
    }
    const entry = (row: ChartObjectSnapshot | undefined): boolean => row !== undefined && row.kind !== 'drawing';
    // Each `!` below reads an index the loop bounds or `entry` has just found a row at.
    if (direction === -1) {
      let i = at - 1;
      while (i >= 0 && !entry(stack[i]) && stack[i]!.band === 'series') i--;
      return entry(stack[i]) ? { target: stack[i]!.id, where: 'below' } : null;
    }
    let i = at + 1;
    while (i < stack.length && stack[i]!.band === 'series' && !entry(stack[i])) i++;
    if (!entry(stack[i])) return null;
    let top = i;
    while (stack[top + 1]?.band === 'series' && !entry(stack[top + 1])) top++;
    return { target: stack[top]!.id, where: 'above' };
  }

  function act(action: Action, id: string, event?: MouseEvent): void {
    if (closed) return;
    const item = objects.get(id);
    let success = false;
    try {
      if (item?.capabilities[action]) {
        switch (action) {
          case 'select': success = objects.select(id, event?.ctrlKey === true || event?.metaKey === true); break;
          case 'visibility': success = objects.setVisible(id, !item.visible); break;
          case 'lock': success = objects.setLocked(id, !item.locked); break;
          case 'settings': success = objects.openSettings(id); break;
          case 'focus': success = objects.focus(id); break;
          case 'remove': success = objects.remove(id); break;
        }
      }
    } catch { /* A host provider can reject an action without changing its object. */ }
    if (!success) ctx.toast(widgetText(ctx, FAILURES[action], { name: item?.name ?? widgetText(ctx, 'object') }), 'error');
  }

  function makeRow(item: ChartObjectSnapshot): ObjectRow {
    const node = el(doc, 'div', 'oac-objects__row');
    node.dataset.objectId = item.id;
    node.setAttribute('role', 'listitem');
    node.addEventListener('dragstart', event => {
      const current = objects.get(item.id);
      if (closed || !(current?.capabilities.place || current?.capabilities.reorder)) { event.preventDefault(); return; }
      event.stopPropagation();
      draggedId = item.id;
      event.dataTransfer?.setData('text/plain', item.id);
      if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move';
    });
    node.addEventListener('dragend', () => { draggedId = null; clearDropMarks(); });
    node.addEventListener('dragleave', () => { node.classList.remove('is-drop-before', 'is-drop-after'); });
    // Only a drop the bands can paint is accepted, so the pointer shows a
    // refused drop before release rather than the order snapping back after.
    node.addEventListener('dragover', event => {
      // The row decides: the pane section under it would take any drop as a pane move.
      event.stopPropagation();
      if (draggedId === null || draggedId === item.id) return;
      const source = objects.get(draggedId), where = dropSide(node, event, item.id);
      const allowed = source !== undefined && (source.paneIndex !== item.paneIndex ? source.capabilities.move === true
        : objects.canPlace(source.id, item.id, where) || (source.band === undefined && source.kind === item.kind && source.capabilities.reorder === true));
      clearDropMarks();
      if (!allowed) return;
      event.preventDefault();
      node.classList.add(where === 'below' ? 'is-drop-before' : 'is-drop-after');
    });
    node.addEventListener('drop', event => {
      event.preventDefault(); event.stopPropagation();
      dropOn(item.id, dropSide(node, event, item.id)); draggedId = null;
    });
    // The keyboard's drag: Alt with an arrow steps the row the way Earlier and Later do.
    node.addEventListener('keydown', event => {
      const key = (event as KeyboardEvent).key;
      if (!(event as KeyboardEvent).altKey || (key !== 'ArrowUp' && key !== 'ArrowDown')) return;
      const control = rows.get(item.id)?.buttons.get(key === 'ArrowUp' ? 'earlier' : 'later');
      if (control === undefined) return;
      event.preventDefault();
      event.stopPropagation();
      if (!control.disabled) control.click();
    });
    const grip = el(doc, 'span', 'oac-objects__grip');
    grip.setAttribute('aria-hidden', 'true');
    grip.innerHTML = chromeIconSvg('grip');
    node.appendChild(grip);
    const summary = item.capabilities.select
      ? button(doc, { label: '', onClick: event => act('select', item.id, event) })
      : el(doc, 'div');
    summary.classList.add('oac-objects__summary');
    if (item.capabilities.select) summary.dataset.action = 'select';
    const name = el(doc, 'span', 'oac-objects__name');
    const meta = el(doc, 'span', 'oac-objects__meta');
    const status = el(doc, 'span', 'oac-objects__status');
    const identity = `oac-object-${++rowSequence}`;
    meta.id = `${identity}-meta`;
    status.id = `${identity}-status`;
    if (item.capabilities.select) summary.setAttribute('aria-describedby', `${meta.id} ${status.id}`);
    summary.append(name, meta, status);
    const actions = el(doc, 'div', 'oac-objects__actions');
    node.append(summary, actions);
    const members = item.kind === 'group' ? el(doc, 'div', 'oac-objects__members') : undefined;
    if (members) { members.setAttribute('role', 'list'); node.appendChild(members); }
    return { el: node, summary, name, meta, status, actions, selectable: item.capabilities.select, buttons: new Map(), members };
  }

  function updateRow(row: ObjectRow, item: ChartObjectSnapshot): void {
    row.name.textContent = item.name;
    row.el.draggable = item.capabilities.reorder === true || item.capabilities.place === true;
    row.el.dataset.groupId = item.groupId ?? '';
    row.el.classList.toggle('is-group-member', item.groupId !== undefined);
    const meta = [kindLabel(item), paneLabel(item), item.visible ? widgetText(ctx, 'Visible') : widgetText(ctx, 'Hidden')];
    // Where a drawing paints, when it is not the default place in front.
    if (item.kind === 'drawing' && item.band === 'below') meta.push(text('behind', 'Behind the series'));
    if (item.kind === 'drawing' && item.band === 'series') {
      const under = all.find(other => other.id === item.stackAbove);
      meta.push(text('above', 'Above {name}', { name: under?.name ?? text('hidden', 'a hidden study') }));
    }
    if (item.locked !== undefined) meta.push(item.locked ? widgetText(ctx, 'Locked') : widgetText(ctx, 'Unlocked'));
    if (item.selected) meta.push(widgetText(ctx, 'Selected'));
    if (item.groupId) { const group = all.find(row => row.id === item.groupId); if (group) meta.push(group.name); }
    row.meta.textContent = meta.join(', ');
    row.el.classList.toggle('is-selected', item.selected);
    if (row.selectable) {
      row.summary.setAttribute('aria-label', widgetText(ctx, 'Select {name}', { name: item.name }));
      row.summary.setAttribute('aria-pressed', String(item.selected));
    }
    row.status.textContent = item.dataStatus === undefined ? '' : widgetText(ctx, `schema.dataStatus.${item.dataStatus.state}`, {}, STATUS[item.dataStatus.state]);
    row.status.hidden = item.dataStatus === undefined;
    row.status.dataset.state = item.dataStatus?.state ?? '';

    let index = 0;
    for (const action of ACTIONS) {
      let control = row.buttons.get(action);
      if (!item.capabilities[action]) {
        control?.remove();
        row.buttons.delete(action);
        continue;
      }
      if (control === undefined) {
        control = button(doc, { label: '', variant: action === 'remove' ? 'danger' : 'ghost', onClick: () => act(action, item.id) });
        control.dataset.action = action;
        row.buttons.set(action, control);
      }
      const label = action === 'visibility' ? (item.visible ? widgetText(ctx, 'Hide') : widgetText(ctx, 'Show'))
        : action === 'lock' ? (item.locked ? widgetText(ctx, 'Unlock') : widgetText(ctx, 'Lock'))
          : action === 'settings' ? widgetText(ctx, 'Settings') : action === 'focus' ? widgetText(ctx, 'Focus')
            // A drawing is deleted, as its menu and toolbar say; a study is removed from the chart.
            : item.kind === 'drawing' ? widgetText(ctx, 'Delete') : widgetText(ctx, 'Remove');
      control.textContent = label;
      control.setAttribute('aria-label', widgetText(ctx, action === 'visibility' ? (item.visible ? 'Hide {name}' : 'Show {name}') : action === 'lock' ? (item.locked ? 'Unlock {name}' : 'Lock {name}') : action === 'settings' ? 'Settings for {name}' : action === 'focus' ? 'Focus {name}' : item.kind === 'drawing' ? 'Delete {name}' : 'Remove {name}', { name: item.name }));
      if (row.actions.children[index] !== control) row.actions.insertBefore(control, row.actions.children[index] ?? null);
      index++;
    }
    if (item.kind === 'drawing' && item.id === 'drawing:' + item.sourceId && objects.canGroup()) {
      let control = row.buttons.get('add-selection');
      if (!control) {
        control = button(doc, { label: '', variant: 'ghost', onClick: () => {
          if (!closed) objects.select(item.id, true);
        } });
        control.dataset.action = 'add-selection';
        row.buttons.set('add-selection', control);
      }
      control.textContent = text(item.selected ? 'deselect' : 'selectMore', item.selected ? 'Deselect' : 'Select');
      // Named for the action it takes, so it carries no pressed state; the row's summary says selected.
      control.setAttribute('aria-label', text(item.selected ? 'deselectLabel' : 'selectMoreLabel', item.selected ? 'Remove {name} from selection' : 'Add {name} to selection', { name: item.name }));
      if (row.actions.children[index] !== control) row.actions.insertBefore(control, row.actions.children[index] ?? null);
      index++;
    }
    for (const [action, direction] of [['earlier', -1], ['later', 1]] as const) {
      let control = row.buttons.get(action);
      if (!item.capabilities.reorder && !item.capabilities.place) { control?.remove(); row.buttons.delete(action); continue; }
      if (!control) {
        control = button(doc, { label: '', variant: 'ghost', onClick: () => {
          if (closed) return;
          // A row in its pane's stack steps through the draw order the panel
          // shows; any other keeps stepping among its own kind.
          const current = objects.get(item.id);
          const move = current?.band !== undefined ? step(current, direction) : null;
          const done = current?.band !== undefined
            ? move !== null && objects.place(item.id, move.target, move.where)
            : objects.reorder(item.id, direction);
          if (!done) ctx.toast(text('reorderFailed', 'Could not reorder object'), 'error');
        } });
        control.dataset.action = action;
        row.buttons.set(action, control);
      }
      control.textContent = text(action, direction === -1 ? 'Earlier' : 'Later');
      control.setAttribute('aria-label', text(action + 'Label', direction === -1 ? 'Move {name} earlier' : 'Move {name} later', { name: item.name }));
      const move = item.band !== undefined ? step(item, direction) : null;
      control.disabled = item.band !== undefined ? move === null || !objects.canPlace(item.id, move.target, move.where)
        : !objects.canReorder(item.id, direction);
      if (row.actions.children[index] !== control) row.actions.insertBefore(control, row.actions.children[index] ?? null);
      index++;
    }
    if (item.capabilities.move) {
      if (!row.move) {
        row.move = el(doc, 'select', 'oac-objects__move');
        row.move.dataset.action = 'move';
        row.move.addEventListener('change', () => moveTo(item.id, Number(row.move!.value)));
      }
      row.move.setAttribute('aria-label', text('movePane', 'Move {name} to pane', { name: item.name }));
      const total = objects.paneCount();
      const names = Array.from({ length: total + 1 }, (_, pane) => pane === total ? text('newPane', 'New pane') : paneName(pane));
      // Rebuilt when a name changes as well as the count: moving the price
      // pane renames two targets without adding one.
      if (row.move.children.length !== names.length || names.some((name, pane) => row.move!.children[pane]?.textContent !== name)) {
        row.move.replaceChildren();
        names.forEach((name, pane) => {
          const option = el(doc, 'option');
          option.value = String(pane);
          option.textContent = name;
          row.move!.appendChild(option);
        });
      }
      row.move.value = String(item.paneIndex);
      if (row.actions.children[index] !== row.move) row.actions.insertBefore(row.move, row.actions.children[index] ?? null);
      index++;
    } else { row.move?.remove(); row.move = undefined; }
    row.actions.hidden = index === 0;
  }

  function paint(): void {
    if (closed) return;
    const query = search.value.trim().toLowerCase();
    const matches = new Set(all.filter(item => `${item.name} ${kindLabel(item)} ${paneLabel(item)}`.toLowerCase().includes(query)).map(item => item.id));
    for (const item of all) if (item.groupId && matches.has(item.groupId)) matches.add(item.id);
    const shown = all.filter(item => matches.has(item.id) || all.some(member => member.groupId === item.id && matches.has(member.id)));
    const kept = new Set(shown.map(item => item.id));
    const focused = doc.activeElement as HTMLElement | null;
    const heldFocus = focused !== null && list.contains(focused);
    for (const [id, row] of rows) {
      if (kept.has(id)) continue;
      row.el.remove();
      rows.delete(id);
    }
    const paneIndices = [...new Set(shown.map(item => item.paneIndex))].sort((a, b) => a - b);
    for (const [pane, section] of sections) if (!paneIndices.includes(pane)) { section.element.remove(); sections.delete(pane); }
    paneIndices.forEach((pane, index) => {
      let section = sections.get(pane);
      if (!section) {
        const element = el(doc, 'section', 'oac-objects__pane');
        element.dataset.paneIndex = String(pane);
        const heading = el(doc, 'h3', 'oac-objects__pane-title');
        const children = el(doc, 'div');
        element.append(heading, children);
        element.addEventListener('dragover', event => { if (draggedId !== null && objects.get(draggedId)?.capabilities.move) event.preventDefault(); });
        element.addEventListener('drop', event => {
          event.preventDefault();
          if (draggedId !== null && objects.get(draggedId)?.capabilities.move) moveTo(draggedId, pane);
          draggedId = null;
        });
        section = { element, rows: children, heading };
        sections.set(pane, section);
      }
      // Named on every paint: a section keeps its slot while the price pane moves in or out of it.
      const name = paneName(pane);
      if (section.heading.textContent !== name) {
        section.heading.textContent = name;
        section.element.setAttribute('aria-label', name);
      }
      if (list.children[index] !== section.element) list.insertBefore(section.element, list.children[index] ?? null);
    });
    // Each pane lists its stack in draw order, back to front, a group where its
    // first member paints; rows outside the stack follow in inventory order.
    const order = new Map<string, number>();
    for (const pane of paneIndices) objects.stack(pane).forEach((item, index) => order.set(item.id, index));
    const rank = (item: ChartObjectSnapshot): number => {
      if (order.has(item.id)) return order.get(item.id)!;
      const members = all.filter(member => member.groupId === item.id && order.has(member.id)).map(member => order.get(member.id)!);
      return members.length ? Math.min(...members) - 0.5 : Number.MAX_SAFE_INTEGER;
    };
    const sorted = shown.map((item, index) => ({ item, index }))
      .sort((a, b) => rank(a.item) - rank(b.item) || a.index - b.index).map(entry => entry.item);
    const positions = new Map<HTMLElement, number>();
    sorted.forEach(item => {
      let row = rows.get(item.id);
      if (row === undefined || row.selectable !== item.capabilities.select) {
        row?.el.remove();
        row = makeRow(item);
        rows.set(item.id, row);
      }
      updateRow(row, item);
      // Leave stable rows attached so canvas selection and live data updates
      // cannot interrupt a user typing or tabbing through object actions.
      const group = item.groupId ? all.find(group => group.id === item.groupId && group.paneIndex === item.paneIndex) : undefined;
      const parent = (group ? rows.get(group.id)?.members : undefined) ?? sections.get(item.paneIndex)!.rows;
      const index = positions.get(parent) ?? 0;
      if (parent.children[index] !== row.el) parent.insertBefore(row.el, parent.children[index] ?? null);
      positions.set(parent, index + 1);
    });
    updateGroupButton();
    empty.hidden = shown.length > 0;
    empty.textContent = all.length === 0 ? widgetText(ctx, 'No objects on this chart.') : widgetText(ctx, 'No objects match your search.');
    const one = all.length === 1;
    count.textContent = query === '' ? widgetText(ctx, one ? '{count} object' : '{count} objects', { count: all.length })
      : widgetText(ctx, one ? '{shown} of {count} object' : '{shown} of {count} objects', { shown: shown.length, count: all.length });
    if (heldFocus) {
      if (!list.contains(focused)) search.focus();
      else if (doc.activeElement !== focused) focused!.focus();
    }
  }

  search.addEventListener('input', paint);
  const unsubscribe = objects.subscribe(items => {
    if (closed) return;
    // Rows of one name carry their number (numberedNames), or every one's
    // actions read the same. Drawings count in the controller's order, as the
    // alert editor lists them, whatever order an inventory gives.
    const drawn = new Map((ctx.draw?.drawings() ?? []).map((drawing, index) => [drawing.id, index]));
    const place = (item: ChartObjectSnapshot): number => (item.kind === 'drawing' ? drawn.get(item.sourceId) ?? drawn.size : -1);
    const names = numberedNames([...items].sort((a, b) => place(a) - place(b)), item => item.name);
    all = items.map(item => (names.get(item.id) === item.name ? item : { ...item, name: names.get(item.id)! }));
    paint();
  });
  const dispose = (): void => {
    if (closed) return;
    closed = true;
    unsubscribe();
    content.removeEventListener('pointerdown', stopPointer);
    search.removeEventListener('input', paint);
    groupName.removeEventListener('input', updateGroupButton);
    rows.clear();
    sections.clear();
    draggedId = null;
    all = [];
    opts.onClose?.();
  };
  return { element: content, initialFocus: search, destroy: dispose };
}

/** Open the object tree in the existing popup interface. */
export function mountObjectsPanel(ctx: WidgetContext, anchor?: HTMLElement, opts: ObjectsPanelOptions = {}): PanelHandle {
  const content = createObjectsPanelContent(ctx, opts);
  const frame = dialogFrame(ctx.document, { translate: ctx.translate, title: widgetText(ctx, 'Objects'), className: 'oac-objects', onClose: () => handle.close(), closeText: true });
  frame.body.appendChild(content.element);
  frame.actions.appendChild(button(ctx.document, { label: widgetText(ctx, 'Done'), variant: 'primary', onClick: () => handle.close() }));
  const handle = openPanel(ctx, frame.el, {
    ...(anchor === undefined ? { placement: 'center' as const, modal: true } : { anchor, placement: 'below' as const }),
    initialFocus: content.initialFocus, onClose: () => content.destroy(),
  }, () => {});
  return handle;
}

/** Append beside the shared widget and dialog styles when mounting this panel. */
export const OBJECTS_PANEL_CSS = `
.oac-widget .oac-objects { width: 440px; min-width: 0; }
.oac-widget .oac-objects .oac-dialog__body { display: flex; flex-direction: column; gap: 8px; overflow: hidden; }
.oac-widget .oac-objects-content { display: flex; flex-direction: column; min-height: 0; gap: 8px; }
.oac-widget .oac-objects__pane-title { margin: 6px 2px; color: var(--oac-mut); font-size: 11px; text-transform: uppercase; }
.oac-widget .oac-objects__grouping { display: flex; gap: 4px; }
.oac-widget .oac-objects__group-name { min-width: 0; width: 100%; }
.oac-widget .oac-objects__move { min-width: 90px; max-width: 130px; height: 26px; font-size: 11px; }
.oac-widget .oac-objects__row.is-group-member { margin-left: 10px; border: 0; border-left: 1px solid var(--oac-bd-soft); border-radius: 0; }
.oac-widget .oac-objects__members { min-width: 0; }
.oac-widget .oac-objects__list { scrollbar-width: thin; scrollbar-color: var(--oac-bd-soft) var(--oac-bg); }
.oac-widget .oac-objects__list::-webkit-scrollbar { width: 6px; }
.oac-widget .oac-objects__list::-webkit-scrollbar-track { background: var(--oac-bg); }
.oac-widget .oac-objects__list::-webkit-scrollbar-thumb { background: var(--oac-bd-soft); border-radius: 3px; }
.oac-widget .oac-objects__list::-webkit-scrollbar-thumb:hover { background: var(--oac-mut); }
.oac-widget .oac-objects__find { width: 100%; min-width: 0; flex: none; }
.oac-widget .oac-objects__list { min-height: 0; overflow: auto; overscroll-behavior: contain; padding: 2px; }
.oac-widget .oac-objects__row { position: relative; display: flex; flex-direction: column; gap: 4px; padding: 6px; margin-bottom: 4px;
  border: 1px solid var(--oac-bd-soft); border-radius: 6px; min-width: 0; }
.oac-widget .oac-objects__row[draggable="true"] { cursor: grab; }
.oac-widget .oac-objects__grip { display: none; position: absolute; top: 7px; right: 6px; color: var(--oac-faint); line-height: 0; pointer-events: none; }
.oac-widget .oac-objects__row[draggable="true"] > .oac-objects__grip { display: block; }
.oac-widget .oac-objects__grip > svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; }
.oac-widget .oac-objects__row[draggable="true"] > .oac-objects__summary { padding-right: 18px; }
.oac-widget .oac-objects__hint { margin: 0 2px; color: var(--oac-faint); font-size: 11px; line-height: 1.4; }
.oac-widget .oac-objects__row.is-selected { border-color: var(--oac-acc); background: var(--oac-elev); }
.oac-widget .oac-objects__row.is-drop-before { box-shadow: inset 0 2px 0 var(--oac-acc); }
.oac-widget .oac-objects__row.is-drop-after { box-shadow: inset 0 -2px 0 var(--oac-acc); }
.oac-widget .oac-objects__summary { display: flex; flex-direction: column; align-items: flex-start; justify-content: center;
  gap: 2px; width: 100%; min-width: 0; height: auto; padding: 3px 4px; text-align: left; white-space: normal; }
.oac-widget .oac-objects__name { font-weight: 600; overflow-wrap: anywhere; }
.oac-widget .oac-objects__meta, .oac-widget .oac-objects__status { font-size: 11px; color: var(--oac-mut); overflow-wrap: anywhere; }
.oac-widget .oac-objects__status[data-state="error"] { color: var(--oac-danger); }
.oac-widget .oac-objects__actions { display: flex; flex-wrap: wrap; gap: 3px; }
.oac-widget .oac-objects__actions .oac-btn { height: 26px; padding: 0 6px; font-size: 11px; }
.oac-widget .oac-objects__count { color: var(--oac-mut); font-size: 11px; }
`;
