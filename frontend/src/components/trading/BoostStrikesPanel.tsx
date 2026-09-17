/**
 * Badged stocks, and the liquid strikes you could actually trade them with.
 *
 * Two sections, because that is the order the decision is made in: which stock
 * the ranked list is flagging, and then which contract on it has enough volume
 * to get in and out of. Only badged names appear -- the full list lives in the
 * TradeFinder panel, and repeating it here would bury the handful that matter.
 *
 * The chain is fetched for one stock at a time, on selection. A chain call
 * quotes every strike through the broker, so pulling one for every badge at
 * once would be slow and would spend the rate limit on contracts nobody opened.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { optionChainApi } from '@/api/option-chain'
import { type BoostMovementRow, tradefinderApi } from '@/api/tradefinder'
import { badgeFor } from '@/lib/trading/boostBadge'
import { tradableSymbol } from '@/lib/trading/tfSymbol'
import { cn } from '@/lib/utils'
import { PANEL_HEADER, PanelShell } from './panelShell'

interface Props {
  apiKey: string
  /** Charts the underlying when a badged stock is picked, matching the
   * TradeFinder panel's behaviour so the two feel like one surface. */
  onPick?(row: { symbol: string; exchange: string }): void
  activeSymbol?: string
}

/** One tradable contract, flattened out of the chain's per-strike CE/PE pair. */
interface StrikeRow {
  symbol: string
  strike: number
  side: 'CE' | 'PE'
  label: string
  ltp: number
  bid: number
  ask: number
  volume: number
  oi: number
  lotsize: number
}

/** A contract nobody is trading cannot be got out of, whatever it shows. */
const MIN_VOLUME = 10_000
/** Where the split between the two sections is remembered. */
const LIST_HEIGHT_KEY = 'oa-trading-boost-list-height'
const DEFAULT_LIST_HEIGHT = 240
/** Below this a section shows fewer than three rows and stops being a list. */
const MIN_SECTION = 96
const MAX_SECTION = 600
/** Shared by the strike header and every strike row, so the columns line up. */
const STRIKE_GRID = 'grid grid-cols-[1fr_auto_auto_auto_auto] items-center gap-x-2'
const STRIKES_SHOWN = 8

function spreadPct(row: StrikeRow): number | null {
  if (!row.bid || !row.ask || row.ask <= 0) return null
  return ((row.ask - row.bid) / row.ask) * 100
}

export function BoostStrikesPanel({ apiKey, onPick, activeSymbol }: Props) {
  const [movement, setMovement] = useState<BoostMovementRow[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [expiry, setExpiry] = useState<string | null>(null)
  const [strikes, setStrikes] = useState<StrikeRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // ── section one: the badged stocks ──────────────────────────────────────
  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const res = await tradefinderApi.getBoostMovement(apiKey, 'intraday_boost')
        if (!alive) return
        const badged = (res.symbols ?? []).filter(
          (row) => row.present !== false && badgeFor(row.event)
        )
        setMovement(badged)
        setSelected((current) => current ?? badged[0]?.symbol ?? null)
      } catch {
        if (alive) setMovement([])
      }
    }
    load()
    const timer = setInterval(load, 60_000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [apiKey])

  // ── section two: the chain for whichever stock is selected ──────────────
  useEffect(() => {
    if (!selected) return
    let alive = true
    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        // TradeFinder may still be using a pre-rename name; the broker will not.
        const tradable = tradableSymbol(selected)
        const expiries = await optionChainApi.getExpiries(apiKey, tradable, 'NFO')
        const nearest = expiries.data?.[0]
        if (!nearest) {
          if (alive) {
            setStrikes([])
            setError('No listed options for this stock.')
          }
          return
        }
        if (alive) setExpiry(nearest)
        // /expiry answers in DD-MMM-YY ("29-SEP-26") while /optionchain expects
        // the master's own DDMMMYY ("29SEP26"), and the mismatch fails as a flat
        // "No strikes found" that reads like the stock has no options.
        const chain = await optionChainApi.getOptionChain(
          apiKey,
          tradable,
          'NSE',
          nearest.replace(/-/g, ''),
          6
        )
        if (!alive) return
        const rows: StrikeRow[] = []
        for (const entry of chain.chain ?? []) {
          for (const side of ['ce', 'pe'] as const) {
            const leg = entry[side]
            if (!leg) continue
            rows.push({
              symbol: leg.symbol,
              strike: entry.strike,
              side: side.toUpperCase() as 'CE' | 'PE',
              label: leg.label,
              ltp: leg.ltp,
              bid: leg.bid,
              ask: leg.ask,
              volume: leg.volume,
              oi: leg.oi,
              lotsize: leg.lotsize,
            })
          }
        }
        setStrikes(rows)
      } catch {
        if (alive) {
          setStrikes([])
          setError('Could not load the option chain for this stock.')
        }
      } finally {
        if (alive) setLoading(false)
      }
    }
    load()
    return () => {
      alive = false
    }
  }, [apiKey, selected])

  // How much of the panel the stock list gets. A trader watching two names
  // wants most of it on strikes; one watching twenty wants the opposite, and
  // no single split serves both -- so it is dragged and remembered, the same
  // way PanelShell treats the panel's own width.
  const [listHeight, setListHeight] = useState(() => {
    const saved = Number(localStorage.getItem(LIST_HEIGHT_KEY))
    return Number.isFinite(saved) && saved >= MIN_SECTION && saved <= MAX_SECTION
      ? saved
      : DEFAULT_LIST_HEIGHT
  })
  const heightRef = useRef(listHeight)
  const persistHeight = useCallback((value: number) => {
    localStorage.setItem(LIST_HEIGHT_KEY, String(Math.round(value)))
  }, [])
  /** Moves the divider and keeps the ref in step in the same breath.
   *
   * Assigning the ref during render instead leaves it a beat behind: a drag
   * that is one move and a release, or a key pressed and let go quickly, runs
   * its handler before React has re-rendered, and what gets written to storage
   * is the value from before the gesture. */
  const applyHeight = useCallback((next: number) => {
    const clamped = Math.min(MAX_SECTION, Math.max(MIN_SECTION, next))
    heightRef.current = clamped
    setListHeight(clamped)
  }, [])

  const startDrag = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) return
      event.preventDefault()
      const startY = event.clientY
      const startHeight = heightRef.current
      const onMove = (e: PointerEvent) => {
        // Dragging down grows the list above the handle.
        applyHeight(startHeight + (e.clientY - startY))
      }
      const onUp = () => {
        document.body.classList.remove('select-none', 'cursor-row-resize')
        window.removeEventListener('pointermove', onMove)
        window.removeEventListener('pointerup', onUp)
        window.removeEventListener('pointercancel', onUp)
        persistHeight(heightRef.current)
      }
      document.body.classList.add('select-none', 'cursor-row-resize')
      window.addEventListener('pointermove', onMove)
      window.addEventListener('pointerup', onUp)
      window.addEventListener('pointercancel', onUp)
    },
    [persistHeight, applyHeight]
  )

  const badge = movement.find((row) => row.symbol === selected)
  /** An up badge points at calls and a down badge at puts, so the side the
   * signal actually called is listed first rather than left to be found. */
  const preferredSide = badge?.run_direction === 'down' ? 'PE' : 'CE'

  const liquid = useMemo(() => {
    const tradable = strikes.filter((row) => row.volume >= MIN_VOLUME)
    return tradable
      .sort((a, b) => {
        if (a.side !== b.side) return a.side === preferredSide ? -1 : 1
        return b.volume - a.volume
      })
      .slice(0, STRIKES_SHOWN)
  }, [strikes, preferredSide])

  return (
    <PanelShell
      id="oa-panel-boost"
      label="Boost strikes"
      storageKey="oa-trading-boost-width"
      defaultWidth={300}
    >
      {/* The header's rule lands on the same line as every pane toolbar's, so
          the workspace reads as one horizon rather than a panel bolted on. */}
      <div className={PANEL_HEADER}>
        <span className="flex-1 truncate text-[13px] font-medium">Badged stocks</span>
        <span className="text-[11px] tabular-nums text-muted-foreground">{movement.length}</span>
      </div>

      <div className="min-h-0 shrink-0 overflow-y-auto" style={{ height: listHeight }}>
        {movement.length === 0 && (
          <p className="px-2 py-3 text-[11px] text-muted-foreground">
            Nothing is badged right now. Stocks appear here once the engine has enough of today's
            snapshots to call a move, from about 09:30.
          </p>
        )}
        {movement.map((row) => {
          const style = badgeFor(row.event)
          return (
            <button
              key={row.symbol}
              type="button"
              onClick={() => {
                setSelected(row.symbol)
                onPick?.({ symbol: row.symbol, exchange: 'NSE' })
              }}
              className={cn(
                'flex w-full items-center gap-1.5 px-2 py-1 text-left text-[12px] hover:bg-accent',
                selected === row.symbol && 'bg-accent',
                activeSymbol === row.symbol && 'font-medium'
              )}
            >
              <span className="w-5 shrink-0 text-right tabular-nums text-muted-foreground">
                {row.current_rank}
              </span>
              <span className="flex-1 truncate">{row.symbol}</span>
              {style && (
                <span className={cn('shrink-0 text-[10px] font-bold', style.className)}>
                  {style.text}
                </span>
              )}
              <span className="w-12 shrink-0 text-right tabular-nums">
                {row.day_change_pct != null ? `${row.day_change_pct.toFixed(2)}%` : ''}
              </span>
            </button>
          )
        })}
      </div>

      {/* The divider between the sections, dragged like the panel's own edge.
          Keyboard users get the arrow keys rather than a pointer gesture. */}
      {/* biome-ignore lint/a11y/useSemanticElements: the rule points at <hr>,
          which cannot be focusable or carry pointer handlers. role=separator
          with tabindex and aria-valuenow IS the ARIA window-splitter pattern. */}
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize badged stocks"
        aria-valuenow={listHeight}
        aria-valuemin={MIN_SECTION}
        aria-valuemax={MAX_SECTION}
        tabIndex={0}
        onPointerDown={startDrag}
        onKeyDown={(e) => {
          const step = e.key === 'ArrowUp' ? -16 : e.key === 'ArrowDown' ? 16 : 0
          if (!step) return
          applyHeight(heightRef.current + step)
          e.preventDefault()
        }}
        onKeyUp={() => persistHeight(heightRef.current)}
        onBlur={() => persistHeight(heightRef.current)}
        className="h-1 shrink-0 cursor-row-resize border-t bg-transparent transition-colors hover:bg-primary/40 focus-visible:bg-primary/40 focus-visible:outline-none"
      />

      <div className={cn(PANEL_HEADER, 'border-t')}>
        <span className="flex-1 truncate text-[13px] font-medium">
          {selected ? `${selected} strikes` : 'Strikes'}
        </span>
        {badge?.run_direction && (
          <span className="shrink-0 text-[10px] text-muted-foreground">{preferredSide} first</span>
        )}
        <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
          {expiry ?? ''}
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && <p className="px-2 py-3 text-[11px] text-muted-foreground">Loading…</p>}
        {!loading && error && <p className="px-2 py-3 text-[11px] text-red-500">{error}</p>}
        {!loading && !error && liquid.length === 0 && selected && (
          <p className="px-2 py-3 text-[11px] text-muted-foreground">
            No strike on this stock has traded {MIN_VOLUME.toLocaleString()} contracts today.
            Anything thinner is hard to get out of.
          </p>
        )}
        {!loading && liquid.length > 0 && (
          <div>
            {/* A grid rather than a table: every row is a button that charts
                the contract, and a button is the honest element for that.
                The template is shared with the header so the columns line up. */}
            <div className={cn(STRIKE_GRID, 'px-2 py-1 text-[10px] text-muted-foreground')}>
              <span>Strike</span>
              <span className="text-right">LTP</span>
              <span className="text-right">Spread</span>
              <span className="text-right">Volume</span>
              <span className="text-right">Lot</span>
            </div>
            {liquid.map((row) => {
              const spread = spreadPct(row)
              return (
                <button
                  key={row.symbol}
                  type="button"
                  title={`Chart ${row.symbol}`}
                  onClick={() => onPick?.({ symbol: row.symbol, exchange: 'NFO' })}
                  className={cn(
                    STRIKE_GRID,
                    'w-full px-2 py-1 text-left text-[12px] tabular-nums hover:bg-accent',
                    activeSymbol === row.symbol && 'bg-accent font-medium'
                  )}
                >
                  <span className="truncate">
                    <span
                      className={cn(
                        'font-medium',
                        row.side === 'CE' ? 'text-emerald-500' : 'text-red-500'
                      )}
                    >
                      {row.strike} {row.side}
                    </span>
                    {row.label && (
                      <span className="ml-1 text-[10px] text-muted-foreground">{row.label}</span>
                    )}
                  </span>
                  <span className="text-right">{row.ltp.toFixed(2)}</span>
                  <span
                    className={cn('text-right', spread != null && spread > 2 && 'text-amber-500')}
                  >
                    {spread != null ? `${spread.toFixed(1)}%` : '—'}
                  </span>
                  <span className="text-right">{(row.volume / 1000).toFixed(0)}k</span>
                  <span className="text-right text-muted-foreground">{row.lotsize}</span>
                </button>
              )
            })}
          </div>
        )}
      </div>
    </PanelShell>
  )
}
