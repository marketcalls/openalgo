// frontend/src/components/pnl/PnlBreakdown.tsx
/**
 * Day / Week / Month / Scrip views of the P&L page (fork-only), each as bars or
 * as a table, with a CSV export of the table. The time views sum the model's
 * daily series, so they follow the P&L type, the filters and the strategy
 * selection like everything else on the page.
 */
import { Download, ImageDown } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { exportElementAsPng } from '@/lib/exportPng'
import { type Bucket, type BucketUnit, bucketize } from '@/lib/pnlBuckets'
import { monthly } from '@/lib/pnlCurve'
import type { PnlModel } from '@/lib/pnlModel'
import { cn, sanitizeCSV } from '@/lib/utils'
import { showToast } from '@/utils/toast'
import { PnlBarChart } from './PnlBarChart'
import { PnlScripBars, type ScripBar } from './PnlScripBars'

type ViewKey = 'day' | 'week' | 'month' | 'scrip'

const MONTH_LABELS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]

const pnlClass = (value: number) => (value >= 0 ? 'text-green-600' : 'text-red-600')

function monthTint(value: number, maxAbs: number): string {
  if (value === 0 || maxAbs === 0) return 'transparent'
  const alpha = 0.1 + Math.min(Math.abs(value) / maxAbs, 1) * 0.5
  return value > 0 ? `rgba(34, 197, 94, ${alpha})` : `rgba(239, 68, 68, ${alpha})`
}

interface ScripRow {
  key: string
  symbol: string
  exchange: string
  product: string | null
  closedQuantity: number
  buyValue: number
  sellValue: number
  realized: number
  openQuantity: number
  averagePrice: number | null
  ltp: number | null
  unrealized: number | null
}

interface Props {
  model: PnlModel
  pnlType: 'realized' | 'unrealized' | 'combined'
  isDark: boolean
  formatCurrency: (value: number) => string
  startDate: string
  endDate: string
}

export function PnlBreakdown({
  model,
  pnlType,
  isDark,
  formatCurrency,
  startDate,
  endDate,
}: Props) {
  const [view, setView] = useState<ViewKey>('day')
  const [mode, setMode] = useState<'chart' | 'table'>('chart')
  const chartAreaRef = useRef<HTMLDivElement>(null)
  const showRealized = pnlType !== 'unrealized'
  const showUnrealized = pnlType !== 'realized'

  const { series } = model
  const unit: BucketUnit = view === 'scrip' ? 'day' : view
  const buckets: Bucket[] = useMemo(
    () => bucketize(series.dates, series.total, unit),
    [series, unit]
  )
  const monthRows = useMemo(() => monthly(series.dates, series.total), [series])
  const monthMaxAbs = Math.max(
    0,
    ...monthRows.flatMap((r) => r.months.map((m) => Math.abs(m ?? 0)))
  )

  // Scrip rows: every closed lot and open position by symbol and exchange.
  const scripRows: ScripRow[] = useMemo(() => {
    const rows = new Map<string, ScripRow>()
    const blank = (symbol: string, exchange: string, product: string | null): ScripRow => ({
      key: `${symbol}|${exchange}`,
      symbol,
      exchange,
      product,
      closedQuantity: 0,
      buyValue: 0,
      sellValue: 0,
      realized: 0,
      openQuantity: 0,
      averagePrice: null,
      ltp: null,
      unrealized: null,
    })
    for (const t of model.lots) {
      const key = `${t.symbol}|${t.exchange}`
      const row = rows.get(key) ?? blank(t.symbol, t.exchange, t.product)
      const isLong = t.entry_action === 'BUY'
      row.closedQuantity += t.quantity
      row.buyValue += t.quantity * (isLong ? t.entry_price : t.exit_price)
      row.sellValue += t.quantity * (isLong ? t.exit_price : t.entry_price)
      row.realized += t.realized_pnl
      rows.set(key, row)
    }
    const notional = new Map<string, number>()
    for (const p of model.open) {
      const key = `${p.symbol}|${p.exchange}`
      const row = rows.get(key) ?? blank(p.symbol, p.exchange, p.product)
      if (!row.product) row.product = p.product
      row.openQuantity += p.action === 'BUY' ? p.quantity : -p.quantity
      notional.set(key, (notional.get(key) ?? 0) + p.quantity * p.average_price)
      row.averagePrice = (notional.get(key) ?? 0) / Math.abs(row.openQuantity || 1)
      row.ltp = p.ltp
      if (p.unrealized_pnl != null) row.unrealized = (row.unrealized ?? 0) + p.unrealized_pnl
      rows.set(key, row)
    }
    return Array.from(rows.values()).sort((a, b) => a.symbol.localeCompare(b.symbol))
  }, [model.lots, model.open])

  const scripBars: ScripBar[] = scripRows.map((r) => ({
    symbol: r.symbol,
    realized: r.realized,
    unrealized: r.unrealized,
  }))

  const exportImage = async () => {
    const element = chartAreaRef.current
    if (!element) return
    try {
      await exportElementAsPng(element, `pnl_${view}_${startDate}_${endDate}.png`)
      showToast.success('Chart saved', 'system')
    } catch {
      showToast.error('Could not save the chart image', 'system')
    }
  }

  const exportCsv = () => {
    let headers: string[]
    let rows: (string | number)[][]
    if (view === 'scrip') {
      headers = [
        'Symbol',
        'Exchange',
        'Product',
        'Closed Qty',
        'Buy Value',
        'Sell Value',
        'Realized P&L',
        'Open Qty',
        'Avg Price',
        'LTP',
        'Unrealized P&L',
      ]
      rows = scripRows.map((r) => [
        r.symbol,
        r.exchange,
        r.product ?? '',
        r.closedQuantity,
        r.buyValue.toFixed(2),
        r.sellValue.toFixed(2),
        r.realized.toFixed(2),
        r.openQuantity,
        r.averagePrice == null ? '' : r.averagePrice.toFixed(2),
        r.ltp == null ? '' : r.ltp.toFixed(2),
        r.unrealized == null ? '' : r.unrealized.toFixed(2),
      ])
    } else {
      headers = [
        view === 'day' ? 'Date' : view === 'week' ? 'Week of' : 'Month',
        'Days',
        'P&L',
        'Cumulative',
      ]
      rows = buckets.map((b) => [b.start, b.days, b.value.toFixed(2), b.cumulative.toFixed(2)])
    }
    if (rows.length === 0) {
      showToast.error('No data to export', 'system')
      return
    }
    const csv = [headers, ...rows.map((row) => row.map((c) => sanitizeCSV(c)))]
      .map((row) => row.join(','))
      .join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `pnl_${view}_${startDate}_${endDate}.csv`
    a.click()
    URL.revokeObjectURL(url)
    showToast.success(`Downloaded pnl_${view}_${startDate}_${endDate}.csv`, 'clipboard')
  }

  const description: Record<ViewKey, string> = {
    day: 'P&L for each trading day, for the selected P&L type.',
    week: 'P&L for each week, Monday to Sunday.',
    month: 'P&L for each calendar month.',
    scrip: 'Every closed lot and open position merged by symbol. Biggest winners first.',
  }

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-start justify-between gap-3">
        <div>
          <CardTitle>Breakdown</CardTitle>
          <CardDescription>{description[view]}</CardDescription>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Tabs value={view} onValueChange={(v) => setView(v as ViewKey)}>
            <TabsList>
              <TabsTrigger value="day">Day</TabsTrigger>
              <TabsTrigger value="week">Week</TabsTrigger>
              <TabsTrigger value="month">Month</TabsTrigger>
              <TabsTrigger value="scrip">Scrip</TabsTrigger>
            </TabsList>
          </Tabs>
          <Button
            size="sm"
            variant={mode === 'chart' ? 'default' : 'outline'}
            onClick={() => setMode('chart')}
          >
            Chart
          </Button>
          <Button
            size="sm"
            variant={mode === 'table' ? 'default' : 'outline'}
            onClick={() => setMode('table')}
          >
            Table
          </Button>
          {mode === 'chart' ? (
            <Button
              size="sm"
              variant="outline"
              onClick={exportImage}
              aria-label="Download the chart as an image"
            >
              <ImageDown className="mr-2 h-4 w-4" />
              Image
            </Button>
          ) : (
            <Button size="sm" variant="outline" onClick={exportCsv} aria-label="Export CSV">
              <Download className="mr-2 h-4 w-4" />
              CSV
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {view === 'scrip' ? (
          scripRows.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              No matching trades in this date range
            </p>
          ) : mode === 'chart' ? (
            <div ref={chartAreaRef}>
              <p className="mb-2 text-sm font-medium">
                Scrip-wise P&L, {startDate} to {endDate}
              </p>
              <PnlScripBars
                rows={scripBars}
                isDark={isDark}
                formatCurrency={formatCurrency}
                showRealized={showRealized}
                showUnrealized={showUnrealized}
              />
            </div>
          ) : (
            <div className="max-h-[560px] overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Exchange</TableHead>
                    <TableHead>Product</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Buy Value</TableHead>
                    <TableHead className="text-right">Sell Value</TableHead>
                    <TableHead className="text-right">Realized P&L</TableHead>
                    <TableHead className="text-right">Open Qty</TableHead>
                    <TableHead className="text-right">Avg Price</TableHead>
                    <TableHead className="text-right">LTP</TableHead>
                    <TableHead className="text-right">Unrealized P&L</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {scripRows.map((row) => (
                    <TableRow key={row.key}>
                      <TableCell>{row.symbol}</TableCell>
                      <TableCell>{row.exchange}</TableCell>
                      <TableCell>{row.product ?? '-'}</TableCell>
                      <TableCell className="text-right">{row.closedQuantity || '-'}</TableCell>
                      <TableCell className="text-right">
                        {row.closedQuantity ? formatCurrency(row.buyValue) : '-'}
                      </TableCell>
                      <TableCell className="text-right">
                        {row.closedQuantity ? formatCurrency(row.sellValue) : '-'}
                      </TableCell>
                      <TableCell
                        className={cn(
                          'text-right font-medium',
                          row.closedQuantity ? pnlClass(row.realized) : 'text-muted-foreground'
                        )}
                      >
                        {row.closedQuantity ? formatCurrency(row.realized) : '-'}
                      </TableCell>
                      <TableCell className="text-right">{row.openQuantity || '-'}</TableCell>
                      <TableCell className="text-right">
                        {row.averagePrice == null ? '-' : formatCurrency(row.averagePrice)}
                      </TableCell>
                      <TableCell className="text-right">
                        {row.ltp == null ? '-' : formatCurrency(row.ltp)}
                      </TableCell>
                      <TableCell
                        className={cn(
                          'text-right font-medium',
                          row.unrealized == null
                            ? 'text-muted-foreground'
                            : pnlClass(row.unrealized)
                        )}
                      >
                        {row.unrealized == null ? '-' : formatCurrency(row.unrealized)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )
        ) : buckets.length === 0 ? (
          <p className="py-8 text-center text-muted-foreground">Nothing in this date range</p>
        ) : mode === 'chart' ? (
          <div ref={chartAreaRef}>
            <p className="mb-2 text-sm font-medium">
              {view === 'day' ? 'Daily' : view === 'week' ? 'Weekly' : 'Monthly'} P&L, {startDate}{' '}
              to {endDate}
            </p>
            <PnlBarChart buckets={buckets} isDark={isDark} formatCurrency={formatCurrency} />
          </div>
        ) : view === 'month' ? (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Year</TableHead>
                  {MONTH_LABELS.map((label) => (
                    <TableHead key={label} className="text-right">
                      {label}
                    </TableHead>
                  ))}
                  <TableHead className="text-right">Year</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {monthRows.map((row) => (
                  <TableRow key={row.year}>
                    <TableCell className="font-medium">{row.year}</TableCell>
                    {row.months.map((value, i) => (
                      <TableCell
                        // biome-ignore lint/suspicious/noArrayIndexKey: the index is the month
                        key={i}
                        className={cn(
                          'text-right',
                          value === null ? 'text-muted-foreground' : pnlClass(value)
                        )}
                        style={{
                          backgroundColor:
                            value === null ? undefined : monthTint(value, monthMaxAbs),
                        }}
                      >
                        {value === null ? '-' : formatCurrency(value)}
                      </TableCell>
                    ))}
                    <TableCell className={cn('text-right font-medium', pnlClass(row.total))}>
                      {formatCurrency(row.total)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          <div className="max-h-[560px] overflow-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{view === 'day' ? 'Date' : 'Week of'}</TableHead>
                  {view === 'week' && <TableHead className="text-right">Days</TableHead>}
                  <TableHead className="text-right">P&L</TableHead>
                  <TableHead className="text-right">Cumulative</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {[...buckets].reverse().map((b) => (
                  <TableRow key={b.key}>
                    <TableCell>{b.start}</TableCell>
                    {view === 'week' && <TableCell className="text-right">{b.days}</TableCell>}
                    <TableCell className={cn('text-right font-medium', pnlClass(b.value))}>
                      {formatCurrency(b.value)}
                    </TableCell>
                    <TableCell className={cn('text-right', pnlClass(b.cumulative))}>
                      {formatCurrency(b.cumulative)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
