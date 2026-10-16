/**
 * Chart linking groups: a grid of charts that behaves as one workspace.
 *
 * Headless, in the spirit of `ComparisonController` and `ReplayController`. It
 * ships no DOM, so the host draws its own link badge / colour chips and decides
 * which charts belong to which group.
 *
 * Each channel switches independently because a user routinely
 * wants one without the others (mirror the cursor across four timeframes but
 * keep each zoom; or slave every chart's symbol but let each keep its own
 * window):
 *
 * - **crosshair**: hovering one chart marks the same instant on the others.
 * - **viewport**: panning or zooming one moves the others to the same window.
 * - **symbol**: changing the instrument on one changes it on the others.
 * - **interval**: changing a timeframe asks each following host to adopt it.
 * - **chartType**: changing the chart style (candles, bars, a line) asks each
 *   following host to adopt it, the same way. Colours, scales and the status
 *   line are appearance, not chart type: a user linking candles to candles
 *   may well want each chart's own colours.
 * - **appearance**: visual settings pass through a structural host adapter.
 * - **drawings**: the group decides which charts share drawings, and the draw
 *   tier moves them, only between charts on the same instrument. See `./drawings`.
 *
 * Four decisions carry the design.
 *
 * 1. **Everything crosses a chart boundary as a time, never as a logical
 *    index.** See `./align`. This is the whole difficulty of the feature: the
 *    naive version works perfectly on two charts of the same symbol and
 *    interval, which is how it would ship broken.
 *
 * 2. **A follower's crosshair is a primitive, not the chart's own crosshair.**
 *    The engine's crosshair belongs to the pointer inside that chart; a linked
 *    one is a second, weaker mark that must not fight it. See `./crosshair`.
 *
 * 3. **One re-entrancy guard covers every channel.** A syncs B, B echoes
 *    back to A, and the pair either oscillates forever or blows the stack. Any
 *    member event that arrives *while the group is broadcasting* is an echo of
 *    that broadcast by definition (a human cannot pan two charts in one call
 *    stack), so it is dropped. The guard is deliberately group-wide rather than
 *    per channel: a symbol change that reloads data can move a viewport, and
 *    that second-order echo is the same bug wearing a different hat.
 *
 * 4. **The group never keeps a destroyed chart alive.** `Chart.destroy` sets
 *    `isDestroyed` and emits `'destroy'`, so a member is released the moment it
 *    dies rather than at the next channel event. A `LinkChart` that is not a
 *    `Chart` may report neither, so members are also probed by pane count
 *    before every use (the price pane can never be removed by any other route) and
 *    dropped on the spot, which matters because `addPrimitive` on a destroyed
 *    chart would resurrect a pane.
 *
 * The host owns instrument selection and loading. It tells the group a selection changed (by
 * emitting `'symbol'` on the chart's own event bus, or by calling `setSymbol`),
 * and it supplies the per-member `onSymbol` callback that actually loads the
 * new instrument's bars. A member without `onSymbol` broadcasts symbol changes
 * but never receives them, which is how a host pins one chart of a grid.
 */
import type { IPrimitive } from '../primitives/primitive';
import type { LogicalRange } from '../scale/time-scale';
import { LinkCrosshair } from './crosshair';
import { followerIndex, followerRange, type LinkDataLayer, type LinkMissingPolicy } from './align';
import { filterLinkAppearance, type LinkAppearanceAdapter } from './appearance';
import type { LinkDrawingsAdapter } from './drawings';

/**
 * The slice of the chart a link group drives. `Chart` satisfies it; declaring
 * it structurally keeps the group testable against a stub, which is the only
 * practical way to prove the feedback guard (the engine's own programmatic
 * setters do not echo today, and the guard exists for the day they do and for
 * the host callbacks that echo right now).
 */
export interface LinkChart {
  on(event: string, cb: (payload: unknown) => void): () => void;
  getVisibleLogicalRange(): LogicalRange;
  setVisibleLogicalRange(range: LogicalRange): void;
  readonly dataLayer: LinkDataLayer;
  /**
   * Set by `Chart`. Optional so the group stays testable against a stub and
   * usable by a host wrapping something that is not a `Chart`, but when it is
   * there it is the answer: an empty pane list is only ever an inference.
   */
  readonly isDestroyed?: boolean;
  /** Only the count is read: the fallback destruction probe. See `alive`. */
  panes(): readonly unknown[];
  addPrimitive(primitive: IPrimitive, paneIndex?: number): void;
  removePrimitive(primitive: IPrimitive): void;
  /** Optional readout support alongside the group's vertical marker. */
  setLinkedCrosshairIndex?(index: number | null): void;
}

export interface LinkOptions {
  /** Mirror the hovered instant onto every other member. Default true. */
  crosshair?: boolean;
  /** Mirror pan and zoom as a wall-clock window. Default true. */
  viewport?: boolean;
  /** Mirror the instrument, via each member's `onSymbol`. Default false. */
  symbol?: boolean;
  /** Mirror the timeframe, via each member's `onInterval`. Default false. */
  interval?: boolean;
  /** Mirror the chart type (candles, bars, a line), via each member's `onChartType`. Default false. */
  chartType?: boolean;
  /** Copy visual chart settings through each member's adapter. Default false. */
  appearance?: boolean;
  /**
   * Share drawings through each member's `drawings` adapter. Default false.
   * Only charts on the same instrument share, and only what is drawn while it
   * is on: see `LinkDrawingsAdapter` for the whole rule.
   */
  drawings?: boolean;
  /** What a follower does with an instant it has no bar for. Default 'nearest'. */
  whenMissing?: LinkMissingPolicy;
}

export interface LinkMemberOptions {
  /** Visual settings only; no instrument, timeframe, study or trading state is copied. */
  appearance?: LinkAppearanceAdapter;
  /** The instrument this chart is showing right now, if the host tracks one. */
  symbol?: string;
  /**
   * Load `symbol` into this chart. The group calls it; the host does the work
   * (fetch bars, `series.setData`). Omit to make the member symbol-read-only:
   * it still broadcasts its own changes, it just never follows anyone else's.
   */
  onSymbol?: (symbol: string, chart: LinkChart) => void;
  /** The interval this chart is showing, if the host tracks one. */
  interval?: string;
  /** Apply the interval synchronously; return false to refuse an unsupported token. */
  onInterval?: (interval: string, chart: LinkChart) => boolean | void;
  /** The chart type this chart is showing (a registered chart type id), if the host tracks one. */
  chartType?: string;
  /**
   * Show `chartType` on this chart. Return false to refuse one it cannot draw,
   * which leaves the member on its own type and asks again on the next change.
   * Omit to keep this chart's type out of the group's reach.
   */
  onChartType?: (chartType: string, chart: LinkChart) => boolean | void;
  /** This chart's side of drawing sharing. Without one it never shares drawings. */
  drawings?: LinkDrawingsAdapter;
}

/** Every option resolved, as `options()` reports them. */
export type ResolvedLinkOptions = Required<LinkOptions>;

const DEFAULT_OPTIONS: ResolvedLinkOptions = {
  crosshair: true,
  viewport: true,
  symbol: false,
  interval: false,
  chartType: false,
  appearance: false,
  drawings: false,
  whenMissing: 'nearest',
};

/**
 * The channels that carry one host-owned token and follow through a member
 * callback. Interval and chart type behave identically (reported, recorded
 * even while off, converged when switched on, refusable by a follower), so
 * they share one implementation rather than two copies that could drift.
 */
type TokenChannel = 'interval' | 'chartType';
type TokenFollower = (value: string, chart: LinkChart) => boolean | void;
const TOKEN_CHANNELS: readonly TokenChannel[] = ['interval', 'chartType'];
const FOLLOWERS = { interval: 'onInterval', chartType: 'onChartType' } as const;

interface Member {
  chart: LinkChart;
  appearance: LinkAppearanceAdapter | null;
  symbol: string | null;
  onSymbol: ((symbol: string, chart: LinkChart) => void) | null;
  /** What this chart shows on each token channel, as last reported or accepted. */
  tokens: Record<TokenChannel, string | null>;
  follow: Record<TokenChannel, TokenFollower | null>;
  drawings: LinkDrawingsAdapter | null;
  /** True between the adapter's `join` and its `leave`, so neither is ever called twice in a row. */
  sharing: boolean;
  unsubscribe: (() => void)[];
  /** One linked crosshair per pane, mirroring the global crosshair's reach. */
  crosshairs: LinkCrosshair[];
}

/**
 * Is this chart still usable?
 *
 * `isDestroyed` when the member reports it, because a flag the chart sets
 * itself cannot be wrong. The pane-count probe stays as the fallback for a host
 * whose `LinkChart` is not a `Chart`: the price pane, in whatever slot, can never
 * be removed by any other route, so an empty pane list still means destruction there.
 */
function alive(chart: LinkChart): boolean {
  if (chart.isDestroyed === true) return false;
  return chart.panes().length > 0;
}

function validToken(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

export class LinkGroup {
  private readonly _members: Member[] = [];
  private _options: ResolvedLinkOptions;
  /** True while the group is applying a change to followers. See decision 3. */
  private _broadcasting = false;
  private _symbol: string | null = null;
  /** The latest selection on each token channel, kept even while that channel is off. */
  private readonly _tokens: Record<TokenChannel, string | null> = { interval: null, chartType: null };
  private _destroyed = false;

  public constructor(options: LinkOptions = {}) {
    this._options = { ...DEFAULT_OPTIONS, ...options };
  }

  public options(): ResolvedLinkOptions {
    return { ...this._options };
  }

  /**
   * Flip switches at runtime. Turning `crosshair` off clears the linked lines
   * immediately rather than leaving the last one frozen on every follower;
   * turning `symbol` on makes the group agree on the instrument it already
   * knows, because a switch that only takes effect on the *next* change would
   * leave a linked grid visibly unlinked.
   *
   * `interval` and `chartType` converge the same way, on the latest selection.
   * Turning `drawings` on joins every member that has an adapter, and turning
   * it off makes each leave.
   *
   * `viewport` has no equivalent convergence: nothing in the group says which
   * member's window the others should have adopted, so it takes effect on the
   * next pan or zoom.
   */
  public setOptions(patch: LinkOptions): void {
    const before = this._options;
    this._options = { ...before, ...patch };
    if (before.crosshair && !this._options.crosshair) {
      for (const m of this._members) this._detachCrosshairs(m);
    }
    if (!before.symbol && this._options.symbol) this._convergeSymbol();
    for (const channel of TOKEN_CHANNELS) {
      if (!before[channel] && this._options[channel]) this._convergeToken(channel);
    }
    const sharing = this._options.drawings === true;
    if (before.drawings !== sharing) for (const m of [...this._members]) this._share(m, sharing);
  }

  public members(): readonly LinkChart[] {
    this._prune();
    return this._members.map((m) => m.chart);
  }

  public has(chart: LinkChart): boolean {
    return this._find(chart) !== null;
  }

  /** The instrument the group has agreed on, or null if nobody declared one. */
  public symbol(): string | null {
    return this._symbol;
  }

  /** Latest interval selected by a member, even while interval linking is off. */
  public interval(): string | null {
    return this._tokens.interval;
  }

  /** Latest chart type selected by a member, even while chart type linking is off. */
  public chartType(): string | null {
    return this._tokens.chartType;
  }

  /**
   * The member's own logical index its linked crosshair is marking, or null
   * when it is showing none (it is the chart being hovered, the leader's
   * instant falls outside its coverage, or crosshair sync is off).
   *
   * A host wanting the linked bar's OHLC reads it back with
   * `chart.dataLayer.indexToTime(...)`, the same way a native crosshair readout
   * does.
   */
  public crosshairIndex(chart: LinkChart): number | null {
    return this._find(chart)?.crosshairs[0]?.index() ?? null;
  }

  /**
   * Put a chart in the group. Adding one twice updates its member options
   * instead of double-subscribing.
   *
   * A member joining a group that already has a symbol adopts it (when symbol
   * sync is on and it can follow), because joining a linked workspace is
   * exactly the moment a user expects the new chart to fall in line. The same
   * holds for the interval and the chart type, and a member joining while
   * drawings are shared joins the sharing.
   */
  public add(chart: LinkChart, member: LinkMemberOptions = {}): void {
    if (this._destroyed || !alive(chart)) return;
    const existing = this._find(chart);
    if (existing !== null) {
      if (member.symbol !== undefined) existing.symbol = member.symbol;
      if (member.onSymbol !== undefined) existing.onSymbol = member.onSymbol;
      for (const channel of TOKEN_CHANNELS) {
        const value = member[channel], follow = member[FOLLOWERS[channel]];
        if (validToken(value)) existing.tokens[channel] = value;
        if (follow !== undefined) existing.follow[channel] = follow;
      }
      if (member.appearance !== undefined) existing.appearance = member.appearance;
      if (member.drawings !== undefined && member.drawings !== existing.drawings) {
        // The old adapter leaves before the new one joins, so a host moving a
        // chart's drawings to another sharer never has it in both at once.
        this._share(existing, false);
        existing.drawings = member.drawings;
      }
      for (const channel of TOKEN_CHANNELS) if (this._options[channel]) this._convergeToken(channel);
      this._share(existing, this._options.drawings === true);
      return;
    }
    const entry: Member = {
      chart,
      appearance: member.appearance ?? null,
      symbol: member.symbol ?? null,
      onSymbol: member.onSymbol ?? null,
      tokens: {
        interval: validToken(member.interval) ? member.interval : null,
        chartType: validToken(member.chartType) ? member.chartType : null,
      },
      follow: { interval: member.onInterval ?? null, chartType: member.onChartType ?? null },
      drawings: member.drawings ?? null,
      sharing: false,
      unsubscribe: [],
      crosshairs: [],
    };
    entry.unsubscribe.push(
      chart.on('crosshair:move', (p) => this._onCrosshair(entry, p)),
      chart.on('pan', () => this._onViewport(entry)),
      chart.on('zoom', () => this._onViewport(entry)),
      chart.on('symbol', (p) => this._onSymbolEvent(entry, p)),
      chart.on('style:change', () => this.syncAppearance(chart)),
      ...TOKEN_CHANNELS.map(channel => chart.on(channel, (p) => {
        const value = typeof p === 'string' ? p : (p as Record<string, unknown> | null)?.[channel];
        if (validToken(value)) this._applyToken(entry, channel, value);
      })),
      // Without this the group holds a destroyed chart (and every listener
      // closure it captured) until the next channel event happens to prune it,
      // which for a group whose other member is idle is forever.
      chart.on('destroy', () => this._prune()),
    );
    this._members.push(entry);
    // The first member to declare an instrument establishes the group's.
    if (this._symbol === null && entry.symbol !== null) this._symbol = entry.symbol;
    if (this._options.symbol) this._convergeSymbol();
    for (const channel of TOKEN_CHANNELS) {
      if (this._tokens[channel] === null) this._tokens[channel] = entry.tokens[channel];
      if (this._options[channel]) this._convergeToken(channel);
    }
    // Strictly true: an option spread in as undefined is off, and must not leave unjoined.
    this._share(entry, this._options.drawings === true);
  }

  /** Take a chart out of the group. Safe to call twice, and after `destroy`. */
  public remove(chart: LinkChart): void {
    const i = this._members.findIndex((m) => m.chart === chart);
    if (i < 0) return;
    // Out of the list before any host callback runs, so an adapter's `leave`
    // that removes this chart again finds nothing left to splice.
    const [member] = this._members.splice(i, 1);
    this._release(member!); // `i` was found in the list
  }

  /**
   * The host reporting an instrument change on one member: the imperative twin
   * of emitting `'symbol'` on that chart's event bus. Records it and, when
   * symbol sync is on, loads it into every other member that can follow.
   */
  public setSymbol(chart: LinkChart, symbol: string): void {
    const entry = this._find(chart);
    if (entry === null) return;
    this._applySymbol(entry, symbol);
  }

  /** Report a host-owned interval selection; followers opt in through `onInterval`. */
  public setInterval(chart: LinkChart, interval: string): void {
    this._report(chart, 'interval', interval);
  }

  /**
   * Report a host-owned chart type selection: the imperative twin of emitting
   * `'chartType'` on that chart's event bus. Followers opt in through `onChartType`.
   */
  public setChartType(chart: LinkChart, chartType: string): void {
    this._report(chart, 'chartType', chartType);
  }

  /** Report an appearance edit. `style:change` does this automatically for settings patches. */
  public syncAppearance(chart: LinkChart): void {
    if (this._destroyed || this._broadcasting || !this._options.appearance || !alive(chart)) return;
    const from = this._find(chart);
    if (from?.appearance === null || from === null) return;
    const values = filterLinkAppearance(from.appearance.read());
    if (Object.keys(values).length === 0) return;
    this._broadcast(from, target => target.appearance?.apply({ ...values }));
  }

  /** Unlink everything: no listeners, no linked crosshairs, no references. */
  public destroy(): void {
    this._destroyed = true;
    // Emptied first: a drawings adapter's `leave` is host code and may call back in.
    for (const m of this._members.splice(0)) this._release(m);
    this._symbol = null;
    this._tokens.interval = null;
    this._tokens.chartType = null;
  }

  // ── channels ──────────────────────────────────────────────────────────────

  private _onCrosshair(from: Member, payload: unknown): void {
    if (!this._options.crosshair) return;
    const time = (payload as { time?: number | null } | null)?.time ?? null;
    this._broadcast(from, (target) => {
      const index = time === null
        ? null
        : followerIndex(target.chart.dataLayer, time, this._options.whenMissing);
      this._setCrosshair(target, index);
    }, (leader) => {
      // The leader is drawing its own, real crosshair, and a linked one on top of
      // it would double the line under the user's cursor.
      this._setCrosshair(leader, null);
    });
  }

  private _onViewport(from: Member): void {
    if (!this._options.viewport) return;
    if (!alive(from.chart)) { this._prune(); return; }
    const range = from.chart.getVisibleLogicalRange();
    const leaderData = from.chart.dataLayer;
    this._broadcast(from, (target) => {
      const mapped = followerRange(leaderData, target.chart.dataLayer, range);
      if (mapped !== null) target.chart.setVisibleLogicalRange(mapped);
    });
  }

  private _onSymbolEvent(from: Member, payload: unknown): void {
    const symbol = typeof payload === 'string'
      ? payload
      : (payload as { symbol?: unknown } | null)?.symbol;
    if (typeof symbol !== 'string' || symbol.length === 0) return;
    this._applySymbol(from, symbol);
  }

  private _applySymbol(from: Member, symbol: string): void {
    // The same guard as the token channels: a follower's loader may announce
    // the name it normalised to while the group is still applying the leader's,
    // and that echo must not become the group's instrument.
    if (this._broadcasting || this._destroyed || !alive(from.chart)) return;
    // Recorded even with the switch off, so turning it on later has something
    // to converge on rather than silently agreeing on a stale instrument.
    from.symbol = symbol;
    this._symbol = symbol;
    if (!this._options.symbol) return;
    this._broadcast(from, (target) => {
      if (target.symbol === symbol) return;
      target.symbol = symbol;
      target.onSymbol?.(symbol, target.chart);
    });
  }

  /** Push the group's agreed symbol onto everyone who is not already on it. */
  private _convergeSymbol(): void {
    const symbol = this._symbol;
    if (symbol === null || !this._options.symbol) return;
    this._broadcast(null, (target) => {
      if (target.symbol === symbol) return;
      target.symbol = symbol;
      target.onSymbol?.(symbol, target.chart);
    });
  }

  private _report(chart: LinkChart, channel: TokenChannel, value: string): void {
    const entry = this._find(chart);
    if (entry !== null && validToken(value)) this._applyToken(entry, channel, value);
  }

  private _applyToken(from: Member, channel: TokenChannel, value: string): void {
    // A follower can echo a normalized token while applying the request. Such
    // an echo must not replace the leader's selection before the guard runs.
    if (this._broadcasting || this._destroyed || !alive(from.chart)) return;
    from.tokens[channel] = value;
    this._tokens[channel] = value;
    if (this._options[channel]) this._broadcast(from, target => this._followToken(target, channel, value));
  }

  private _followToken(target: Member, channel: TokenChannel, value: string): void {
    const follow = target.follow[channel];
    if (target.tokens[channel] === value || follow === null) return;
    // Recorded only when accepted, so a refusal is asked again next time.
    if (follow(value, target.chart) !== false) target.tokens[channel] = value;
  }

  private _convergeToken(channel: TokenChannel): void {
    const value = this._tokens[channel];
    if (value !== null && this._options[channel]) {
      this._broadcast(null, target => this._followToken(target, channel, value));
    }
  }

  /** Join or leave drawing sharing, each at most once in a row. See `LinkDrawingsAdapter`. */
  private _share(member: Member, on: boolean): void {
    if (member.drawings === null || member.sharing === on) return;
    // A host callback may have removed the member, or destroyed the group, meanwhile.
    if (on && (this._destroyed || !this._members.includes(member) || !alive(member.chart))) return;
    member.sharing = on;
    if (on) member.drawings.join();
    else member.drawings.leave();
  }

  // ── plumbing ──────────────────────────────────────────────────────────────

  /**
   * Run `apply` on every member except the originator, exactly once, with the
   * echo guard held. `onLeader` (optional) runs on the originator itself.
   *
   * Re-entrant calls return without doing anything, which is what breaks the
   * A -> B -> A loop: the inner call is always an echo of the outer one.
   */
  private _broadcast(
    from: Member | null,
    apply: (target: Member) => void,
    onLeader?: (leader: Member) => void,
  ): void {
    if (this._broadcasting) return;
    this._broadcasting = true;
    try {
      this._prune();
      if (from !== null && this._members.includes(from)) onLeader?.(from);
      // Snapshot: a host callback is free to add or remove members, and the
      // list must not shift underneath the loop.
      for (const target of [...this._members]) {
        if (target === from) continue;
        if (!this._members.includes(target)) continue;
        if (!alive(target.chart)) continue; // pruned on the next pass
        apply(target);
      }
    } finally {
      this._broadcasting = false;
    }
  }

  /** Drop destroyed members, releasing the group's reference to them. */
  private _prune(): void {
    for (let i = this._members.length - 1; i >= 0; i--) {
      // A drawings adapter's `leave` below is host code and may remove other
      // members, which only shifts the unvisited ones down: an index past the
      // end is skipped, and every member still below is visited.
      const member = this._members[i];
      if (member === undefined || alive(member.chart)) continue;
      // No `_release`: its chart is gone, so unsubscribing and detaching
      // primitives would only touch a corpse (and `addPrimitive` on one would
      // resurrect a pane). Dropping the entry is the whole job, apart from
      // telling the host's drawing sharer, which keeps a list of its own.
      this._members.splice(i, 1);
      this._share(member, false);
    }
  }

  private _find(chart: LinkChart): Member | null {
    return this._members.find((m) => m.chart === chart) ?? null;
  }

  private _release(member: Member): void {
    for (const off of member.unsubscribe) off();
    member.unsubscribe.length = 0;
    this._detachCrosshairs(member);
    this._share(member, false);
  }

  /**
   * Point this member's linked crosshair at one of its own bars (or clear it),
   * keeping one primitive per pane so the line spans price, volume and
   * indicator panes the way the native global crosshair does.
   */
  private _setCrosshair(member: Member, index: number | null): void {
    if (!alive(member.chart)) return;
    const wanted = index === null ? member.crosshairs.length : member.chart.panes().length;
    while (member.crosshairs.length > wanted) {
      const extra = member.crosshairs.pop();
      if (extra !== undefined) member.chart.removePrimitive(extra);
    }
    while (member.crosshairs.length < wanted) {
      const line = new LinkCrosshair();
      // Panes are indexed 0..n-1 and `wanted` never exceeds the pane count, so
      // this cannot create one.
      member.chart.addPrimitive(line, member.crosshairs.length);
      member.crosshairs.push(line);
    }
    for (const line of member.crosshairs) line.setIndex(index);
    member.chart.setLinkedCrosshairIndex?.(index);
  }

  private _detachCrosshairs(member: Member): void {
    if (alive(member.chart)) {
      for (const line of member.crosshairs) member.chart.removePrimitive(line);
      member.chart.setLinkedCrosshairIndex?.(null);
    }
    member.crosshairs.length = 0;
  }
}

/** Create a link group. `group.add(chart)` puts a chart in it. */
export function createLinkGroup(options: LinkOptions = {}): LinkGroup {
  return new LinkGroup(options);
}
