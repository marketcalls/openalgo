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
}

/** Positional greeks sum — per share, not yet scaled by qty. */
function positionalGreeks(
  legs: StrategyLeg[],
  greeksByLeg: Record<string, LegGreeks>,
  inRupees: boolean
): { delta: number; theta: number; gamma: number; vega: number } {
  let d = 0,
    th = 0,
    g = 0,
    v = 0
  for (const leg of legs) {
    if (!leg.active || leg.segment !== 'OPTION') continue
    const grk = greeksByLeg[leg.id]
    if (!grk) continue
    const sign = leg.side === 'BUY' ? 1 : -1
    const qty = leg.lots * leg.lotSize
    const scale = inRupees ? sign * qty : sign
    d += scale * (grk.delta ?? 0)
    th += scale * (grk.theta ?? 0)
    g += scale * (grk.gamma ?? 0)
    v += scale * (grk.vega ?? 0)
  }
  return { delta: d, theta: th, gamma: g, vega: v }
}

function fmt(v: number | null, digits = 4): string {
  if (v === null || !isFinite(v)) return '-'
  return v.toFixed(digits)
}

export function GreeksTab({ legs, greeksByLeg }: GreeksTabProps) {
  const [inRupees, setInRupees] = useState(false)
  const positional = positionalGreeks(legs, greeksByLeg, inRupees)
  const digits = inRupees ? 2 : 4

  return (
    <div className="space-y-3 rounded-lg border bg-card p-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="text-xs">Position</TableHead>
            <TableHead className="text-xs">IV</TableHead>
            <TableHead className="text-xs">Delta</TableHead>
            <TableHead className="text-xs">Theta</TableHead>
            <TableHead className="text-xs">Gamma</TableHead>
            <TableHead className="text-xs">Vega</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {legs.length === 0 && (
            <TableRow>
              <TableCell colSpan={6} className="py-8 text-center text-xs text-muted-foreground">
                No legs yet.
              </TableCell>
            </TableRow>
          )}
          {legs.map((leg) => {
            const grk = greeksByLeg[leg.id]
            const sign = leg.side === 'BUY' ? 1 : -1
            const qty = leg.lots * leg.lotSize
            const scale = inRupees ? sign * qty : sign
            const descriptor =
              leg.segment === 'OPTION' && leg.strike !== undefined && leg.optionType
                ? `${leg.strike}${leg.optionType}`
                : 'FUT'
            return (
              <TableRow key={leg.id} className={leg.active ? '' : 'opacity-50'}>
                <TableCell className="text-xs font-medium">
                  {sign > 0 ? '+' : '-'}
                  {leg.lots}x {leg.expiry} {descriptor}
                </TableCell>
                <TableCell className="text-xs tabular-nums">{fmt(grk?.iv ?? null, 2)}</TableCell>
                <TableCell className="text-xs tabular-nums">
                  {fmt(
                    grk?.delta !== undefined && grk?.delta !== null ? scale * grk.delta : null,
                    digits
                  )}
                </TableCell>
                <TableCell className="text-xs tabular-nums">
                  {fmt(
                    grk?.theta !== undefined && grk?.theta !== null ? scale * grk.theta : null,
                    digits
                  )}
                </TableCell>
                <TableCell className="text-xs tabular-nums">
                  {fmt(
                    grk?.gamma !== undefined && grk?.gamma !== null ? scale * grk.gamma : null,
                    inRupees ? 2 : 6
                  )}
                </TableCell>
                <TableCell className="text-xs tabular-nums">
                  {fmt(
                    grk?.vega !== undefined && grk?.vega !== null ? scale * grk.vega : null,
                    digits
                  )}
                </TableCell>
              </TableRow>
            )
          })}
          {legs.length > 0 && (
            <TableRow className="bg-muted/40 font-semibold">
              <TableCell className="text-xs">Positional Greeks</TableCell>
              <TableCell className="text-xs">—</TableCell>
              <TableCell className="text-xs tabular-nums">
                {positional.delta.toFixed(digits)}
              </TableCell>
              <TableCell className="text-xs tabular-nums">
                {positional.theta.toFixed(digits)}
              </TableCell>
              <TableCell className="text-xs tabular-nums">
                {positional.gamma.toFixed(inRupees ? 2 : 6)}
              </TableCell>
              <TableCell className="text-xs tabular-nums">
                {positional.vega.toFixed(digits)}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      <div className="flex items-center gap-6 border-t pt-3">
        <label className="flex items-center gap-2 text-xs">
          <Checkbox checked={!inRupees} onCheckedChange={() => setInRupees(false)} />
          Greeks in Decimals
        </label>
        <label className="flex items-center gap-2 text-xs">
          <Checkbox checked={inRupees} onCheckedChange={() => setInRupees(true)} />
          Greeks in ₹ (per-position)
        </label>
      </div>
    </div>
  )
}
