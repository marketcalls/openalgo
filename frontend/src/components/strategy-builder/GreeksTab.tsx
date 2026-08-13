import { useState } from 'react'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { StrategyLeg } from '@/lib/strategyMath'

export interface LegGreeks {
  legId: string
  iv: number | null
  delta: number | null
  gamma: number | null
  theta: number | null
  vega: number | null
}

export interface GreeksTabProps {
  legs: StrategyLeg[]
  greeksByLeg: Record<string, LegGreeks>
  formatCurrency: (value: number) => string
}

/** Aggregate signed position sensitivities at each leg's actual contract quantity. */
export function aggregatePositionGreeks(
  legs: StrategyLeg[],
  greeksByLeg: Record<string, LegGreeks>
): { delta: number; theta: number; gamma: number; vega: number } {
  let delta = 0
  let theta = 0
  let gamma = 0
  let vega = 0

  for (const leg of legs) {
    if (!leg.active) continue
    const sign = leg.side === 'BUY' ? 1 : -1
    const scale = sign * leg.lots * leg.lotSize
    if (leg.segment === 'FUTURE') {
      delta += scale
      continue
    }

    const greeks = greeksByLeg[leg.id]
    if (!greeks) continue
    delta += scale * (greeks.delta ?? 0)
    theta += scale * (greeks.theta ?? 0)
    gamma += scale * (greeks.gamma ?? 0)
    vega += scale * (greeks.vega ?? 0)
  }

  return { delta, theta, gamma, vega }
}

function formatDecimal(value: number | null, digits: number): string {
  if (value === null || !Number.isFinite(value)) return '-'
  return value.toFixed(digits)
}

export function GreeksTab({ legs, greeksByLeg, formatCurrency }: GreeksTabProps) {
  const [currencyValues, setCurrencyValues] = useState(false)
  const positional = aggregatePositionGreeks(legs, greeksByLeg)
  const formatThetaOrVega = (value: number | null) => {
    if (value === null || !Number.isFinite(value)) return '-'
    return currencyValues ? formatCurrency(value) : value.toFixed(2)
  }

  return (
    <div className="space-y-3 rounded-lg border bg-card p-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-xs">Position</TableHead>
            <TableHead className="text-xs">IV</TableHead>
            <TableHead className="text-xs">Delta (underlying units)</TableHead>
            <TableHead className="text-xs">Theta (position currency per day)</TableHead>
            <TableHead className="text-xs">Gamma (delta units / price point)</TableHead>
            <TableHead className="text-xs">Vega (position currency per 1% IV)</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {legs.filter((leg) => leg.active).length === 0 && (
            <TableRow>
              <TableCell colSpan={6} className="py-8 text-center text-xs text-muted-foreground">
                {legs.length === 0
                  ? 'No legs yet.'
                  : 'All legs are excluded. Re-include at least one from the Positions panel.'}
              </TableCell>
            </TableRow>
          )}
          {legs
            .filter((leg) => leg.active)
            .map((leg) => {
              const greeks = greeksByLeg[leg.id]
              const sign = leg.side === 'BUY' ? 1 : -1
              const scale = sign * leg.lots * leg.lotSize
              const isFuture = leg.segment === 'FUTURE'
              const descriptor =
                leg.segment === 'OPTION' && leg.strike !== undefined && leg.optionType
                  ? `${leg.strike}${leg.optionType}`
                  : 'FUT'
              return (
                <TableRow key={leg.id}>
                  <TableCell className="text-xs font-medium">
                    {sign > 0 ? '+' : '-'}
                    {leg.lots}x {leg.expiry} {descriptor}
                  </TableCell>
                  <TableCell className="text-xs tabular-nums">
                    {formatDecimal(greeks?.iv ?? null, 2)}
                  </TableCell>
                  <TableCell className="text-xs tabular-nums">
                    {isFuture
                      ? scale.toFixed(2)
                      : formatDecimal(
                          greeks?.delta !== undefined && greeks.delta !== null
                            ? scale * greeks.delta
                            : null,
                          2
                        )}
                  </TableCell>
                  <TableCell className="text-xs tabular-nums">
                    {formatThetaOrVega(
                      isFuture
                        ? 0
                        : greeks?.theta !== undefined && greeks.theta !== null
                          ? scale * greeks.theta
                          : null
                    )}
                  </TableCell>
                  <TableCell className="text-xs tabular-nums">
                    {isFuture
                      ? (0).toFixed(6)
                      : formatDecimal(
                          greeks?.gamma !== undefined && greeks.gamma !== null
                            ? scale * greeks.gamma
                            : null,
                          6
                        )}
                  </TableCell>
                  <TableCell className="text-xs tabular-nums">
                    {formatThetaOrVega(
                      isFuture
                        ? 0
                        : greeks?.vega !== undefined && greeks.vega !== null
                          ? scale * greeks.vega
                          : null
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          {legs.length > 0 && (
            <TableRow className="bg-muted/40 font-semibold">
              <TableCell className="text-xs">Positional Greeks</TableCell>
              <TableCell className="text-xs">—</TableCell>
              <TableCell className="text-xs tabular-nums" data-testid="net-delta">
                {positional.delta.toFixed(2)}
              </TableCell>
              <TableCell className="text-xs tabular-nums" data-testid="net-theta">
                {formatThetaOrVega(positional.theta)}
              </TableCell>
              <TableCell className="text-xs tabular-nums" data-testid="net-gamma">
                {positional.gamma.toFixed(6)}
              </TableCell>
              <TableCell className="text-xs tabular-nums" data-testid="net-vega">
                {formatThetaOrVega(positional.vega)}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      <div className="flex items-center gap-6 border-t pt-3">
        <label className="flex items-center gap-2 text-xs">
          <Checkbox checked={!currencyValues} onCheckedChange={() => setCurrencyValues(false)} />
          Decimal values
        </label>
        <label className="flex items-center gap-2 text-xs">
          <Checkbox checked={currencyValues} onCheckedChange={() => setCurrencyValues(true)} />
          Currency values
        </label>
        <span className="text-xs text-muted-foreground">Signed position quantity</span>
      </div>
    </div>
  )
}
