import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { scalpingApi } from '@/api/scalping'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useMarketData } from '@/hooks/useMarketData'
import type { OptionChainRow, SelectedLeg } from '@/types/scalping'

const DEFAULT_STRIKE_COUNT = 10

function buildLeg(
  row: OptionChainRow | undefined,
  type: 'ce' | 'pe',
  foExchange: string
): SelectedLeg | null {
  if (!row) return null
  const leg = row[type]
  if (!leg?.symbol) return null
  return {
    symbol: leg.symbol,
    exchange: foExchange,
    optionType: type.toUpperCase() as 'CE' | 'PE',
    strike: row.strike,
    lotsize: leg.lotsize ?? 0,
    tickSize: leg.tick_size ?? 0,
  }
}

interface TickerProps {
  title: string
  symbol?: string
  ltp?: number
  changePercent?: number
}

function Ticker({ title, symbol, ltp, changePercent }: TickerProps) {
  const isUp = (changePercent ?? 0) >= 0
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="font-mono text-xs text-muted-foreground">{symbol ?? '—'}</div>
        <div className="font-mono text-2xl font-semibold tabular-nums">
          {ltp != null ? ltp.toFixed(2) : '—'}
        </div>
        {changePercent != null && (
          <div className={`font-mono text-sm ${isUp ? 'text-green-600' : 'text-red-600'}`}>
            {isUp ? '+' : ''}
            {changePercent.toFixed(2)}%
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function Scalping() {
  const [underlying, setUnderlying] = useState<string>('')
  const [expiry, setExpiry] = useState<string>('')
  const [ceStrike, setCeStrike] = useState<string>('')
  const [peStrike, setPeStrike] = useState<string>('')

  // Underlyings
  const { data: underlyingsResp } = useQuery({
    queryKey: ['scalping', 'underlyings'],
    queryFn: () => scalpingApi.getUnderlyings(),
  })
  const underlyings = underlyingsResp?.data ?? []
  const underlyingCfg = underlyings.find((u) => u.underlying === underlying)

  // Expiry (depends on underlying)
  const { data: expiryResp } = useQuery({
    queryKey: ['scalping', 'expiry', underlying],
    queryFn: () => scalpingApi.getExpiry(underlying),
    enabled: !!underlying,
  })
  const expiries = expiryResp?.data ?? []

  // Strikes / chain (depends on underlying + expiry)
  const { data: chainResp } = useQuery({
    queryKey: ['scalping', 'strikes', underlying, expiry],
    queryFn: () => scalpingApi.getStrikes(underlying, expiry, DEFAULT_STRIKE_COUNT),
    enabled: !!underlying && !!expiry,
  })
  const chain = useMemo(() => chainResp?.chain ?? [], [chainResp])
  const foExchange = chainResp?.fo_exchange ?? underlyingCfg?.fo_exchange ?? ''
  const indexExchange = chainResp?.index_exchange ?? underlyingCfg?.index_exchange ?? ''

  // Default the CE/PE strike to ATM once the chain loads.
  useEffect(() => {
    if (chainResp?.atm_strike != null && chain.length > 0) {
      const atm = String(chainResp.atm_strike)
      setCeStrike(atm)
      setPeStrike(atm)
    }
  }, [chainResp, chain])

  const ceRow = chain.find((r) => String(r.strike) === ceStrike)
  const peRow = chain.find((r) => String(r.strike) === peStrike)
  const ceLeg = buildLeg(ceRow, 'ce', foExchange)
  const peLeg = buildLeg(peRow, 'pe', foExchange)

  // Subscribe underlying + both legs to the live feed (Quote mode = ltp + change).
  const symbols = useMemo(() => {
    const list: Array<{ symbol: string; exchange: string }> = []
    if (underlying && indexExchange) list.push({ symbol: underlying, exchange: indexExchange })
    if (ceLeg) list.push({ symbol: ceLeg.symbol, exchange: ceLeg.exchange })
    if (peLeg) list.push({ symbol: peLeg.symbol, exchange: peLeg.exchange })
    return list
  }, [underlying, indexExchange, ceLeg, peLeg])

  const {
    data: marketData,
    isConnected,
    isAuthenticated,
    isFallbackMode,
  } = useMarketData({
    symbols,
    mode: 'Quote',
    enabled: symbols.length > 0,
  })

  const underlyingTick = marketData.get(`${indexExchange}:${underlying}`)?.data
  const ceTick = ceLeg ? marketData.get(`${ceLeg.exchange}:${ceLeg.symbol}`)?.data : undefined
  const peTick = peLeg ? marketData.get(`${peLeg.exchange}:${peLeg.symbol}`)?.data : undefined

  const wsBadge = isFallbackMode
    ? { label: 'Polling (REST)', variant: 'secondary' as const }
    : isAuthenticated
      ? { label: 'Live', variant: 'default' as const }
      : isConnected
        ? { label: 'Connecting…', variant: 'secondary' as const }
        : { label: 'Disconnected', variant: 'destructive' as const }

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Scalping Terminal</h1>
        <Badge variant={wsBadge.variant}>{wsBadge.label}</Badge>
      </div>

      {/* Selection controls */}
      <Card>
        <CardContent className="grid grid-cols-1 gap-4 pt-6 md:grid-cols-4">
          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">Underlying</label>
            <Select
              value={underlying}
              onValueChange={(v) => {
                setUnderlying(v)
                setExpiry('')
                setCeStrike('')
                setPeStrike('')
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select underlying" />
              </SelectTrigger>
              <SelectContent>
                {underlyings.map((u) => (
                  <SelectItem key={u.underlying} value={u.underlying}>
                    {u.underlying}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">Expiry</label>
            <Select value={expiry} onValueChange={setExpiry} disabled={!underlying}>
              <SelectTrigger>
                <SelectValue placeholder="Select expiry" />
              </SelectTrigger>
              <SelectContent>
                {expiries.map((e) => (
                  <SelectItem key={e} value={e}>
                    {e}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">Call Strike</label>
            <Select value={ceStrike} onValueChange={setCeStrike} disabled={chain.length === 0}>
              <SelectTrigger>
                <SelectValue placeholder="CE strike" />
              </SelectTrigger>
              <SelectContent>
                {chain.map((r) => (
                  <SelectItem key={`ce-${r.strike}`} value={String(r.strike)}>
                    {r.strike} {r.ce.label ? `(${r.ce.label})` : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">Put Strike</label>
            <Select value={peStrike} onValueChange={setPeStrike} disabled={chain.length === 0}>
              <SelectTrigger>
                <SelectValue placeholder="PE strike" />
              </SelectTrigger>
              <SelectContent>
                {chain.map((r) => (
                  <SelectItem key={`pe-${r.strike}`} value={String(r.strike)}>
                    {r.strike} {r.pe.label ? `(${r.pe.label})` : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Live tickers */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Ticker
          title="Call (CE)"
          symbol={ceLeg?.symbol}
          ltp={ceTick?.ltp}
          changePercent={ceTick?.change_percent}
        />
        <Ticker
          title={underlying || 'Underlying'}
          symbol={underlying}
          ltp={underlyingTick?.ltp}
          changePercent={underlyingTick?.change_percent}
        />
        <Ticker
          title="Put (PE)"
          symbol={peLeg?.symbol}
          ltp={peTick?.ltp}
          changePercent={peTick?.change_percent}
        />
      </div>
    </div>
  )
}
