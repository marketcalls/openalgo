import { describe, expect, it, vi } from 'vitest';
import { ReplayGroup, type ReplayGroupMember } from '../src/replay/group';
import { ReplayController, type ReplayScheduler } from '../src/replay/controller';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';

const T = 1700000000;
function member(id: string, seconds = 60, count = 20, start = 0) {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), { document: doc, shortcuts: false,
    pixelRatio: () => 1, raf: { schedule: () => 0 } });
  chart.applySize(600, 400);
  const series = chart.addSeries('candlestick');
  const data = Array.from({ length: count }, (_, index) => ({ time: T + start + seconds * index,
    open: 100, high: 110, low: 90, close: 105 + index, volume: 10 + index }));
  series.setData(data);
  const input: ReplayGroupMember = { id, chart, options: { timing: { barEndTime: bar => bar.time + seconds } } };
  return { chart, series, data, input };
}
class Clock {
  public ms = 0;
  public timers = new Map<() => void, number>();
  public now = () => this.ms;
  public schedule: ReplayScheduler = (callback, ms) => {
    this.timers.set(callback, ms);
    return () => { this.timers.delete(callback); };
  };
  public advance(ms: number) { this.ms += ms; for (const callback of [...this.timers.keys()]) callback(); }
}

describe('ReplayGroup', () => {
  it('projects unequal intervals and later histories onto one time', () => {
    const a = member('a'), b = member('b', 300, 4), c = member('c', 60, 5, 300);
    const group = new ReplayGroup([a.input, b.input, c.input], { scope: 'all', startTime: T + 120 });
    expect([a.series.getData().length, b.series.getData().length, c.series.getData().length]).toEqual([2, 0, 0]);
    group.seekTime(T + 300);
    expect([a.series.getData().length, b.series.getData().length, c.series.getData().length]).toEqual([5, 1, 0]);
    group.step();
    expect(group.state().time).toBe(T + 360);
    expect(c.series.getData()).toHaveLength(1);
    group.destroy();
    expect(a.series.getData()).toEqual(a.data);
    expect(b.series.getData()).toEqual(b.data);
    expect(c.series.getData()).toEqual(c.data);
  });

  it('shares partial observation times without summing open interest or revealing final candles', () => {
    const a = member('a', 60, 5), b = member('b', 300, 1);
    // Minute volumes that fit inside the five-minute bar's, as one feed's would.
    b.input.options.subBars = a.data.map((bar, index) => ({ ...bar, volume: 3, oi: index * 10 }));
    b.input.options.timing.subBarEndTime = bar => bar.time + 60;
    const group = new ReplayGroup([a.input, b.input], { scope: 'all', startTime: T + 180 });
    expect(b.series.getData()[0]).toMatchObject({ close: 107, volume: 9, oi: 20 });
    expect(group.state().total).toBe(5);
    group.seekTime(T + 300);
    expect(b.series.getData()).toEqual(b.data);
    group.destroy();
  });

  it('uses one timer, changes speed, caps catch-up and stops on the union end', () => {
    const a = member('a', 60, 100), b = member('b', 300, 20), clock = new Clock();
    const group = new ReplayGroup([a.input, b.input], { scope: 'all', now: clock.now, scheduler: clock.schedule });
    group.play(); expect(clock.timers.size).toBe(1);
    clock.advance(1000); expect(group.state().time).toBe(T + 120);
    group.play({ speed: 2 }); expect(clock.timers.size).toBe(1);
    clock.advance(500); expect(group.state().time).toBe(T + 180);
    clock.advance(100000); expect(group.state().time).toBe(T + 780);
    group.pause(); expect(clock.timers.size).toBe(0);
    group.seek(group.state().total - 2);
    group.play(); clock.advance(500);
    expect(group.state().time).toBe(T + 6000);
    expect(group.state().playing).toBe(false);
    expect(clock.timers.size).toBe(0);
    group.destroy();
  });

  it('changes scope at the same time and restores charts leaving the focused set', () => {
    const a = member('a'), b = member('b', 300, 4), clock = new Clock();
    b.chart.timeScale.setBarSpacing(7); b.chart.timeScale.setRightOffset(3);
    const group = new ReplayGroup([a.input, b.input], { startTime: T + 180, now: clock.now, scheduler: clock.schedule });
    expect(group.state()).toMatchObject({ scope: 'focused', focusedId: 'a', time: T + 180 });
    expect(b.series.getData()).toEqual(b.data);
    group.play();
    group.setScope('all');
    expect(group.state().time).toBe(T + 180);
    expect(b.series.getData()).toEqual([]);
    expect(clock.timers.size).toBe(1);
    group.setScope('focused', 'b');
    expect(a.series.getData()).toEqual(a.data);
    expect(group.state().time).toBe(T + 180);
    clock.advance(1000);
    expect(group.state().time).toBe(T + 300);
    expect(b.series.getData()).toHaveLength(1);
    group.setScope('focused', 'a');
    expect(b.series.getData()).toEqual(b.data);
    expect(b.chart.timeScale.barSpacing).toBe(7);
    expect(b.chart.timeScale.rightOffset).toBe(3);
    group.destroy(); expect(clock.timers.size).toBe(0);
  });

  it('captures current inactive-chart data on entry and restores it without dropping newer bars', () => {
    const a = member('a'), b = member('b');
    const group = new ReplayGroup([a.input, b.input]);
    const latest = [...b.data, { ...b.data[0], time: T + 1200, close: 200 }];
    b.series.setData(latest);
    group.setScope('all'); group.stop();
    expect(b.series.getData()).toEqual(latest);
    const next = [...a.data, { ...a.data[0], time: T + 1200, close: 201 }];
    a.series.setData(next);
    group.play(); group.stop();
    expect(a.series.getData()).toEqual(next);
    group.destroy();
  });

  it('preserves focused replay when fresh data for an entering member fails validation', () => {
    const a = member('a'), b = member('b'), clock = new Clock();
    b.input.options.series = b.series;
    const group = new ReplayGroup([a.input, b.input], { now: clock.now, scheduler: clock.schedule });
    group.play();
    const before = group.state();
    const read = vi.spyOn(b.series, 'getData').mockImplementation(() => { throw new Error('history unavailable'); });
    expect(() => group.setScope('all')).toThrow('history unavailable');
    expect(group.state()).toEqual(before);
    expect(clock.timers.size).toBe(1);
    read.mockRestore(); group.destroy();
  });

  it('notifies hosts after every member reaches the frame and reports group playback state', () => {
    const a = member('a'), b = member('b'), clock = new Clock();
    const frames: number[][] = [], groupFrames: number[][] = [], playing: boolean[] = [];
    a.input.options.onFrame = () => frames.push([a.series.getData().length, b.series.getData().length]);
    a.chart.on('replay:frame', state => playing.push((state as { playing: boolean }).playing));
    const group = new ReplayGroup([a.input, b.input], { scope: 'all', now: clock.now, scheduler: clock.schedule,
      onChange: state => groupFrames.push(state.members.map(value => value.state.index)) });
    group.play(); clock.advance(1000);
    expect(frames).toEqual([[1, 1], [2, 2]]);
    expect(groupFrames[groupFrames.length - 1]).toEqual([1, 1]);
    expect(playing[playing.length - 1]).toBe(true);
    expect(group.state().members.every(value => value.state.playing)).toBe(true);
    group.destroy();
  });

  it('validates every member before changing a chart', () => {
    const a = member('a'), b = member('b');
    b.input.options.timing.barEndTime = () => NaN;
    expect(() => new ReplayGroup([a.input, b.input], { scope: 'all' })).toThrow(/time/);
    expect(a.series.getData()).toEqual(a.data);
    expect(b.series.getData()).toEqual(b.data);
    expect(() => new ReplayGroup([], {})).toThrow(/member/);
    expect(() => new ReplayGroup([a.input, { ...a.input, id: 'other' }])).toThrow(/chart/);
    expect(() => new ReplayGroup([a.input, { ...a.input }])).toThrow(/id/);
    const group = new ReplayGroup([a.input]);
    group.destroy();
  });

  it('rejects a nonrepresentable clock interval before changing data', () => {
    const a = member('a');
    expect(() => new ReplayGroup([a.input], { barMs: Number.MAX_VALUE, speed: Number.MIN_VALUE })).toThrow(/interval/);
    expect(a.series.getData()).toEqual(a.data);
    const group = new ReplayGroup([a.input], { barMs: Number.MAX_VALUE });
    expect(() => group.play({ speed: Number.MIN_VALUE })).toThrow(/interval/);
    expect(group.state().active).toBe(true);
    group.destroy();
  });

  it('rejects overlapping ownership and active standalone replay without mutation', () => {
    const a = member('a');
    const group = new ReplayGroup([a.input]);
    expect(() => new ReplayGroup([a.input])).toThrow(/own/);
    expect(a.series.getData()).toHaveLength(1);
    group.stop();
    expect(() => new ReplayGroup([a.input])).toThrow(/own/);
    group.destroy();
    const standalone = new ReplayController(a.chart);
    expect(() => new ReplayGroup([a.input])).toThrow(/replay/);
    standalone.stop();
    const replacement = new ReplayGroup([a.input]);
    replacement.destroy();
  });

  it('rejects invalid controls without losing the current session or its timer', () => {
    const a = member('a'), clock = new Clock();
    const group = new ReplayGroup([a.input], { now: clock.now, scheduler: clock.schedule });
    group.play();
    const before = group.state();
    expect(() => group.seekTime(NaN)).toThrow(/time/);
    expect(() => group.seek(Infinity)).toThrow(/index/);
    expect(() => group.step(Infinity)).toThrow(/step/);
    expect(() => group.play({ speed: 0 })).toThrow(/speed/);
    expect(() => group.setScope('focused', 'missing')).toThrow(/focus/);
    expect(group.state()).toEqual(before);
    expect(clock.timers.size).toBe(1);
    group.destroy();
  });

  it('handles empty histories and zero/backward steps before any observation', () => {
    const empty = member('empty', 60, 0), a = member('a');
    const group = new ReplayGroup([empty.input, a.input]);
    expect(group.state()).toMatchObject({ time: null, total: 0, playing: false });
    group.play(); group.step(); group.stepBack();
    group.setScope('all');
    expect(group.state().time).toBe(T + 60);
    group.seekTime(T);
    group.stepBack(); group.step(0);
    expect(a.series.getData()).toEqual([]);
    expect(group.state().time).toBe(T);
    group.destroy();
  });

  it('stops and can re-enter from the captured initial time', () => {
    const a = member('a'), clock = new Clock();
    const group = new ReplayGroup([a.input], { startTime: T + 180, now: clock.now, scheduler: clock.schedule });
    group.step(5); group.stop(); group.stop();
    expect(a.series.getData()).toEqual(a.data);
    expect(group.state()).toMatchObject({ active: false, time: T + 180 });
    group.play();
    expect(a.series.getData()).toHaveLength(3);
    expect(clock.timers.size).toBe(1);
    group.destroy(); group.destroy();
    expect(() => group.step()).toThrow(/destroy/);
  });

  it('restores survivors and releases the timer when an active chart is destroyed', () => {
    const a = member('a'), b = member('b'), clock = new Clock();
    const group = new ReplayGroup([a.input, b.input], { scope: 'all', now: clock.now, scheduler: clock.schedule });
    group.play(); a.chart.destroy();
    expect(clock.timers.size).toBe(0);
    expect(a.chart.panes()).toHaveLength(0);
    expect(b.series.getData()).toEqual(b.data);
    expect(group.state()).toMatchObject({ active: false, destroyed: true });
    const replacement = new ReplayGroup([b.input]);
    replacement.destroy();
  });

  it('removes an inactive destroyed chart while focused replay continues', () => {
    const a = member('a'), b = member('b'), clock = new Clock();
    const group = new ReplayGroup([a.input, b.input], { now: clock.now, scheduler: clock.schedule });
    group.play(); b.chart.destroy(); clock.advance(1000);
    expect(group.state()).toMatchObject({ active: true, destroyed: false, time: T + 120 });
    expect(group.state().members.map(value => value.id)).toEqual(['a']);
    expect(clock.timers.size).toBe(1);
    group.destroy();
  });

  it('finishes notifications when an inactive chart is removed during a member frame', () => {
    const a = member('a'), b = member('b'), clock = new Clock();
    let armed = false, frames = 0;
    a.input.options.onFrame = () => { frames++; };
    const group = new ReplayGroup([a.input, b.input], { now: clock.now, scheduler: clock.schedule,
      onChange: state => { if (armed && state.active) group.pause(); } });
    group.play(); armed = true;
    a.chart.once('replay:frame', () => b.chart.destroy());
    clock.advance(1000);
    expect(group.state()).toMatchObject({ active: true, destroyed: false, playing: false, time: T + 120 });
    expect(frames).toBe(2);
    group.destroy();
  });

  it('releases its own lifecycle listener without removing another subscriber', () => {
    const a = member('a');
    let other = 0, disposed = 0;
    a.chart.on('destroy', () => { other++; });
    const on = a.chart.on.bind(a.chart);
    vi.spyOn(a.chart, 'on').mockImplementation((event, callback) => {
      const off = on(event, callback);
      return () => { disposed++; off(); };
    });
    const group = new ReplayGroup([a.input]);
    group.destroy();
    // The group's own listener and the one its member controller holds while
    // it owns the chart's data, each released once.
    expect(disposed).toBe(2);
    a.chart.destroy();
    expect(other).toBe(1);
  });

  it('cancels a scheduler returned after a synchronous stop and ignores stale callbacks', () => {
    const a = member('a'), clock = new Clock();
    let last: (() => void) | undefined;
    const group = new ReplayGroup([a.input], { now: clock.now, scheduler: callback => {
      last = callback;
      const cancel = clock.schedule(callback, 1000);
      group.stop();
      return cancel;
    } });
    group.play();
    expect(clock.timers.size).toBe(0);
    clock.ms = 10000; last!();
    expect(group.state()).toMatchObject({ active: false, playing: false });
    expect(a.series.getData()).toEqual(a.data);
    group.destroy();
  });

  it('rolls back all members and releases ownership after a projection failure', () => {
    const a = member('a'), b = member('b');
    const group = new ReplayGroup([a.input, b.input], { scope: 'all' });
    const set = b.series.setData.bind(b.series);
    vi.spyOn(b.series, 'setData').mockImplementationOnce(() => { throw new Error('source failed'); }).mockImplementation(set);
    expect(() => group.seekTime(T + 180)).toThrow('source failed');
    expect(a.series.getData()).toEqual(a.data);
    expect(b.series.getData()).toEqual(b.data);
    expect(group.state().destroyed).toBe(true);
    const next = new ReplayGroup([a.input, b.input]); next.destroy();
  });

  it('releases construction resources when the host callback throws', () => {
    const a = member('a'), b = member('b');
    expect(() => new ReplayGroup([a.input, b.input], { scope: 'all',
      onChange: () => { throw new Error('host failed'); } })).toThrow('host failed');
    expect(a.series.getData()).toEqual(a.data);
    expect(b.series.getData()).toEqual(b.data);
    const next = new ReplayGroup([a.input, b.input]); next.destroy();
  });

  it('stops the timer and restores data when a later frame callback throws', () => {
    const a = member('a'), clock = new Clock();
    const group = new ReplayGroup([a.input], { now: clock.now, scheduler: clock.schedule,
      onChange: state => { if (state.time === T + 120) throw new Error('frame failed'); } });
    group.play();
    expect(() => clock.advance(1000)).toThrow('frame failed');
    expect(clock.timers.size).toBe(0);
    expect(a.series.getData()).toEqual(a.data);
  });

  it('does not resume stale projection after a chart event stops the group', () => {
    const a = member('a'), b = member('b');
    const group = new ReplayGroup([a.input, b.input], { scope: 'all' });
    a.chart.once('replay:frame', () => group.stop());
    group.seekTime(T + 180);
    expect(group.state().active).toBe(false);
    expect(a.series.getData()).toEqual(a.data);
    expect(b.series.getData()).toEqual(b.data);
    group.destroy();
  });
});
