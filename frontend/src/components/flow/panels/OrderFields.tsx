/**
 * The order-field pickers, each able to take a {{variable}} instead.
 *
 * These five controls were repeated inline across every order node, which is
 * why only `symbol` ever accepted a reference: it was the one field rendered as
 * a plain text input. A dropdown cannot express `{{webhook.exchange}}` and a
 * number input cannot express `{{webhook.quantity}}`, so a webhook-driven order
 * could name its instrument and nothing else.
 *
 * The executor has always interpolated these fields (`ORDER_CRITICAL_FIELDS` in
 * flow_executor_service.py), and refuses to dispatch an order whose reference
 * did not resolve rather than substituting a default. The gap was only in the
 * form.
 */

import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { EXCHANGES, ORDER_ACTIONS, PRICE_TYPES, PRODUCT_TYPES } from '@/lib/flow/constants'
import { cn } from '@/lib/utils'

import { TemplatableField } from './TemplatableField'

interface FieldProps {
  /**
   * The caller's own expression, passed through untouched. Several sites do not
   * read the node key directly: Product follows the exchange when the author
   * has not picked one, and Exchange defaults to NSE_INDEX or NFO on the nodes
   * where that is the sane starting point. Recomputing any of that here would
   * quietly flatten it.
   */
  value: unknown
  onChange: (value: string | number) => void
  label?: string
  /** Where the picker lands when a reference is switched back off. */
  fallback?: string | number
  /**
   * Smallest accepted quantity. Zero is meaningful on smartOrder, where it is a
   * target position size and therefore an instruction to flatten, so that node
   * passes 0 and an empty box reads as 0 rather than snapping to 1.
   */
  min?: number
}

export function ExchangeField({
  value,
  onChange,
  label = 'Exchange',
  fallback = 'NSE',
}: FieldProps) {
  return (
    <TemplatableField
      label={label}
      value={value}
      onChange={onChange}
      fallback={fallback}
      placeholder="{{webhook.exchange}}"
    >
      <Select value={value as string} onValueChange={onChange}>
        <SelectTrigger className="h-8">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {EXCHANGES.map((e) => (
            <SelectItem key={e.value} value={e.value}>
              {e.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </TemplatableField>
  )
}

export function ActionField({ value, onChange, label = 'Action', fallback = 'BUY' }: FieldProps) {
  return (
    <TemplatableField
      label={label}
      value={value}
      onChange={onChange}
      fallback={fallback}
      placeholder="{{webhook.action}}"
      hint="Must resolve to BUY or SELL."
    >
      <div className="grid grid-cols-2 gap-2">
        {ORDER_ACTIONS.map((a) => (
          <button
            key={a.value}
            type="button"
            onClick={() => onChange(a.value)}
            className={cn(
              'rounded-lg border py-2 text-sm font-semibold',
              value === a.value
                ? a.value === 'BUY'
                  ? 'bg-green-500/20 border-green-500 text-green-600'
                  : 'bg-red-500/20 border-red-500 text-red-600'
                : 'border-border bg-muted'
            )}
          >
            {a.label}
          </button>
        ))}
      </div>
    </TemplatableField>
  )
}

export function QuantityField({
  value,
  onChange,
  label = 'Quantity',
  fallback = 1,
  min = 1,
}: FieldProps) {
  return (
    <TemplatableField
      label={label}
      value={value}
      onChange={onChange}
      fallback={fallback}
      placeholder="{{webhook.quantity}}"
      hint="A field holding one whole token keeps its type, so this arrives as a number."
    >
      <Input
        type="number"
        min={min}
        className="h-8"
        value={value as number}
        onChange={(e) => {
          const parsed = parseInt(e.target.value, 10)
          // An emptied box is not a zero unless zero is a legal size here.
          if (Number.isNaN(parsed)) return onChange(min)
          onChange(parsed === 0 && min > 0 ? min : parsed)
        }}
      />
    </TemplatableField>
  )
}

export function ProductField({ value, onChange, label = 'Product', fallback = 'MIS' }: FieldProps) {
  return (
    <TemplatableField
      label={label}
      value={value}
      onChange={onChange}
      fallback={fallback}
      placeholder="{{webhook.product}}"
    >
      <Select value={value as string} onValueChange={onChange}>
        <SelectTrigger className="h-8">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PRODUCT_TYPES.map((t) => (
            <SelectItem key={t.value} value={t.value}>
              {t.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </TemplatableField>
  )
}

export function PriceTypeField({
  value,
  onChange,
  label = 'Price Type',
  fallback = 'MARKET',
}: FieldProps) {
  return (
    <TemplatableField
      label={label}
      value={value}
      onChange={onChange}
      fallback={fallback}
      placeholder="{{webhook.priceType}}"
      hint="Must resolve to MARKET, LIMIT, SL or SL-M."
    >
      <Select value={value as string} onValueChange={onChange}>
        <SelectTrigger className="h-8">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {PRICE_TYPES.map((t) => (
            <SelectItem key={t.value} value={t.value}>
              {t.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </TemplatableField>
  )
}

interface ExpiryFieldProps {
  /**
   * Either one of the four relative choices, or an exact DDMMMYY date, or a
   * reference. One field holds all three because the executor accepts all
   * three from the same key: a DDMMMYY value is used as given, anything else
   * is resolved as a relative type.
   */
  value: unknown
  onChange: (value: string | number) => void
  /** Monthly-only underlyings get the weekly choices filtered out. */
  options: readonly { value: string; label: string }[]
}

/**
 * Expiry, as one control.
 *
 * The four relative choices cover almost every order and stay the picker. They
 * cannot name a far contract, so the toggle swaps to a text box that takes
 * either an exact date or a {{reference}} - the same shape every other field
 * here uses, rather than a second box sitting permanently underneath.
 */
export function ExpiryField({ value, onChange, options }: ExpiryFieldProps) {
  return (
    <TemplatableField
      label="Expiry"
      value={value}
      onChange={onChange}
      fallback="current_week"
      placeholder="{{webhook.expiry}}"
      hint="A relative type, an exact date such as 28OCT25, or a reference."
    >
      <Select value={value as string} onValueChange={onChange}>
        <SelectTrigger className="h-8">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((e) => (
            <SelectItem key={e.value} value={e.value}>
              {e.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </TemplatableField>
  )
}
