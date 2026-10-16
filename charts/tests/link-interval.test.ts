import { describe, expect, it, vi } from 'vitest';
import { createLinkGroup, type LinkChart } from '../src/link';
import { DataLayer } from '../src/model/data-layer';
import type { IPrimitive } from '../src/primitives/primitive';

class MemberChart implements LinkChart {
  readonly dataLayer = new DataLayer();
  readonly listeners = new Map<string, Set<(payload: unknown) => void>>();
  isDestroyed = false;
  on(event: string, cb: (payload: unknown) => void) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event)!.add(cb);
    return () => { this.listeners.get(event)?.delete(cb); };
  }
  emit(event: string, payload: unknown) {
    for (const cb of [...(this.listeners.get(event) ?? [])]) cb(payload);
  }
  panes() { return this.isDestroyed ? [] : [{}]; }
  getVisibleLogicalRange() { return { from: 0, to: 10 }; }
  setVisibleLogicalRange() {}
  addPrimitive(_primitive: IPrimitive) {}
  removePrimitive(_primitive: IPrimitive) {}
}

describe('independent interval linking', () => {
  it('is off by default and remembers the latest selection before enabling', () => {
    const group = createLinkGroup();
    const a = new MemberChart(); const b = new MemberChart();
    const follow = vi.fn();
    group.add(a, { interval: '1m' });
    group.add(b, { interval: '1h', onInterval: follow });
    expect(group.options().interval).toBe(false);
    group.setInterval(a, '5m');
    expect(follow).not.toHaveBeenCalled();
    group.setOptions({ interval: true });
    expect(follow).toHaveBeenCalledExactlyOnceWith('5m', b);
    expect(group.interval()).toBe('5m');
    expect(group.options().symbol).toBe(false);
  });

  it('follows events and imperative changes without notifying the leader', () => {
    const group = createLinkGroup({ interval: true });
    const a = new MemberChart(); const b = new MemberChart();
    const first = vi.fn(); const second = vi.fn();
    group.add(a, { interval: '1m', onInterval: first });
    group.add(b, { interval: '1m', onInterval: second });
    a.emit('interval', { interval: '15m' });
    expect(second).toHaveBeenLastCalledWith('15m', b);
    expect(first).not.toHaveBeenCalled();
    b.emit('interval', '1h');
    expect(first).toHaveBeenLastCalledWith('1h', a);
    group.setInterval(a, '1h');
    expect(second).toHaveBeenCalledTimes(1);
  });

  it('converges a late member and releases every listener when destroyed', () => {
    const group = createLinkGroup({ interval: true });
    const a = new MemberChart(); const b = new MemberChart();
    const follow = vi.fn();
    group.add(a, { interval: '15m' });
    group.add(b, { interval: '1m', onInterval: follow });
    expect(follow).toHaveBeenCalledExactlyOnceWith('15m', b);
    group.destroy();
    expect(group.interval()).toBeNull();
    expect([...a.listeners.values()].every(list => list.size === 0)).toBe(true);
    expect([...b.listeners.values()].every(list => list.size === 0)).toBe(true);
    a.emit('interval', '1h');
    expect(follow).toHaveBeenCalledTimes(1);
  });

  it('does not let a follower echo overwrite the agreed interval', () => {
    const group = createLinkGroup({ interval: true });
    const a = new MemberChart(); const b = new MemberChart(); const c = new MemberChart();
    const follow = vi.fn();
    group.add(a, { interval: '1m' });
    group.add(b, { interval: '1m', onInterval: () => b.emit('interval', '1h') });
    group.add(c, { interval: '1m', onInterval: follow });
    group.setInterval(a, '5m');
    expect(follow).toHaveBeenCalledExactlyOnceWith('5m', c);
    expect(group.interval()).toBe('5m');
    const late = new MemberChart(); const lateFollow = vi.fn();
    group.add(late, { interval: '1m', onInterval: lateFollow });
    expect(lateFollow).toHaveBeenCalledExactlyOnceWith('5m', late);
  });

  it('does not call members removed during a broadcast', () => {
    const group = createLinkGroup({ interval: true });
    const a = new MemberChart(); const b = new MemberChart(); const c = new MemberChart();
    const follow = vi.fn();
    group.add(a, { interval: '1m' });
    group.add(b, { interval: '1m', onInterval: () => group.remove(c) });
    group.add(c, { interval: '1m', onInterval: follow });
    group.setInterval(a, '5m');
    expect(follow).not.toHaveBeenCalled();
    expect(c.listeners.get('interval')?.size).toBe(0);
  });

  it('ignores invalid events and reports from nonmembers', () => {
    const group = createLinkGroup({ interval: true });
    const a = new MemberChart(); const b = new MemberChart();
    const follow = vi.fn();
    group.add(a, { interval: '1m' });
    group.add(b, { interval: '1m', onInterval: follow });
    for (const invalid of [null, undefined, '', '   ', 5, {}, { interval: 5 }]) a.emit('interval', invalid);
    group.setInterval(new MemberChart(), '5m');
    expect(group.interval()).toBe('1m');
    expect(follow).not.toHaveBeenCalled();
  });

  it('can update member callbacks without adding duplicate subscriptions', () => {
    const group = createLinkGroup({ interval: true });
    const a = new MemberChart(); const b = new MemberChart(); const follow = vi.fn();
    group.add(a, { interval: '1m' }); group.add(b, { interval: '1m' });
    group.add(b, { onInterval: follow });
    a.emit('interval', '5m');
    expect(follow).toHaveBeenCalledExactlyOnceWith('5m', b);
    expect(b.listeners.get('interval')?.size).toBe(1);
  });

  it('allows a host to refuse an unsupported interval without recording acceptance', () => {
    const group = createLinkGroup({ interval: true });
    const a = new MemberChart(); const b = new MemberChart();
    const follow = vi.fn().mockReturnValueOnce(false).mockReturnValue(true);
    group.add(a, { interval: '1m' });
    group.add(b, { interval: '1m', onInterval: follow });
    group.setInterval(a, '1h');
    group.setInterval(a, '1h');
    expect(follow).toHaveBeenCalledTimes(2);
    group.setInterval(a, '1h');
    expect(follow).toHaveBeenCalledTimes(2);
  });
});
