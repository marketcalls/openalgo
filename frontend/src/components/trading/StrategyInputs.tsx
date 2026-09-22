/**
 * The form a script's own parameters are set in.
 *
 * **One form, because there are two places a parameter is set and they must
 * mean the same thing.** A trader tunes a strategy in the backtest panel until
 * the report looks right, then sets it running from the strategies panel, and
 * the second has to accept exactly what the first accepted. Two forms is two
 * answers to "is 0.5 allowed here", and the one that disagrees is discovered by
 * a run that would not start or, worse, by a live strategy trading on a number
 * the backtest never saw.
 *
 * **Every field is the declaration's own.** A boolean gets two choices, a
 * declaration with an options list gets those options and nothing else, and a
 * number carries the script's minimum, maximum and step onto the box. None of
 * that is this form's opinion: the engine holds a supplied value to the same
 * three before the first bar, so a box that allowed more would be a box that
 * takes a value and then refuses the run.
 *
 * **An empty box means the script's own default, and says so.** It is not zero
 * and not an empty string. Sending every field back would make this form the
 * authority on defaults, and the first divergence would be a run whose inputs
 * the script never agreed to.
 */

import { type InputDeclaration, defaultValueOf } from '@/lib/trading/backtestInputs'

interface Props {
  declarations: readonly InputDeclaration[]
  /** What the trader has typed, by key. Only what they changed. */
  edited: Readonly<Record<string, string>>
  onChange(key: string, value: string): void
  /** The sentence under the fields, which differs by where the form is used. */
  note?: string
}

export function StrategyInputs({ declarations, edited, onChange, note }: Props) {
  if (declarations.length === 0) return null

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Inputs</span>

      {declarations.map((one) => {
        const fallback = defaultValueOf(one)
        return (
          <label key={one.key} className="flex items-center gap-1.5">
            <span className="flex-1 truncate text-[11px]" title={one.tooltip ?? one.label}>
              {one.label}
            </span>

            {one.kind === 'bool' ? (
              <select
                className="h-7 w-28 rounded border border-border bg-background px-1 text-[11px]"
                value={edited[one.key] ?? String(fallback ?? 'false')}
                onChange={(e) => onChange(one.key, e.target.value)}
              >
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            ) : one.options && one.options.length > 0 ? (
              <select
                className="h-7 w-28 rounded border border-border bg-background px-1 text-[11px]"
                value={edited[one.key] ?? String(fallback ?? '')}
                onChange={(e) => onChange(one.key, e.target.value)}
              >
                {one.options.map((option) => (
                  <option key={String(option)} value={String(option)}>
                    {String(option)}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type={one.kind === 'number' ? 'number' : 'text'}
                className="h-7 w-28 rounded border border-border bg-background px-1.5 text-[11px]"
                placeholder={fallback === null ? '' : String(fallback)}
                value={edited[one.key] ?? ''}
                min={one.min ?? undefined}
                max={one.max ?? undefined}
                step={one.step ?? undefined}
                onChange={(e) => onChange(one.key, e.target.value)}
              />
            )}
          </label>
        )
      })}

      <p className="text-[10px] text-muted-foreground">
        {note ?? "A box left empty uses the script's own default."}
      </p>
    </div>
  )
}
