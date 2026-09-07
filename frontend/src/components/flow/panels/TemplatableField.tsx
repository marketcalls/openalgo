/**
 * A field that takes either a picked value or a {{variable}}.
 *
 * The executor already interpolates every order-defining field
 * (`ORDER_CRITICAL_FIELDS` in flow_executor_service.py), so `exchange`,
 * `action` and `quantity` accept a reference exactly as `symbol` does. Only the
 * form stopped you: a dropdown cannot express `{{webhook.exchange}}` and a
 * number input cannot express `{{webhook.quantity}}`, so a webhook-driven order
 * could name its instrument and nothing else.
 *
 * The picker stays the default, because most orders are fixed and a free-text
 * box for BUY/SELL would be a worse control. The toggle swaps it for a text
 * input only when the author wants the value to come from the payload.
 *
 * Layout note: the label is a direct child of the wrapper and the toggle is the
 * last child, on purpose. The panel's tests reach a control as
 * `getByText(label).parentElement.querySelector('button' | 'input')`, which is
 * how a person finds it too. Nesting the label beside the toggle in a flex row
 * pushed it a level deeper and made that lookup return the toggle instead.
 */

import { Braces } from 'lucide-react'
import type { ReactNode } from 'react'

import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

/** A value is a reference the moment it carries a token, not by a flag we store. */
export function isTemplateValue(value: unknown): boolean {
  return typeof value === 'string' && value.includes('{{')
}

interface TemplatableFieldProps {
  label: string
  value: unknown
  onChange: (value: string | number) => void
  /**
   * What the field returns to when the author switches back to picking. Without
   * it the control would land on an empty value the picker cannot show.
   */
  fallback: string | number
  /** Suggested reference, also the seed when the toggle is switched on. */
  placeholder?: string
  /** The picker: a Select, a button pair, a number input. */
  children: ReactNode
  hint?: string
  /**
   * Id of the control this labels. Without it the label stops naming anything,
   * which breaks both a screen reader and `getByLabelText`.
   */
  htmlFor?: string
}

export function TemplatableField({
  label,
  value,
  onChange,
  fallback,
  placeholder = '{{webhook.field}}',
  children,
  hint,
  htmlFor,
}: TemplatableFieldProps) {
  const dynamic = isTemplateValue(value)

  return (
    <div className="relative space-y-2">
      <Label className="text-xs" htmlFor={htmlFor}>
        {label}
      </Label>

      {dynamic ? (
        <Input
          id={htmlFor}
          className="h-8 font-mono text-xs"
          placeholder={placeholder}
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        children
      )}

      {dynamic && hint && <p className="text-[10px] text-muted-foreground">{hint}</p>}

      {/* Last child, and an icon rather than text: the control above it stays
          the first button in this wrapper, and this one adds nothing to the
          wrapper's text content. */}
      <button
        type="button"
        onClick={() => onChange(dynamic ? fallback : placeholder)}
        aria-label={dynamic ? `Use a fixed ${label}` : `Take ${label} from the payload`}
        title={dynamic ? 'Pick a fixed value instead' : 'Take this value from the payload'}
        className={cn(
          'absolute right-0 top-0 rounded p-0.5 transition-colors',
          dynamic ? 'text-primary' : 'text-muted-foreground/50 hover:bg-muted hover:text-foreground'
        )}
      >
        <Braces className="h-3 w-3" />
      </button>
    </div>
  )
}
