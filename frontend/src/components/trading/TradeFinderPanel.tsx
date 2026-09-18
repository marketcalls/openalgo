/**
 * TradeFinder's ranked lists (Intraday Boost / Breakout Beacon / High
 * Powered / Sectors) surfaced in the charting terminal's right sidebar.
 *
 * Both endpoints behind this panel are poll-only -- neither pushes an update
 * over the socket -- and the snapshotter that feeds `/boostsnapshots` for
 * backtesting only samples every 5 minutes, so polling this panel faster
 * than that buys nothing. 30s keeps the panel visibly live without hammering
 * the server-side TradeFinder session.
 *
 * `breakout_beacon`'s param_0/param_1/param_2 are not genuine ltp/prev_close/
 * change_pct (see services/tradefinder_service.py:_map_items) -- one of them
 * is actually a BULL/BEAR sentiment label that the backend coerces to 0.0.
 * Score is the only reliable field on that list, so LTP/Chg% are hidden for
 * it rather than shown as misleading zeros.
 */

import {
  ArrowDown,
  ArrowUp,
  History,
  Pin,
  PinOff,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import {
  type BoostMovementRow,
  type BoostSnapshotsResponse,
  type JwtHealthResponse,
  type MarketPulseData,
  type RankTimelinePoint,
  type SectorScopeData,
  type SectorStockItem,
  type TfListItem,
  tradefinderApi,
} from '@/api/tradefinder'
import { watchlistApi } from '@/api/watchlist'
import { useSocketContext } from '@/components/socket/SocketProvider'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { MOVEMENT_BADGE, minuteOfDay } from '@/lib/trading/boostBadge'
import type { SearchRow } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'
import { PANEL_HEADER, PanelShell } from './panelShell'

const PREFS_KEY = 'oa-trading-tradefinder'
const FEATURES_KEY = 'oa-trading-tradefinder-features'
const ACTIVE_WATCHLIST_KEY = 'oa-trading-watchlist'

const POLL_INTERVALS = [5_000, 15_000, 30_000, 60_000] as const
/** How many of the most recent polls the sparkline keeps. */
const SCORE_HISTORY_LEN = 20
/** How far down the list counts as "the top" for the new-entrant alert. */
const NEW_ENTRANT_TOP_N = 10

/* ── clean-climb / base-breakout badge thresholds ──
   Both read the whole day's rank+price timeline (5-min snapshot cadence, from
   /boostsnapshots), refetched every CLIMB_POLL_MS -- polling faster than the
   snapshotter's own cadence buys nothing. */
const CLIMB_POLL_MS = 5 * 60_000
/** Must reach this rank or better today to count as "made it to the top." */
const CLIMB_TOP_K = 10
/** Must have been worse than this near the open, or it was already near the
 * top and this isn't a climb. */
const CLIMB_EARLY_RANK_FLOOR = 20
/** First snapshot's ltp this far above prev_close or more is a gap-up, not a
 * climb -- excluded. */
const GAP_UP_MAX_PCT = 2
/** Trailing window (minutes, excluding the latest couple of points) used as
 * the consolidation "base" for the breakout check. */
const CONSOLIDATION_WINDOW_MIN = 60
/** The base's (max-min)/min must stay under this to count as consolidating. */
const CONSOLIDATION_RANGE_MAX_PCT = 1.5
/** The latest price must clear the base's high by at least this much to
 * count as a breakout rather than noise. */
const BREAKOUT_MARGIN_PCT = 0.5
const CPR_FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'bullish', label: 'Bullish only' },
  { id: 'bearish', label: 'Bearish only' },
] as const
type CprFilter = (typeof CPR_FILTERS)[number]['id']

/** Every feature here defaults to off. Nothing in this panel changes
 * behaviour until the user opens the settings popover and switches it on
 * themselves -- same rule the Gainers/Losers sort follows. */
interface Features {
  freshness: boolean
  pauseAutoRefresh: boolean
  rankArrows: boolean
  search: boolean
  compactDensity: boolean
  addToWatchlist: boolean
  columns: { ltp: boolean; chg: boolean; score: boolean; cpr: boolean; directional: boolean }
  /** Off = the hardcoded 30s default; any other value is the user's choice. */
  pollIntervalMs: number
  jwtHealth: boolean
  retryBackoff: boolean
  /** null = no filter. Only meaningful once a real value is set. */
  scoreThreshold: number | null
  cprFilter: CprFilter
  sectorChips: boolean
  /** Whether the pin icon shows at all -- pinning changes row order, so it
   * stays opt-in like everything else here, not just the pinned list itself. */
  pinning: boolean
  /** Pinned symbols float to the top of whichever list/sector view they
   * appear in, ahead of the active sort. */
  pinnedSymbols: string[]
  scoreSparkline: boolean
  rankTimeline: boolean
  newEntrantAlert: boolean
  /** null = off. When set, any symbol crossing this score (from below to
   * at-or-above) toasts once -- not per watched symbol, every symbol on
   * whichever list is active, which needs no separate watchlist UI. */
  scoreCrossAlert: number | null
  /** Aggressive by design -- automatically charts whoever takes rank #1 on
   * the active list. Must never be on by default. */
  autoChartTop1: boolean
  /** Sectors-only: rank-over-the-day chart for a sector, same idea as
   * `rankTimeline` but reading the "sector_index" list_type the scheduler
   * writes alongside the three boost lists. */
  sectorRankTimeline: boolean
  /** A stock that climbed from outside CLIMB_EARLY_RANK_FLOOR into the top
   * CLIMB_TOP_K today without a gap-up open at the first snapshot -- a
   * genuine intraday mover, not a stock that opened high and sat there. */
  cleanClimbAlert: boolean
  /** A stock that consolidated in a tight range then broke above it. */
  baseBreakoutAlert: boolean
  /** Toast the strongest NEW backend rank-movement events (Top-10 entry or
   * better: jumps, fast climbs, Top-5). The badges render regardless; this
   * only decides whether a new one also interrupts. */
  movementAlerts: boolean
  /** null = off (show the full list). Otherwise narrows the active ranked
   * list to its N highest directional_score rows -- "identify the
   * directional stock" without scanning past the choppy ones by eye. */
  topN: number | null
}

const DEFAULT_FEATURES: Features = {
  freshness: false,
  pauseAutoRefresh: false,
  rankArrows: false,
  search: false,
  compactDensity: false,
  addToWatchlist: false,
  columns: { ltp: true, chg: true, score: true, cpr: true, directional: false },
  pollIntervalMs: 30_000,
  jwtHealth: false,
  retryBackoff: false,
  scoreThreshold: null,
  cprFilter: 'all',
  sectorChips: false,
  pinning: false,
  pinnedSymbols: [],
  scoreSparkline: false,
  rankTimeline: false,
  newEntrantAlert: false,
  scoreCrossAlert: null,
  autoChartTop1: false,
  sectorRankTimeline: false,
  cleanClimbAlert: false,
  baseBreakoutAlert: false,
  movementAlerts: false,
  topN: null,
}

function readFeatures(): Features {
  try {
    const saved = JSON.parse(localStorage.getItem(FEATURES_KEY) || '{}')
    return {
      ...DEFAULT_FEATURES,
      ...saved,
      columns: { ...DEFAULT_FEATURES.columns, ...saved.columns },
      pinnedSymbols: Array.isArray(saved.pinnedSymbols) ? saved.pinnedSymbols : [],
    }
  } catch {
    return DEFAULT_FEATURES
  }
}

/** Sentinel sector key for "every sector combined", distinct from any real
 * `"<name>_r_factor"` key so it can share the same selection state. */
const ALL_SECTORS = '__all__'

const SORT_MODES = [
  { id: 'gainers', label: 'Gainers' },
  { id: 'losers', label: 'Losers' },
] as const
type SortMode = (typeof SORT_MODES)[number]['id']

const VIEWS = [
  { id: 'intraday_boost', label: 'Intraday Boost' },
  { id: 'breakout_beacon', label: 'Breakout Beacon' },
  { id: 'high_powered_stocks', label: 'High Powered' },
  { id: 'sectors', label: 'Sectors' },
] as const
type ViewId = (typeof VIEWS)[number]['id']
type ListView = Exclude<ViewId, 'sectors'>

function readView(): ViewId {
  const saved = localStorage.getItem(PREFS_KEY)
  return (VIEWS.find((v) => v.id === saved)?.id ?? 'intraday_boost') as ViewId
}

const ROW_GRID = 'grid grid-cols-[22px_1fr_52px_48px_44px_44px] items-center gap-1'

/** Preset choices for the "Top N by directional score" filter -- 'null'
 * means off (show the full list). */
const TOP_N_OPTIONS = [10, 20, 30, 50] as const

function ChgCell({ value }: { value: number }) {
  return (
    <span
      className={cn(
        'text-right tabular-nums',
        value > 0 && 'text-emerald-600 dark:text-emerald-400',
        value < 0 && 'text-rose-600 dark:text-rose-400'
      )}
    >
      {value > 0 ? '+' : ''}
      {value.toFixed(2)}%
    </span>
  )
}

/** Score with a direction arrow -- the number alone doesn't say whether the
 * symbol is moving up or down, only how strongly TradeFinder is ranking it. */
function ScoreCell({ score, direction }: { score: number; direction: 'up' | 'down' | null }) {
  return (
    <span className="flex items-center justify-end gap-0.5 tabular-nums">
      {score.toFixed(1)}
      {direction === 'up' && (
        <TrendingUp className="h-3 w-3 shrink-0 text-emerald-600 dark:text-emerald-400" />
      )}
      {direction === 'down' && (
        <TrendingDown className="h-3 w-3 shrink-0 text-rose-600 dark:text-rose-400" />
      )}
    </span>
  )
}

/** "Steadiness since open" score (0-100, Kaufman efficiency ratio) -- how
 * cleanly the stock has moved in one direction rather than churning. Title
 * carries the reversal count, the concrete number behind "without hiccups."
 * null (not yet computed -- market just opened, or fetch failed) renders as
 * a blank cell, never as 0, since 0 would misleadingly read as "pure chop." */
function DirectionalScoreCell({ item }: { item: TfListItem }) {
  if (item.directional_score == null) return <span />
  const reversals = item.directional_reversals
  const title =
    reversals != null ? `${reversals} reversal${reversals === 1 ? '' : 's'} since open` : undefined
  return (
    <span
      className="flex items-center justify-end gap-0.5 tabular-nums"
      title={title}
      aria-label={title}
    >
      {item.directional_score.toFixed(0)}
      {item.directional_direction === 'up' && (
        <TrendingUp className="h-3 w-3 shrink-0 text-emerald-600 dark:text-emerald-400" />
      )}
      {item.directional_direction === 'down' && (
        <TrendingDown className="h-3 w-3 shrink-0 text-rose-600 dark:text-rose-400" />
      )}
    </span>
  )
}

/** A session-only trend line -- last SCORE_HISTORY_LEN polls, not a
 * backtest source. One point renders nothing (no line to draw); the colour
 * reads first-vs-last, matching the up/down arrow's own convention. */
function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null
  const w = 40
  const h = 14
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * w
      const y = h - ((v - min) / range) * h
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
  const up = values.at(-1)! >= values[0]
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="shrink-0" aria-hidden="true">
      <polyline
        points={points}
        fill="none"
        strokeWidth="1.5"
        className={up ? 'stroke-emerald-500' : 'stroke-rose-500'}
      />
    </svg>
  )
}

/** Today's rank-over-time for one symbol, fetched on demand from
 * /boostsnapshots (the backtesting endpoint -- the only place rank history
 * lives). Inverted: a lower rank number is a better position, so the line
 * should read as "up" when the symbol climbed the list, not the axis. */
function RankTimelineChart({ points }: { points: RankTimelinePoint[] }) {
  if (points.length < 2) {
    return <p className="p-3 text-[12px] text-muted-foreground">Not enough data yet today.</p>
  }
  const w = 220
  const h = 60
  const ranks = points.map((p) => p[1])
  const minRank = Math.min(...ranks)
  const maxRank = Math.max(...ranks)
  const rankRange = maxRank - minRank || 1
  const minMin = points[0][0]
  const maxMin = points.at(-1)![0]
  const minRange = maxMin - minMin || 1
  const coords = points
    .map(([minuteOfDay, rank]) => {
      const x = ((minuteOfDay - minMin) / minRange) * w
      // Inverted on purpose: rank 1 is the top of the list, so it belongs
      // at the top of the chart, not the bottom a plain value axis would put it.
      const y = ((rank - minRank) / rankRange) * h
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
  return (
    <div className="p-2">
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="text-primary">
        <polyline points={coords} fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
      <p className="mt-1 flex justify-between text-[10px] text-muted-foreground">
        <span>Best rank {minRank}</span>
        <span>Worst rank {maxRank}</span>
      </p>
    </div>
  )
}

/** One sector as a horizontal bar: length scaled to its magnitude relative to
 * the strongest sector on screen, so "how hot is this sector" reads at a
 * glance instead of requiring a mental ranking of raw numbers.
 *
 * The "ALL" row is a different kind of value -- a stock count, not an
 * rfactor -- so it gets its own colour and a plain number instead of ChgCell,
 * matching how TradeFinder's own UI sets it apart from the per-sector rows. */
function SectorBarRow({
  label,
  value,
  maxAbs,
  selected,
  disabled,
  onClick,
  isAll,
  countLabel,
}: {
  label: string
  value: number
  maxAbs: number
  selected: boolean
  disabled: boolean
  onClick(): void
  isAll?: boolean
  countLabel?: number
}) {
  const pct = maxAbs > 0 ? Math.min(100, (Math.abs(value) / maxAbs) * 100) : 0
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        'flex w-full items-center gap-2 border-b border-border/40 px-2 py-1.5 text-left text-[12px] transition-colors hover:bg-accent disabled:opacity-50',
        selected && 'bg-accent font-medium ring-1 ring-inset ring-primary/60'
      )}
    >
      <span className={cn('w-[92px] shrink-0 truncate', isAll && 'font-semibold')}>{label}</span>
      <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-muted">
        <span
          className={cn(
            'block h-full rounded-full',
            isAll ? 'bg-amber-500' : value >= 0 ? 'bg-emerald-500' : 'bg-rose-500'
          )}
          style={{ width: `${pct}%` }}
        />
      </span>
      {isAll ? (
        <span className="text-right font-semibold tabular-nums text-amber-600 dark:text-amber-400">
          {countLabel ?? 0}
        </span>
      ) : (
        <ChgCell value={value} />
      )}
    </button>
  )
}

/** How long ago a Date was, in the coarse units a freshness caption needs --
 * seconds up to a minute, then minutes. Never "just now": a caption that
 * flips between two strings every second is harder to read at a glance than
 * one that only changes once a real interval has passed. */
function formatAgo(date: Date): string {
  const seconds = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  return `${Math.round(seconds / 60)}m ago`
}

/** Rank movement since the previous poll -- a small arrow only, no number,
 * since "moved up 3 places" matters far less than the direction. */
function RankDeltaIcon({ delta }: { delta: number | undefined }) {
  if (!delta) return null
  return delta > 0 ? (
    <ArrowUp className="h-3 w-3 shrink-0 text-emerald-600 dark:text-emerald-400" />
  ) : (
    <ArrowDown className="h-3 w-3 shrink-0 text-rose-600 dark:text-rose-400" />
  )
}

/** The server-side TF token's health -- unknown (grey) until the first poll
 * answers, then green/amber/red by how much runway is left. Refreshing
 * shows as amber regardless of the remaining time, since a refresh in
 * flight means the answer is about to change anyway. */
function JwtHealthBadge({ health }: { health: JwtHealthResponse | null }) {
  const label = !health
    ? 'TradeFinder token: checking…'
    : health.refreshing
      ? 'TradeFinder token: refreshing…'
      : !health.hasToken
        ? 'TradeFinder token: missing'
        : `TradeFinder token: ${Math.round((health.expiresInSeconds ?? 0) / 60)}m left`

  const color = !health
    ? 'bg-muted-foreground/40'
    : health.refreshing
      ? 'bg-amber-500'
      : !health.hasToken || (health.expiresInSeconds ?? 0) < 300
        ? 'bg-rose-500'
        : (health.expiresInSeconds ?? 0) < 1800
          ? 'bg-amber-500'
          : 'bg-emerald-500'

  return (
    <span
      className={cn('h-2 w-2 shrink-0 rounded-full', color)}
      title={label}
      aria-label={label}
      role="status"
    />
  )
}

/** A small dot beside the symbol, coloured by CPR bias -- only intraday_boost
 * ever carries this. Title text is the only place cpr_width_pct/
 * first_candle_range_pct show, since there is no room for two more columns. */
function CprDot({ item }: { item: TfListItem }) {
  if (item.cpr_bias == null && item.cpr_width_pct == null) return null
  const parts: string[] = []
  if (item.cpr_width_pct != null) parts.push(`CPR width ${item.cpr_width_pct.toFixed(2)}%`)
  if (item.first_candle_range_pct != null) {
    parts.push(`1st candle range ${item.first_candle_range_pct.toFixed(2)}%`)
  }
  return (
    <span
      className={cn(
        'inline-block h-1.5 w-1.5 shrink-0 rounded-full',
        item.cpr_bias === 'bullish' && 'bg-emerald-500',
        item.cpr_bias === 'bearish' && 'bg-rose-500',
        item.cpr_bias == null && 'bg-muted-foreground/40'
      )}
      title={parts.join(' · ') || undefined}
      aria-hidden="true"
    />
  )
}

/** Persistent per-row flag for the clean-climb / base-breakout detectors --
 * unlike the toasts, this stays visible for as long as the condition holds
 * this session, so scanning the list finds it without having caught the
 * popup. `detail` carries the specific numbers into the tooltip. */
function MomentumBadge({ kind, detail }: { kind: 'climb' | 'breakout'; detail: string }) {
  const Icon = kind === 'climb' ? TrendingUp : ArrowUp
  return (
    <span title={detail} className="inline-flex shrink-0">
      <Icon
        className={cn('h-3 w-3', kind === 'climb' ? 'text-orange-500' : 'text-emerald-500')}
        aria-hidden="true"
      />
    </span>
  )
}

/** Only the strongest events raise a toast when `movementAlerts` is on --
 * Top-10 entry/re-entry and above (jumps, fast climb, Top-5, a clean run).
 * Sustained and Top-20 stay visual-only; they are a state, not a moment. */
const MOVEMENT_ALERT_MIN_PRIORITY = 68
/** A symbol flickering around a threshold must not re-toast for a while. */
const MOVEMENT_ALERT_COOLDOWN_MS = 5 * 60_000

function MovementBadge({ mv }: { mv: BoostMovementRow }) {
  const badge = MOVEMENT_BADGE[mv.event]
  if (!badge) return null
  const vel = mv.rank_velocity != null ? ` · ${mv.rank_velocity.toFixed(1)}/min` : ''
  const zone =
    mv.is_stable_zone && mv.zone_low != null ? ` · zone ${mv.zone_low}-${mv.zone_high}` : ''
  // The run is the whole point of the badge when there is one: how far it has
  // moved since it turned, and how much of that it has handed back.
  const run =
    mv.run_clean && mv.run_move_pct != null
      ? ` · moved ${mv.run_move_pct > 0 ? '+' : ''}${mv.run_move_pct.toFixed(2)} points since ${
          mv.run_from_min != null ? minuteOfDay(mv.run_from_min) : 'the turn'
        }, gave back ${mv.run_adverse_pct?.toFixed(2)}${
          mv.day_change_pct != null
            ? ` · stock is ${mv.day_change_pct > 0 ? '+' : ''}${mv.day_change_pct.toFixed(2)}% on the day`
            : ''
        }`
      : ''
  return (
    <span
      title={`${mv.event.replace(/_/g, ' ')} · ${mv.first_seen_rank}→${mv.current_rank}${vel}${zone}${run}`}
      className={cn('shrink-0 text-[10px] font-bold tabular-nums', badge.className)}
    >
      {badge.text}
    </span>
  )
}

/** One row: a label and a Switch, the same shape WatchlistPanel already uses
 * for its column toggles. Kept generic so both top-level features and the
 * nested column checkboxes render identically. */
function FeatureRow({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange(next: boolean): void
}) {
  return (
    <label className="flex items-center justify-between gap-3 py-1 text-[12px]">
      <span className="text-foreground">{label}</span>
      <Switch checked={checked} onCheckedChange={onChange} className="scale-90" />
    </label>
  )
}

/** A section header that names its scope explicitly -- every setting under
 * it applies to exactly the view(s) named here, nothing wider or narrower. */
function ScopeHeader({ title, scope }: { title: string; scope: string }) {
  return (
    <div className="mt-1 border-t pt-1.5 first:mt-0 first:border-t-0 first:pt-0">
      <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70">
        {title}
      </p>
      <p className="text-[10px] text-muted-foreground/70">{scope}</p>
    </div>
  )
}

/** All 20-feature-audit toggles, off by default, persisted by the caller.
 * Grouped to match the plan's categories so the popover reads as a menu,
 * not a flat wall of switches. */
function FeatureSettings({
  features,
  onChange,
}: {
  features: Features
  /** A React state updater, not a plain setter -- reading `features` off
   * this component's own props would race two switches flipped in the same
   * render tick (each computing "next" from the same stale snapshot, so
   * only the last one's change survives). The functional form always reads
   * the true latest state. */
  onChange(updater: (prev: Features) => Features): void
}) {
  const set = <K extends keyof Features>(key: K, value: Features[K]) =>
    onChange((prev) => ({ ...prev, [key]: value }))
  const setColumn = <K extends keyof Features['columns']>(key: K, value: boolean) =>
    onChange((prev) => ({ ...prev, columns: { ...prev.columns, [key]: value } }))

  return (
    <div className="flex flex-col gap-2">
      {/* Every setting below is scoped to exactly one of these three groups
          -- a switch that only does something on two of the four views
          (Intraday Boost/Breakout Beacon/High Powered are one group here,
          Sectors is its own) needs to say so, or "why isn't this doing
          anything" is the first thing a user hits after turning it on
          while looking at the wrong tab. */}
      <ScopeHeader title="All views" scope="Applies everywhere -- ranked lists and Sectors" />
      <FeatureRow
        label="Freshness caption"
        checked={features.freshness}
        onChange={(v) => set('freshness', v)}
      />
      <FeatureRow
        label="Pause auto-refresh"
        checked={features.pauseAutoRefresh}
        onChange={(v) => set('pauseAutoRefresh', v)}
      />
      <label className="flex items-center justify-between gap-3 py-1 text-[12px]">
        <span className="text-foreground">Poll interval</span>
        <Select
          value={String(features.pollIntervalMs)}
          onValueChange={(v) => set('pollIntervalMs', Number(v))}
        >
          <SelectTrigger className="h-6 w-20 text-[11px]" aria-label="Poll interval">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {POLL_INTERVALS.map((ms) => (
              <SelectItem key={ms} value={String(ms)} className="text-[11px]">
                {ms / 1000}s
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </label>
      <FeatureRow
        label="JWT health badge"
        checked={features.jwtHealth}
        onChange={(v) => set('jwtHealth', v)}
      />
      <FeatureRow
        label="Retry backoff on failure"
        checked={features.retryBackoff}
        onChange={(v) => set('retryBackoff', v)}
      />
      <FeatureRow
        label="Compact rows"
        checked={features.compactDensity}
        onChange={(v) => set('compactDensity', v)}
      />
      <FeatureRow
        label="Add-to-watchlist button"
        checked={features.addToWatchlist}
        onChange={(v) => set('addToWatchlist', v)}
      />

      <ScopeHeader
        title="Ranked lists only"
        scope="Intraday Boost · Breakout Beacon · High Powered -- has no effect on Sectors"
      />
      <FeatureRow
        label="Symbol search"
        checked={features.search}
        onChange={(v) => set('search', v)}
      />
      <FeatureRow
        label="Rank change arrows"
        checked={features.rankArrows}
        onChange={(v) => set('rankArrows', v)}
      />
      <FeatureRow
        label="Pin/favorite symbols"
        checked={features.pinning}
        onChange={(v) => set('pinning', v)}
      />
      <FeatureRow
        label="Score sparkline"
        checked={features.scoreSparkline}
        onChange={(v) => set('scoreSparkline', v)}
      />
      <FeatureRow
        label="Rank timeline chart"
        checked={features.rankTimeline}
        onChange={(v) => set('rankTimeline', v)}
      />
      <label className="flex items-center justify-between gap-3 py-1 text-[12px]">
        <span className="text-foreground">Min score</span>
        <input
          type="number"
          min={0}
          step={0.5}
          value={features.scoreThreshold ?? ''}
          onChange={(e) =>
            set('scoreThreshold', e.target.value === '' ? null : Number(e.target.value))
          }
          placeholder="Off"
          className="h-6 w-16 rounded border bg-background px-1.5 text-right text-[11px]"
        />
      </label>
      <label className="flex flex-col gap-0.5 py-1 text-[12px]">
        <span className="flex items-center justify-between gap-3">
          <span className="text-foreground">CPR bias</span>
          <Select
            value={features.cprFilter}
            onValueChange={(v) => set('cprFilter', v as CprFilter)}
          >
            <SelectTrigger className="h-6 w-28 text-[11px]" aria-label="CPR bias filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CPR_FILTERS.map((f) => (
                <SelectItem key={f.id} value={f.id} className="text-[11px]">
                  {f.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </span>
        <span className="text-[10px] text-muted-foreground">
          Only Intraday Boost carries real CPR data -- filtering the other two lists returns
          nothing.
        </span>
      </label>
      <FeatureRow
        label={`New entrant (top ${NEW_ENTRANT_TOP_N})`}
        checked={features.newEntrantAlert}
        onChange={(v) => set('newEntrantAlert', v)}
      />
      <label className="flex items-center justify-between gap-3 py-1 text-[12px]">
        <span className="text-foreground">Alert on score ≥</span>
        <input
          type="number"
          min={0}
          step={0.5}
          value={features.scoreCrossAlert ?? ''}
          onChange={(e) =>
            set('scoreCrossAlert', e.target.value === '' ? null : Number(e.target.value))
          }
          placeholder="Off"
          className="h-6 w-16 rounded border bg-background px-1.5 text-right text-[11px]"
        />
      </label>
      <FeatureRow
        label="Auto-chart rank #1"
        checked={features.autoChartTop1}
        onChange={(v) => set('autoChartTop1', v)}
      />
      <FeatureRow
        label="Clean climber badge"
        checked={features.cleanClimbAlert}
        onChange={(v) => set('cleanClimbAlert', v)}
      />
      <span className="block pb-1 text-[10px] text-muted-foreground">
        Flags a stock that climbed from outside the top {CLIMB_EARLY_RANK_FLOOR} into the top{' '}
        {CLIMB_TOP_K} today without a gap-up open.
      </span>
      <FeatureRow
        label="Base breakout badge"
        checked={features.baseBreakoutAlert}
        onChange={(v) => set('baseBreakoutAlert', v)}
      />
      <span className="block pb-1 text-[10px] text-muted-foreground">
        Flags a stock that consolidated in a tight range, then broke above it. Both badges refresh
        every 5 min, matching the snapshot cadence.
      </span>
      <FeatureRow
        label="Rank movement alerts"
        checked={features.movementAlerts}
        onChange={(v) => set('movementAlerts', v)}
      />
      <span className="block pb-1 text-[10px] text-muted-foreground">
        Toasts a new Top-10 entry, fast climb or rank jump on the active list. The badges show
        either way.
      </span>
      <label className="flex flex-col gap-0.5 py-1 text-[12px]">
        <span className="text-foreground">Columns</span>
        <span className="text-[10px] text-muted-foreground">
          LTP/Change % are hidden on Breakout Beacon regardless of this setting -- that list's own
          fields aren't real quote data.
        </span>
      </label>
      <FeatureRow
        label="LTP"
        checked={features.columns.ltp}
        onChange={(v) => setColumn('ltp', v)}
      />
      <FeatureRow
        label="Change %"
        checked={features.columns.chg}
        onChange={(v) => setColumn('chg', v)}
      />
      <FeatureRow
        label="Score"
        checked={features.columns.score}
        onChange={(v) => setColumn('score', v)}
      />
      <FeatureRow
        label="CPR indicator"
        checked={features.columns.cpr}
        onChange={(v) => setColumn('cpr', v)}
      />
      <FeatureRow
        label="Directional score"
        checked={features.columns.directional}
        onChange={(v) => setColumn('directional', v)}
      />
      <label className="flex flex-col gap-0.5 py-1 text-[12px]">
        <span className="flex items-center justify-between gap-3">
          <span className="text-foreground">Top N (by directional score)</span>
          <Select
            value={String(features.topN ?? 'off')}
            onValueChange={(v) => set('topN', v === 'off' ? null : Number(v))}
          >
            <SelectTrigger className="h-6 w-16 text-[11px]" aria-label="Top N filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="off" className="text-[11px]">
                Off
              </SelectItem>
              {TOP_N_OPTIONS.map((n) => (
                <SelectItem key={n} value={String(n)} className="text-[11px]">
                  {n}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </span>
        <span className="text-[10px] text-muted-foreground">
          Only Intraday Boost carries a directional score -- has no effect on the other lists.
        </span>
      </label>

      <ScopeHeader
        title="Sectors only"
        scope="Has no effect on Intraday Boost/Breakout Beacon/High Powered"
      />
      <FeatureRow
        label="Sector quick-filter chips"
        checked={features.sectorChips}
        onChange={(v) => set('sectorChips', v)}
      />
      <FeatureRow
        label="Sector rank timeline chart"
        checked={features.sectorRankTimeline}
        onChange={(v) => set('sectorRankTimeline', v)}
      />
      {features.sectorRankTimeline && (
        <p className="text-[10px] text-muted-foreground/70">
          Needs the backend snapshot scheduler enabled (TF_BOOST_SNAPSHOT_ENABLED) -- shows today's
          history only, from the moment it was turned on.
        </p>
      )}
    </div>
  )
}

interface Props {
  apiKey: string
  onPick(row: SearchRow): void
  activeSymbol?: string | null
}

export function TradeFinderPanel({ apiKey, onPick, activeSymbol }: Props) {
  const [view, setView] = useState<ViewId>(readView)
  const [pulse, setPulse] = useState<MarketPulseData | null>(null)
  const [pulseError, setPulseError] = useState<string | null>(null)
  const [pulseLoading, setPulseLoading] = useState(false)

  const [sectorData, setSectorData] = useState<SectorScopeData | null>(null)
  const [sectorError, setSectorError] = useState<string | null>(null)
  const [sectorLoading, setSectorLoading] = useState(false)
  const [selectedSector, setSelectedSector] = useState<string | null>(null)
  /** Off (null) until the user picks one from the panel -- the stock list
   * keeps its default ranking by |rfactor| unless Gainers/Losers is chosen. */
  const [sortMode, setSortMode] = useState<SortMode | null>(null)

  /** Bumped by the refresh button to force an immediate reload. */
  const [attempt, setAttempt] = useState(0)
  const attemptRef = useRef(0)

  const [features, setFeatures] = useState<Features>(readFeatures)
  /** Read inside the poll interval's closure instead of as an effect
   * dependency -- restarting the interval on every toggle would also reset
   * its timing, so a pause flipped on right before a tick would still let
   * that tick through. A ref always reads the latest value without that. */
  const pauseRef = useRef(features.pauseAutoRefresh)
  useEffect(() => {
    pauseRef.current = features.pauseAutoRefresh
  }, [features.pauseAutoRefresh])
  /** Same reasoning as pauseRef, for retryBackoff -- read fresh inside the
   * poll effect's closure without making it an effect dependency. */
  // The one app-wide Socket.IO connection, so the panel is told when a snapshot
  // lands instead of discovering it on its own timer.
  const { socket } = useSocketContext()

  const featuresRef = useRef(features)
  useEffect(() => {
    featuresRef.current = features
  }, [features])
  /** Same reasoning again -- autoChartTop1 needs to know the active view
   * without the market_pulse poll effect restarting (and losing its rank
   * history) every time the user switches tabs. */
  const viewRef = useRef(view)
  useEffect(() => {
    viewRef.current = view
  }, [view])
  /** Read by the climb/breakout detector below, which runs on its own timer
   * independent of the market_pulse poll that actually sets this. */
  const pulseRef = useRef(pulse)
  useEffect(() => {
    pulseRef.current = pulse
  }, [pulse])
  /** Not guaranteed stable across renders (no memoization contract on the
   * prop), and this effect only runs once per apiKey/interval change --
   * without a ref, autoChartTop1 could call a version of onPick captured
   * from whichever render happened to be live when the effect last ran. */
  const onPickRef = useRef(onPick)
  useEffect(() => {
    onPickRef.current = onPick
  }, [onPick])

  // Rebuilt every render from listRows/selectedStocks below, so ArrowUp/Down
  // can move DOM focus to the newly-charted row without a second index to
  // keep in sync with activeSymbol.
  const listRowRefs = useRef<(HTMLButtonElement | null)[]>([])
  const sectorRowRefs = useRef<(HTMLButtonElement | null)[]>([])

  /** This poll's rank per symbol, so the next poll can tell whether each
   * symbol moved up or down the list -- compared, then overwritten, once
   * per successful fetch. Null until a symbol has been seen twice. */
  const prevRanksRef = useRef<Map<string, number>>(new Map())
  const [rankDeltas, setRankDeltas] = useState<Map<string, number>>(new Map())

  /** Last SCORE_HISTORY_LEN scores per (list, symbol), for the sparkline --
   * session-only, resets on remount. Not a backtest source, just "did this
   * just move" at a glance. */
  const scoreHistoryRef = useRef<Map<string, number[]>>(new Map())
  const [scoreHistoryTick, setScoreHistoryTick] = useState(0)

  /** This poll's top-N symbols per list, so a genuinely new entrant can be
   * told apart from a symbol that was always there. */
  const prevTopNRef = useRef<Map<string, Set<string>>>(new Map())
  /** Symbols already toasted for crossing scoreCrossAlert, cleared the
   * moment a symbol drops back below the threshold -- otherwise every poll
   * while it stays above would toast again. */
  const alertedSymbolsRef = useRef<Set<string>>(new Set())
  /** This poll's #1 symbol per list, so autoChartTop1 only fires on an
   * actual change of leader, not every poll the same leader holds. */
  const prevTop1Ref = useRef<Map<string, string>>(new Map())

  /** Symbols currently flagged by each detector, keyed by `${listKey}:${symbol}`
   * -- badges persist on the row for as long as the condition holds, unlike
   * the toasts below. Recomputed wholesale each detector poll (line ~955),
   * so a symbol that drops out of listRows or stops qualifying is dropped
   * too, rather than accumulating forever. */
  const [climbFlags, setClimbFlags] = useState<Map<string, string>>(new Map())
  const [breakoutFlags, setBreakoutFlags] = useState<Map<string, string>>(new Map())
  /** symbol -> current-day backend rank-movement row, for the active list.
   * Polled from /boostmovement (reconstructed from the server's snapshots, no
   * upstream fetch); empty on an older backend so rows just render no badge. */
  const [movement, setMovement] = useState<Map<string, BoostMovementRow>>(new Map())
  /** Why the badges are missing, when they are. Null means they simply are not
   * due yet -- the engine needs ten of today's snapshots before it calls a run. */
  const [movementError, setMovementError] = useState<string | null>(null)
  /** Symbols already toasted today for each detector -- same dedup shape as
   * alertedSymbolsRef, but never cleared mid-session (unlike scoreCrossAlert,
   * a climb/breakout is a one-time event for the day, not a level that can
   * be re-crossed). */
  const climbToastedRef = useRef<Set<string>>(new Set())
  const breakoutToastedRef = useRef<Set<string>>(new Set())

  const [pulseUpdatedAt, setPulseUpdatedAt] = useState<Date | null>(null)
  const [sectorUpdatedAt, setSectorUpdatedAt] = useState<Date | null>(null)
  const [search, setSearch] = useState('')
  const [jwtHealth, setJwtHealth] = useState<JwtHealthResponse | null>(null)
  const [timelineFor, setTimelineFor] = useState<string | null>(null)
  const [timelineData, setTimelineData] = useState<RankTimelinePoint[] | null>(null)
  const [timelineError, setTimelineError] = useState<string | null>(null)

  useEffect(() => {
    localStorage.setItem(PREFS_KEY, view)
  }, [view])

  useEffect(() => {
    localStorage.setItem(FEATURES_KEY, JSON.stringify(features))
  }, [features])

  /* ── market_pulse: the three ranked lists, polled regardless of which one
     is on screen so switching views never shows a stale list mid-load ── */
  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` is a deliberate re-run trigger, not a value this effect reads; the refresh button bumps it to refetch without changing the contract
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setInterval> | null = null
    let backoffTimer: ReturnType<typeof setTimeout> | null = null
    let backoffStep = 0

    const load = async () => {
      if (!alive || document.hidden) return
      setPulseLoading(true)
      try {
        const res = await tradefinderApi.getMarketPulse(apiKey)
        if (!alive) return
        if (res.status === 'success' && res.data) {
          setPulse(res.data)
          setPulseError(null)
          setPulseUpdatedAt(new Date())
          backoffStep = 0

          // Rank delta: this poll's position minus the last poll's, per
          // (list, symbol). Keyed by list too, since the same symbol can
          // hold a different rank on each of the three lists at once.
          const nextRanks = new Map<string, number>()
          const deltas = new Map<string, number>()
          const isFirstPoll = prevRanksRef.current.size === 0
          for (const listKey of [
            'intraday_boost',
            'breakout_beacon',
            'high_powered_stocks',
          ] as const) {
            const prevTopN = prevTopNRef.current.get(listKey) ?? new Set<string>()
            const nextTopN = new Set<string>()

            res.data[listKey].forEach((item, i) => {
              const key = `${listKey}:${item.symbol}`
              const rank = i + 1
              nextRanks.set(key, rank)
              const prevRank = prevRanksRef.current.get(key)
              if (prevRank != null && prevRank !== rank) deltas.set(key, prevRank - rank)

              if (featuresRef.current.scoreSparkline || featuresRef.current.rankTimeline) {
                const history = scoreHistoryRef.current.get(key) ?? []
                history.push(item.score)
                if (history.length > SCORE_HISTORY_LEN) history.shift()
                scoreHistoryRef.current.set(key, history)
              }

              if (i < NEW_ENTRANT_TOP_N) nextTopN.add(item.symbol)
              // A first poll has nothing to compare against -- every symbol
              // would read as "new", which is just noise on page load.
              if (
                featuresRef.current.newEntrantAlert &&
                !isFirstPoll &&
                i < NEW_ENTRANT_TOP_N &&
                !prevTopN.has(item.symbol)
              ) {
                showToast.info(`${item.symbol} entered the top ${NEW_ENTRANT_TOP_N} (${listKey})`)
              }

              const threshold = featuresRef.current.scoreCrossAlert
              if (threshold != null) {
                const alertKey = `${listKey}:${item.symbol}`
                if (item.score >= threshold) {
                  if (!alertedSymbolsRef.current.has(alertKey)) {
                    alertedSymbolsRef.current.add(alertKey)
                    showToast.success(
                      `${item.symbol} crossed score ${threshold} (${item.score.toFixed(1)})`
                    )
                  }
                } else {
                  alertedSymbolsRef.current.delete(alertKey)
                }
              }
            })
            prevTopNRef.current.set(listKey, nextTopN)

            if (featuresRef.current.autoChartTop1 && viewRef.current === listKey) {
              const top1 = res.data[listKey][0]?.symbol
              if (top1 && prevTop1Ref.current.get(listKey) !== top1 && !isFirstPoll) {
                onPickRef.current({ symbol: top1, exchange: 'NSE' })
              }
              if (top1) prevTop1Ref.current.set(listKey, top1)
            }
          }
          prevRanksRef.current = nextRanks
          setRankDeltas(deltas)
          if (featuresRef.current.scoreSparkline) setScoreHistoryTick((n) => n + 1)
        } else {
          setPulseError(res.message ?? 'Failed to load TradeFinder data')
          scheduleBackoffRetry()
        }
      } catch {
        if (!alive) return
        setPulseError('Failed to load TradeFinder data')
        scheduleBackoffRetry()
      } finally {
        if (alive) setPulseLoading(false)
      }
    }

    /** Off by default -- on, a failed fetch retries at 2s/5s/15s instead of
     * waiting out the rest of the normal poll interval. Caps at 15s and
     * resets the moment a fetch succeeds, so a real outage doesn't spin. */
    const scheduleBackoffRetry = () => {
      if (!featuresRef.current.retryBackoff || !alive || pauseRef.current) return
      const delays = [2_000, 5_000, 15_000]
      const delay = delays[Math.min(backoffStep, delays.length - 1)]
      backoffStep += 1
      backoffTimer = setTimeout(load, delay)
    }

    load()
    timer = setInterval(
      () => {
        if (!pauseRef.current) load()
      },
      Math.max(5_000, features.pollIntervalMs)
    )
    const onVisible = () => {
      if (!document.hidden && !pauseRef.current) load()
    }
    document.addEventListener('visibilitychange', onVisible)

    return () => {
      alive = false
      if (timer) clearInterval(timer)
      if (backoffTimer) clearTimeout(backoffTimer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [apiKey, attempt, features.pollIntervalMs])

  /* ── rank-movement: current-day engine state for the active boost list.
     Polled every 60s (the snapshots are 1-minute, so faster buys nothing) and
     only for the ranked lists, not Sectors. Degrades to an empty map. ── */
  useEffect(() => {
    // Drop the previous list's rows before the first fetch of the new one:
    // they are keyed by symbol alone, so leaving them up would badge the new
    // list's rows from the old list's state and feed the alert baseline below
    // a movement map that does not belong to `view`.
    setMovement(new Map())
    if (view === 'sectors') return
    let alive = true
    const load = async () => {
      if (!alive || document.hidden) return
      try {
        const res = await tradefinderApi.getBoostMovement(apiKey, view)
        if (!alive) return
        const ok = res.status === 'success' && res.symbols
        setMovement(ok ? new Map(res.symbols!.map((r) => [r.symbol, r])) : new Map())
        // An empty board and a board that failed to load look identical, which
        // is how "I don't see the badge" became unanswerable: nobody could tell
        // whether nothing qualified or nothing arrived. Say which.
        setMovementError(ok ? null : (res.message ?? 'Movement data unavailable'))
      } catch {
        if (alive) {
          setMovement(new Map())
          setMovementError('Could not reach the movement engine')
        }
      }
    }
    load()
    // The snapshot is written 0.8s after the minute, so waiting on a blind 60s
    // timer added another 31s on average before the badge reached the screen.
    // The recorder now emits `boost_snapshot` the moment the row exists; the
    // timer stays as the fallback for a disconnected socket or an older backend.
    const onSnapshot = () => load()
    socket?.on('boost_snapshot', onSnapshot)
    const timer = setInterval(load, 60_000)
    return () => {
      alive = false
      socket?.off('boost_snapshot', onSnapshot)
      clearInterval(timer)
    }
  }, [apiKey, view, socket])

  /** How many tracked symbols currently carry a badge -- counted from the same
   * table MovementBadge draws from, so the header cannot claim a badge the rows
   * do not show. */
  const badgedCount = [...movement.values()].filter((mv) => MOVEMENT_BADGE[mv.event]).length

  /* ── rank-movement alerts: toast a NEW salient backend event. The first
     populated poll of each list only sets a baseline (otherwise every event
     already in progress toasts at once), and the toggle-off path keeps that
     baseline current so switching it on later never dumps a backlog. Keys
     carry the list, because the panel swaps `movement` wholesale when the
     view changes and a shared key set would read that as 200 new events. ── */
  const movementAlertedRef = useRef<Map<string, string>>(new Map())
  const movementCooldownRef = useRef<Map<string, number>>(new Map())
  const movementBaselinedRef = useRef<Set<string>>(new Set())
  useEffect(() => {
    if (movement.size === 0) return
    const baseline = () => {
      for (const [sym, mv] of movement) movementAlertedRef.current.set(`${view}:${sym}`, mv.event)
    }
    if (!movementBaselinedRef.current.has(view)) {
      movementBaselinedRef.current.add(view)
      baseline()
      return
    }
    if (!featuresRef.current.movementAlerts) {
      baseline()
      return
    }
    const now = Date.now()
    const fresh: string[] = []
    for (const [sym, mv] of movement) {
      if (mv.event_priority < MOVEMENT_ALERT_MIN_PRIORITY) continue
      const key = `${view}:${sym}`
      if (movementAlertedRef.current.get(key) === mv.event) continue
      movementAlertedRef.current.set(key, mv.event)
      const last = movementCooldownRef.current.get(key) ?? 0
      if (now - last < MOVEMENT_ALERT_COOLDOWN_MS) continue
      movementCooldownRef.current.set(key, now)
      fresh.push(sym)
    }
    // Forget symbols that left THIS list, so a re-entry alerts again. Other
    // lists' keys are left alone -- they are not in `movement` right now.
    for (const key of [...movementAlertedRef.current.keys()]) {
      const [listKey, sym] = [key.slice(0, key.indexOf(':')), key.slice(key.indexOf(':') + 1)]
      if (listKey === view && !movement.has(sym)) movementAlertedRef.current.delete(key)
    }
    if (fresh.length === 0) return
    const summary = fresh
      .slice(0, 4)
      .map((s) => `${s} ${movement.get(s)!.event.replace(/_/g, ' ').toLowerCase()}`)
      .join(', ')
    showToast.info(`Rank movers: ${summary}`)
  }, [movement, view])

  /* ── sector_scope: only fetched while that view is actually selected ── */
  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` is a deliberate re-run trigger, not a value this effect reads; the refresh button bumps it to refetch without changing the contract
  useEffect(() => {
    if (view !== 'sectors') return
    let alive = true
    let timer: ReturnType<typeof setInterval> | null = null
    let backoffTimer: ReturnType<typeof setTimeout> | null = null
    let backoffStep = 0

    const load = async () => {
      if (!alive || document.hidden) return
      setSectorLoading(true)
      try {
        const res = await tradefinderApi.getSectorScope(apiKey)
        if (!alive) return
        if (res.status === 'success' && res.data) {
          setSectorData(res.data)
          setSectorError(null)
          setSectorUpdatedAt(new Date())
          backoffStep = 0
        } else {
          setSectorError(res.message ?? 'Failed to load sector data')
          scheduleBackoffRetry()
        }
      } catch {
        if (!alive) return
        setSectorError('Failed to load sector data')
        scheduleBackoffRetry()
      } finally {
        if (alive) setSectorLoading(false)
      }
    }

    const scheduleBackoffRetry = () => {
      if (!featuresRef.current.retryBackoff || !alive || pauseRef.current) return
      const delays = [2_000, 5_000, 15_000]
      const delay = delays[Math.min(backoffStep, delays.length - 1)]
      backoffStep += 1
      backoffTimer = setTimeout(load, delay)
    }

    load()
    timer = setInterval(
      () => {
        if (!pauseRef.current) load()
      },
      Math.max(5_000, features.pollIntervalMs)
    )
    return () => {
      alive = false
      if (timer) clearInterval(timer)
      if (backoffTimer) clearTimeout(backoffTimer)
    }
  }, [apiKey, view, attempt, features.pollIntervalMs])

  /* ── JWT health: off by default, a slow 60s poll -- this only checks the
     server-side token's expiry and kicks off a refresh if it's close, it
     never blocks on the actual (slow, browser-based) refresh itself. ── */
  useEffect(() => {
    if (!features.jwtHealth) return
    let alive = true
    const load = async () => {
      if (!alive || document.hidden) return
      try {
        const res = await tradefinderApi.getJwtHealth(apiKey)
        if (alive) setJwtHealth(res)
      } catch {
        // Silent: this is a secondary status indicator, not a fetch the
        // rest of the panel depends on -- an error here just means the
        // badge goes back to unknown until the next tick.
      }
    }
    load()
    const timer = setInterval(load, 60_000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [apiKey, features.jwtHealth])

  const refresh = () => {
    attemptRef.current += 1
    setAttempt(attemptRef.current)
  }

  const chartSymbol = (symbol: string) => {
    if (!symbol) return
    onPick({ symbol, exchange: 'NSE' })
  }

  /** Adds to whichever list WatchlistPanel currently has open -- reads the
   * same localStorage key it writes, rather than asking the user to pick a
   * list twice. Falls back to the first list if none is marked active. */
  const addToWatchlist = async (symbol: string) => {
    try {
      const savedId = Number(localStorage.getItem(ACTIVE_WATCHLIST_KEY))
      let listId = Number.isFinite(savedId) && savedId > 0 ? savedId : null
      if (listId == null) {
        const lists = await watchlistApi.list()
        listId = lists[0]?.id ?? null
      }
      if (listId == null) {
        showToast.error('No watchlist to add to -- create one first')
        return
      }
      await watchlistApi.addItem(listId, symbol, 'NSE')
      showToast.success(`Added ${symbol} to watchlist`)
    } catch {
      showToast.error(`Could not add ${symbol} to watchlist`)
    }
  }

  /* ── clean-climb / base-breakout badges: scans the whole day's rank+price
     timeline for the active list, every CLIMB_POLL_MS. Separate from the 30s
     market_pulse poll -- this data only refreshes every 5 min server-side
     (the snapshotter's own cadence), so polling it faster buys nothing. */
  useEffect(() => {
    if (!features.cleanClimbAlert && !features.baseBreakoutAlert) return
    if (view === 'sectors') return

    let alive = true

    const scan = async () => {
      const listKey = viewRef.current
      if (listKey === 'sectors' || !alive) return
      const symbols = pulseRef.current?.[listKey]?.map((r) => r.symbol) ?? []
      if (symbols.length === 0) return

      const today = new Date().toISOString().slice(0, 10)
      let res: BoostSnapshotsResponse
      try {
        res = await tradefinderApi.getBoostSnapshots(apiKey, today, listKey, {
          includePrices: true,
        })
      } catch {
        return
      }
      if (!alive || res.status !== 'success') return

      const ranks = res.ranks ?? {}
      const prices = res.prices ?? {}
      const nextClimb = new Map<string, string>()
      const nextBreakout = new Map<string, string>()

      for (const symbol of symbols) {
        const key = `${listKey}:${symbol}`
        const item = pulseRef.current?.[listKey]?.find((r) => r.symbol === symbol)

        if (featuresRef.current.cleanClimbAlert) {
          const rankPoints = ranks[symbol]?.[today] ?? []
          const priceForGap = prices[symbol]?.[today]?.[0]?.[1]
          if (rankPoints.length >= 2 && item) {
            const earlyRank = rankPoints[0][1]
            const bestRank = Math.min(...rankPoints.map((p) => p[1]))
            const gapPct =
              priceForGap != null && item.prev_close
                ? ((priceForGap - item.prev_close) / item.prev_close) * 100
                : 0
            if (
              earlyRank > CLIMB_EARLY_RANK_FLOOR &&
              bestRank <= CLIMB_TOP_K &&
              Math.abs(gapPct) < GAP_UP_MAX_PCT
            ) {
              const detail = `Climbed #${earlyRank} -> #${bestRank} today, no gap-up open`
              nextClimb.set(key, detail)
              if (!climbToastedRef.current.has(key)) {
                climbToastedRef.current.add(key)
                showToast.info(`${symbol}: ${detail}`)
              }
            }
          }
        }

        if (featuresRef.current.baseBreakoutAlert) {
          const pricePoints = prices[symbol]?.[today] ?? []
          if (pricePoints.length >= 4) {
            const latest = pricePoints[pricePoints.length - 1]
            // The base excludes the last couple of points -- otherwise the
            // breakout print itself would widen its own base range and could
            // never clear it.
            const baseCutoff = latest[0] - CONSOLIDATION_WINDOW_MIN
            const base = pricePoints
              .slice(0, -2)
              .filter((p) => p[0] >= baseCutoff)
              .map((p) => p[1])
            if (base.length >= 3) {
              const baseMin = Math.min(...base)
              const baseMax = Math.max(...base)
              const rangePct = ((baseMax - baseMin) / baseMin) * 100
              const breakoutPct = ((latest[1] - baseMax) / baseMax) * 100
              if (rangePct < CONSOLIDATION_RANGE_MAX_PCT && breakoutPct >= BREAKOUT_MARGIN_PCT) {
                const detail = `Broke a ${rangePct.toFixed(1)}% base, +${breakoutPct.toFixed(1)}% breakout`
                nextBreakout.set(key, detail)
                if (!breakoutToastedRef.current.has(key)) {
                  breakoutToastedRef.current.add(key)
                  showToast.info(`${symbol}: ${detail}`)
                }
              }
            }
          }
        }
      }

      if (!alive) return
      if (featuresRef.current.cleanClimbAlert) setClimbFlags(nextClimb)
      if (featuresRef.current.baseBreakoutAlert) setBreakoutFlags(nextBreakout)
    }

    scan()
    const timer = setInterval(scan, CLIMB_POLL_MS)
    return () => {
      alive = false
      clearInterval(timer)
    }
    // biome-ignore lint/correctness/useExhaustiveDependencies: apiKey is stable for the panel's life; pulse/featuresRef/viewRef are read fresh via ref on each tick rather than restarting the timer
  }, [features.cleanClimbAlert, features.baseBreakoutAlert, view, apiKey])

  /** Fetches once per click, not polled -- this is a look-up, not a live
   * value, and the endpoint it calls is the backtesting one, not something
   * meant for repeated hammering. */
  const openTimeline = async (symbol: string, listKey: ListView | 'sector_index') => {
    setTimelineFor(symbol)
    setTimelineData(null)
    setTimelineError(null)
    try {
      const today = new Date().toISOString().slice(0, 10)
      const res: BoostSnapshotsResponse = await tradefinderApi.getBoostSnapshots(
        apiKey,
        today,
        listKey
      )
      if (res.status === 'success') {
        setTimelineData(res.ranks?.[symbol]?.[today] ?? [])
      } else {
        setTimelineError(res.message ?? 'Failed to load rank history')
      }
    } catch {
      setTimelineError('Failed to load rank history')
    }
  }

  const loading = view === 'sectors' ? sectorLoading : pulseLoading

  const pinnedSet = new Set(features.pinnedSymbols)
  const togglePin = (symbol: string) => {
    setFeatures((prev) => ({
      ...prev,
      pinnedSymbols: prev.pinnedSymbols.includes(symbol)
        ? prev.pinnedSymbols.filter((s) => s !== symbol)
        : [...prev.pinnedSymbols, symbol],
    }))
  }

  const listRowsAll: TfListItem[] = view === 'sectors' ? [] : (pulse?.[view as ListView] ?? [])
  let listRows = listRowsAll
  if (features.search && search.trim()) {
    const q = search.trim().toLowerCase()
    listRows = listRows.filter((r) => r.symbol.toLowerCase().includes(q))
  }
  if (features.scoreThreshold != null) {
    listRows = listRows.filter((r) => r.score >= (features.scoreThreshold as number))
  }
  if (features.cprFilter !== 'all') {
    listRows = listRows.filter((r) => r.cpr_bias === features.cprFilter)
  }
  if (features.pinning && pinnedSet.size > 0) {
    // Stable partition, not a re-sort: everything keeps the rank order the
    // backend gave it, pinned rows just move as a block to the front.
    listRows = [
      ...listRows.filter((r) => pinnedSet.has(r.symbol)),
      ...listRows.filter((r) => !pinnedSet.has(r.symbol)),
    ]
  }
  // Only intraday_boost ever carries a directional_score (same server-side
  // enrichment scope as CPR/first-candle) -- applying this on the other
  // lists would just re-sort everything to null and return nothing useful.
  if (features.topN != null && view === 'intraday_boost') {
    listRows = listRows
      .slice()
      .sort((a, b) => (b.directional_score ?? -1) - (a.directional_score ?? -1))
      .slice(0, features.topN)
  }
  const showQuoteColumns = view !== 'breakout_beacon'

  const sectorEntries = sectorData
    ? Object.entries(sectorData.sectors).map(([key, stocks]) => ({
        name: key.replace(/_r_factor$/, ''),
        key,
        stocks,
      }))
    : []
  const sectorIndex = sectorData?.index ?? []

  /** Every sector's stocks combined, deduped by symbol -- a stock can sit in
   * more than one sector group, and "ALL" means one row per stock, not one
   * per (sector, stock) pair. */
  const allStocksMap = new Map<string, SectorStockItem>()
  for (const entry of sectorEntries) {
    for (const stock of Object.values(entry.stocks)) {
      if (!allStocksMap.has(stock.symbol)) allStocksMap.set(stock.symbol, stock)
    }
  }

  const selectedStocksRaw: SectorStockItem[] =
    selectedSector === ALL_SECTORS
      ? Array.from(allStocksMap.values())
      : selectedSector
        ? Object.values(sectorEntries.find((s) => s.key === selectedSector)?.stocks ?? {})
        : []

  const selectedStocks = selectedStocksRaw.slice().sort((a, b) => {
    if (sortMode === 'gainers') return b.param_3 - a.param_3
    if (sortMode === 'losers') return a.param_3 - b.param_3
    return Math.abs(b.param_3) - Math.abs(a.param_3)
  })

  return (
    <PanelShell
      id="oa-panel-tradefinder"
      label="TradeFinder"
      storageKey="oa-trading-tradefinder-width"
      defaultWidth={340}
      minWidth={300}
    >
      <div className={PANEL_HEADER}>
        <Select
          value={view}
          onValueChange={(value) => {
            setView(value as ViewId)
            setSelectedSector(null)
          }}
        >
          <SelectTrigger className="h-8 min-w-0 flex-1 text-[12px]" aria-label="TradeFinder list">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {VIEWS.map((v) => (
              <SelectItem key={v.id} value={v.id} className="text-[12px]">
                {v.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {features.jwtHealth && <JwtHealthBadge health={jwtHealth} />}

        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={refresh}
          title="Refresh"
          aria-label="Refresh TradeFinder data"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
        </Button>

        <Popover>
          <PopoverTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 shrink-0"
              title="TradeFinder settings"
              aria-label="TradeFinder settings"
            >
              <Settings2 className="h-3.5 w-3.5" />
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="max-h-[80vh] w-64 overflow-y-auto p-3">
            <FeatureSettings features={features} onChange={setFeatures} />
          </PopoverContent>
        </Popover>
      </div>

      {/* Whether the movement data arrived, and how much of it. Badges missing
          because nothing qualified, because nothing arrived, and because the
          page is running an older bundle all looked identical on screen -- and
          that is the whole question when someone says they cannot see a badge. */}
      {view !== 'sectors' && (
        <div className="shrink-0 border-b px-2 py-1 text-[10px]">
          {movementError ? (
            <span className="text-amber-500">{movementError} -- no rank badges</span>
          ) : (
            <span className="text-muted-foreground">
              {movement.size === 0
                ? 'Waiting for the movement engine'
                : `${movement.size} symbols tracked, ${badgedCount} badged`}
            </span>
          )}
        </div>
      )}

      {/* Off by default, like every feature here -- filters the active list
          by typed text once turned on in settings. */}
      {features.search && view !== 'sectors' && (
        <div className="flex shrink-0 items-center gap-1.5 border-b px-2 py-1.5">
          <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter symbols…"
            className="h-7 text-[12px]"
          />
        </div>
      )}

      {view !== 'sectors' && (
        <>
          <div
            className={cn(
              ROW_GRID,
              'shrink-0 border-b px-2 py-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70'
            )}
          >
            <span>#</span>
            <span>Symbol</span>
            <span className="text-right">
              {showQuoteColumns && features.columns.ltp ? 'LTP' : ''}
            </span>
            <span className="text-right">
              {showQuoteColumns && features.columns.chg ? 'Chg' : ''}
            </span>
            <span className="text-right">{features.columns.score ? 'Score' : ''}</span>
            <span className="text-right">{features.columns.directional ? 'Dir' : ''}</span>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {pulseError && listRows.length === 0 ? (
              <div className="flex flex-col items-center gap-2 p-6 text-center">
                <p className="text-[12px] text-muted-foreground">{pulseError}</p>
                <Button variant="outline" size="sm" className="h-7 gap-1.5" onClick={refresh}>
                  <RefreshCw className="h-3.5 w-3.5" />
                  Retry
                </Button>
              </div>
            ) : pulseLoading && listRows.length === 0 ? (
              <p className="p-3 text-[12px] text-muted-foreground">Loading TradeFinder list…</p>
            ) : listRows.length === 0 ? (
              <p className="p-3 text-[12px] text-muted-foreground">
                {search.trim() ? 'No symbols match.' : 'No symbols in this list right now.'}
              </p>
            ) : (
              listRows.map((item, i) => (
                <button
                  key={item.symbol}
                  ref={(el) => {
                    listRowRefs.current[i] = el
                  }}
                  type="button"
                  onClick={(e) => {
                    chartSymbol(item.symbol)
                    // Click-to-focus on a <button> isn't guaranteed (macOS
                    // Safari skips it without Full Keyboard Access), so without
                    // this an arrow key right after a mouse click would do
                    // nothing until the row was tabbed to instead.
                    e.currentTarget.focus()
                  }}
                  onKeyDown={(e) => {
                    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
                    e.preventDefault()
                    const next = i + (e.key === 'ArrowDown' ? 1 : -1)
                    if (next < 0 || next >= listRows.length) return
                    chartSymbol(listRows[next].symbol)
                    listRowRefs.current[next]?.focus()
                    listRowRefs.current[next]?.scrollIntoView({ block: 'nearest' })
                  }}
                  className={cn(
                    ROW_GRID,
                    'w-full border-b border-border/40 px-2 text-left text-[12px] transition-colors hover:bg-accent',
                    features.compactDensity ? 'py-0.5' : 'py-1',
                    activeSymbol === `NSE:${item.symbol}` &&
                      'font-medium ring-1 ring-inset ring-primary/60'
                  )}
                  title={`Chart ${item.symbol}`}
                >
                  <span className="text-muted-foreground tabular-nums">{i + 1}</span>
                  <span className="flex min-w-0 items-center justify-between gap-1">
                    <span className="flex min-w-0 items-center gap-1 truncate">
                      {features.columns.cpr && <CprDot item={item} />}
                      <span className="truncate">{item.symbol}</span>
                      {movement.has(item.symbol) && (
                        <MovementBadge mv={movement.get(item.symbol)!} />
                      )}
                      {climbFlags.has(`${view}:${item.symbol}`) && (
                        <MomentumBadge
                          kind="climb"
                          detail={climbFlags.get(`${view}:${item.symbol}`)!}
                        />
                      )}
                      {breakoutFlags.has(`${view}:${item.symbol}`) && (
                        <MomentumBadge
                          kind="breakout"
                          detail={breakoutFlags.get(`${view}:${item.symbol}`)!}
                        />
                      )}
                    </span>
                    <span className="flex shrink-0 items-center gap-1">
                      {features.rankArrows && (
                        <RankDeltaIcon delta={rankDeltas.get(`${view}:${item.symbol}`)} />
                      )}
                      {features.pinning && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            togglePin(item.symbol)
                          }}
                          className={cn(
                            'rounded p-0.5 hover:bg-primary/10',
                            pinnedSet.has(item.symbol)
                              ? 'text-primary'
                              : 'text-muted-foreground hover:text-primary'
                          )}
                          title={
                            pinnedSet.has(item.symbol)
                              ? `Unpin ${item.symbol}`
                              : `Pin ${item.symbol}`
                          }
                          aria-label={
                            pinnedSet.has(item.symbol)
                              ? `Unpin ${item.symbol}`
                              : `Pin ${item.symbol}`
                          }
                        >
                          {pinnedSet.has(item.symbol) ? (
                            <PinOff className="h-3 w-3" />
                          ) : (
                            <Pin className="h-3 w-3" />
                          )}
                        </button>
                      )}
                      {features.addToWatchlist && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            addToWatchlist(item.symbol)
                          }}
                          className="rounded p-0.5 text-muted-foreground hover:bg-primary/10 hover:text-primary"
                          title={`Add ${item.symbol} to watchlist`}
                          aria-label={`Add ${item.symbol} to watchlist`}
                        >
                          <Plus className="h-3 w-3" />
                        </button>
                      )}
                      {(features.scoreSparkline || features.rankTimeline) && (
                        <Popover
                          open={timelineFor === item.symbol}
                          onOpenChange={(open) => {
                            if (!open) setTimelineFor(null)
                          }}
                        >
                          <PopoverTrigger asChild>
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                if (timelineFor === item.symbol) {
                                  setTimelineFor(null)
                                } else if (features.rankTimeline) {
                                  openTimeline(item.symbol, view as ListView)
                                } else {
                                  setTimelineFor(item.symbol)
                                }
                              }}
                              className="rounded p-0.5 text-muted-foreground hover:bg-primary/10 hover:text-primary"
                              title={`${item.symbol} history`}
                              aria-label={`${item.symbol} history`}
                            >
                              <History className="h-3 w-3" />
                            </button>
                          </PopoverTrigger>
                          <PopoverContent
                            align="end"
                            className="w-auto p-0"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {features.scoreSparkline && (
                              <div className="flex items-center gap-2 border-b p-2">
                                <span className="text-[10px] text-muted-foreground">
                                  Score trend
                                </span>
                                <Sparkline
                                  key={scoreHistoryTick}
                                  values={
                                    scoreHistoryRef.current.get(`${view}:${item.symbol}`) ?? []
                                  }
                                />
                              </div>
                            )}
                            {features.rankTimeline &&
                              (timelineError ? (
                                <p className="p-3 text-[12px] text-muted-foreground">
                                  {timelineError}
                                </p>
                              ) : timelineData === null ? (
                                <p className="p-3 text-[12px] text-muted-foreground">Loading…</p>
                              ) : (
                                <RankTimelineChart points={timelineData} />
                              ))}
                          </PopoverContent>
                        </Popover>
                      )}
                    </span>
                  </span>
                  <span className="text-right tabular-nums">
                    {showQuoteColumns && features.columns.ltp && item.ltp
                      ? item.ltp.toFixed(2)
                      : ''}
                  </span>
                  {showQuoteColumns && features.columns.chg ? (
                    <ChgCell value={item.change_pct} />
                  ) : (
                    <span />
                  )}
                  {features.columns.score ? (
                    <ScoreCell
                      score={item.score}
                      direction={showQuoteColumns ? (item.change_pct >= 0 ? 'up' : 'down') : null}
                    />
                  ) : (
                    <span />
                  )}
                  {features.columns.directional ? <DirectionalScoreCell item={item} /> : <span />}
                </button>
              ))
            )}
          </div>

          {/* Off by default -- when on, a silent caption unless the feed has
              actually gone stale, matching OptionChainPanel's pattern. */}
          {features.freshness && pulseUpdatedAt && (
            <p
              className={cn(
                'shrink-0 border-t px-2 py-1 text-[10px]',
                pulseError ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'
              )}
            >
              {pulseError ? 'Not updating. ' : 'Updated '}
              {formatAgo(pulseUpdatedAt)}
            </p>
          )}
        </>
      )}

      {/* Sectors: both halves stay on screen at once -- picking a sector
          filled the whole panel with its stocks and hid every other sector's
          progress, so comparing two sectors meant bouncing back and forth.
          A fixed 50/50 split keeps the full index visible while drilling in. */}
      {view === 'sectors' && (
        <div className="flex min-h-0 flex-1 flex-col">
          {/* Off by default -- a faster way to jump straight to one of the
              strongest sectors without scrolling the full bar list first. */}
          {features.sectorChips && sectorIndex.length > 0 && (
            <div className="flex shrink-0 flex-wrap gap-1 border-b px-2 py-1.5">
              {sectorIndex
                .slice()
                .sort((a, b) => Math.abs(b.param_3) - Math.abs(a.param_3))
                .slice(0, 6)
                .map((sector) => {
                  const key = `${sector.Symbol}_r_factor`
                  return (
                    <button
                      key={sector.Symbol}
                      type="button"
                      onClick={() => setSelectedSector(key)}
                      disabled={!sectorEntries.some((s) => s.key === key)}
                      className={cn(
                        'rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors disabled:opacity-50',
                        selectedSector === key
                          ? 'border-primary bg-primary text-primary-foreground'
                          : 'border-border bg-background text-muted-foreground hover:bg-accent'
                      )}
                    >
                      {sector.Symbol.replace(/^NIFTY\s+/, '')}
                    </button>
                  )
                })}
            </div>
          )}
          <div className="min-h-0 flex-1 overflow-y-auto">
            {sectorError && sectorIndex.length === 0 ? (
              <div className="flex flex-col items-center gap-2 p-6 text-center">
                <p className="text-[12px] text-muted-foreground">{sectorError}</p>
                <Button variant="outline" size="sm" className="h-7 gap-1.5" onClick={refresh}>
                  <RefreshCw className="h-3.5 w-3.5" />
                  Retry
                </Button>
              </div>
            ) : sectorLoading && sectorIndex.length === 0 ? (
              <p className="p-3 text-[12px] text-muted-foreground">Loading sector data…</p>
            ) : sectorIndex.length === 0 ? (
              <p className="p-3 text-[12px] text-muted-foreground">No sector data right now.</p>
            ) : (
              (() => {
                const sorted = sectorIndex
                  .slice()
                  .sort((a, b) => Math.abs(b.param_3) - Math.abs(a.param_3))
                const maxAbs = Math.max(1e-6, ...sorted.map((s) => Math.abs(s.param_3)))
                return (
                  <>
                    {/* Every stock across every sector, ranked by highest
                        rfactor -- the one row that isn't a sector at all. */}
                    <SectorBarRow
                      label="ALL"
                      value={maxAbs}
                      maxAbs={maxAbs}
                      selected={selectedSector === ALL_SECTORS}
                      disabled={allStocksMap.size === 0}
                      onClick={() => setSelectedSector(ALL_SECTORS)}
                      isAll
                      countLabel={allStocksMap.size}
                    />
                    {sorted.map((sector) => {
                      const key = `${sector.Symbol}_r_factor`
                      return (
                        <SectorBarRow
                          key={sector.Symbol}
                          label={sector.Symbol.replace(/^NIFTY\s+/, '')}
                          value={sector.param_3}
                          maxAbs={maxAbs}
                          selected={selectedSector === key}
                          disabled={!sectorEntries.some((s) => s.key === key)}
                          onClick={() => setSelectedSector(key)}
                        />
                      )
                    })}
                  </>
                )
              })()
            )}
          </div>

          {/* Bottom half: the selected sector's stocks. A fixed height
              (not flex-1) so it holds its 50% share even while empty --
              otherwise the top half's list would jump to fill the panel
              every time the selection cleared. */}
          <div className="flex min-h-0 flex-1 flex-col border-t">
            <div className="flex shrink-0 items-center justify-between gap-2 border-b bg-muted/30 px-2 py-1">
              <span className="flex min-w-0 items-center gap-1">
                <span className="truncate text-[11px] font-medium">
                  {selectedSector === ALL_SECTORS
                    ? 'ALL'
                    : selectedSector
                      ? selectedSector.replace(/_r_factor$/, '')
                      : 'Select a sector'}
                </span>
                {features.sectorRankTimeline &&
                  selectedSector &&
                  selectedSector !== ALL_SECTORS &&
                  (() => {
                    const sectorSymbol = selectedSector.replace(/_r_factor$/, '')
                    return (
                      <Popover
                        open={timelineFor === sectorSymbol}
                        onOpenChange={(open) => {
                          if (!open) setTimelineFor(null)
                        }}
                      >
                        <PopoverTrigger asChild>
                          <button
                            type="button"
                            onClick={() => {
                              if (timelineFor === sectorSymbol) {
                                setTimelineFor(null)
                              } else {
                                openTimeline(sectorSymbol, 'sector_index')
                              }
                            }}
                            className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-primary/10 hover:text-primary"
                            title={`${sectorSymbol} rank history`}
                            aria-label={`${sectorSymbol} rank history`}
                          >
                            <History className="h-3 w-3" />
                          </button>
                        </PopoverTrigger>
                        <PopoverContent align="start" className="w-auto p-0">
                          {timelineError ? (
                            <p className="p-3 text-[12px] text-muted-foreground">{timelineError}</p>
                          ) : timelineData === null ? (
                            <p className="p-3 text-[12px] text-muted-foreground">Loading…</p>
                          ) : (
                            <RankTimelineChart points={timelineData} />
                          )}
                        </PopoverContent>
                      </Popover>
                    )
                  })()}
              </span>
              {/* Off by default -- the list keeps its |rfactor| ranking until
                  the user explicitly asks to see gainers or losers first.
                  Clicking the active mode again turns sorting back off. */}
              {selectedSector && (
                <div className="flex shrink-0 gap-1">
                  {SORT_MODES.map((mode) => (
                    <button
                      key={mode.id}
                      type="button"
                      onClick={() =>
                        setSortMode((current) => (current === mode.id ? null : mode.id))
                      }
                      className={cn(
                        'rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors',
                        sortMode === mode.id
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-background text-muted-foreground hover:bg-accent'
                      )}
                    >
                      {mode.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {!selectedSector ? (
                <p className="p-3 text-[12px] text-muted-foreground">
                  Pick a sector above to see its stocks here.
                </p>
              ) : selectedStocks.length === 0 ? (
                <p className="p-3 text-[12px] text-muted-foreground">No stocks in this sector.</p>
              ) : (
                selectedStocks.map((stock, i) => (
                  <button
                    key={stock.symbol}
                    ref={(el) => {
                      sectorRowRefs.current[i] = el
                    }}
                    type="button"
                    onClick={(e) => {
                      chartSymbol(stock.symbol)
                      e.currentTarget.focus()
                    }}
                    onKeyDown={(e) => {
                      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
                      e.preventDefault()
                      const next = i + (e.key === 'ArrowDown' ? 1 : -1)
                      if (next < 0 || next >= selectedStocks.length) return
                      chartSymbol(selectedStocks[next].symbol)
                      sectorRowRefs.current[next]?.focus()
                      sectorRowRefs.current[next]?.scrollIntoView({ block: 'nearest' })
                    }}
                    className={cn(
                      'grid w-full grid-cols-[1fr_52px_48px_44px] items-center gap-1 border-b border-border/40 px-2 text-left text-[12px] transition-colors hover:bg-accent',
                      features.compactDensity ? 'py-0.5' : 'py-1',
                      activeSymbol === `NSE:${stock.symbol}` &&
                        'font-medium ring-1 ring-inset ring-primary/60'
                    )}
                    title={`Chart ${stock.symbol}`}
                  >
                    <span className="flex min-w-0 items-center justify-between gap-1">
                      <span className="truncate">{stock.symbol}</span>
                      {features.addToWatchlist && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            addToWatchlist(stock.symbol)
                          }}
                          className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-primary/10 hover:text-primary"
                          title={`Add ${stock.symbol} to watchlist`}
                          aria-label={`Add ${stock.symbol} to watchlist`}
                        >
                          <Plus className="h-3 w-3" />
                        </button>
                      )}
                    </span>
                    <span className="text-right tabular-nums">{stock.param_0.toFixed(2)}</span>
                    <ChgCell value={stock.param_2} />
                    <span className="text-right tabular-nums">{stock.param_3.toFixed(2)}</span>
                  </button>
                ))
              )}
            </div>
            {features.freshness && sectorUpdatedAt && (
              <p
                className={cn(
                  'shrink-0 border-t px-2 py-1 text-[10px]',
                  sectorError ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'
                )}
              >
                {sectorError ? 'Not updating. ' : 'Updated '}
                {formatAgo(sectorUpdatedAt)}
              </p>
            )}
          </div>
        </div>
      )}
    </PanelShell>
  )
}
