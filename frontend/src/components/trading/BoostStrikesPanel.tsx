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

import { useEffect, useMemo, useState } from 'react'
import { optionChainApi } from '@/api/option-chain'
import { type BoostMovementRow, tradefinderApi } from '@/api/tradefinder'
import { badgeFor } from '@/lib/trading/boostBadge'
import { tradableSymbol } from '@/lib/trading/tfSymbol'
import { cn } from '@/lib/utils'

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
    <div className="flex h-full min-h-0 flex-col text-[12px]">
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex items-center justify-between border-b px-2 py-1.5">
          <span className="font-medium">Badged stocks</span>
          <span className="text-[10px] text-muted-foreground">{movement.length}</span>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
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
                  'flex w-full items-center gap-2 px-2 py-1 text-left hover:bg-accent',
                  selected === row.symbol && 'bg-accent',
                  activeSymbol === row.symbol && 'font-medium'
                )}
              >
                <span className="w-6 shrink-0 text-right tabular-nums text-muted-foreground">
                  {row.current_rank}
                </span>
                <span className="flex-1 truncate">{row.symbol}</span>
                {style && (
                  <span className={cn('shrink-0 text-[10px] font-bold', style.className)}>
                    {style.text}
                  </span>
                )}
                <span className="w-14 shrink-0 text-right tabular-nums">
                  {row.day_change_pct != null ? `${row.day_change_pct.toFixed(2)}%` : ''}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col border-t">
        <div className="flex items-center justify-between border-b px-2 py-1.5">
          <span className="font-medium">
            {selected ? `${selected} strikes` : 'Strikes'}
            {badge?.run_direction && (
              <span className="ml-1 text-[10px] text-muted-foreground">{preferredSide} first</span>
            )}
          </span>
          <span className="text-[10px] text-muted-foreground">{expiry ?? ''}</span>
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
            <table className="w-full">
              <thead className="text-[10px] text-muted-foreground">
                <tr>
                  <th className="px-2 py-1 text-left font-normal">strike</th>
                  <th className="py-1 text-right font-normal">ltp</th>
                  <th className="py-1 text-right font-normal">spread</th>
                  <th className="py-1 text-right font-normal">volume</th>
                  <th className="px-2 py-1 text-right font-normal">lot</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {liquid.map((row) => {
                  const spread = spreadPct(row)
                  return (
                    <tr key={row.symbol} className="hover:bg-accent">
                      <td className="px-2 py-1">
                        <span
                          className={cn(
                            'font-medium',
                            row.side === 'CE' ? 'text-emerald-500' : 'text-red-500'
                          )}
                        >
                          {row.strike} {row.side}
                        </span>
                        {row.label && (
                          <span className="ml-1 text-[10px] text-muted-foreground">
                            {row.label}
                          </span>
                        )}
                      </td>
                      <td className="py-1 text-right">{row.ltp.toFixed(2)}</td>
                      <td
                        className={cn(
                          'py-1 text-right',
                          spread != null && spread > 2 && 'text-amber-500'
                        )}
                      >
                        {spread != null ? `${spread.toFixed(1)}%` : '—'}
                      </td>
                      <td className="py-1 text-right">{(row.volume / 1000).toFixed(0)}k</td>
                      <td className="px-2 py-1 text-right text-muted-foreground">{row.lotsize}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
