/**
 * The chart grid's link groups: which charts link with which, on which
 * channels, and how a group reads and writes itself in a workspace.
 *
 * Each group is one engine `LinkGroup` (crosshair, time range, symbol,
 * interval, chart type, appearance) and one draw tier `DrawingLinkGroup`
 * that the link group's drawings switch lets each member join. A chart is in
 * one group or in none. The grid starts with one group holding every chart,
 * which is the whole desk linking as it did before groups existed, and it
 * writes a workspace exactly as it did then until the user makes a second
 * group, names one or takes a chart out.
 *
 * Three decisions carry it:
 *
 * - **A group lasts as long as its charts.** The grid drops a group the
 *   moment its last chart leaves, so no group keeps an instrument, interval or
 *   chart type nobody is showing for the next chart to adopt: a new group
 *   starts from the chart that makes it.
 * - **A group's letter is its own.** Letters are handed out as groups are
 *   made and kept, so group C stays C when group B empties; colour follows the
 *   letter and never carries the meaning alone.
 * - **Older readers get only what every chart can follow together.** With
 *   groups written, the flat channels a reader from before groups applies to
 *   the whole desk are on only when one group holds every chart; otherwise
 *   they are all off, which can neither refuse a desk nor pull one chart onto
 *   another's instrument.
 */
import {
  applyChartSettings, createLinkGroup, isKnownInterval, readChartSettings,
  type Chart, type ChartEventMap, type LinkChart, type LinkGroup, type LinkMemberOptions, type LinkOptions, type ResolvedLinkOptions,
} from 'openalgo-charts';
import { DrawingLinkGroup } from 'openalgo-charts/draw';
import type { WorkspaceLinkChannels, WorkspaceLinkGroup, WorkspacePayload, WorkspaceSync } from 'openalgo-charts/workspace';
import type { Widget } from './widget';
import { isChartTypeChoice } from './chart-type-choice';

/** One link group as the grid reports it. */
export interface ChartGridLinkGroup {
  /** What each chart's `linkGroup` and a saved pane's `linkGroup` name. */
  readonly id: string;
  /** The group's name: the one given it, or `Group A` and on, in the host's language. */
  readonly name: string;
  /** The letter its charts are marked with, A to P. */
  readonly letter: string;
  readonly links: ResolvedLinkOptions;
  /** The pane ids of its charts, in reading order. */
  readonly cells: readonly string[];
}

/** What a link group holds besides its engine groups: the linked window, see grid.ts `fit`. */
export interface GridGroup<C = unknown> {
  readonly id: string;
  readonly letter: string;
  /** Null until someone names it: the name is then `Group {letter}` in whatever language shows it. */
  name: string | null;
  readonly links: LinkGroup;
  readonly drawings: DrawingLinkGroup;
  view: { from: number; to: number } | null;
  keeper: C | null;
}

/** The slice of a grid cell the links drive. */
interface LinkedCell {
  readonly id: string;
  readonly widget: Widget;
  member: LinkChart;
  group: GridGroup | null;
}

/** The boolean channels, in the order a menu lists them and a document writes them. */
export type LinkChannel = 'crosshair' | 'viewport' | 'symbol' | 'interval' | 'chartType' | 'appearance' | 'drawings';

const LETTERS = 'ABCDEFGHIJKLMNOP';
/** A document takes at most sixteen groups; a grid of sixteen charts never needs more. */
const MAX_LINK_GROUPS = LETTERS.length;
/**
 * The drawings link matches charts by symbol and exchange and refuses a blank
 * exchange. A host that names no exchange (a feed with one venue) still
 * shares drawings between charts on one symbol, under this stand-in.
 */
const NO_EXCHANGE = '-';
export const ALL_OFF: ResolvedLinkOptions = {
  crosshair: false, viewport: false, symbol: false, interval: false, chartType: false, appearance: false, drawings: false, whenMissing: 'nearest',
};

/**
 * An instrument as the one string the link group compares. The exchange rides
 * inside it: one ticker on two exchanges is two instruments, and a bare ticker
 * would let a change of exchange alone pass the followers by.
 */
export const instrument = (symbol: string, exchange: string): string => JSON.stringify([symbol, exchange]);

/** The channels a group writes: the four the schema requires, then only what differs from off. */
function savedChannels(o: ResolvedLinkOptions): WorkspaceLinkChannels {
  return {
    crosshair: o.crosshair, viewport: o.viewport, symbol: o.symbol, interval: o.interval, appearance: o.appearance,
    ...(o.chartType ? { chartType: true } : {}), ...(o.drawings ? { drawings: true } : {}),
    ...(o.whenMissing === 'hide' ? { whenMissing: 'hide' as const } : {}),
  };
}

/** A saved group's or desk's channels as link options; absent optional channels are off. */
export function channelsOf(sync: Partial<WorkspaceLinkChannels>): ResolvedLinkOptions {
  return {
    crosshair: sync.crosshair === true, viewport: sync.viewport === true, symbol: sync.symbol === true, interval: sync.interval === true,
    chartType: sync.chartType === true, appearance: sync.appearance === true, drawings: sync.drawings === true,
    whenMissing: sync.whenMissing === 'hide' ? 'hide' : 'nearest',
  };
}

/**
 * Why a payload's links cannot be honoured, or ''. Joining a linked group
 * converges its members, which would overwrite a chart saved on another
 * instrument, interval or chart type, so a group that disagrees is refused.
 */
export function checkLinks(p: WorkspacePayload): string {
  const sync = p.sync as WorkspaceSync;
  const panes = p.panes;
  const groups: Array<{ channels: Partial<WorkspaceLinkChannels>; panes: typeof panes }> = [];
  if (sync.groups === undefined) groups.push({ channels: sync, panes });
  else {
    if (!Array.isArray(sync.groups) || sync.groups.length > MAX_LINK_GROUPS) return 'invalid link groups';
    const ids = new Set<string>();
    for (const g of sync.groups) {
      if (typeof g !== 'object' || g === null || typeof g.id !== 'string' || g.id === '' || ids.has(g.id)) return 'invalid or duplicate link group id';
      ids.add(g.id);
      groups.push({ channels: g, panes: panes.filter(pane => pane.linkGroup === g.id) });
    }
    for (const pane of panes) if (pane.linkGroup !== undefined && !ids.has(pane.linkGroup)) return `${pane.id}: undeclared link group ${String(pane.linkGroup)}`;
  }
  for (const { channels, panes: members } of groups) {
    const differ = (key: (pane: typeof panes[number]) => string): boolean => new Set(members.map(key)).size > 1;
    if (channels.symbol === true && differ(x => instrument(x.symbol, x.exchange))) return 'linked symbols differ between charts';
    if (channels.interval === true && differ(x => x.interval)) return 'linked intervals differ between charts';
    if (channels.chartType === true && differ(x => x.chartType)) return 'linked chart types differ between charts';
  }
  return '';
}

/**
 * A chart as its link group reaches it. A pan or zoom the chart did not make
 * itself (`own`: fresh bars, the grid, the group following another chart)
 * is not passed on, and a window the group sets goes through `follow`, so the
 * chart can tell that move from its own.
 */
export function linkMember(chart: Chart, own: () => boolean, follow: (move: () => void) => void): LinkChart {
  return {
    // The link group asks only for names the chart's map declares, so the
    // forward stays on the typed overload rather than the string form 3.0.0 drops.
    on: (event, cb) => chart.on(event as keyof ChartEventMap, event === 'pan' || event === 'zoom'
      ? payload => { if (!own()) cb(payload); }
      : event === 'symbol'
        ? payload => { const p = payload as { symbol: string; exchange: string }; cb({ symbol: instrument(p.symbol, p.exchange) }); }
        : cb),
    getVisibleLogicalRange: () => chart.getVisibleLogicalRange(),
    setVisibleLogicalRange: range => follow(() => chart.setVisibleLogicalRange(range)),
    get dataLayer() { return chart.dataLayer; },
    get isDestroyed() { return chart.isDestroyed; },
    panes: () => chart.panes(),
    addPrimitive: (primitive, pane) => chart.addPrimitive(primitive, pane),
    removePrimitive: primitive => chart.removePrimitive(primitive),
    setLinkedCrosshairIndex: index => chart.setLinkedCrosshairIndex(index),
  };
}

/**
 * One chart's side of a group: how it reports and follows each channel. A
 * linked change is the leader's step, taken back on the leader's timeline and
 * sent here again; on this chart's own timeline it is never a step, so every
 * follower applies inside `history.ignore`.
 */
function memberOptions(cell: LinkedCell, group: GridGroup): LinkMemberOptions {
  const { widget } = cell;
  const chart = widget.chart;
  return {
    symbol: instrument(widget.symbol(), widget.exchange()), interval: widget.interval(), chartType: widget.chartType(),
    onSymbol: key => { const [symbol, exchange] = JSON.parse(key) as [string, string]; widget.setSymbol(symbol, exchange); },
    onInterval: interval => {
      if (!isKnownInterval(interval)) return false;
      widget.setInterval(interval);
      return true;
    },
    onChartType: type => {
      if (!isChartTypeChoice(type)) return false;
      widget.history.ignore(() => widget.setChartType(type));
      return widget.chartType() === type;
    },
    appearance: { read: () => readChartSettings(chart), apply: values => widget.history.ignore(() => applyChartSettings(chart, values)) },
    drawings: {
      join: () => group.drawings.add(chart, widget.draw, () => ({ symbol: widget.symbol(), exchange: widget.exchange() || NO_EXCHANGE })),
      leave: () => group.drawings.remove(chart),
    },
  };
}

/** The desk's link groups and who is in which. The grid owns the cells; this owns the groups. */
export class GridLinks<C extends LinkedCell> {
  public groups: GridGroup<C>[] = [];

  public constructor(private readonly defaults: LinkOptions = {}) {}

  /** A new, empty group on the grid's channels with `links` over them, or null when every letter is taken. */
  public create(options: { id?: string | undefined; name?: string | null; links?: LinkOptions | undefined } = {}): GridGroup<C> | null {
    const free = (l: string): boolean => !this.groups.some(g => g.letter === l);
    // The grid names a group by its letter, so a saved group comes back under
    // the letter it was marked with, gaps an emptied group left included.
    const own = options.id !== undefined && /^[a-p]$/.test(options.id) ? options.id.toUpperCase() : '';
    const letter = own !== '' && free(own) ? own : [...LETTERS].find(free);
    if (letter === undefined) return null;
    let id = options.id ?? letter.toLowerCase();
    for (let n = 2; this.groups.some(g => g.id === id); n++) id = `${letter.toLowerCase()}${n}`;
    const group: GridGroup<C> = {
      id, letter, name: options.name ?? null, links: createLinkGroup({ ...this.defaults, ...options.links }),
      drawings: new DrawingLinkGroup({ enabled: true }), view: null, keeper: null,
    };
    this.groups.push(group);
    return group;
  }

  public find(id: string): GridGroup<C> | undefined {
    return this.groups.find(g => g.id === id);
  }

  /**
   * Put `cell` in `group`, out of the one it was in. A group with charts
   * converges the newcomer on the channels it links; the caller prunes the
   * group it left if that emptied it.
   */
  public join(cell: C, group: GridGroup<C>): void {
    if (cell.group === group) return;
    this.leave(cell);
    cell.group = group;
    group.links.add(cell.member, memberOptions(cell, group));
  }

  /** Take `cell` out of its group, keeping the drawings it already received. */
  public leave(cell: C): void {
    const group = cell.group;
    if (group === null) return;
    cell.group = null;
    group.links.remove(cell.member);
    if (group.keeper === cell) { group.view = null; group.keeper = null; }
  }

  /** Drop the groups no chart is in. */
  public prune(cells: readonly C[]): void {
    for (const group of this.groups.slice()) {
      if (cells.some(c => c.group === group)) continue;
      this.groups.splice(this.groups.indexOf(group), 1);
      group.links.destroy();
      group.drawings.destroy();
    }
  }

  public destroy(): void {
    for (const group of this.groups.splice(0)) {
      group.links.destroy();
      group.drawings.destroy();
    }
  }

  /** One group holding every chart under no name: the desk as it linked before groups. */
  public trivial(cells: readonly C[]): boolean {
    return this.groups.length === 1 && this.groups[0]!.name === null && cells.every(c => c.group === this.groups[0]); // length checked first
  }

  /** The channels of `cell`'s group, or every channel off for a chart in none. */
  public optionsOf(cell: C | null): ResolvedLinkOptions {
    return cell?.group?.links.options() ?? { ...ALL_OFF };
  }

  /**
   * The `sync` a workspace saves. Flat channels only, until groups say more
   * than the flat ones can; an unnamed group is saved under the name it shows.
   */
  public sync(cells: readonly C[], name: (group: GridGroup<C>) => string): WorkspaceSync {
    if (this.trivial(cells)) return savedChannels(this.groups[0]!.links.options()) as WorkspaceSync; // trivial: exactly one group
    const whole = this.groups.find(g => cells.every(c => c.group === g));
    const flat = savedChannels(whole?.links.options() ?? ALL_OFF);
    const groups: WorkspaceLinkGroup[] = this.groups.filter(g => cells.some(c => c.group === g))
      .map(g => ({ id: g.id, name: name(g), ...savedChannels(g.links.options()) }));
    return { ...flat, groups };
  }
}

/** The link groups as the public API reports them. */
export function describeGroups<C extends LinkedCell>(links: GridLinks<C>, cells: readonly C[], name: (group: GridGroup<C>) => string): ChartGridLinkGroup[] {
  return links.groups.map(g => ({
    id: g.id, name: name(g), letter: g.letter, links: g.links.options(),
    cells: cells.filter(c => c.group === g).map(c => c.id),
  }));
}
