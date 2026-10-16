/**
 * Drawing policies: selection, editing, persistence and the object inventory
 * restricted independently of one another and of `locked`. Each restriction
 * is checked on every path that could reach the drawing, since a policy that
 * one path honours and another ignores is not a policy.
 */
import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { ChartObjects } from '../src/model/chart-objects';
import { fakeDocument } from './helpers/fake-dom';
import { darkTheme } from '../src/theme';
import {
  DrawingController, DrawingLayer, migrateDrawings, encodeClipboardPayload, cloneDrawing, registerDrawingTool,
  type ClipboardPort, type Drawing, type DrawingGroup, type DrawingInput, type DrawingPolicy,
} from '../src/draw/index';
import type { DrawingChartHost } from '../src/draw/controller';
import type { Bar } from '../src/model/bar';
import type { DataLayer } from '../src/model/data-layer';
import { RecordingContext } from './helpers/fake-ctx';

const T0 = 1700000000;

beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

const bars = (n: number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = 100 + Math.sin(i / 4) * 5;
    return { time: T0 + i * 60, open: c, high: c + 2, low: c - 2, close: c, volume: 10 };
  });

const charts: Chart[] = [];
function makeChart(): Chart {
  const chart = new Chart(fakeDocument().createElement('div') as unknown as HTMLElement, {
    document: fakeDocument(),
    raf: { schedule: (cb: (t: number) => void) => { cb(0); return 0; } },
    pixelRatio: () => 1, shortcuts: false,
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(bars(120));
  charts.push(chart);
  return chart;
}
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

/** A host with a working bus, no pixel mapping, and the last state it was handed. */
function busHost(): DrawingChartHost & { state: unknown } {
  const handlers = new Map<string, ((p: unknown) => void)[]>();
  const host = {
    state: undefined as unknown,
    on: (event: string, handler: (p: unknown) => void) => {
      const list = handlers.get(event) ?? [];
      list.push(handler);
      handlers.set(event, list);
      return () => handlers.set(event, (handlers.get(event) ?? []).filter((h) => h !== handler));
    },
    emit: (event: string, payload: unknown) => { for (const h of handlers.get(event) ?? []) h(payload); },
    addPrimitive: () => {},
    removePrimitive: () => {},
    dataLayer: { baseIndex: 2, indexToTime: (i: number) => T0 + i * 300 } as unknown as DataLayer,
    getVisibleLogicalRange: () => null,
    drawingState: () => null,
    setDrawingState: (value: unknown) => { host.state = value; },
  };
  return host;
}

/** A clipboard that holds one string, the way the OS one does. */
function memoryPort(): ClipboardPort & { text: string } {
  const port = { text: '', writeText: async (t: string) => { port.text = t; }, readText: async () => port.text };
  return port;
}

const line = (draw: DrawingController, extra: Partial<DrawingInput> = {}): Drawing => draw.add({
  tool: 'trend-line', paneIndex: 0, style: {},
  points: [{ time: 1000, price: 10 }, { time: 2000, price: 20 }],
  ...extra,
});

const drag = (chart: DrawingChartHost, id: string, time: number, price: number): void =>
  chart.emit('drag', { id, time, price, paneIndex: 0 });

describe('a read-only drawing (editable: false)', () => {
  it('still selects, and every user edit leaves it exactly as it was', async () => {
    const chart = busHost();
    const draw = new DrawingController(chart, { clipboard: memoryPort() });
    const fixed = line(draw, { policy: { editable: false }, style: { color: '#123456' } });
    const before = JSON.stringify(draw.get(fixed.id));
    draw.select(fixed.id);
    expect(draw.selection()).toEqual([fixed.id]);
    expect(draw.update(fixed.id, { style: { color: '#ff0000' } })).toBe(false);
    draw.updateMany([{ id: fixed.id, patch: { visible: false, locked: true } }]);
    draw.nudge([fixed.id], 10, 10);
    expect(draw.remove(fixed.id)).toBe(false);
    draw.removeMany([fixed.id]);
    draw.clear();
    expect(await draw.cut(fixed.id)).toBe(false);
    // The body and a handle, grabbed and dragged.
    draw.select(fixed.id);
    drag(chart, `draw:${fixed.id}`, 1000, 10);
    drag(chart, `draw:${fixed.id}`, 1500, 15);
    chart.emit('drag:end', {});
    drag(chart, `draw:${fixed.id}#1`, 2500, 25);
    chart.emit('drag:end', {});
    expect(JSON.stringify(draw.get(fixed.id))).toBe(before);
    expect(draw.canUndo()).toBe(false);
  });

  it('is left alone by a multi-selection edit while the rest of the selection changes', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    const fixed = line(draw, { policy: { editable: false } });
    const free = line(draw, { points: [{ time: 5000, price: 50 }, { time: 6000, price: 60 }] });
    draw.select([fixed.id, free.id]);
    draw.updateMany([fixed.id, free.id].map((id) => ({ id, patch: { style: { color: '#00ff00' } } })));
    expect(draw.get(fixed.id)?.style.color).toBeUndefined();
    expect(draw.get(free.id)?.style.color).toBe('#00ff00');
    drag(chart, `draw:${free.id}`, 5000, 50);
    drag(chart, `draw:${free.id}`, 5100, 51);
    chart.emit('drag:end', {});
    expect(draw.get(free.id)?.points[0]).toEqual({ time: 5100, price: 51 });
    expect(draw.get(fixed.id)?.points[0]).toEqual({ time: 1000, price: 10 });
    draw.removeMany([fixed.id, free.id]);
    expect(draw.drawings().map((d) => d.id)).toEqual([fixed.id]);
  });

  it('moves, restyles and goes when the host says force', () => {
    const draw = new DrawingController(busHost());
    const fixed = line(draw, { policy: { editable: false } });
    expect(draw.update(fixed.id, { points: [{ time: 3000, price: 30 }, { time: 4000, price: 40 }] }, { force: true })).toBe(true);
    expect(draw.get(fixed.id)?.points[0]).toEqual({ time: 3000, price: 30 });
    draw.updateMany([{ id: fixed.id, patch: { style: { color: '#abcdef' } } }], { force: true });
    expect(draw.get(fixed.id)?.style.color).toBe('#abcdef');
    expect(draw.remove(fixed.id, { force: true })).toBe(true);
    const again = line(draw, { policy: { editable: false } });
    draw.clear({ force: true });
    expect(draw.get(again.id)).toBeUndefined();
    const third = line(draw, { policy: { editable: false } });
    draw.removeMany([third.id], { force: true });
    expect(draw.drawings()).toEqual([]);
  });

  it('keeps out of the undo history, so undo neither removes, restores nor rewinds it', () => {
    const draw = new DrawingController(busHost());
    const fixed = line(draw, { policy: { editable: false } });
    // A host placing its own drawing is not a step the user can take back.
    expect(draw.canUndo()).toBe(false);
    const mine = line(draw, { points: [{ time: 5000, price: 50 }, { time: 6000, price: 60 }] });
    expect(draw.undo()).toBe(true);
    expect(draw.get(mine.id)).toBeUndefined();
    expect(draw.get(fixed.id)).toBeDefined();
    expect(draw.canRedo()).toBe(true);
    // A forced host edit neither records a step nor wipes the redo branch.
    draw.update(fixed.id, { style: { color: '#010203' } }, { force: true });
    expect(draw.canUndo()).toBe(false);
    expect(draw.canRedo()).toBe(true);
    expect(draw.redo()).toBe(true);
    expect(draw.get(mine.id)).toBeDefined();
    // A drawing made read-only after the user moved it is not moved back.
    draw.nudge([mine.id], 10, 0);
    const moved = draw.get(mine.id)?.points[0].time;
    draw.update(mine.id, { policy: { editable: false } });
    draw.undo();
    expect(draw.get(mine.id)?.points[0].time).toBe(moved);
    expect(draw.get(mine.id)?.policy?.editable).toBe(false);
    // Neither is a forced removal something undo brings back.
    draw.remove(fixed.id, { force: true });
    while (draw.undo()) { /* walk the whole history */ }
    expect(draw.get(fixed.id)).toBeUndefined();
  });

  it('survives a user removal of its group, and goes with the group only when the host removes it', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    const fixed = line(draw, { policy: { editable: false } });
    const free = line(draw);
    const both = draw.createGroup('Both', [fixed.id, free.id], { force: true })!;
    expect(draw.removeGroup(both.id, true)).toBe(false);
    expect(draw.drawings().map((d) => d.id)).toEqual([fixed.id, free.id]);
    expect(draw.groups().map((g) => g.members)).toEqual([[fixed.id, free.id]]);
    // The host's own removal takes the group and every drawing in it, and the
    // saved state sees that.
    expect(draw.removeGroup(both.id, true, { force: true })).toBe(true);
    expect(draw.drawings()).toEqual([]);
    expect(draw.groups()).toEqual([]);
    expect((chart.state as { drawings: unknown[] }).drawings).toEqual([]);
    expect((chart.state as { groups?: unknown }).groups).toBeUndefined();
  });

  it('copies the policy it is handed, so the caller\'s object cannot lift it afterwards', () => {
    const draw = new DrawingController(busHost());
    const policy: DrawingPolicy = { editable: false };
    const fixed = line(draw, { policy });
    policy.editable = true;
    expect(draw.get(fixed.id)?.policy).toEqual({ editable: false });
    expect(draw.remove(fixed.id)).toBe(false);
  });

  it('keeps the group the host gave it, whatever grouping the user does', () => {
    const draw = new DrawingController(busHost());
    const fixed = line(draw, { policy: { editable: false } });
    const free = line(draw);
    const host = draw.createGroup('Host', [fixed.id, free.id], { force: true })!;
    expect(host.members).toEqual([fixed.id, free.id]);
    // A group the user makes takes their own drawings and leaves this one
    // in the group it was in.
    const mine = draw.createGroup('Mine', [fixed.id, free.id])!;
    expect(mine.members).toEqual([free.id]);
    expect(draw.createGroup('Only the fixed one', [fixed.id])).toBeNull();
    expect(draw.groups().map((g) => [g.name, g.members])).toEqual([['Host', [fixed.id]], ['Mine', [free.id]]]);
    // Its group is not the user's to rename, dissolve or delete around it.
    expect(draw.renameGroup(host.id, 'Renamed')).toBe(false);
    expect(draw.removeGroup(host.id)).toBe(false);
    expect(draw.removeGroup(host.id, true)).toBe(false);
    expect(draw.groups().map((g) => g.name)).toEqual(['Host', 'Mine']);
    // A user group becomes the host's the moment one of its drawings is made read-only.
    draw.update(free.id, { policy: { editable: false } });
    expect(draw.removeGroup(mine.id, true)).toBe(false);
    expect(draw.get(free.id)).toBeDefined();
    // The host still can.
    expect(draw.renameGroup(host.id, 'Signals', { force: true })).toBe(true);
    expect(draw.removeGroup(host.id, false, { force: true })).toBe(true);
    expect(draw.groups().map((g) => g.name)).toEqual(['Mine']);
    expect(draw.get(fixed.id)).toBeDefined();
  });

  it('copies and duplicates into the user\'s own drawing, without the policy', async () => {
    const draw = new DrawingController(busHost(), { clipboard: memoryPort() });
    const fixed = line(draw, { policy: { editable: false, persistent: false, listed: false } });
    const [dup] = draw.duplicate([fixed.id]);
    expect(dup.policy).toBeUndefined();
    expect(draw.update(dup.id, { style: { color: '#222222' } })).toBe(true);
    expect(await draw.copy(fixed.id)).toBe(true);
    const [pasted] = await draw.paste();
    expect(pasted.policy).toBeUndefined();
    expect(encodeClipboardPayload([draw.get(fixed.id)!])).not.toContain('policy');
    expect(draw.remove(pasted.id)).toBe(true);
  });
});

describe('the policy and the undo history', () => {
  it('records no step for a policy change, and no undo or redo brings back an older policy', () => {
    const draw = new DrawingController(busHost());
    const d = line(draw);
    draw.nudge([d.id], 8, 0);
    const moved = draw.get(d.id)!.points[0].time;
    draw.update(d.id, { policy: { selectable: false } });
    draw.updateMany([{ id: d.id, patch: { policy: { listed: false, persistent: false } } }]);
    const policy = { selectable: false, listed: false, persistent: false };
    // The first undo is the user's nudge, not the host's restriction.
    expect(draw.undo()).toBe(true);
    expect(draw.get(d.id)?.points[0].time).not.toBe(moved);
    expect(draw.get(d.id)?.policy).toEqual(policy);
    draw.select(d.id);
    expect(draw.selection()).toEqual([]);
    // Taking the drawing back and bringing it again keeps the policy as well.
    expect(draw.undo()).toBe(true);
    expect(draw.get(d.id)).toBeUndefined();
    expect(draw.redo()).toBe(true);
    expect(draw.redo()).toBe(true);
    expect(draw.get(d.id)?.policy).toEqual(policy);
    expect(draw.get(d.id)?.points[0].time).toBe(moved);
    expect(draw.toJSON().drawings).toEqual([]);
  });

  it('records no step for a host drawing placed with any restriction, nor for a forced call', () => {
    const draw = new DrawingController(busHost());
    const ghost = line(draw, { policy: { selectable: false, listed: false, persistent: false } });
    expect(draw.canUndo()).toBe(false);
    expect(draw.undo()).toBe(false);
    expect(draw.get(ghost.id)).toBeDefined();
    // Moving and retiring it is the host's business as well.
    draw.update(ghost.id, { points: [{ time: 3000, price: 30 }, { time: 4000, price: 40 }] }, { force: true });
    draw.remove(ghost.id, { force: true });
    expect(draw.canUndo()).toBe(false);
    expect(draw.undo()).toBe(false);
    expect(draw.get(ghost.id)).toBeUndefined();
  });

  it('has nothing to undo or redo once every step left is on a drawing made read-only', () => {
    const draw = new DrawingController(busHost());
    const d = line(draw);
    const other = line(draw, { points: [{ time: 5000, price: 50 }, { time: 6000, price: 60 }] });
    draw.nudge([d.id], 8, 0);
    draw.update(d.id, { policy: { editable: false } });
    // The step that added `other` still does something; the rest do not.
    expect(draw.canUndo()).toBe(true);
    expect(draw.undo()).toBe(true);
    expect(draw.get(other.id)).toBeUndefined();
    expect(draw.canUndo()).toBe(false);
    expect(draw.undo()).toBe(false);
    // The redo branch follows the same rule.
    expect(draw.redo()).toBe(true);
    const e = line(draw, { points: [{ time: 7000, price: 70 }, { time: 8000, price: 80 }] });
    draw.nudge([e.id], 8, 0);
    expect(draw.undo()).toBe(true);
    expect(draw.canRedo()).toBe(true);
    draw.update(e.id, { policy: { editable: false } });
    expect(draw.canRedo()).toBe(false);
    expect(draw.redo()).toBe(false);
  });
});

describe('grouping and the undo history', () => {
  const second = { points: [{ time: 5000, price: 50 }, { time: 6000, price: 60 }] };

  it('never dissolves the group of a drawing made read-only, and still moves the user\'s own drawing', () => {
    const draw = new DrawingController(busHost());
    const a = line(draw);
    const b = line(draw, second);
    const mine = draw.createGroup('Mine', [a.id, b.id])!;
    draw.update(a.id, { policy: { editable: false } });
    expect(draw.removeGroup(mine.id)).toBe(false);
    expect(draw.renameGroup(mine.id, 'Other')).toBe(false);
    // The step still takes the user's drawing back out of the group, and
    // leaves the read-only one in the group the controller will not dissolve.
    expect(draw.undo()).toBe(true);
    expect(draw.groups()).toEqual([{ id: mine.id, name: 'Mine', members: [a.id] }]);
    expect(draw.redo()).toBe(true);
    expect(draw.groups()).toEqual([{ id: mine.id, name: 'Mine', members: [a.id, b.id] }]);
  });

  it('puts no read-only drawing back into a group the user removed', () => {
    const draw = new DrawingController(busHost());
    const a = line(draw);
    const b = line(draw, second);
    const mine = draw.createGroup('Mine', [a.id, b.id])!;
    expect(draw.removeGroup(mine.id)).toBe(true);
    draw.update(a.id, { policy: { editable: false } });
    expect(draw.undo()).toBe(true);
    expect(draw.groups()).toEqual([{ id: mine.id, name: 'Mine', members: [b.id] }]);
    // What the undo put back is the user's, so they can take it away again.
    expect(draw.removeGroup(mine.id)).toBe(true);
    expect(draw.groups()).toEqual([]);
  });

  it('has nothing to undo once every grouping step reached only a drawing now read-only', () => {
    const draw = new DrawingController(busHost());
    const a = line(draw);
    const mine = draw.createGroup('Mine', [a.id])!;
    expect(draw.renameGroup(mine.id, 'Renamed')).toBe(true);
    draw.update(a.id, { policy: { editable: false } });
    expect(draw.canUndo()).toBe(false);
    expect(draw.undo()).toBe(false);
    expect(draw.groups()).toEqual([{ id: mine.id, name: 'Renamed', members: [a.id] }]);
  });
});

describe('the host\'s forced calls and the undo history', () => {
  const second = { points: [{ time: 5000, price: 50 }, { time: 6000, price: 60 }] };

  it('drops the step that made a drawing the host then removed, so no press brings it back', () => {
    const draw = new DrawingController(busHost());
    const a = line(draw);
    draw.remove(a.id, { force: true });
    expect(draw.canUndo()).toBe(false);
    expect(draw.undo()).toBe(false);
    expect(draw.canRedo()).toBe(false);
    expect(draw.redo()).toBe(false);
    expect(draw.get(a.id)).toBeUndefined();
  });

  it('keeps a forced move through the user\'s own undo and redo of that drawing', () => {
    const draw = new DrawingController(busHost());
    const a = line(draw);
    draw.update(a.id, { style: { color: '#ff0000' } });
    const moved = [{ time: 3000, price: 30 }, { time: 4000, price: 40 }];
    draw.update(a.id, { points: moved }, { force: true });
    // Taking back the colour leaves the host's move, and so does taking the
    // drawing back and bringing it again.
    expect(draw.undo()).toBe(true);
    expect(draw.get(a.id)?.style.color).toBeUndefined();
    expect(draw.get(a.id)?.points).toEqual(moved);
    expect(draw.undo()).toBe(true);
    expect(draw.get(a.id)).toBeUndefined();
    expect(draw.redo()).toBe(true);
    expect(draw.get(a.id)?.points).toEqual(moved);
    expect(draw.redo()).toBe(true);
    expect(draw.get(a.id)?.style.color).toBe('#ff0000');
    expect(draw.get(a.id)?.points).toEqual(moved);
  });

  it('keeps a forced move\'s anchors exactly where the tool\'s constraint put them', () => {
    // A constraint that reads which anchor moved, the way the position tools
    // do: one anchor moved stays as placed, a whole-shape move is shifted.
    registerDrawingTool({
      id: 'test-handle', name: 'Test handle', points: 2,
      constrain: (points, handle) => points.map((p) => ({ ...p, price: p.price + (handle === null ? 100 : 0) })),
      draw: () => {}, distance: () => 0,
    });
    const draw = new DrawingController(busHost());
    const a = line(draw, { tool: 'test-handle' });
    draw.update(a.id, { points: [{ time: 1100, price: 11 }, { time: 2100, price: 21 }] });
    // One anchor on from where the drawing is now, so the constraint leaves
    // it; from the shape the history recorded, both anchors differ.
    const placed = [{ time: 1100, price: 111 }, { time: 2500, price: 125 }];
    draw.update(a.id, { points: placed }, { force: true });
    expect(draw.get(a.id)?.points).toEqual(placed);
    expect(draw.undo()).toBe(true);
    expect(draw.get(a.id)).toBeUndefined();
    expect(draw.redo()).toBe(true);
    expect(draw.get(a.id)?.points).toEqual(placed);
  });

  it('never brings back a group the host removed', () => {
    const draw = new DrawingController(busHost());
    const fixed = line(draw, { policy: { editable: false } });
    const free = line(draw, second);
    const host = draw.createGroup('Host', [fixed.id, free.id], { force: true })!;
    draw.createGroup('Mine', [free.id]);
    expect(draw.removeGroup(host.id, false, { force: true })).toBe(true);
    expect(draw.undo()).toBe(true);
    expect(draw.groups()).toEqual([]);
    expect(draw.redo()).toBe(true);
    expect(draw.groups().map((g) => [g.name, g.members])).toEqual([['Mine', [free.id]]]);
  });

  it('keeps the name the host gave a group, while the user\'s own step still undoes', () => {
    const draw = new DrawingController(busHost());
    const fixed = line(draw, { policy: { editable: false } });
    const free = line(draw, second);
    const host = draw.createGroup('Host', [fixed.id, free.id], { force: true })!;
    draw.createGroup('Mine', [free.id]);
    expect(draw.renameGroup(host.id, 'Signals', { force: true })).toBe(true);
    expect(draw.undo()).toBe(true);
    expect(draw.groups()).toEqual([{ id: host.id, name: 'Signals', members: [fixed.id, free.id] }]);
  });

  it('keeps a group the host made through the undo and redo of its drawing', () => {
    const draw = new DrawingController(busHost());
    const x = line(draw);
    const host = draw.createGroup('Host', [x.id], { force: true })!;
    expect(draw.undo()).toBe(true);
    expect(draw.get(x.id)).toBeUndefined();
    expect(draw.redo()).toBe(true);
    expect(draw.groups()).toEqual([{ id: host.id, name: 'Host', members: [x.id] }]);
  });

  it('drops a grouping step the host has since undone itself, so the first press does something', () => {
    const draw = new DrawingController(busHost());
    const free = line(draw);
    const mine = draw.createGroup('Mine', [free.id])!;
    expect(draw.removeGroup(mine.id, false, { force: true })).toBe(true);
    expect(draw.undo()).toBe(true);
    expect(draw.get(free.id)).toBeUndefined();
    expect(draw.canUndo()).toBe(false);
  });

  it('keeps the rest of a host patch that carries a policy through history', () => {
    const draw = new DrawingController(busHost());
    const a = line(draw);
    draw.update(a.id, { style: { color: '#ff0000' } });
    draw.update(a.id, { policy: { listed: false }, style: { lineWidth: 5 } });
    // The colour, then the drawing itself, and back again.
    expect(draw.undo()).toBe(true);
    expect(draw.undo()).toBe(true);
    expect(draw.redo()).toBe(true);
    expect(draw.get(a.id)?.style.lineWidth).toBe(5);
    expect(draw.get(a.id)?.style.color).toBeUndefined();
    expect(draw.get(a.id)?.policy).toEqual({ listed: false });
  });

  it('never gives the host\'s group an id a recorded step still holds, so an undo keeps both groups', () => {
    const at = (id: string, time: number, policy?: DrawingPolicy) => ({ id, tool: 'trend-line', paneIndex: 0, zIndex: 0, style: {},
      points: [{ time, price: 10 }, { time: time + 1000, price: 20 }], ...(policy ? { policy } : {}) });
    const byId = (groups: readonly DrawingGroup[]) => [...groups].sort((x, y) => x.id.localeCompare(y.id));
    // The host's drawing read-only, and not.
    for (const policy of [{ editable: false }, undefined]) {
      const draw = new DrawingController(busHost());
      draw.fromJSON({ version: 2, drawings: [at('a', 1000), at('b', 3000), at('c', 5000, policy)],
        groups: [{ id: 'group-1', name: 'Mine', members: ['a', 'b'] }] });
      // `group-1` is now only in the step that removed it.
      expect(draw.removeGroup('group-1')).toBe(true);
      const host = draw.createGroup('Host', ['c'], { force: true })!;
      expect(draw.undo()).toBe(true);
      expect(byId(draw.groups())).toEqual(byId([
        { id: 'group-1', name: 'Mine', members: ['a', 'b'] },
        { id: host.id, name: 'Host', members: ['c'] },
      ]));
      expect(draw.redo()).toBe(true);
      expect(draw.groups()).toEqual([{ id: host.id, name: 'Host', members: ['c'] }]);
    }
  });
});

describe('what the host\'s forced calls cost the undo history', () => {
  const second = { points: [{ time: 5000, price: 50 }, { time: 6000, price: 60 }] };
  const trail = (price: number) => [{ time: 1000, price }, { time: 2000, price }];
  // A rewrite parses both snapshots of every recorded step, and nothing else
  // on these paths parses, so the count is the rewrite's work.
  const parses = (run: () => void): number => {
    const spy = vi.spyOn(JSON, 'parse');
    try { run(); return spy.mock.calls.length; } finally { spy.mockRestore(); }
  };
  /** A read-only level beside the user's drawing and its 21 recorded steps. */
  const history = () => {
    const draw = new DrawingController(busHost());
    const level = line(draw, { policy: { editable: false } });
    const free = line(draw, second);
    for (let i = 0; i < 20; i++) draw.nudge([free.id], 8, 0);
    return { draw, level, free };
  };

  it('rewrites no recorded step to move or restyle a read-only drawing, however long the history', () => {
    const { draw, level, free } = history();
    const nudged = cloneDrawing(draw.get(free.id)!);
    // A trailing level, once a tick.
    expect(parses(() => {
      for (let tick = 1; tick <= 10; tick++) {
        draw.update(level.id, { points: trail(10 + tick), style: { color: '#ff0000' } }, { force: true });
      }
    })).toBe(0);
    // Every step of the user's is still there, and none of them moves the level.
    for (let i = 0; i < 21; i++) expect(draw.undo()).toBe(true);
    expect(draw.canUndo()).toBe(false);
    expect(draw.get(free.id)).toBeUndefined();
    for (let i = 0; i < 21; i++) expect(draw.redo()).toBe(true);
    expect(draw.get(free.id)).toEqual(nudged);
    expect(draw.get(level.id)?.points).toEqual(trail(20));
    expect(draw.get(level.id)?.style.color).toBe('#ff0000');
  });

  it('still rewrites every recorded step for a change of policy, and for the host\'s restack', () => {
    const { draw, free } = history();
    expect(parses(() => draw.update(free.id, { policy: { editable: false } }))).toBeGreaterThanOrEqual(42);
    // Each step moved only the drawing now read-only, so each is gone.
    expect(draw.canUndo()).toBe(false);

    const again = history();
    // The user restacks the read-only level, which is theirs to do; the host
    // then puts it where it wants it, and undoing the restack leaves it there.
    expect(again.draw.reorder(again.level.id, 1)).toBe(true);
    expect(parses(() => again.draw.update(again.level.id, { zIndex: 5 }, { force: true }))).toBeGreaterThanOrEqual(44);
    expect(again.draw.undo()).toBe(true);
    expect(again.draw.get(again.level.id)?.zIndex).toBe(5);
  });

  it('puts the moves it skipped into history once the host makes the drawing editable again', () => {
    const draw = new DrawingController(busHost());
    const a = line(draw);
    const b = line(draw, second);
    draw.removeMany([a.id, b.id]);
    expect(draw.undo()).toBe(true);
    draw.update(a.id, { policy: { editable: false } });
    draw.update(a.id, { points: trail(30), style: { lineWidth: 4 } }, { force: true });
    draw.update(a.id, { policy: { editable: true } }, { force: true });
    // The delete, redone and undone, brings the drawing back where and as the host left it.
    expect(draw.redo()).toBe(true);
    expect(draw.get(a.id)).toBeUndefined();
    expect(draw.undo()).toBe(true);
    expect(draw.get(a.id)?.points).toEqual(trail(30));
    expect(draw.get(a.id)?.style.lineWidth).toBe(4);
  });

  it('forgets the moves it held back once a restore replaces the drawings and the history', () => {
    const draw = new DrawingController(busHost());
    const level = line(draw, { policy: { editable: false } });
    draw.update(level.id, { points: trail(30) }, { force: true });
    // The same id comes back as the user's own, from a layout without its policy.
    draw.fromJSON({ version: 2, drawings: [{ id: level.id, tool: 'trend-line', paneIndex: 0, zIndex: 0, style: {}, points: trail(10) }] });
    draw.update(level.id, { points: trail(20) });
    // Any rewrite of the history, here the host retiring a drawing of its own.
    const mark = line(draw, { policy: { editable: false } });
    draw.remove(mark.id, { force: true });
    expect(draw.undo()).toBe(true);
    expect(draw.get(level.id)?.points).toEqual(trail(10));
  });
});

describe('one call holding both a user edit and a host policy', () => {
  it('records the user\'s edit as one step, which takes back only that edit', () => {
    const draw = new DrawingController(busHost());
    const a = line(draw);
    const b = line(draw, { points: [{ time: 5000, price: 50 }, { time: 6000, price: 60 }] });
    draw.updateMany([
      { id: a.id, patch: { style: { color: '#00ff00' } } },
      { id: b.id, patch: { policy: { listed: false }, style: { lineWidth: 6 } } },
    ]);
    expect(draw.undo()).toBe(true);
    expect(draw.get(a.id)?.style.color).toBeUndefined();
    expect(draw.get(b.id)?.style.lineWidth).toBe(6);
    expect(draw.get(b.id)?.policy).toEqual({ listed: false });
    expect(draw.redo()).toBe(true);
    expect(draw.get(a.id)?.style.color).toBe('#00ff00');
  });
});

describe('a policy that arrives from a linked chart', () => {
  it('holds through this chart\'s history, which then offers no press that does nothing', () => {
    const draw = new DrawingController(busHost());
    const a = line(draw);
    const b = line(draw, { points: [{ time: 5000, price: 50 }, { time: 6000, price: 60 }] });
    draw.applyLinkedDrawing(b.id, { ...draw.get(b.id)!, policy: { listed: false } });
    // Taking the drawing back and bringing it again keeps the linked policy.
    expect(draw.undo()).toBe(true);
    expect(draw.get(b.id)).toBeUndefined();
    expect(draw.redo()).toBe(true);
    expect(draw.get(b.id)?.policy).toEqual({ listed: false });
    // A linked read-only policy leaves the step that placed it with nothing to do.
    draw.applyLinkedDrawing(a.id, { ...draw.get(a.id)!, policy: { editable: false } });
    expect(draw.undo()).toBe(true);
    expect(draw.get(b.id)).toBeUndefined();
    expect(draw.canUndo()).toBe(false);
    expect(draw.undo()).toBe(false);
  });

  it('holds when it arrives during a drag of another drawing that is then cancelled', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    draw.fromJSON({ version: 2, drawings: [{ id: 'mine', tool: 'trend-line', paneIndex: 0, zIndex: 0, style: {},
      points: [{ time: 1000, price: 10 }, { time: 2000, price: 20 }] }] });
    const b = line(draw, { points: [{ time: 5000, price: 50 }, { time: 6000, price: 60 }] });
    drag(chart, 'draw:mine', 1000, 10);
    drag(chart, 'draw:mine', 1500, 15);
    draw.applyLinkedDrawing(b.id, { ...draw.get(b.id)!, policy: { editable: false } });
    // The drag is taken back, and with it the history as it stood before the
    // drag, which must not bring back the step the policy emptied.
    expect(draw.cancelDrag()).toBe(true);
    expect(draw.get('mine')?.points[0]).toEqual({ time: 1000, price: 10 });
    expect(draw.canUndo()).toBe(false);
    expect(draw.undo()).toBe(false);
  });

  it('holds for the redo branch a cancelled drag puts back', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    draw.fromJSON({ version: 2, drawings: [{ id: 'mine', tool: 'trend-line', paneIndex: 0, zIndex: 0, style: {},
      points: [{ time: 1000, price: 10 }, { time: 2000, price: 20 }] }] });
    const b = line(draw, { points: [{ time: 5000, price: 50 }, { time: 6000, price: 60 }] });
    const placed = cloneDrawing(draw.get(b.id)!);
    expect(draw.undo()).toBe(true);
    drag(chart, 'draw:mine', 1000, 10);
    drag(chart, 'draw:mine', 1500, 15);
    // The other chart puts the drawing back, read-only.
    draw.applyLinkedDrawing(b.id, { ...placed, policy: { editable: false } });
    expect(draw.cancelDrag()).toBe(true);
    expect(draw.canRedo()).toBe(false);
    expect(draw.redo()).toBe(false);
    expect(draw.get(b.id)?.policy).toEqual({ editable: false });
  });
});

describe('a drawing that cannot be selected (selectable: false)', () => {
  it('never joins the selection, whoever asks', () => {
    const chart = busHost();
    const draw = new DrawingController(chart);
    const ghost = line(draw, { policy: { selectable: false } });
    const other = line(draw);
    draw.select(ghost.id);
    expect(draw.selection()).toEqual([]);
    draw.select([ghost.id, other.id]);
    expect(draw.selection()).toEqual([other.id]);
    draw.select(ghost.id, true);
    expect(draw.selection()).toEqual([other.id]);
    // A click reported on it (the pane's hit test never reports one) reads
    // as a click on empty space: nothing is picked, the selection clears.
    chart.emit('click', { id: `draw:${ghost.id}`, time: 1, price: 1, paneIndex: 0, point: { x: 1, y: 1 } });
    expect(draw.selection()).toEqual([]);
    chart.emit('hover', { id: `draw:${ghost.id}` });
    expect(draw.hovered()).toBeNull();
    // A drag the chart reports on it moves nothing.
    drag(chart, `draw:${ghost.id}`, 1000, 10);
    drag(chart, `draw:${ghost.id}`, 1400, 14);
    chart.emit('drag:end', {});
    expect(draw.get(ghost.id)?.points[0]).toEqual({ time: 1000, price: 10 });
  });

  it('leaves the selection the moment the policy is applied', () => {
    const draw = new DrawingController(busHost());
    const a = line(draw);
    draw.select(a.id);
    draw.update(a.id, { policy: { selectable: false } });
    expect(draw.selection()).toEqual([]);
  });
});

describe('a transient drawing (persistent: false)', () => {
  it('stays out of toJSON, the chart state and a saved group, and still undoes in the session', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const kept = line(draw, { points: [{ time: T0, price: 100 }, { time: T0 + 600, price: 101 }] });
    const temp = line(draw, { policy: { persistent: false }, points: [{ time: T0, price: 99 }, { time: T0 + 600, price: 98 }] });
    draw.createGroup('Both', [kept.id, temp.id]);
    const only = line(draw, { policy: { persistent: false } });
    draw.createGroup('Temporary', [only.id]);
    const doc = draw.toJSON();
    expect(doc.drawings.map((d) => d.id)).toEqual([kept.id]);
    expect(doc.groups).toEqual([{ id: expect.any(String), name: 'Both', members: [kept.id] }]);
    const state = chart.getState().drawings as { drawings: Drawing[] };
    expect(state.drawings.map((d) => d.id)).toEqual([kept.id]);
    expect(JSON.stringify(chart.getState())).not.toContain(temp.id);
    // The model still has it, and a user edit to it still undoes.
    expect(draw.get(temp.id)).toBeDefined();
    draw.update(temp.id, { style: { color: '#333333' } });
    expect(draw.undo()).toBe(true);
    expect(draw.get(temp.id)?.style.color).toBeUndefined();
    expect(draw.get(temp.id)?.policy?.persistent).toBe(false);
    // A restore replaces the transient drawings with what was saved, whether
    // the chart restores its state or the host hands the document back.
    chart.restoreState(JSON.parse(JSON.stringify(chart.getState())));
    expect(draw.drawings().map((d) => d.id)).toEqual([kept.id]);
    line(draw, { policy: { persistent: false } });
    draw.fromJSON(doc);
    expect(draw.drawings().map((d) => d.id)).toEqual([kept.id]);
    draw.destroy();
  });
});

describe('the policy as data', () => {
  it('survives a save and a restore, and the migration keeps only its known flags', () => {
    const draw = new DrawingController(busHost());
    const a = line(draw, { policy: { editable: false, listed: false } });
    const doc = JSON.parse(JSON.stringify(draw.toJSON()));
    expect(doc.drawings[0].policy).toEqual({ editable: false, listed: false });
    const restored = new DrawingController(busHost());
    restored.fromJSON(doc);
    expect(restored.get(a.id)?.policy).toEqual({ editable: false, listed: false });
    expect(restored.remove(a.id)).toBe(false);
    const migrated = migrateDrawings([{ id: 'x', tool: 'trend-line', points: [{ time: 1, price: 1 }],
      policy: { editable: 'no', selectable: false, persistent: true, extra: false, listed: 0 } }]);
    expect(migrated.drawings[0].policy).toEqual({ selectable: false, persistent: true });
    const empty = migrateDrawings([{ id: 'y', tool: 'trend-line', points: [{ time: 1, price: 1 }], policy: { junk: 1 } }]);
    expect(empty.drawings[0].policy).toBeUndefined();
  });

  it('is copied, not shared, by a clone', () => {
    const d: Drawing = { id: 'c', tool: 'trend-line', points: [{ time: 1, price: 1 }], style: {}, paneIndex: 0, zIndex: 0,
      policy: { editable: false } };
    const copy = cloneDrawing(d);
    expect(copy.policy).toEqual({ editable: false });
    expect(copy.policy).not.toBe(d.policy);
  });

  it('leaves a step that never changed anything taking one press, as it always did', () => {
    const draw = new DrawingController(busHost());
    const a = line(draw);
    draw.update(a.id, {});
    expect(draw.undo()).toBe(true);
    expect(draw.get(a.id)).toBeDefined();
    expect(draw.undo()).toBe(true);
    expect(draw.get(a.id)).toBeUndefined();
  });

  it('changes nothing for a drawing without one, or with every flag on', () => {
    const draw = new DrawingController(busHost());
    const plain = line(draw);
    const open = line(draw, { policy: { selectable: true, editable: true, persistent: true, listed: true } });
    draw.select([plain.id, open.id]);
    expect(draw.selection()).toEqual([plain.id, open.id]);
    draw.nudge([plain.id, open.id], 8, 0);
    expect(draw.get(open.id)?.points[0].time).toBe(draw.get(plain.id)?.points[0].time);
    expect(draw.toJSON().drawings.map((d) => d.id)).toEqual([plain.id, open.id]);
    expect(draw.remove(open.id)).toBe(true);
  });
});

/** Identity mapping: time is x, price is y. */
const rc = {
  timeScale: { indexToX: (i: number) => i },
  priceScale: { priceToY: (p: number) => p, format: (p: number) => String(p) },
  dataLayer: { timeToIndexFloat: (t: number) => t },
  plotWidth: 800, plotHeight: 600, priceAxisWidth: 60, dpr: 1, theme: darkTheme,
} as never;

const at = (id: string, extra: Partial<Drawing> = {}): Drawing => ({
  id, tool: 'trend-line', paneIndex: 0, zIndex: 0, style: {},
  points: [{ time: 100, price: 100 }, { time: 300, price: 300 }], ...extra,
});

describe('the pane hit test', () => {
  it('lets a click pass through an unselectable drawing to whatever lies under it', () => {
    const layer = new DrawingLayer('top');
    layer.setDrawings([at('under'), at('ghost', { zIndex: 1, policy: { selectable: false } })]);
    expect(layer.hitTest(200, 200, rc)?.externalId).toBe('draw:under');
    layer.setDrawings([at('ghost', { policy: { selectable: false } })]);
    expect(layer.hitTest(200, 200, rc)).toBeNull();
  });

  it('answers a read-only body as clickable but not draggable, and never offers its handles', () => {
    const layer = new DrawingLayer('top');
    layer.setDrawings([at('fixed', { policy: { editable: false } })]);
    layer.setSelected(['fixed']);
    const body = layer.hitTest(200, 200, rc);
    expect(body?.externalId).toBe('draw:fixed');
    expect(body?.draggable).not.toBe(true);
    // The anchor where a handle would be answers as the body.
    expect(layer.hitTest(100, 100, rc)?.externalId).toBe('draw:fixed');
    layer.setDrawings([at('free')]);
    layer.setSelected(['free']);
    expect(layer.hitTest(100, 100, rc)?.externalId).toBe('draw:free#0');
    expect(layer.hitTest(200, 200, rc)?.draggable).toBe(true);
  });
});

describe('the pane paint', () => {
  /** The line width of every stroke drawn after the shape itself: the anchor handles. */
  const handleStrokes = (extra: Partial<Drawing>): number[] => {
    const layer = new DrawingLayer('top');
    layer.setDrawings([at('d', extra)]);
    layer.setSelected(['d']);
    const bare = new RecordingContext();
    layer.setSelected([]);
    layer.draw(bare as never, rc);
    layer.setSelected(['d']);
    const rec = new RecordingContext();
    layer.draw(rec as never, rc);
    return rec.ops.slice(bare.ops.length).filter((o) => o.type === 'stroke').map((o) => o.lineWidth ?? 0);
  };

  it('draws a selected read-only drawing\'s anchors at the faint hover weight, and an editable one\'s at full weight', () => {
    const editable = handleStrokes({});
    const fixed = handleStrokes({ policy: { editable: false } });
    expect(editable).toHaveLength(2);
    expect(fixed).toHaveLength(2);
    expect(Math.max(...fixed)).toBeLessThan(Math.min(...editable));
  });

  it('draws the faint anchors for a selected read-only drawing under the series too', () => {
    const below = (extra: Partial<Drawing>): number[] => {
      const top = new DrawingLayer('top');
      const bottom = new DrawingLayer('bottom');
      top.setBelow(bottom);
      bottom.setDrawings([at('d', { zIndex: -1, ...extra })]);
      const bare = new RecordingContext();
      top.draw(bare as never, rc);
      bottom.setSelected(['d']);
      const rec = new RecordingContext();
      top.draw(rec as never, rc);
      return rec.ops.slice(bare.ops.length).filter((o) => o.type === 'stroke').map((o) => o.lineWidth ?? 0);
    };
    const editable = below({});
    const fixed = below({ policy: { editable: false } });
    expect(fixed).toHaveLength(2);
    expect(Math.max(...fixed)).toBeLessThan(Math.min(...editable));
  });

  it('offers no anchors on hover over a read-only drawing, where an editable one shows them', () => {
    const hoverStrokes = (extra: Partial<Drawing>): number => {
      const layer = new DrawingLayer('top');
      layer.setDrawings([at('d', extra)]);
      const bare = new RecordingContext();
      layer.draw(bare as never, rc);
      layer.setHovered('d');
      const rec = new RecordingContext();
      layer.draw(rec as never, rc);
      return rec.ops.slice(bare.ops.length).filter((o) => o.type === 'stroke').length;
    };
    expect(hoverStrokes({})).toBe(2);
    expect(hoverStrokes({ policy: { editable: false } })).toBe(0);
  });
});

describe('the object inventory', () => {
  it('omits unlisted drawings, from the list and from their group', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const shown = line(draw);
    const hidden = line(draw, { policy: { listed: false } });
    const alone = line(draw, { policy: { listed: false } });
    draw.createGroup('Mixed', [shown.id, hidden.id]);
    draw.createGroup('Unlisted', [alone.id]);
    const objects = new ChartObjects(chart, { drawings: draw });
    const ids = objects.list().map((row) => row.id);
    expect(ids).toContain('drawing:' + shown.id);
    expect(ids).not.toContain('drawing:' + hidden.id);
    expect(ids).not.toContain('drawing:' + alone.id);
    expect(objects.list().filter((row) => row.kind === 'group').map((row) => row.name)).toEqual(['Mixed']);
    // A group action reaches only the members the inventory shows.
    const group = objects.list().find((row) => row.kind === 'group')!;
    expect(objects.setVisible(group.id, false)).toBe(true);
    expect(draw.get(shown.id)?.visible).toBe(false);
    expect(draw.get(hidden.id)?.visible).not.toBe(false);
    objects.destroy();
    draw.destroy();
  });

  it('removes only the listed members through a group row, and does not ungroup around an unlisted one', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const shown = line(draw);
    const hidden = line(draw, { policy: { listed: false } });
    const group = draw.createGroup('Mixed', [shown.id, hidden.id])!;
    const objects = new ChartObjects(chart, { drawings: draw });
    const row = objects.list().find((item) => item.kind === 'group')!;
    expect(objects.remove(row.id)).toBe(true);
    expect(draw.get(shown.id)).toBeUndefined();
    expect(draw.get(hidden.id)).toBeDefined();
    expect(draw.groups()).toEqual([{ id: group.id, name: 'Mixed', members: [hidden.id] }]);
    // One step, which brings the listed member back into its group.
    expect(draw.undo()).toBe(true);
    expect(draw.groups()).toEqual([{ id: group.id, name: 'Mixed', members: [shown.id, hidden.id] }]);
    // Ungrouping would take the unlisted drawing out of its group too.
    expect(objects.ungroup(row.id)).toBe(false);
    expect(draw.groups()).toEqual([{ id: group.id, name: 'Mixed', members: [shown.id, hidden.id] }]);
    objects.destroy();
    draw.destroy();
  });

  it('skips a group member its source no longer holds, and still offers ungroup and remove', () => {
    const chart = makeChart();
    const a = { id: 'a', tool: 'trend-line', paneIndex: 0, points: [{ time: T0, price: 100 }, { time: T0 + 600, price: 101 }] };
    const calls: unknown[][] = [];
    const source = {
      drawings: () => [a], get: (id: string) => (id === 'a' ? a : undefined), selection: () => [],
      select: () => {}, update: () => {}, remove: () => true,
      groups: () => [{ id: 'g', name: 'G', members: ['gone', 'a'] }],
      removeGroup: (id: string, removeDrawings?: boolean) => { calls.push([id, removeDrawings]); return true; },
    };
    const objects = new ChartObjects(chart, { drawings: source });
    const group = objects.get('group:g')!;
    expect(group.capabilities).toMatchObject({ remove: true, visibility: true, lock: true });
    expect(objects.get('drawing:a')?.groupId).toBe('group:g');
    expect(objects.ungroup('group:g')).toBe(true);
    expect(objects.remove('group:g')).toBe(true);
    expect(calls).toEqual([['g', false], ['g', true]]);
    objects.destroy();
  });

  it('answers ungroup with a boolean whatever the source returns', () => {
    const chart = makeChart();
    const a = { id: 'a', tool: 'trend-line', paneIndex: 0, points: [{ time: T0, price: 100 }, { time: T0 + 600, price: 101 }] };
    const source = {
      drawings: () => [a], get: (id: string) => (id === 'a' ? a : undefined), selection: () => [],
      select: () => {}, update: () => {}, remove: () => true,
      groups: () => [{ id: 'g', name: 'G', members: ['a'] }],
      removeGroup: (() => undefined) as unknown as (id: string) => boolean,
    };
    const objects = new ChartObjects(chart, { drawings: source });
    expect(objects.ungroup('group:g')).toBe(false);
    objects.destroy();
  });

  it('offers a read-only drawing no hide, lock or remove, and an unselectable one no select', () => {
    const chart = makeChart();
    const draw = new DrawingController(chart);
    const fixed = line(draw, { policy: { editable: false } });
    const ghost = line(draw, { policy: { selectable: false } });
    const free = line(draw);
    draw.createGroup('With a fixed member', [fixed.id, free.id], { force: true });
    const objects = new ChartObjects(chart, { drawings: draw, onSettings: () => {} });
    const row = objects.get('drawing:' + fixed.id)!;
    expect(row.capabilities).toMatchObject({ select: true, visibility: false, lock: false, remove: false, settings: true });
    expect(objects.remove(row.id)).toBe(false);
    expect(objects.setVisible(row.id, false)).toBe(false);
    expect(draw.get(fixed.id)).toBeDefined();
    expect(objects.get('drawing:' + ghost.id)?.capabilities.select).toBe(false);
    expect(objects.select('drawing:' + ghost.id)).toBe(false);
    const group = objects.list().find((item) => item.kind === 'group')!;
    expect(group.capabilities).toMatchObject({ visibility: false, lock: false, remove: false });
    objects.destroy();
    draw.destroy();
  });
});
