/**
 * The filter rows.
 *
 * Two kinds, because an indicator offers two kinds of answer. A **value** filter
 * compares one of its output columns against a number or another column, which
 * is what plots are for. An **alert** filter asks the indicator's own declared
 * condition -- the direct analogue of Pine's `alertcondition()` -- and is
 * usually the better question: an indicator that already knows what a buy signal
 * looks like should not have that logic guessed at from its plot values.
 */
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
import { COMPARE_LABELS, type CompareOp, type Filter, type Operand } from '@/lib/screener/model'

export interface FilterColumn {
  key: string
  label: string
}

interface Props {
  columns: FilterColumn[]
  alerts: { id: string; title: string }[]
  filters: Filter[]
  onChange(filters: Filter[]): void
}

const OPS: CompareOp[] = ['>', '<', '>=', '<=', 'crossesAbove', 'crossesBelow', 'between']

function nextId(): string {
  return `f${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
}

/** A number field that can also point at another column. */
function OperandField({
  operand,
  columns,
  onChange,
}: {
  operand: Operand
  columns: FilterColumn[]
  onChange(next: Operand): void
}) {
  return (
    <div className="flex items-center gap-1">
      <Select
        value={operand.kind === 'const' ? '__const' : operand.key}
        onValueChange={(v) =>
          onChange(v === '__const' ? { kind: 'const', value: 0 } : { kind: 'column', key: v })
        }
      >
        <SelectTrigger className="h-8 w-[130px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="__const">a value</SelectItem>
          {columns.map((c) => (
            <SelectItem key={c.key} value={c.key}>
              {c.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {operand.kind === 'const' && (
        <Input
          type="number"
          className="h-8 w-[90px]"
          value={Number.isFinite(operand.value) ? operand.value : ''}
          onChange={(e) => onChange({ kind: 'const', value: Number(e.target.value) })}
        />
      )}
    </div>
  )
}

export function FilterBuilder({ columns, alerts, filters, onChange }: Props) {
  const replace = (id: string, next: Filter) =>
    onChange(filters.map((f) => (f.id === id ? next : f)))
  const remove = (id: string) => onChange(filters.filter((f) => f.id !== id))

  const addValue = () => {
    if (columns.length === 0) return
    onChange([
      ...filters,
      {
        id: nextId(),
        kind: 'value',
        column: columns[0].key,
        op: '>',
        rhs: { kind: 'const', value: 0 },
      },
    ])
  }

  const addAlert = () => {
    if (alerts.length === 0) return
    onChange([...filters, { id: nextId(), kind: 'alert', alertId: alerts[0].id }])
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <Label className="text-xs uppercase tracking-wide text-muted-foreground">Filters</Label>
        <div className="flex gap-1">
          <Button size="sm" variant="outline" onClick={addValue} disabled={columns.length === 0}>
            Add value
          </Button>
          <Button size="sm" variant="outline" onClick={addAlert} disabled={alerts.length === 0}>
            Add condition
          </Button>
        </div>
      </div>

      {filters.length === 0 && (
        <p className="text-xs text-muted-foreground">
          No filters: every symbol with data will be listed, with the indicator's values as columns.
        </p>
      )}

      {filters.map((filter) => (
        <div key={filter.id} className="flex flex-wrap items-center gap-1 rounded border p-2">
          {filter.kind === 'alert' ? (
            <>
              <span className="text-[13px] text-muted-foreground">Condition</span>
              <Select
                value={filter.alertId}
                onValueChange={(v) => replace(filter.id, { ...filter, alertId: v })}
              >
                <SelectTrigger className="h-8 w-[200px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {alerts.map((a) => (
                    <SelectItem key={a.id} value={a.id}>
                      {a.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <span className="text-[13px] text-muted-foreground">fires</span>
            </>
          ) : (
            <>
              <Select
                value={filter.column}
                onValueChange={(v) => replace(filter.id, { ...filter, column: v })}
              >
                <SelectTrigger className="h-8 w-[150px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {columns.map((c) => (
                    <SelectItem key={c.key} value={c.key}>
                      {c.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Select
                value={filter.op}
                onValueChange={(v) => {
                  const op = v as CompareOp
                  replace(filter.id, {
                    ...filter,
                    op,
                    // 'between' needs an upper bound; every other operator must
                    // not carry a stale one around.
                    rhs2:
                      op === 'between' ? (filter.rhs2 ?? { kind: 'const', value: 0 }) : undefined,
                  })
                }}
              >
                <SelectTrigger className="h-8 w-[140px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {OPS.map((op) => (
                    <SelectItem key={op} value={op}>
                      {COMPARE_LABELS[op]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <OperandField
                operand={filter.rhs}
                columns={columns}
                onChange={(rhs) => replace(filter.id, { ...filter, rhs })}
              />

              {filter.op === 'between' && (
                <>
                  <span className="text-[13px] text-muted-foreground">and</span>
                  <OperandField
                    operand={filter.rhs2 ?? { kind: 'const', value: 0 }}
                    columns={columns}
                    onChange={(rhs2) => replace(filter.id, { ...filter, rhs2 })}
                  />
                </>
              )}
            </>
          )}

          <Button
            size="sm"
            variant="ghost"
            className="ml-auto h-8"
            onClick={() => remove(filter.id)}
          >
            Remove
          </Button>
        </div>
      ))}

      {filters.length > 1 && (
        <p className="text-xs text-muted-foreground">All filters must pass.</p>
      )}
    </div>
  )
}
