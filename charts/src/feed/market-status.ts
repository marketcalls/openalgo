/**
 * Which part of the trading day an instant falls in, and what a status readout
 * says about "now", read from a session calendar rather than from a clock.
 *
 * A calendar lays each local date out as windows of hours: the regular session,
 * the pre-open and post-close hours around it, extended hours of their own, and
 * a whole-date holiday. Where they overlap one wins by a fixed precedence, and
 * everything left over is closed. The answer is a partition of time into spans,
 * which is the one shape every reader needs: a phase is the span an instant
 * sits in, a status is that span and the one after it, and a shade paints the
 * spans in view without asking about every bar.
 */
import type { MarketPhaseFn } from '../primitives/price-levels';

/**
 * The part of the trading day an instant falls in. `regular` is the session
 * itself; `pre` and `post` are the hours the calendar trades before the first
 * opening and after the last close of a trading date; `extended` is extended
 * hours of their own, such as an overnight session; `holiday` is a date the
 * calendar's exceptions close although its weekly sessions would open; and
 * `closed` is every other hour.
 */
export type SessionPhase = 'pre' | 'regular' | 'post' | 'extended' | 'closed' | 'holiday';

/** One stretch of time in a single phase. */
export interface SessionPhaseSpan {
  readonly phase: SessionPhase;
  /** UTC seconds, inclusive. */
  readonly start: number;
  /** UTC seconds, exclusive. */
  readonly end: number;
}

/**
 * Anything that can lay its phases out over a range: `SessionCalendar`,
 * `Instrument`, or a host's own hours. The spans are consecutive, never
 * overlap, and cover the range from its start to its end.
 */
export interface SessionPhaseSource {
  phaseSpans(fromUtcSeconds: number, toUtcSeconds: number): readonly SessionPhaseSpan[];
}

/** The market at one instant, as a status readout shows it. */
export interface MarketStatus {
  /** The phase at the instant asked about. */
  readonly phase: SessionPhase;
  /**
   * When the phase next changes, in UTC seconds, or null when it holds for the
   * next 14 days: a round-the-clock calendar, or a long closure. A readout
   * that has to follow the market sets its timer for this instant.
   */
  readonly changesAt: number | null;
  /** The phase from `changesAt`, or null with it. */
  readonly nextPhase: SessionPhase | null;
  /**
   * The opening of the regular session in force, or else of the next one, in
   * UTC seconds. Null when none opens within 14 days, or when the session in
   * force has run for more than two days, as a round-the-clock one does.
   */
  readonly opensAt: number | null;
  /** The close of that same session, or null when it is not within 14 days. */
  readonly closesAt: number | null;
}

/**
 * A window of hours with its precedence: the index of its phase in
 * `PHASE_ORDER`. How a calendar hands its dates to `partitionPhases`.
 */
export interface PhaseWindow {
  readonly rank: number;
  readonly start: number;
  readonly end: number;
}

/**
 * The precedence where windows overlap, first wins. A regular session beats the
 * hours around it, so a pre-open that reaches into the previous day's session
 * does not relabel it, and any hours at all beat a holiday: an overnight
 * session opening the evening before still runs into the closed date.
 */
const PHASE_ORDER: readonly SessionPhase[] = ['regular', 'pre', 'post', 'extended', 'holiday'];

/**
 * Cut `[from, to)` into consecutive single-phase spans from windows of any
 * order, clipped to the range. A sweep over the window edges rather than a
 * test of every window at every edge, so a range of months stays linear in
 * the windows it holds.
 */
export function partitionPhases(from: number, to: number, windows: readonly PhaseWindow[]): SessionPhaseSpan[] {
  const edges: [time: number, rank: number, delta: number][] = [];
  for (const w of windows) {
    const start = Math.max(w.start, from), end = Math.min(w.end, to);
    if (start < end) edges.push([start, w.rank, 1], [end, w.rank, -1]);
  }
  edges.sort((a, b) => a[0] - b[0]);
  const open = PHASE_ORDER.map(() => 0), out: { phase: SessionPhase; start: number; end: number }[] = [];
  // `e` is read inside `edges`, and every rank is an index of `PHASE_ORDER`, so of `open`.
  for (let t = from, e = 0; t < to;) {
    while (e < edges.length && edges[e]![0] <= t) open[edges[e]![1]]! += edges[e++]![2];
    const next = e < edges.length ? edges[e]![0] : to, rank = open.findIndex(count => count > 0);
    const phase = rank < 0 ? 'closed' : PHASE_ORDER[rank]!, last = out[out.length - 1];
    if (last?.phase === phase) last.end = next;
    else out.push({ phase, start: t, end: next });
    t = next;
  }
  return out;
}

const DAY = 86400;
/** How far back a status looks for the start of the phase in force. */
const BEHIND = 2 * DAY;
/** How far ahead a status looks for the next change and the next opening. */
const AHEAD = 14 * DAY;

/** The status at `utcSeconds` from a source known to lay out phases. */
export function statusOf(source: SessionPhaseSource, utcSeconds: number): MarketStatus {
  const from = utcSeconds - BEHIND, to = utcSeconds + AHEAD, spans = source.phaseSpans(from, to);
  const at = spans.findIndex(span => utcSeconds >= span.start && utcSeconds < span.end);
  // A host's own source may leave a gap; an hour nobody accounts for is not trading.
  const now = spans[at] ?? { phase: 'closed', start: utcSeconds, end: utcSeconds };
  const changesAt = at >= 0 && now.end < to ? now.end : null;
  const next = changesAt === null ? undefined : spans.find(span => span.start === changesAt);
  const session = now.phase === 'regular' ? now : spans.find(span => span.phase === 'regular' && span.start > utcSeconds);
  return {
    phase: now.phase,
    changesAt,
    nextPhase: changesAt === null ? null : next?.phase ?? 'closed',
    opensAt: session && session.start > from ? session.start : null,
    closesAt: session && session.end < to ? session.end : null,
  };
}

/**
 * The market status at an instant, from anything that lays out phases:
 * `SessionCalendar`, `Instrument`, or the calendar a chart was given, read
 * back from `chart.dataLayer.sessionCalendar`. Null when the source is absent
 * or cannot lay out phases, such as a host's hours with `sessionFrom` alone.
 * Pass `Date.now() / 1000` for "now". A calendar with a window whose boundary
 * a daylight-saving change removes throws, as its `sessionAt` does on that
 * date. A status lays out the days around the instant, so it throws from
 * about fifteen days before that date to four after, and a readout catches it.
 */
export function marketStatusAt(
  source: { phaseSpans?: SessionPhaseSource['phaseSpans'] } | null | undefined,
  utcSeconds: number,
): MarketStatus | null {
  return source?.phaseSpans ? statusOf(source as SessionPhaseSource, utcSeconds) : null;
}

/**
 * A `PriceLevels` phase classifier from a calendar, so the four extended-hours
 * levels need no host code: a bar in the pre-open reads `pre`, and so on.
 * Extended hours of their own, closed hours and holidays read as unknown,
 * since those levels describe the hours either side of one session.
 *
 * The levels ask about every bar of a session on every frame, so the spans of
 * about a week are kept and walked in time order, and the calendar is asked
 * again only when a bar falls outside them. A calendar that cannot answer
 * leaves the phase unknown rather than stopping the frame.
 */
export function calendarMarketPhase(source: SessionPhaseSource): MarketPhaseFn {
  let spans: readonly SessionPhaseSpan[] = [], from = NaN, to = NaN, hint = 0;
  return bar => {
    const t = bar.time;
    if (!(t >= from && t < to)) {
      if (!Number.isFinite(t)) return null;
      from = t - DAY; to = t + 7 * DAY; hint = 0;
      try { spans = source.phaseSpans(from, to); } catch { spans = []; }
    }
    if (spans[hint] && t < spans[hint]!.start) hint = 0;
    while (hint < spans.length && t >= spans[hint]!.end) hint++;
    const phase = spans[hint]?.phase;
    return phase === 'pre' || phase === 'regular' || phase === 'post' ? phase : null;
  };
}
