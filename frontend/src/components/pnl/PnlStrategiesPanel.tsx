// frontend/src/components/pnl/PnlStrategiesPanel.tsx
/**
 * Strategies pane of the P&L page (fork-only): one row per strategy that the
 * Filters button has let through, with its realized, unrealized, net, max
 * drawdown and current drawdown. It does not filter anything itself: the
 * strategy filter lives in the Filters dialog and this pane shows the result.
 */
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cumulative, currentDrawdown, strategySummaries } from '@/lib/pnlCurve'
import type { PnlModel } from '@/lib/pnlModel'
import { strategyColor } from '@/lib/pnlPalette'
import { cn } from '@/lib/utils'

const pnlClass = (value: number) => (value >= 0 ? 'text-green-600' : 'text-red-600')

function percent(value: number | null): string {
  return value === null ? '-' : `${(value * 100).toFixed(0)}%`
}

function ratio(value: number | null): string {
  return value === null ? '-' : value.toFixed(2)
}

interface Props {
  model: PnlModel
  formatCurrency: (value: number) => string
  isDark: boolean
}

export function PnlStrategiesPanel({ model, formatCurrency, isDark }: Props) {
  const [open, setOpen] = useState(true)

  const rows = useMemo(() => {
    const dates = model.series.dates
    return strategySummaries(model.series).map((row) => {
      const daily = model.series.byStrategy.get(row.strategy) ?? []
      const parts = model.perStrategy.get(row.strategy)
      return {
        ...row,
        realized: parts?.realized ?? 0,
        unrealized: parts?.unrealized ?? null,
        currentDrawdown: currentDrawdown(dates, cumulative(daily)).depth,
      }
    })
  }, [model.series, model.perStrategy])

  if (rows.length === 0) return null

  return (
    <Card>
      <CardHeader className="pb-3">
        <button
          type="button"
          className="flex items-start gap-2 text-left"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
        >
          {open ? (
            <ChevronDown className="mt-1 h-4 w-4" />
          ) : (
            <ChevronRight className="mt-1 h-4 w-4" />
          )}
          <span>
            <CardTitle className="text-base">Strategies</CardTitle>
            <CardDescription>
              The strategies selected in Filters. Each is judged on the days it closed something.
            </CardDescription>
          </span>
        </button>
      </CardHeader>
      {open && (
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Strategy</TableHead>
                  <TableHead className="text-right">Net P&L</TableHead>
                  <TableHead className="text-right">Realized</TableHead>
                  <TableHead className="text-right">Unrealized</TableHead>
                  <TableHead className="text-right">Max drawdown</TableHead>
                  <TableHead className="text-right">Current drawdown</TableHead>
                  <TableHead className="text-right">Win days</TableHead>
                  <TableHead className="text-right">Profit factor</TableHead>
                  <TableHead className="text-right">Active days</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.strategy}>
                    <TableCell>
                      <span className="flex items-center gap-2">
                        <span
                          className="inline-block h-2.5 w-2.5 rounded-full"
                          style={{
                            backgroundColor: strategyColor(row.strategy, model.coloured, isDark),
                          }}
                        />
                        {row.strategy}
                      </span>
                    </TableCell>
                    <TableCell className={cn('text-right font-medium', pnlClass(row.netPnl))}>
                      {formatCurrency(row.netPnl)}
                    </TableCell>
                    <TableCell className={cn('text-right', pnlClass(row.realized))}>
                      {formatCurrency(row.realized)}
                    </TableCell>
                    <TableCell
                      className={cn(
                        'text-right',
                        row.unrealized === null ? 'text-muted-foreground' : pnlClass(row.unrealized)
                      )}
                    >
                      {row.unrealized === null ? '-' : formatCurrency(row.unrealized)}
                    </TableCell>
                    <TableCell className="text-right">{formatCurrency(row.maxDrawdown)}</TableCell>
                    <TableCell
                      className={cn(
                        'text-right',
                        row.currentDrawdown < 0 ? 'text-red-600' : 'text-green-600'
                      )}
                    >
                      {formatCurrency(row.currentDrawdown)}
                    </TableCell>
                    <TableCell className="text-right">{percent(row.winRate)}</TableCell>
                    <TableCell className="text-right">{ratio(row.profitFactor)}</TableCell>
                    <TableCell className="text-right">{row.activeDays}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      )}
    </Card>
  )
}
