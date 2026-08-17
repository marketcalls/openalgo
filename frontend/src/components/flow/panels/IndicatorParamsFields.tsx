// components/flow/panels/IndicatorParamsFields.tsx
// Parameter editor for the Indicator node's `params`.
//
// The node stores `params` as a JSON string because the backend forwards the
// parsed object straight to openalgo.ta as kwargs
// (services/flow_executor_service.execute_indicator). That storage format is
// unchanged here - only the editing surface is. Every other node in the config
// panel asks for typed fields, so asking for hand-written JSON made the
// Indicator node the odd one out: the user had to know each indicator's kwarg
// names and defaults, and a stray comma silently failed the run with
// "Invalid params JSON".
//
// Unrecognized keys already in a saved workflow are preserved untouched, and a
// raw JSON mode stays available for the one thing fields cannot express -
// {{variable}} interpolation, which execute_indicator applies to the whole
// params string before parsing it.

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { INDICATOR_PARAMS, type IndicatorParam } from '@/lib/flow/constants'

interface IndicatorParamsFieldsProps {
  indicatorName: string
  /** Raw `params` JSON string as stored on the node. */
  value: string
  onChange: (raw: string) => void
}

type ParamValue = number | string | boolean

/** Parse the stored JSON, distinguishing "empty" from "malformed". */
function parseParams(raw: string): { values: Record<string, unknown>; error: string | null } {
  const text = (raw || '').trim()
  if (!text) return { values: {}, error: null }
  try {
    const parsed = JSON.parse(text)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { values: {}, error: 'Params must be a JSON object, e.g. {"period": 14}' }
    }
    return { values: parsed as Record<string, unknown>, error: null }
  } catch (e) {
    return { values: {}, error: e instanceof Error ? e.message : 'Invalid JSON' }
  }
}

/** Serialize back, keeping the spec order first and any unknown keys after. */
function serialize(specs: readonly IndicatorParam[], values: Record<string, unknown>): string {
  const known = new Set(specs.map((s) => s.name))
  const out: Record<string, unknown> = {}
  for (const spec of specs) {
    if (spec.name in values) out[spec.name] = values[spec.name]
  }
  for (const [key, val] of Object.entries(values)) {
    if (!known.has(key)) out[key] = val
  }
  return Object.keys(out).length ? JSON.stringify(out) : ''
}

export function IndicatorParamsFields({
  indicatorName,
  value,
  onChange,
}: IndicatorParamsFieldsProps) {
  const specs = INDICATOR_PARAMS[indicatorName] ?? []
  const { values, error } = parseParams(value)
  // In-progress text for number fields. A controlled number input cannot hold
  // a transient "" or "-" while the user retypes a value, so the draft holds
  // it and only parseable text is committed to the node.
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [jsonMode, setJsonMode] = useState(false)

  // Malformed JSON (hand-written, or interpolated) has no field representation
  // - editing it as fields would silently discard whatever is in there.
  const showJson = jsonMode || error !== null

  const commit = (name: string, next: ParamValue) => {
    onChange(serialize(specs, { ...values, [name]: next }))
  }

  const current = (spec: IndicatorParam): ParamValue => {
    const stored = values[spec.name]
    if (stored === undefined) return spec.default
    return stored as ParamValue
  }

  const renderField = (spec: IndicatorParam) => {
    if (spec.type === 'bool') {
      return (
        <div key={spec.name} className="flex items-center justify-between rounded-lg border p-3">
          <Label className="text-xs">{spec.label}</Label>
          <Switch checked={Boolean(current(spec))} onCheckedChange={(v) => commit(spec.name, v)} />
        </div>
      )
    }

    if (spec.choices) {
      return (
        <div key={spec.name} className="space-y-2">
          <Label className="text-xs">{spec.label}</Label>
          <Select value={String(current(spec))} onValueChange={(v) => commit(spec.name, v)}>
            <SelectTrigger className="h-8">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {spec.choices.map((choice) => (
                <SelectItem key={choice} value={choice}>
                  {choice}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )
    }

    if (spec.type === 'string') {
      return (
        <div key={spec.name} className="space-y-2">
          <Label className="text-xs">{spec.label}</Label>
          <Input
            className="h-8"
            placeholder={String(spec.default)}
            value={String(current(spec))}
            onChange={(e) => commit(spec.name, e.target.value)}
          />
        </div>
      )
    }

    const draft = drafts[spec.name]
    return (
      <div key={spec.name} className="space-y-2">
        <Label className="text-xs">{spec.label}</Label>
        <Input
          type="number"
          step={spec.type === 'float' ? 'any' : 1}
          className="h-8"
          placeholder={String(spec.default)}
          value={draft ?? String(current(spec))}
          onChange={(e) => {
            const text = e.target.value
            setDrafts((d) => ({ ...d, [spec.name]: text }))
            const parsed =
              spec.type === 'float' ? Number.parseFloat(text) : Number.parseInt(text, 10)
            if (Number.isFinite(parsed)) commit(spec.name, parsed)
          }}
          onBlur={() =>
            setDrafts((d) => {
              const { [spec.name]: _dropped, ...rest } = d
              return rest
            })
          }
        />
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Label className="text-xs">Parameters</Label>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-[10px]"
          onClick={() => setJsonMode((m) => !m)}
        >
          {showJson ? 'Use fields' : 'Edit as JSON'}
        </Button>
      </div>

      {showJson ? (
        <div className="space-y-2">
          <Input
            className="h-8"
            placeholder='{"period": 14}'
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
          {error ? (
            <p className="text-[10px] text-destructive">{error}</p>
          ) : (
            <p className="text-[10px] text-muted-foreground">
              Raw kwargs passed to the indicator. Use this for {'{{variable}}'} references, which
              are interpolated before the JSON is parsed - the fields view cannot represent them.
            </p>
          )}
        </div>
      ) : specs.length === 0 ? (
        <p className="text-[10px] text-muted-foreground">This indicator takes no parameters.</p>
      ) : (
        <div className="space-y-3">{specs.map(renderField)}</div>
      )}
    </div>
  )
}
