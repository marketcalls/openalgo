import { afterEach, describe, expect, it, vi } from 'vitest';
import { DrawingController } from '../src/draw/index';
import { DrawingLinkGroup } from '../src/draw/drawing-link';
import { DrawingLayer } from '../src/draw/layer';
import { DataLayer } from '../src/model/data-layer';
import type { DrawingChartHost } from '../src/draw/controller';
import type { Drawing } from '../src/draw/types';

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
function host(interval = 60) {
  const listeners = new Map<string, Set<(p: unknown) => void>>();
  const primitives: DrawingLayer[] = [];
  const dataLayer = new DataLayer();
  dataLayer.setSeriesData(dataLayer.createSeries(), [0, 1, 2].map(i => ({
    time: 1000 + i * interval, open: 100, high: 110, low: 90, close: 105,
  })));
  const chart: DrawingChartHost = {
    on(event, cb) {
      const set = listeners.get(event) ?? new Set(); set.add(cb); listeners.set(event, set);
      return () => { set.delete(cb); };
    },
    emit(event, payload) { for (const cb of [...listeners.get(event) ?? []]) cb(payload); },
    addPrimitive(p) { primitives.push(p as DrawingLayer); },
    removePrimitive(p) { const at = primitives.indexOf(p as DrawingLayer); if (at >= 0) primitives.splice(at, 1); },
    dataLayer, getVisibleLogicalRange: () => ({ from: 0, to: 2 }),
    drawingState: () => null, setDrawingState() {}, panes: () => [{}],
  };
  return { chart, draw: new DrawingController(chart), primitives };
}
const identity = { symbol: 'ABC', exchange: 'NSE' };
const add = (draw: DrawingController, extra: Partial<Drawing> = {}) => draw.add({
  tool: 'trend-line', points: [{ time: 1030, price: 100 }, { time: 1190, price: 110 }],
  paneIndex: 0, style: {}, ...extra,
});
const drag = (chart: DrawingChartHost, id: string) => chart.emit('drag', {
  id: `draw:${id}`, fromTime: 1030, fromPrice: 100, time: 1090, price: 105, paneIndex: 0,
});

describe('drawing linking', () => {
  it('uses all 128 cryptographic bits for lineage when randomUUID is unavailable', async () => {
    vi.resetModules();
    vi.stubGlobal('crypto', { getRandomValues(bytes: Uint8Array) {
      bytes.set([0, 1, 2, 3, 4, 5, 6, 7, 248, 249, 250, 251, 252, 253, 254, 255]);
      return bytes;
    } });
    const { DrawingLinkGroup: IsolatedGroup } = await import('../src/draw/drawing-link');
    const a = host(); const b = host(); const group = new IsolatedGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const first = add(a.draw); const second = add(a.draw);
    const lineage = (id: string) => a.draw.get(id)?.props?.['openalgo-charts/drawing-link'];
    expect(lineage(first.id)).toMatchObject({ id: '0001020304050607f8f9fafbfcfdfeff:1' });
    expect(lineage(second.id)).toMatchObject({ id: '0001020304050607f8f9fafbfcfdfeff:2' });
    expect(b.draw.get(first.id)?.props).toEqual(a.draw.get(first.id)?.props);
    b.draw.update(second.id, { style: { color: '#123456' } });
    expect(a.draw.get(second.id)?.style.color).toBe('#123456');
    group.destroy();
  });

  it('refuses to create a lineage namespace without Web Crypto, and only when a drawing is shared', async () => {
    // Without Web Crypto the tier still loads, for every host that never
    // links charts; the refusal comes at the first lineage a group makes.
    vi.resetModules();
    vi.stubGlobal('crypto', undefined);
    const { DrawingLinkGroup: IsolatedGroup } = await import('../src/draw/drawing-link');
    const a = host(); const b = host(); const group = new IsolatedGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    expect(() => add(a.draw)).toThrow(/^openalgo-charts: drawing links require Web Crypto/);
    group.destroy();
  });

  it('requires opt-in and exact known symbol and exchange, regardless of interval', () => {
    const members = [host(), host(300), host(), host(), host()];
    const group = new DrawingLinkGroup();
    members.forEach((m, i) => group.add(m.chart, m.draw, i < 2 ? identity
      : i === 2 ? { ...identity, exchange: 'BSE' } : i === 3 ? { ...identity, symbol: 'XYZ' } : {}));
    add(members[0].draw);
    expect(members[1].draw.drawings()).toHaveLength(0);
    group.setOptions({ enabled: true });
    const d = add(members[0].draw);
    expect(members[1].draw.drawings()[0]?.points).toEqual(d.points);
    for (const m of members.slice(2)) expect(m.draw.drawings()).toHaveLength(0);
    add(members[0].draw, { paneIndex: 1 });
    expect(members[1].draw.drawings()).toHaveLength(1);
  });

  it('leaves existing drawings local until explicit sharing and handles id collisions', () => {
    const a = host(); const b = host(); const c = host();
    const local = add(a.draw, { id: 'existing' });
    add(b.draw, { id: 'existing', style: { color: '#ff0000' } });
    const group = new DrawingLinkGroup({ enabled: true });
    for (const m of [a, b, c]) group.add(m.chart, m.draw, identity);
    a.draw.update(local.id, { style: { color: '#00ff00' } });
    expect(b.draw.drawings()).toHaveLength(1);
    expect(group.share(a.chart, [local.id])).toBe(1);
    expect(b.draw.drawings()).toHaveLength(2);
    expect(b.draw.get('existing')?.style.color).toBe('#ff0000');
    expect(c.draw.drawings()).toHaveLength(1);
    const shared = b.draw.drawings()[1];
    b.draw.update(shared.id, { style: { levels: [{ ratio: 0.5 }] }, props: { nested: { value: 1 } } });
    expect(a.draw.get(local.id)?.style.levels).toEqual([{ ratio: 0.5 }]);
    shared.style.levels![0].ratio = 7;
    (shared.props!.nested as { value: number }).value = 3;
    expect(a.draw.get(local.id)?.style.levels?.[0].ratio).toBe(0.5);
    expect(a.draw.get(local.id)?.props?.nested).toEqual({ value: 1 });
  });

  it('synchronizes local undo and redo while preserving peer selection and history', () => {
    const a = host(); const b = host();
    const local = add(b.draw); b.draw.select(local.id);
    const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const d = add(a.draw);
    expect(b.draw.selection()).toEqual([local.id]);
    b.draw.undo();
    expect(b.draw.drawings().map(x => x.id)).toEqual([d.id]);
    a.draw.update(d.id, { style: { color: '#abcdef' } });
    b.draw.redo();
    expect(b.draw.get(d.id)?.style.color).toBe('#abcdef');
    a.draw.undo(); expect(b.draw.get(d.id)?.style.color).not.toBe('#abcdef');
    a.draw.redo(); expect(b.draw.get(d.id)?.style.color).toBe('#abcdef');
    a.draw.remove(d.id); expect(b.draw.get(d.id)).toBeUndefined();
    a.draw.undo(); expect(b.draw.get(d.id)?.style.color).toBe('#abcdef');
    expect(b.draw.get(local.id)).toBeDefined();
  });

  it('renders drag previews without persistence, then restores them on cancel and unlink', () => {
    const a = host(); const b = host();
    const painted = new Map<DrawingLayer, readonly Drawing[]>();
    const original = DrawingLayer.prototype.setDrawings;
    vi.spyOn(DrawingLayer.prototype, 'setDrawings').mockImplementation(function (this: DrawingLayer, drawings) {
      painted.set(this, drawings.map(d => structuredClone(d))); original.call(this, drawings);
    });
    const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const d = add(a.draw);
    const points = structuredClone(d.points);
    const rendered = () => b.primitives.flatMap(p => painted.get(p) ?? []).find(x => x.id === d.id);
    drag(a.chart, d.id);
    expect(rendered()?.points[0]).toEqual({ time: 1090, price: 105 });
    expect(b.draw.get(d.id)?.points).toEqual(points);
    a.chart.emit('drag:cancel', {});
    expect(a.draw.get(d.id)?.points).toEqual(points);
    expect(rendered()?.points).toEqual(points);
    drag(a.chart, d.id); group.remove(a.chart);
    expect(rendered()?.points).toEqual(points);
  });

  it('clears previews and old membership when context changes or the controller dies', () => {
    const a = host(); const b = host();
    const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const d = add(a.draw);
    expect(b.draw.get(d.id)).toBeDefined();
    expect(group.has(a.chart)).toBe(true);
    drag(a.chart, d.id);
    b.chart.emit('data:context', { symbol: 'XYZ', exchange: 'NSE', interval: '1h' });
    expect(b.draw.get(d.id)).toBeUndefined();
    a.chart.emit('drag:end', {});
    expect(b.draw.drawings()).toHaveLength(0);
    group.setContext(b.chart, identity);
    a.draw.destroy();
    expect(group.has(a.chart)).toBe(false);
    expect(() => group.destroy()).not.toThrow();
  });

  it('undoes only locally edited fields after a remote change to the same drawing', () => {
    const a = host(); const b = host();
    const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const d = add(a.draw, { style: { color: '#111111' } });
    b.draw.update(d.id, { style: { color: '#222222' } });
    const moved = [{ time: 1200, price: 200 }, { time: 1300, price: 300 }];
    a.draw.update(d.id, { points: moved, style: { lineWidth: 5 } });
    b.draw.undo();
    expect(b.draw.get(d.id)?.points).toEqual(moved);
    expect(b.draw.get(d.id)?.style).toMatchObject({ color: '#111111', lineWidth: 5 });
    expect(a.draw.get(d.id)?.points).toEqual(moved);
    b.draw.redo();
    expect(b.draw.get(d.id)?.style).toMatchObject({ color: '#222222', lineWidth: 5 });
  });

  it('does not treat index shifts from local deletion as edits to another drawing', () => {
    const a = host(); const b = host();
    const local = add(b.draw);
    const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const d = add(a.draw, { style: { color: '#111111' } });
    b.draw.remove(local.id);
    a.draw.update(d.id, { style: { color: '#222222' } });
    b.draw.undo();
    expect(b.draw.get(d.id)?.style.color).toBe('#222222');
    expect(a.draw.get(d.id)?.style.color).toBe('#222222');
  });

  it('clears a received preview when the same instrument changes interval', () => {
    const a = host(); const b = host();
    const painted = new Map<DrawingLayer, readonly Drawing[]>();
    const original = DrawingLayer.prototype.setDrawings;
    vi.spyOn(DrawingLayer.prototype, 'setDrawings').mockImplementation(function (this: DrawingLayer, drawings) {
      painted.set(this, drawings.map(d => structuredClone(d))); original.call(this, drawings);
    });
    const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const d = add(a.draw); const points = structuredClone(d.points);
    drag(a.chart, d.id);
    expect(b.primitives.flatMap(p => painted.get(p) ?? [])[0].points).not.toEqual(points);
    b.chart.emit('data:context', { ...identity, interval: '1h' });
    expect(b.primitives.flatMap(p => painted.get(p) ?? [])[0].points).toEqual(points);
  });

  it('cancels a drag without consuming or invalidating earlier undo and redo', () => {
    const a = host(); const d = add(a.draw);
    a.draw.update(d.id, { style: { color: '#123456' } }); a.draw.undo();
    drag(a.chart, d.id); expect(a.draw.cancel()).toBe(true);
    expect(a.draw.canRedo()).toBe(true);
    a.draw.redo(); expect(a.draw.get(d.id)?.style.color).toBe('#123456');
    a.draw.undo(); a.draw.undo(); expect(a.draw.get(d.id)).toBeUndefined();
  });

  it('reconnects restored shared drawings while keeping restored local drawings local', () => {
    const a = host(); const b = host();
    add(a.draw, { id: 'local', style: { color: '#111111' } });
    add(b.draw, { id: 'local', style: { color: '#222222' } });
    const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const d = add(a.draw); const saved = b.draw.toJSON();
    b.draw.fromJSON(saved);
    a.draw.update(d.id, { style: { color: '#abcdef' } });
    expect(b.draw.drawings()).toHaveLength(2);
    expect(b.draw.get(d.id)?.style.color).toBe('#abcdef');
    b.draw.update('local', { style: { color: '#fedcba' } });
    expect(a.draw.get(d.id)?.style.color).toBe('#abcdef');
    expect(a.draw.get('local')?.style.color).toBe('#111111');
  });

  it('does not write chart state while clearing a destroyed member preview', () => {
    const a = host(); const b = host();
    const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const d = add(a.draw); drag(a.chart, d.id);
    const write = vi.spyOn(b.chart, 'setDrawingState');
    Object.assign(b.chart, { isDestroyed: true });
    b.chart.emit('destroy', {});
    expect(group.has(b.chart)).toBe(false);
    expect(write).not.toHaveBeenCalled();
    expect(() => group.destroy()).not.toThrow();
  });

  it('reconnects restored copies automatically by matching persisted lineage and identity', () => {
    const a = host(); const b = host();
    const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const d = add(a.draw, { props: { custom: { value: 5 } } });
    const saved = JSON.parse(JSON.stringify(a.draw.toJSON()));
    a.draw.destroy();
    const rebuilt = host(300); rebuilt.draw.fromJSON(saved);
    b.draw.update(d.id, { style: { color: '#111111' } });
    group.add(rebuilt.chart, rebuilt.draw, identity);
    expect(rebuilt.draw.get(d.id)?.style.color).toBe('#111111');
    b.draw.update(d.id, { style: { color: '#abcdef' } });
    expect(rebuilt.draw.get(d.id)?.style.color).toBe('#abcdef');
    group.share(rebuilt.chart);
    expect(b.draw.drawings()).toHaveLength(1);
    group.share(rebuilt.chart);
    expect(b.draw.drawings()).toHaveLength(1);
    rebuilt.draw.update(d.id, { style: { color: '#123456' } });
    expect(b.draw.get(d.id)?.style.color).toBe('#123456');
    expect(b.draw.get(d.id)?.props?.custom).toEqual({ value: 5 });
  });

  it('gives duplicated and pasted drawings their own lineage, even while linking is disabled', async () => {
    const a = host(); const b = host();
    const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const d = add(a.draw);
    group.setOptions({ enabled: false });
    const duplicate = a.draw.duplicate([d.id])[0];
    await a.draw.copy(d.id); const pasted = (await a.draw.paste())[0];
    group.setOptions({ enabled: true }); group.share(a.chart);
    expect(b.draw.drawings()).toHaveLength(3);
    a.draw.update(duplicate.id, { style: { color: '#123456' } });
    a.draw.update(pasted.id, { style: { color: '#abcdef' } });
    expect(b.draw.get(d.id)?.style.color).not.toBe('#123456');
    expect(b.draw.get(d.id)?.style.color).not.toBe('#abcdef');
  });

  it('restores the local drag on an explicit context change', () => {
    const a = host(); const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); const d = add(a.draw); const points = structuredClone(d.points);
    drag(a.chart, d.id); group.setContext(a.chart, { ...identity, symbol: 'XYZ' });
    expect(a.draw.get(d.id)?.points).toEqual(points);
  });

  it('can destroy a controller with an active drag after its chart has already died', () => {
    const a = host(); const d = add(a.draw); drag(a.chart, d.id);
    const write = vi.spyOn(a.chart, 'setDrawingState');
    Object.assign(a.chart, { isDestroyed: true });
    a.chart.emit('destroy', {}); a.draw.destroy();
    expect(write).not.toHaveBeenCalled();
  });

  it('does not resurrect a remotely deleted drawing when undoing an earlier local update', () => {
    const a = host(); const b = host(); const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const d = add(a.draw); b.draw.update(d.id, { style: { color: '#123456' } });
    a.draw.remove(d.id); b.draw.undo();
    expect(b.draw.get(d.id)).toBeUndefined(); expect(a.draw.get(d.id)).toBeUndefined();
    b.draw.redo();
    expect(b.draw.get(d.id)).toBeUndefined(); expect(a.draw.get(d.id)).toBeUndefined();
    a.draw.undo(); expect(b.draw.get(d.id)).toBeDefined();
  });

  it('uses a host identity resolver on context changes without changing chart data identity', () => {
    const a = host(); const b = host(); const group = new DrawingLinkGroup({ enabled: true });
    let symbol = 'ABC';
    group.add(a.chart, a.draw, identity);
    group.add(b.chart, b.draw, () => ({ symbol, exchange: 'NSE' }));
    const d = add(a.draw);
    expect(b.draw.get(d.id)).toBeDefined();
    b.chart.emit('data:context', { symbol, interval: '1h' });
    a.draw.update(d.id, { style: { color: '#123456' } });
    expect(b.draw.get(d.id)?.style.color).toBe('#123456');
    symbol = 'XYZ'; b.chart.emit('data:context', { symbol, interval: '1h' });
    expect(b.draw.get(d.id)).toBeUndefined();
  });

  it('treats missing or failed resolver identity as ineligible', () => {
    const a = host(); const b = host(); const group = new DrawingLinkGroup({ enabled: true });
    let fail = false;
    group.add(a.chart, a.draw, identity);
    group.add(b.chart, b.draw, () => { if (fail) throw new Error('Unavailable'); return identity; });
    const d = add(a.draw); expect(b.draw.get(d.id)).toBeDefined();
    fail = true;
    expect(() => b.chart.emit('data:context', {})).not.toThrow();
    expect(b.draw.get(d.id)).toBeUndefined();
    group.add(b.chart, b.draw, () => null);
    add(a.draw); expect(b.draw.drawings()).toHaveLength(0);
  });

  it('reconnects lineage after both controllers and the group are restored', () => {
    const a = host(); const b = host(); const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const d = add(a.draw); const left = a.draw.toJSON(); const right = b.draw.toJSON();
    group.destroy();
    const next = new DrawingLinkGroup({ enabled: true });
    a.draw.fromJSON(left); b.draw.fromJSON(right);
    next.add(a.chart, a.draw, identity); next.add(b.chart, b.draw, identity);
    expect(a.draw.drawings()).toHaveLength(1); expect(b.draw.drawings()).toHaveLength(1);
    b.draw.update(d.id, { style: { color: '#abcdef' } });
    expect(a.draw.get(d.id)?.style.color).toBe('#abcdef');
  });

  it('preserves equal-z order of shared drawings without moving unrelated local slots', () => {
    const a = host(); const b = host(); const local = add(b.draw);
    const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const first = add(a.draw); const second = add(a.draw);
    a.draw.sendToBack(second.id);
    expect(a.draw.drawings().map(d => d.id)).toEqual([second.id, first.id]);
    expect(b.draw.drawings().map(d => d.id)).toEqual([local.id, second.id, first.id]);
    a.draw.undo();
    expect(b.draw.drawings().map(d => d.id)).toEqual([local.id, first.id, second.id]);
    a.draw.redo();
    expect(b.draw.drawings().map(d => d.id)).toEqual([local.id, second.id, first.id]);
  });

  it('preserves a later remote reorder when undoing and redoing a local property edit', () => {
    const a = host(); const b = host(); const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const first = add(a.draw, { style: { color: '#111111' } }); const second = add(a.draw);
    b.draw.update(first.id, { style: { color: '#222222' } });
    a.draw.sendToBack(second.id);
    b.draw.undo();
    for (const member of [a, b]) {
      expect(member.draw.drawings().map(d => d.id)).toEqual([second.id, first.id]);
      expect(member.draw.get(first.id)?.style.color).toBe('#111111');
    }
    b.draw.redo();
    for (const member of [a, b]) {
      expect(member.draw.drawings().map(d => d.id)).toEqual([second.id, first.id]);
      expect(member.draw.get(first.id)?.style.color).toBe('#222222');
    }
  });

  it('adopts live peer order when reconnecting saved shared copies', () => {
    const a = host(); const b = host(); const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const first = add(a.draw); const second = add(a.draw); const saved = a.draw.toJSON();
    a.draw.destroy(); b.draw.sendToBack(second.id);
    const rebuilt = host(); rebuilt.draw.fromJSON(saved); group.add(rebuilt.chart, rebuilt.draw, identity);
    expect(rebuilt.draw.drawings().map(d => d.id)).toEqual([second.id, first.id]);
  });

  it('does not reconnect lineage across unknown identity, a different exchange, or a disabled group', () => {
    const a = host(); const b = host(); const group = new DrawingLinkGroup({ enabled: true });
    group.add(a.chart, a.draw, identity); group.add(b.chart, b.draw, identity);
    const d = add(a.draw, { style: { color: '#111111' } }); const saved = a.draw.toJSON();
    a.draw.destroy();
    for (const context of [{ ...identity, exchange: 'BSE' }, {}]) {
      const rebuilt = host(); rebuilt.draw.fromJSON(saved); group.add(rebuilt.chart, rebuilt.draw, context);
      b.draw.update(d.id, { style: { color: '#222222' } });
      expect(rebuilt.draw.get(d.id)?.style.color).toBe('#111111'); group.remove(rebuilt.chart);
    }
    group.setOptions({ enabled: false });
    const rebuilt = host(); rebuilt.draw.fromJSON(saved); group.add(rebuilt.chart, rebuilt.draw, identity);
    expect(rebuilt.draw.get(d.id)?.style.color).toBe('#111111');
  });
});
