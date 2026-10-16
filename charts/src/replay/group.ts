import { CATCH_UP_LIMIT, ReplayController, type ReplayChartHost, type ReplayOptions, type ReplayScheduler, type ReplayState } from './controller';
import type { ReplayTiming } from './timeline';
import { replayWindow, setReplayWindow } from '../model/replay-window';
import { monotonicNow, repeat } from '../helpers/timers';

export type ReplayScope = 'focused' | 'all';

/** Chart implements this; headless hosts may supply the lifecycle hooks too. */
export interface ReplayGroupChartHost extends ReplayChartHost {
  readonly isDestroyed?: boolean;
  on?(event: 'destroy', callback: () => void): () => void;
}

export interface ReplayGroupMember {
  id: string;
  chart: ReplayGroupChartHost;
  /** Transport and clock options belong to the group. */
  options: Pick<ReplayOptions, 'series' | 'bars' | 'subBars' | 'onFrame'> & { timing: ReplayTiming };
}

export interface ReplayGroupState {
  active: boolean;
  destroyed: boolean;
  scope: ReplayScope;
  focusedId: string;
  /** UTC availability time, or null when the active histories have no observations. */
  time: number | null;
  /** Index in the union of active observation times; -1 before the first. */
  index: number;
  total: number;
  playing: boolean;
  speed: number;
  members: readonly { id: string; active: boolean; state: ReplayState }[];
}

export interface ReplayGroupOptions {
  /** Default focused. Changing toolbar focus alone does not redirect replay. */
  scope?: ReplayScope;
  /** Default the first member. */
  focusedId?: string;
  startTime?: number;
  /** Wall-clock milliseconds per observation at speed 1. Default 1000. */
  barMs?: number;
  speed?: number;
  now?: () => number;
  scheduler?: ReplayScheduler;
  /**
   * Runs after all active charts reach a frame or transport transition. One that
   * throws ends replay, as any failure inside a transport call does: the group
   * restores its charts, destroys itself and rethrows.
   */
  onChange?: (state: ReplayGroupState) => void;
}

interface Member {
  id: string;
  chart: ReplayGroupChartHost;
  options: ReplayGroupMember['options'];
  controller: ReplayController;
  dispose?: (() => void) | undefined;
  dead: boolean;
}

/** Externally driven controllers share transport state without owning timers. */
class GroupController extends ReplayController {
  public constructor(chart: ReplayGroupChartHost, options: ReplayOptions,
    private readonly _transport: () => { playing: boolean; speed: number }) {
    super(chart, { ...options, autoStart: false });
  }
  public override state(): ReplayState { return { ...super.state(), ...this._transport() }; }
}

const owners = new WeakMap<object, ReplayGroup>();
const error = (message: string): Error => new Error('openalgo-charts: replay group ' + message);
function finite(value: number, name: string): void {
  if (!Number.isFinite(value)) throw error(name + ' must be finite');
}
function positive(value: number, name: string): void {
  finite(value, name);
  if (value <= 0) throw error(name + ' must be positive');
}
function floorIndex(times: readonly number[], time: number | null): number {
  if (time === null) return -1;
  let from = 0, to = times.length;
  while (from < to) {
    const mid = (from + to) >>> 1;
    if (times[mid]! <= time) from = mid + 1; // from <= mid < to <= length
    else to = mid;
  }
  return from - 1;
}

/** One opt-in clock driving validated ReplayControllers by availability time. */
export class ReplayGroup {
  private _members: Member[] = [];
  private _activeIds = new Set<string>();
  private _times: number[] = [];
  private _scope: ReplayScope;
  private _focusedId: string;
  private _time: number | null = null;
  private _startTime: number | null = null;
  private _active = false;
  private _destroyed = false;
  private _playing = false;
  private _busy = false;
  private _closing = false;
  private _revision = 0;
  private _speed: number;
  private readonly _barMs: number;
  private readonly _now: () => number;
  private readonly _scheduler: ReplayScheduler;
  private readonly _onChange?: ((state: ReplayGroupState) => void) | undefined;
  private _cancel: (() => void) | null = null;
  private _clockRevision = 0;
  private _lastAdvance = 0;
  private _pending: { callback: (state: ReplayState) => void; state: ReplayState }[] = [];

  public constructor(members: readonly ReplayGroupMember[], options: ReplayGroupOptions = {}) {
    if (!members.length) throw error('needs at least one member');
    this._scope = options.scope ?? 'focused';
    this._focusedId = options.focusedId ?? members[0]!.id; // not empty, checked above
    this._speed = options.speed ?? 1;
    this._barMs = options.barMs ?? 1000;
    positive(this._speed, 'speed'); positive(this._barMs, 'barMs');
    positive(this._barMs / this._speed, 'clock interval');
    if (options.startTime !== undefined) finite(options.startTime, 'start time');
    this._now = options.now ?? monotonicNow;
    this._scheduler = options.scheduler ?? repeat;
    this._onChange = options.onChange;
    const ids = new Set<string>(), charts = new Set<object>();
    for (const member of members) {
      if (typeof member.id !== 'string' || !member.id.trim() || ids.has(member.id)) throw error('member id must be unique and nonempty');
      if (charts.has(member.chart)) throw error('cannot drive the same chart twice');
      if (owners.has(member.chart)) throw error('chart already has a replay group owner');
      if (member.chart.isDestroyed) throw error('cannot own a destroyed chart');
      if (replayWindow(member.chart)) throw error('chart already has active replay');
      if (typeof member.options?.timing?.barEndTime !== 'function') throw error('member needs explicit timing');
      ids.add(member.id); charts.add(member.chart);
    }
    this._validateScope(this._scope, this._focusedId, ids);
    // Every constructor only prepares. A bad later member cannot strand an
    // earlier chart in replay before the group has acquired ownership.
    for (const member of members) {
      const input = { id: member.id, chart: member.chart,
        options: { ...member.options, timing: { ...member.options.timing } } };
      this._members.push({ ...input, controller: this._prepare(input), dead: false });
    }
    this._execute(() => {
      for (const member of this._members) {
        owners.set(member.chart, this);
        member.dispose = member.chart.on?.('destroy', () => this._chartGone(member));
      }
      this._rebuildTimes();
      this._startTime = options.startTime ?? this._times[0] ?? null;
      this._apply(this._startTime);
    });
  }

  public state(): ReplayGroupState {
    return { active: this._active, destroyed: this._destroyed, scope: this._scope,
      focusedId: this._focusedId, time: this._time, index: floorIndex(this._times, this._time),
      total: this._times.length, playing: this._playing, speed: this._speed,
      members: this._members.map(member => ({ id: member.id, active: this._activeIds.has(member.id), state: member.controller.state() })) };
  }

  public seekTime(time: number): void {
    finite(time, 'time'); this._check();
    if (this._active && time === this._time) return;
    const prepared = this._prepareEntering();
    this._execute(() => { this._install(prepared); this._apply(time); });
  }

  /** Seek an observation index, clamped to the active timeline. */
  public seek(index: number): void {
    finite(index, 'index'); this._check();
    const prepared = this._prepareEntering();
    this._execute(() => {
      this._install(prepared);
      const time = this._times[Math.max(0, Math.min(this._times.length - 1, Math.floor(index)))];
      if (time !== undefined && (!this._active || this._time !== time)) this._apply(time);
    });
  }

  public step(n = 1): void { this._move(n); }
  public stepBack(n = 1): void { this._move(-n); }
  private _move(delta: number): void {
    finite(delta, 'step'); this._check();
    const steps = Math.trunc(delta);
    if (!steps) return;
    const prepared = this._prepareEntering();
    this._execute(() => {
      this._install(prepared);
      const index = floorIndex(this._times, this._time);
      if (steps < 0 && index < 0) return;
      const time = this._times[Math.max(0, Math.min(this._times.length - 1, index + steps))];
      if (time !== undefined && (!this._active || this._time !== time)) this._apply(time);
    });
  }

  public setScope(scope: ReplayScope, focusedId = this._focusedId): void {
    this._check();
    this._validateScope(scope, focusedId, new Set(this._members.map(member => member.id)));
    if (scope === this._scope && focusedId === this._focusedId) return;
    const prepared = this._prepareEntering(scope, focusedId);
    this._execute(() => {
      this._scope = scope; this._focusedId = focusedId;
      if (!this._install(prepared)) this._rebuildTimes();
      this._apply(this._time ?? this._times[0] ?? null);
    });
  }

  public play(options: { speed?: number } = {}): void {
    const speed = options.speed ?? this._speed;
    positive(speed, 'speed'); positive(this._barMs / speed, 'clock interval'); this._check();
    const prepared = this._prepareEntering();
    this._execute(() => {
      this._install(prepared);
      if (!this._active) this._apply(this._startTime ?? this._times[0] ?? null);
      if (!this._active || this._destroyed) return;
      this._speed = speed;
      if (this._atEnd()) { this._emit('replay:end'); this._notify(); return; }
      this._clearClock();
      this._lastAdvance = this._now(); finite(this._lastAdvance, 'clock');
      this._playing = true;
      const revision = ++this._clockRevision;
      const cancel = this._scheduler(() => { if (revision === this._clockRevision) this._tick(); }, this._barMs / this._speed);
      if (this._playing && !this._destroyed && revision === this._clockRevision) this._cancel = cancel;
      else cancel();
      this._emit('replay:play'); this._notify();
    });
  }

  public pause(): void {
    this._check();
    if (!this._playing) return;
    this._execute(() => { this._clearClock(); this._emit('replay:pause'); this._notify(); });
  }

  /** Restore data/viewports, retaining the captured session for later re-entry. */
  public stop(): void {
    if (this._destroyed || this._closing || !this._active) return;
    this._execute(() => { this._cleanup(false); this._notify(); });
  }

  /** Restore surviving charts and release snapshots, listeners and ownership. */
  public destroy(): void {
    if (this._destroyed || this._closing) return;
    this._execute(() => { this._cleanup(true); this._notify(); });
  }

  private _validateScope(scope: ReplayScope, focusedId: string, ids: Set<string>): void {
    if (scope !== 'all' && scope !== 'focused') throw error('scope must be focused or all');
    if (!ids.has(focusedId)) throw error('focus must name a member');
  }
  private _prepare(member: Pick<Member, 'id' | 'chart' | 'options'>): ReplayController {
    const callback = member.options.onFrame;
    return new GroupController(member.chart, { ...member.options,
      onFrame: callback ? state => this._pending.push({ callback, state }) : undefined },
    () => ({ playing: this._playing && this._activeIds.has(member.id), speed: this._speed }));
  }
  private _prepareEntering(scope = this._scope, focusedId = this._focusedId): Map<Member, ReplayController> {
    const prepared = new Map<Member, ReplayController>();
    for (const member of this._members) if ((scope === 'all' || member.id === focusedId) && !this._activeIds.has(member.id)) {
      if (member.dead || member.chart.isDestroyed) throw error('cannot enter a destroyed chart');
      if (replayWindow(member.chart)) throw error('chart already has active replay');
      // Inactive charts may receive live bars. Snapshot at entry so leaving
      // replay cannot discard data that arrived while another chart owned it.
      prepared.set(member, this._prepare(member));
    }
    return prepared;
  }
  private _install(prepared: Map<Member, ReplayController>): boolean {
    if (!prepared.size) return false;
    for (const [member, controller] of prepared) member.controller = controller;
    this._rebuildTimes();
    return true;
  }
  private _wanted(member: Member): boolean { return this._scope === 'all' || member.id === this._focusedId; }
  private _rebuildTimes(): void {
    const times = new Set<number>();
    for (const member of this._members) if (this._wanted(member)) {
      for (const time of member.controller.timePoints()) times.add(time);
    }
    this._times = [...times].sort((a, b) => a - b);
  }
  private _check(): void {
    if (this._destroyed) throw error('has been destroyed');
    if (this._busy) throw error('cannot change transport during a member frame');
    if (this._members.some(member => this._activeIds.has(member.id) && member.chart.isDestroyed)) {
      this.destroy(); throw error('active chart was destroyed');
    }
  }

  private _apply(time: number | null): void {
    const revision = ++this._revision, previous = this._activeIds;
    this._busy = true;
    this._pending = [];
    this._time = time; this._active = true;
    this._activeIds = new Set(this._members.filter(member => this._wanted(member)).map(member => member.id));
    try {
      for (const member of this._members) {
        if (revision !== this._revision) return;
        if (previous.has(member.id) && !this._activeIds.has(member.id)) member.controller.stop();
      }
      for (const member of this._members) {
        if (revision !== this._revision) return;
        if (this._activeIds.has(member.id)) member.controller.seekTime(time ?? 0);
      }
    } finally { this._busy = false; }
    const pending = this._pending; this._pending = [];
    for (const notice of pending) {
      if (revision !== this._revision) return;
      notice.callback(notice.state);
    }
    if (revision !== this._revision) return;
    if (this._playing && this._atEnd()) {
      this._clearClock(); this._emit('replay:pause'); this._emit('replay:end');
    } else if (this._playing) {
      this._emit('replay:play', member => !previous.has(member.id));
    }
    if (revision === this._revision) this._notify();
  }

  private _atEnd(): boolean { return !this._times.length || floorIndex(this._times, this._time) >= this._times.length - 1; }
  private _tick(): void {
    if (!this._playing) return;
    this._execute(() => {
      const now = this._now(); finite(now, 'clock');
      const interval = this._barMs / this._speed;
      if (now < this._lastAdvance) { this._lastAdvance = now; return; }
      let due = Math.floor((now - this._lastAdvance) / interval);
      if (due <= 0) return;
      if (due > CATCH_UP_LIMIT) { due = CATCH_UP_LIMIT; this._lastAdvance = now; }
      else this._lastAdvance += due * interval;
      this._move(due);
    });
  }
  private _clearClock(): void {
    this._playing = false; this._clockRevision++;
    const cancel = this._cancel; this._cancel = null;
    cancel?.();
  }
  private _emit(event: string, include: (member: Member) => boolean = () => true): void {
    const revision = this._revision;
    for (const member of this._members) {
      if (revision !== this._revision) return;
      if (this._activeIds.has(member.id) && include(member)) member.chart.emit(event, member.controller.state());
    }
  }
  private _notify(): void { this._onChange?.(this.state()); }
  private _execute(action: () => void): void {
    try { action(); }
    catch (failure) {
      try { this._cleanup(true); } catch { /* Finish other cleanup without replacing the original failure. */ }
      throw failure;
    }
  }

  private _chartGone(member: Member): void {
    member.dead = true;
    if (this._closing || this._destroyed) return;
    if (this._activeIds.has(member.id) || member.id === this._focusedId) { this.destroy(); return; }
    this._execute(() => {
      const writing = this._busy;
      if (!writing) this._revision++;
      member.dispose?.(); owners.delete(member.chart);
      this._members = this._members.filter(value => value !== member);
      this._rebuildTimes();
      // The current frame still owes its member callbacks. Removing an
      // inactive chart does not invalidate that frame or notify inside it.
      if (!writing) this._notify();
    });
  }
  private _cleanup(terminal: boolean): void {
    if (this._closing) return;
    this._closing = true; this._revision++;
    const previous = this._activeIds;
    this._activeIds = new Set(); this._active = false; this._pending = [];
    let failure: unknown;
    const attempt = (action: () => void): void => { try { action(); } catch (caught) { failure ??= caught; } };
    attempt(() => this._clearClock());
    for (const member of this._members) if (previous.has(member.id)) {
      if (member.dead || member.chart.isDestroyed) attempt(() => setReplayWindow(member.chart));
      else attempt(() => member.controller.stop());
    }
    terminal ||= failure !== undefined || this._members.some(member => member.dead && (previous.has(member.id) || member.id === this._focusedId));
    for (const member of this._members) if (terminal || member.dead) {
      attempt(() => member.dispose?.());
      if (owners.get(member.chart) === this) owners.delete(member.chart);
    }
    this._time = this._startTime;
    if (terminal) { this._destroyed = true; this._members = []; this._times = []; }
    else { this._members = this._members.filter(member => !member.dead); this._rebuildTimes(); }
    this._closing = false;
    if (failure !== undefined) throw failure;
  }
}
