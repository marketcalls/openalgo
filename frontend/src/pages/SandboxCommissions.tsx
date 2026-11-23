import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  BarChart3,
  Calculator,
  Download,
  Loader2,
  ReceiptText,
  RotateCcw,
  Save,
  Settings,
} from 'lucide-react'
import { Fragment, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import {
  CHARGE_SETTINGS_KEY,
  type ChargeBreakdown,
  type ChargeMarket,
  type ChargeSegment,
  type ChargeSettings,
  type CostReport,
  chargesErrorMessage,
  costReportExportUrl,
  costReportKey,
  type StatutoryRates,
  sandboxChargesApi,
} from '@/api/sandbox-charges'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  CHARGE_WORDS,
  type ChargeLine,
  chargeLinesFor,
  describePlan,
  isAmount,
  type Money,
} from '@/lib/sandboxCharges'
import { cn, makeFormatCurrency } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { showToast } from '@/utils/toast'

/** The brokerage a trader has typed for each segment, saved or not. */
type Draft = Record<string, { flat: string; percent: string }>

const TABS = ['plan', 'report'] as const
type TabName = (typeof TABS)[number]

function draftFrom(settings: ChargeSettings): Draft {
  return Object.fromEntries(
    settings.segments.map((segment) => [
      segment.key,
      { flat: segment.flat, percent: segment.percent },
    ])
  )
}

/** Compared as numbers, so 20 and 20.0 are the same plan. */
function sameAmount(a: string, b: string): boolean {
  return isAmount(a) && isAmount(b) ? Number(a) === Number(b) : a === b
}

function sttText(rates: StatutoryRates): string {
  const buy = Number(rates.stt_buy) > 0
  const sell = Number(rates.stt_sell) > 0
  if (buy && sell) {
    return rates.stt_buy === rates.stt_sell
      ? `${rates.stt_sell}% on buy and sell`
      : `${rates.stt_buy}% on buy, ${rates.stt_sell}% on sell`
  }
  if (sell) return `${rates.stt_sell}% on sell`
  if (buy) return `${rates.stt_buy}% on buy`
  return 'None'
}

/** The exchange rates in the segment's own order, main exchange first. */
function exchangeText(segment: ChargeSegment): string {
  const rates = segment.statutory.exchange_txn
  const listed = segment.exchanges.filter((exchange) => exchange in rates)
  if (listed.length === 0) return 'None'
  return listed.map((exchange) => `${exchange} ${rates[exchange]}%`).join(', ')
}

function rateText(rate: string, suffix = ''): string {
  return Number(rate) > 0 ? `${rate}%${suffix}` : 'None'
}

/** Today's date in the browser's own timezone, as the date input wants it. */
function isoDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function defaultRange(): { from: string; to: string } {
  const to = new Date()
  const from = new Date(to)
  from.setDate(from.getDate() - 29)
  return { from: isoDate(from), to: isoDate(to) }
}

export default function SandboxCommissions() {
  const { user } = useAuthStore()
  const money = useMemo(() => makeFormatCurrency(user?.broker), [user?.broker])
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const requested = searchParams.get('tab') as TabName | null
  const tab: TabName = requested && TABS.includes(requested) ? requested : 'plan'

  const settings = useQuery({ queryKey: CHARGE_SETTINGS_KEY, queryFn: sandboxChargesApi.settings })
  const [draft, setDraft] = useState<Draft>({})
  const [enabled, setEnabled] = useState(true)

  /** Put the stored plan in the fields, in place of whatever was typed. */
  const adopt = (stored: ChargeSettings) => {
    setDraft(draftFrom(stored))
    setEnabled(stored.enabled)
  }

  // On load, the fields take the stored plan.
  useEffect(() => {
    if (settings.data) {
      setDraft(draftFrom(settings.data))
      setEnabled(settings.data.enabled)
    }
  }, [settings.data])

  // A save and a reset both answer with the stored plan, and it is adopted
  // here rather than left to the effect above. The query cache keeps the same
  // object when the plan it is given is equal to the one it holds, so a reset
  // that restores what was already stored would never reach the effect, and a
  // value typed but not saved would stay on screen as if the reset had failed.
  const store = (result: { settings: ChargeSettings; message: string }) => {
    queryClient.setQueryData(CHARGE_SETTINGS_KEY, result.settings)
    adopt(result.settings)
    showToast.success(result.message, 'analyzer')
  }

  const save = useMutation({
    mutationFn: () => sandboxChargesApi.save({ enabled, segments: draft }),
    onSuccess: store,
    onError: (error) =>
      showToast.error(chargesErrorMessage(error, 'The charges could not be saved.'), 'analyzer'),
  })

  const reset = useMutation({
    mutationFn: sandboxChargesApi.reset,
    onSuccess: store,
    onError: (error) =>
      showToast.error(
        chargesErrorMessage(error, 'The defaults could not be restored.'),
        'analyzer'
      ),
  })

  if (settings.isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading sandbox charges
      </div>
    )
  }

  if (settings.isError || !settings.data) {
    return (
      <div className="container mx-auto max-w-5xl px-4 py-8">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            {chargesErrorMessage(settings.error, 'The sandbox charges could not be loaded.')}
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  const saved = settings.data
  const crypto = saved.market === 'crypto'
  const words = CHARGE_WORDS[saved.market]
  const dirty =
    enabled !== saved.enabled ||
    saved.segments.some((segment) => {
      const typed = draft[segment.key]
      return (
        typed !== undefined &&
        (!sameAmount(typed.flat, segment.flat) || !sameAmount(typed.percent, segment.percent))
      )
    })

  return (
    <div className="container mx-auto py-6 px-4">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 gap-4">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <ReceiptText className="h-8 w-8" />
            Sandbox Charges
          </h1>
          <p className="text-muted-foreground mt-1">
            {crypto
              ? 'The venue fee on every sandbox trade, and what it has cost so far'
              : 'Brokerage and statutory charges on every sandbox trade, and what they have cost so far'}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button asChild>
            <Link to="/sandbox/calculator">
              <Calculator className="h-4 w-4 mr-2" />
              {words.calculator}
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/sandbox">
              <Settings className="h-4 w-4 mr-2" />
              Sandbox Config
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link to="/sandbox/mypnl">
              <BarChart3 className="h-4 w-4 mr-2" />
              My P&L
            </Link>
          </Button>
        </div>
      </div>

      <Tabs
        value={tab}
        onValueChange={(value) => setSearchParams(value === 'plan' ? {} : { tab: value })}
      >
        <TabsList className="mb-4">
          <TabsTrigger value="plan" className="gap-2">
            <Settings className="h-4 w-4" />
            {words.plan}
          </TabsTrigger>
          <TabsTrigger value="report" className="gap-2">
            <ReceiptText className="h-4 w-4" />
            Transaction Costs
          </TabsTrigger>
        </TabsList>

        <TabsContent value="plan">
          <PlanTab
            saved={saved}
            draft={draft}
            enabled={enabled}
            dirty={dirty}
            money={money}
            saving={save.isPending}
            resetting={reset.isPending}
            onEnabled={setEnabled}
            onChange={(key, field, value) =>
              setDraft((current) => ({ ...current, [key]: { ...current[key], [field]: value } }))
            }
            onSave={() => save.mutate()}
            onReset={() => reset.mutateAsync()}
          />
        </TabsContent>

        <TabsContent value="report">
          <ReportTab money={money} market={saved.market} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Brokerage plan
// ---------------------------------------------------------------------------

interface PlanTabProps {
  saved: ChargeSettings
  draft: Draft
  enabled: boolean
  dirty: boolean
  money: Money
  saving: boolean
  resetting: boolean
  onEnabled: (enabled: boolean) => void
  onChange: (key: string, field: 'flat' | 'percent', value: string) => void
  onSave: () => void
  onReset: () => Promise<unknown>
}

function PlanTab({
  saved,
  draft,
  enabled,
  dirty,
  money,
  saving,
  resetting,
  onEnabled,
  onChange,
  onSave,
  onReset,
}: PlanTabProps) {
  const [confirmReset, setConfirmReset] = useState(false)
  const crypto = saved.market === 'crypto'
  const none = CHARGE_WORDS[saved.market].none
  const groups = useMemo(() => {
    const order: string[] = []
    const byGroup: Record<string, ChargeSegment[]> = {}
    for (const segment of saved.segments) {
      if (!byGroup[segment.group]) {
        byGroup[segment.group] = []
        order.push(segment.group)
      }
      byGroup[segment.group].push(segment)
    }
    return order.map((name) => ({ name, segments: byGroup[name] }))
  }, [saved.segments])

  const valid = saved.segments.every((segment) => {
    const typed = draft[segment.key]
    return typed === undefined || (isAmount(typed.flat) && isAmount(typed.percent))
  })

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="flex items-start justify-between gap-6 p-6">
          <div className="space-y-1">
            <Label htmlFor="charges-enabled" className="text-base font-semibold">
              Charge sandbox trades
            </Label>
            <p className="text-sm text-muted-foreground">
              {!enabled
                ? 'Sandbox trades cost nothing. Results will look better than the same trades would in a live account.'
                : crypto
                  ? 'Every sandbox trade pays the venue fee entered below. It is taken from the available balance when the order fills.'
                  : 'Every sandbox trade pays brokerage and statutory charges. They are taken from the available balance when the order fills.'}
            </p>
          </div>
          <Switch id="charges-enabled" checked={enabled} onCheckedChange={onEnabled} />
        </CardContent>
      </Card>

      <Card className={cn(!enabled && 'opacity-60')}>
        <CardHeader>
          <CardTitle>{crypto ? 'Venue fee' : 'Brokerage plan'}</CardTitle>
          <CardDescription>
            {crypto
              ? 'Enter the fee your venue charges on each order. When both an amount and a percentage are set, the lower of the two is charged on each executed order. Set either to 0 to leave it out. Until a fee is entered, trades cost nothing here.'
              : 'Enter what your broker charges in each segment. When both an amount and a percentage are set, the lower of the two is charged on each executed order. Set either to 0 to leave it out.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Segment</TableHead>
                  <TableHead className="w-36">Per executed order</TableHead>
                  <TableHead className="w-36">% of trade value</TableHead>
                  <TableHead>Charged as</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {groups.map((group) => (
                  <Fragment key={group.name}>
                    <TableRow className="bg-muted/40 hover:bg-muted/40">
                      <TableCell
                        colSpan={4}
                        className="py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
                      >
                        {group.name}
                      </TableCell>
                    </TableRow>
                    {group.segments.map((segment) => {
                      const typed = draft[segment.key] ?? {
                        flat: segment.flat,
                        percent: segment.percent,
                      }
                      const changed =
                        !sameAmount(typed.flat, segment.flat) ||
                        !sameAmount(typed.percent, segment.percent)
                      return (
                        <TableRow key={segment.key}>
                          <TableCell>
                            <div className="font-semibold">{segment.label}</div>
                            <div className="text-xs text-muted-foreground">
                              {segment.applies_to}
                            </div>
                          </TableCell>
                          <TableCell>
                            <Input
                              type="number"
                              inputMode="decimal"
                              min="0"
                              max={saved.limits.flat_max}
                              step="any"
                              aria-label={`${segment.label} amount per executed order`}
                              aria-invalid={!isAmount(typed.flat)}
                              value={typed.flat}
                              onChange={(event) =>
                                onChange(segment.key, 'flat', event.target.value)
                              }
                            />
                          </TableCell>
                          <TableCell>
                            <Input
                              type="number"
                              inputMode="decimal"
                              min="0"
                              max={saved.limits.percent_max}
                              step="any"
                              aria-label={`${segment.label} percentage of trade value`}
                              aria-invalid={!isAmount(typed.percent)}
                              value={typed.percent}
                              onChange={(event) =>
                                onChange(segment.key, 'percent', event.target.value)
                              }
                            />
                          </TableCell>
                          <TableCell className="text-sm">
                            <span data-testid={`plan-${segment.key}`}>
                              {describePlan(typed.flat, typed.percent, money, none)}
                            </span>
                            {changed && (
                              <Badge variant="secondary" className="ml-2">
                                Not saved
                              </Badge>
                            )}
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </Fragment>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between">
            <Button
              variant="outline"
              onClick={() => setConfirmReset(true)}
              disabled={saving || resetting}
            >
              <RotateCcw className="h-4 w-4 mr-2" />
              Reset to defaults
            </Button>
            <div className="flex items-center gap-3">
              <span className="text-sm text-muted-foreground">
                {dirty
                  ? 'You have changes that are not saved.'
                  : 'Saved. Applies to the next trade.'}
              </span>
              <Button onClick={onSave} disabled={!dirty || !valid || saving || resetting}>
                {saving ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Save className="h-4 w-4 mr-2" />
                )}
                Save charges
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {crypto ? (
        <Card className={cn(!enabled && 'opacity-60')}>
          <CardHeader>
            <CardTitle>Nothing is added to the fee</CardTitle>
            <CardDescription>
              A crypto trade is charged the fee above and nothing else. If your venue adds a tax or
              a levy to its fee, include it in the fee you enter.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <StatutoryCard saved={saved} enabled={enabled} />
      )}

      <Card>
        <CardHeader>
          <CardTitle>What the sandbox does not charge</CardTitle>
          <CardDescription>
            {crypto
              ? 'A live account can cost more than the sandbox in these cases.'
              : 'A live account will cost a little more than the sandbox in these cases.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="list-disc space-y-2 pl-5 text-sm text-muted-foreground">
            {(crypto ? NOT_CHARGED_CRYPTO : NOT_CHARGED_INDIAN).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <Dialog open={confirmReset} onOpenChange={setConfirmReset}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reset charges to the defaults?</DialogTitle>
            <DialogDescription>
              {crypto
                ? 'The fee goes back to the default, which is no fee, and charges are switched on. Your trades, positions, funds and the charges already paid are not changed.'
                : 'The brokerage plan goes back to the default for every segment and charges are switched on. Your trades, positions, funds and the charges already paid are not changed.'}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmReset(false)}>
              Cancel
            </Button>
            <Button
              disabled={resetting}
              onClick={() =>
                onReset()
                  .catch(() => undefined)
                  .finally(() => setConfirmReset(false))
              }
            >
              {resetting && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Reset charges
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

/** What a live Indian account pays that the sandbox leaves out. */
const NOT_CHARGED_INDIAN = [
  'Depository (DP) charges when delivery shares are sold.',
  'STT on an option that is held to expiry and exercised. A position settled at expiry is closed without an order and pays no charges.',
  'A delivery buy and sell on the same day pays delivery rates on both. A broker bills that pair at intraday rates.',
  'Agricultural commodities and NCDEX contracts use the MCX rates for other commodities.',
  "STT and stamp duty are rounded to the nearest rupee on each trade. A contract note rounds them once on the day's total, so a day of many small trades can differ from it by a rupee or two.",
]

/** What a live crypto account pays that the sandbox leaves out. */
const NOT_CHARGED_CRYPTO = [
  "Anything at all, until you enter your venue's fee above. That fee is charged as entered, with nothing added to it.",
  'A different fee for an order that adds to the book and one that takes from it. One fee applies to every executed order.',
  'Any tax or levy your venue adds to its fee, unless you include it in the fee you enter.',
]

function StatutoryCard({ saved, enabled }: { saved: ChargeSettings; enabled: boolean }) {
  return (
    <Card className={cn(!enabled && 'opacity-60')}>
      <CardHeader>
        <CardTitle>Statutory charges</CardTitle>
        <CardDescription>
          Added to every trade on top of brokerage. The exchanges and the government set these and
          they are the same at every broker, so they cannot be changed here. Rates as of{' '}
          {saved.statutory_as_of}.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Segment</TableHead>
                <TableHead>STT / CTT</TableHead>
                <TableHead>Exchange transaction charges</TableHead>
                <TableHead>SEBI charges</TableHead>
                <TableHead>Stamp duty</TableHead>
                <TableHead>GST</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {saved.segments.map((segment) => (
                <TableRow key={segment.key}>
                  <TableCell className="font-semibold">{segment.label}</TableCell>
                  <TableCell>{sttText(segment.statutory)}</TableCell>
                  <TableCell>{exchangeText(segment)}</TableCell>
                  <TableCell>{rateText(segment.statutory.sebi)}</TableCell>
                  <TableCell>{rateText(segment.statutory.stamp_buy, ' on buy')}</TableCell>
                  <TableCell>{rateText(segment.statutory.gst)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <p className="mt-4 text-sm text-muted-foreground">
          GST is charged on brokerage, exchange transaction charges and SEBI charges. STT, CTT and
          stamp duty are a percentage of the trade value; on options that is the premium. STT and
          stamp duty are rounded to the nearest rupee, as on a contract note.
        </p>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Transaction cost report
// ---------------------------------------------------------------------------

function ReportTab({ money, market }: { money: Money; market: ChargeMarket }) {
  const crypto = market === 'crypto'
  const lines = chargeLinesFor(market)
  const [typed, setTyped] = useState(defaultRange)
  const [range, setRange] = useState(typed)
  const report = useQuery({
    queryKey: costReportKey(range.from, range.to),
    queryFn: () => sandboxChargesApi.report(range.from, range.to),
  })

  const data: CostReport | undefined = report.data
  const statutory = data ? data.totals.total_charges - data.totals.brokerage : 0
  const share =
    data && data.totals.turnover > 0
      ? `${((data.totals.total_charges / data.totals.turnover) * 100).toFixed(3)}% of turnover`
      : 'No turnover'

  return (
    <div className="space-y-6">
      <Card>
        <CardContent className="flex flex-col gap-4 p-6 md:flex-row md:items-end">
          <div className="space-y-2">
            <Label htmlFor="report-from">From</Label>
            <Input
              id="report-from"
              type="date"
              value={typed.from}
              max={typed.to}
              onChange={(event) =>
                setTyped((current) => ({ ...current, from: event.target.value }))
              }
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="report-to">To</Label>
            <Input
              id="report-to"
              type="date"
              value={typed.to}
              min={typed.from}
              onChange={(event) => setTyped((current) => ({ ...current, to: event.target.value }))}
            />
          </div>
          <Button onClick={() => setRange(typed)} disabled={!typed.from || !typed.to}>
            Show
          </Button>
          <div className="md:ml-auto">
            <Button
              variant="outline"
              disabled={!data || data.trades_total === 0}
              onClick={() => {
                window.location.href = costReportExportUrl(range.from, range.to)
              }}
            >
              <Download className="h-4 w-4 mr-2" />
              Export CSV
            </Button>
          </div>
        </CardContent>
      </Card>

      {report.isLoading && (
        <div className="flex items-center justify-center py-16 text-muted-foreground">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          Loading transaction costs
        </div>
      )}

      {report.isError && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            {chargesErrorMessage(report.error, 'The report could not be loaded.')}
          </AlertDescription>
        </Alert>
      )}

      {data && data.trades_total === 0 && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <ReceiptText className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <p>No sandbox trades between these dates.</p>
            <p className="text-sm mt-2">
              Charges are recorded on each trade as it fills, from the release that introduced them.
            </p>
          </CardContent>
        </Card>
      )}

      {data && data.trades_total > 0 && (
        <>
          <div
            className={cn('grid grid-cols-2 gap-4', crypto ? 'lg:grid-cols-3' : 'lg:grid-cols-5')}
          >
            <SummaryCard
              label={crypto ? 'Total fees' : 'Total charges'}
              value={money(data.totals.total_charges)}
              note={share}
              strong
            />
            {!crypto && <SummaryCard label="Brokerage" value={money(data.totals.brokerage)} />}
            {!crypto && <SummaryCard label="Statutory charges" value={money(statutory)} />}
            <SummaryCard label="Turnover" value={money(data.totals.turnover)} />
            <SummaryCard label="Trades" value={String(data.totals.trades)} />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>By segment</CardTitle>
            </CardHeader>
            <CardContent>
              <CostTable
                first="Segment"
                rows={data.by_segment.map((bucket) => ({ ...bucket, name: bucket.label }))}
                totals={data.totals}
                lines={lines}
                money={money}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>By day</CardTitle>
            </CardHeader>
            <CardContent>
              <CostTable
                first="Date"
                rows={data.by_day.map((bucket) => ({ ...bucket, name: bucket.date }))}
                totals={data.totals}
                lines={lines}
                money={money}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Trades</CardTitle>
              <CardDescription>
                {data.trades_listed < data.trades_total
                  ? `The latest ${data.trades_listed} of ${data.trades_total} trades. The totals above cover all of them, and the CSV lists every one.`
                  : `All ${data.trades_total} trades in this range, latest first.`}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Time</TableHead>
                      <TableHead>Symbol</TableHead>
                      <TableHead>Action</TableHead>
                      <TableHead className="text-right">Qty</TableHead>
                      <TableHead className="text-right">Price</TableHead>
                      <TableHead className="text-right">Turnover</TableHead>
                      {lines.map((line) => (
                        <TableHead key={line.key} className="text-right">
                          {line.short}
                        </TableHead>
                      ))}
                      <TableHead className="text-right">Total</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.trades.map((trade) => (
                      <TableRow key={trade.tradeid}>
                        <TableCell className="text-xs text-muted-foreground whitespace-nowrap">
                          {trade.timestamp}
                        </TableCell>
                        <TableCell>
                          <div className="font-semibold">{trade.symbol}</div>
                          <div className="text-xs text-muted-foreground">
                            {trade.exchange} {trade.product}, {trade.segment_label}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant={trade.action === 'BUY' ? 'default' : 'destructive'}>
                            {trade.action}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right">{trade.quantity}</TableCell>
                        <TableCell className="text-right">{money(trade.price)}</TableCell>
                        <TableCell className="text-right">{money(trade.turnover)}</TableCell>
                        {lines.map((line) => (
                          <TableCell key={line.key} className="text-right">
                            {money(trade[line.key])}
                          </TableCell>
                        ))}
                        <TableCell className="text-right font-semibold">
                          {money(trade.total_charges)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}

function SummaryCard({
  label,
  value,
  note,
  strong,
}: {
  label: string
  value: string
  note?: string
  strong?: boolean
}) {
  return (
    <Card className={cn(strong && 'border-2 border-primary')}>
      <CardContent className="p-4">
        <div className="text-sm text-muted-foreground">{label}</div>
        <div className="text-2xl font-bold">{value}</div>
        {note && <div className="text-xs text-muted-foreground mt-1">{note}</div>}
      </CardContent>
    </Card>
  )
}

interface CostRow extends ChargeBreakdown {
  name: string
  trades: number
  turnover: number
}

function CostTable({
  first,
  rows,
  totals,
  lines,
  money,
}: {
  first: string
  rows: CostRow[]
  totals: ChargeBreakdown & { trades: number; turnover: number }
  /** The lines of the market the account is on. */
  lines: ChargeLine[]
  money: Money
}) {
  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{first}</TableHead>
            <TableHead className="text-right">Trades</TableHead>
            <TableHead className="text-right">Turnover</TableHead>
            {lines.map((line) => (
              <TableHead key={line.key} className="text-right">
                {line.short}
              </TableHead>
            ))}
            <TableHead className="text-right">Total</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.name}>
              <TableCell className="font-semibold whitespace-nowrap">{row.name}</TableCell>
              <TableCell className="text-right">{row.trades}</TableCell>
              <TableCell className="text-right">{money(row.turnover)}</TableCell>
              {lines.map((line) => (
                <TableCell key={line.key} className="text-right">
                  {money(row[line.key])}
                </TableCell>
              ))}
              <TableCell className="text-right font-semibold">{money(row.total_charges)}</TableCell>
            </TableRow>
          ))}
          <TableRow className="bg-muted/40 font-semibold hover:bg-muted/40">
            <TableCell>Total</TableCell>
            <TableCell className="text-right">{totals.trades}</TableCell>
            <TableCell className="text-right">{money(totals.turnover)}</TableCell>
            {lines.map((line) => (
              <TableCell key={line.key} className="text-right">
                {money(totals[line.key])}
              </TableCell>
            ))}
            <TableCell className="text-right">{money(totals.total_charges)}</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>
  )
}
