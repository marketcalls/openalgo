import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { AlertCircle, BarChart3, Calculator, Loader2, ReceiptText, Settings } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'
import {
  CHARGE_SETTINGS_KEY,
  type ChargeSegment,
  type ChargeSettings,
  chargesErrorMessage,
  type Estimate,
  sandboxChargesApi,
} from '@/api/sandbox-charges'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { CHARGE_WORDS, describePlan, type Money, pnlColor } from '@/lib/sandboxCharges'
import { cn, makeFormatCurrency } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'

/** How long typing must pause before the trade is priced again. */
const SETTLE_MS = 300

/**
 * The tabs of the Indian calculator, and the rate-card groups each one shows.
 *
 * There is no crypto tab. The server sends the segments of the logged-in
 * broker's market alone: an Indian broker gets these tabs, a crypto venue gets
 * its own calculator with no tabs at all, and the two are never on one page.
 * They are priced differently (a schedule of statutory charges here, a venue
 * fee and nothing else there), and a calculator that offered both would offer
 * a trader a market the account cannot trade.
 */
const INDIAN_TABS: { key: string; label: string; groups: string[] }[] = [
  { key: 'equity', label: 'Equities and F&O', groups: ['Equity', 'Equity F&O'] },
  { key: 'currency', label: 'Currency', groups: ['Currency'] },
  { key: 'commodity', label: 'Commodities', groups: ['Commodity'] },
]

const INDIAN_NOTE =
  'Quantity is in units, as on an order: one lot of 75 is 75. For options, the prices are the premium. A buy and a sell are priced together, as one contract note: STT and stamp duty to the nearest rupee, the other lines to the paisa. Each order is charged on its own when it fills, so the two fills can come to a paisa more or less than the figure here.'

const CRYPTO_NOTE =
  'A crypto trade is charged only the venue fee you enter on the Venue Fee page, with nothing added to it. Until you enter one, trades cost nothing here.'

/** A trade each card opens on, so the page shows figures before anything is typed. */
const EXAMPLES: Record<string, { buy: string; sell: string; quantity: string }> = {
  equity_intraday: { buy: '1000', sell: '1100', quantity: '400' },
  equity_delivery: { buy: '1000', sell: '1100', quantity: '400' },
  fno_futures: { buy: '1000', sell: '1100', quantity: '400' },
  fno_options: { buy: '100', sell: '110', quantity: '400' },
  currency_futures: { buy: '88.33', sell: '88.3525', quantity: '1000' },
  currency_options: { buy: '0.25', sell: '0.3', quantity: '1000' },
  commodity_futures: { buy: '250', sell: '252', quantity: '1000' },
  commodity_options: { buy: '100', sell: '110', quantity: '2500' },
  crypto_futures: { buy: '60000', sell: '60500', quantity: '1' },
  crypto_options: { buy: '500', sell: '550', quantity: '1' },
}
const FALLBACK_EXAMPLE = { buy: '100', sell: '110', quantity: '100' }

function useSettled<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delayMs)
    return () => window.clearTimeout(timer)
  }, [value, delayMs])
  return settled
}

function isPositive(value: string): boolean {
  const number = Number(value)
  return value.trim() !== '' && Number.isFinite(number) && number > 0
}

export default function SandboxCalculator() {
  const { user } = useAuthStore()
  const money = useMemo(() => makeFormatCurrency(user?.broker), [user?.broker])
  const settings = useQuery({ queryKey: CHARGE_SETTINGS_KEY, queryFn: sandboxChargesApi.settings })
  const [tab, setTab] = useState(INDIAN_TABS[0].key)

  if (settings.isLoading) {
    return (
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
        Loading the calculator
      </div>
    )
  }

  if (settings.isError || !settings.data) {
    return (
      <div className="container mx-auto max-w-5xl px-4 py-8">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            {chargesErrorMessage(settings.error, 'The calculator could not be loaded.')}
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  const plan: ChargeSettings = settings.data
  const crypto = plan.market === 'crypto'
  const words = CHARGE_WORDS[plan.market]

  return (
    <div className="container mx-auto py-6 px-4">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-8 gap-4">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Calculator className="h-8 w-8" />
            {words.calculator}
          </h1>
          <p className="text-muted-foreground mt-1">
            {crypto
              ? 'What a buy and a sell cost under the venue fee you have entered, before you place them'
              : 'What a buy and a sell cost under your brokerage plan, before you place them'}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button asChild>
            <Link to="/sandbox/commissions">
              <ReceiptText className="h-4 w-4 mr-2" />
              {words.plan}
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

      {!plan.enabled && (
        <Alert className="mb-6">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>
            Charges are switched off, so sandbox trades are not charged right now. These figures are
            what the same trades cost with charges on, and what they cost in a live account.
          </AlertDescription>
        </Alert>
      )}

      {crypto ? (
        <SegmentCards segments={plan.segments} crypto money={money} note={CRYPTO_NOTE} />
      ) : (
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="mb-4">
            {INDIAN_TABS.map((entry) => (
              <TabsTrigger key={entry.key} value={entry.key}>
                {entry.label}
              </TabsTrigger>
            ))}
          </TabsList>

          {INDIAN_TABS.map((entry) => (
            <TabsContent key={entry.key} value={entry.key}>
              <SegmentCards
                segments={plan.segments.filter((segment) => entry.groups.includes(segment.group))}
                crypto={false}
                money={money}
                note={INDIAN_NOTE}
              />
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  )
}

function SegmentCards({
  segments,
  crypto,
  money,
  note,
}: {
  segments: ChargeSegment[]
  crypto: boolean
  money: Money
  note: string
}) {
  return (
    <>
      <div
        className={cn(
          'grid grid-cols-1 gap-4 md:grid-cols-2',
          segments.length > 2 && 'xl:grid-cols-4'
        )}
      >
        {segments.map((segment) => (
          <SegmentCard key={segment.key} segment={segment} crypto={crypto} money={money} />
        ))}
      </div>
      <p className="mt-6 text-sm text-muted-foreground">{note}</p>
    </>
  )
}

interface SegmentCardProps {
  segment: ChargeSegment
  /** Crypto shows the venue fee alone, with none of the statutory lines. */
  crypto: boolean
  money: Money
}

function SegmentCard({ segment, crypto, money }: SegmentCardProps) {
  const example = EXAMPLES[segment.key] ?? FALLBACK_EXAMPLE
  // In the server's order, main exchange first, and the card opens on it: NSE
  // before BSE, NFO before BFO. Reading the codes off the rates object instead
  // gave them sorted, and every card opened on BSE.
  const exchanges = segment.exchanges
  const [exchange, setExchange] = useState(exchanges[0])
  const [buy, setBuy] = useState(example.buy)
  const [sell, setSell] = useState(example.sell)
  const [quantity, setQuantity] = useState(example.quantity)

  const typed = useMemo(() => ({ exchange, buy, sell, quantity }), [exchange, buy, sell, quantity])
  const trade = useSettled(typed, SETTLE_MS)
  const complete = isPositive(trade.buy) && isPositive(trade.sell) && isPositive(trade.quantity)

  // Priced by the server, under the saved plan. The plan is part of the key so
  // a card opened after the plan changed is priced again.
  const estimate = useQuery({
    queryKey: [
      'sandbox-charges',
      'estimate',
      segment.key,
      segment.flat,
      segment.percent,
      trade.exchange,
      trade.buy,
      trade.sell,
      trade.quantity,
    ],
    queryFn: () =>
      sandboxChargesApi.estimate({
        segment: segment.key,
        exchange: trade.exchange,
        buy_price: trade.buy,
        sell_price: trade.sell,
        quantity: trade.quantity,
      }),
    enabled: complete,
    placeholderData: keepPreviousData,
  })

  const result: Estimate | undefined = complete ? estimate.data : undefined
  const id = `calc-${segment.key}`

  return (
    <Card data-testid={id}>
      <CardHeader className="pb-3">
        <CardTitle className="text-lg">{segment.label}</CardTitle>
        <p className="text-xs text-muted-foreground">{segment.applies_to}</p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-3 gap-2">
          <Field id={`${id}-buy`} label="Buy" value={buy} onChange={setBuy} />
          <Field id={`${id}-sell`} label="Sell" value={sell} onChange={setSell} />
          <Field id={`${id}-quantity`} label="Quantity" value={quantity} onChange={setQuantity} />
        </div>

        {exchanges.length > 1 && (
          <fieldset className="flex flex-wrap gap-2">
            <legend className="sr-only">Exchange</legend>
            {exchanges.map((code) => (
              <Button
                key={code}
                type="button"
                size="sm"
                variant={code === exchange ? 'default' : 'outline'}
                aria-pressed={code === exchange}
                onClick={() => setExchange(code)}
              >
                {code}
              </Button>
            ))}
          </fieldset>
        )}

        {estimate.isError && complete ? (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              {chargesErrorMessage(estimate.error, 'These charges could not be worked out.')}
            </AlertDescription>
          </Alert>
        ) : (
          <div className={cn('text-sm', estimate.isFetching && 'opacity-70')}>
            <Row label="Turnover" value={result ? money(result.turnover) : null} />

            <Heading>{crypto ? 'Venue fee' : 'Brokerage'}</Heading>
            <Row
              label={crypto ? 'Fee' : 'Brokerage'}
              value={result ? money(result.total.brokerage) : null}
              testId={`${id}-brokerage`}
            />
            <p className="px-3 pb-2 text-xs text-muted-foreground">
              {describePlan(
                segment.flat,
                segment.percent,
                money,
                CHARGE_WORDS[crypto ? 'crypto' : 'indian'].none
              )}
            </p>

            {!crypto && (
              <>
                <Heading>Statutory charges</Heading>
                <Row
                  label={`${result?.stt_label || segment.statutory.stt_label || 'STT'} total`}
                  value={result ? money(result.total.stt) : null}
                />
                <Row
                  label="Exchange txn charge"
                  value={result ? money(result.total.exchange_charges) : null}
                />
                <Row label="GST" value={result ? money(result.total.gst) : null} />
                <Row
                  label="SEBI charges"
                  value={result ? money(result.total.sebi_charges) : null}
                />
                <Row label="Stamp duty" value={result ? money(result.total.stamp_duty) : null} />
              </>
            )}

            <Row
              label={crypto ? 'Total charges' : 'Total tax and charges'}
              value={result ? money(result.total.total_charges) : null}
              strong
              testId={`${id}-total`}
            />
            <Row
              label="Points to breakeven"
              value={result ? String(result.points_to_breakeven) : null}
            />
            <div className="mt-2 flex items-baseline justify-between border-t px-3 pt-3">
              <span className="font-semibold">Net P&L</span>
              <span
                className={cn('text-xl font-bold', result && pnlColor(result.net_pnl))}
                data-testid={`${id}-net`}
              >
                {result ? money(result.net_pnl) : '-'}
              </span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function Field({
  id,
  label,
  value,
  onChange,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </Label>
      <Input
        id={id}
        type="number"
        inputMode="decimal"
        min="0"
        step="any"
        aria-invalid={!isPositive(value)}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  )
}

function Heading({ children }: { children: string }) {
  return (
    <div className="mt-2 bg-muted/50 px-3 py-1.5 text-center text-xs text-muted-foreground">
      {children}
    </div>
  )
}

function Row({
  label,
  value,
  strong,
  testId,
}: {
  label: string
  value: string | null
  strong?: boolean
  testId?: string
}) {
  return (
    <div
      className={cn('flex items-baseline justify-between px-3 py-1.5', strong && 'font-semibold')}
    >
      <span className={cn(!strong && 'text-muted-foreground')}>{label}</span>
      <span data-testid={testId}>{value ?? '-'}</span>
    </div>
  )
}
