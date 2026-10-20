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
 *
 * **A declaration's group and tooltip are shown, not dropped.** The group is a
 * heading its rows sit under and the tooltip a line of help beneath its row
 * (`stdlib.md` 13.2), the same as the chart's settings dialog draws them, so a
 * strategy explains its parameters in the one place a trader sets them before
 * money is involved. The help is written out rather than left to a hover,
 * which a touch screen and a keyboard never produce.
 */

import { Fragment, useId } from 'react'
import { type InputDeclaration, defaultValueOf } from '@/lib/trading/backtestInputs'

interface Props {
  declarations: readonly InputDeclaration[]
  /** What the trader has typed, by key. Only what they changed. */
  edited: Readonly<Record<string, string>>
  onChange(key: string, value: string): void
  /** The sentence under the fields, which differs by where the form is used. */
  note?: string
}

/**
 * Declarations bucketed under their group, in first-seen order.
 *
 * Bucketed rather than headed wherever the group changes, because a group is a
 * heading its rows sit under: a second input declared into "Exits" further
 * down the file belongs with the first, not under a second "Exits". Rows with
 * no group keep the empty key and get no heading.
 */
function groupsOf(declarations: readonly InputDeclaration[]): [string, InputDeclaration[]][] {
  const out = new Map<string, InputDeclaration[]>()
  for (const one of declarations) {
    const list = out.get(one.group) ?? []
    list.push(one)
    out.set(one.group, list)
  }
  return [...out]
}

export function StrategyInputs({ declarations, edited, onChange, note }: Props) {
  const idBase = useId()
  if (declarations.length === 0) return null

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">Inputs</span>

      {groupsOf(declarations).map(([heading, group]) => (
        <Fragment key={heading}>
          {heading !== '' && (
            <h4 className="pt-1 text-[11px] font-medium text-muted-foreground">{heading}</h4>
          )}
          {group.map((one) => {
            const fallback = defaultValueOf(one)
            const helpId = one.tooltip ? `${idBase}-${one.key}-help` : undefined
            return (
              <div key={one.key} className="flex flex-col gap-0.5">
                <InputRow
                  one={one}
                  fallback={fallback}
                  edited={edited}
                  onChange={onChange}
                  helpId={helpId}
                />
                {one.tooltip && (
                  <p id={helpId} className="text-[10px] leading-snug text-muted-foreground">
                    {one.tooltip}
                  </p>
                )}
              </div>
            )
          })}
        </Fragment>
      ))}

      <p className="text-[10px] text-muted-foreground">
        {note ?? "A box left empty uses the script's own default."}
      </p>
    </div>
  )
}

/** One declaration's label and control. */
function InputRow({
  one,
  fallback,
  edited,
  onChange,
  helpId,
}: {
  one: InputDeclaration
  fallback: ReturnType<typeof defaultValueOf>
  edited: Readonly<Record<string, string>>
  onChange(key: string, value: string): void
  helpId: string | undefined
}) {
  return (
    <label className="flex items-center gap-1.5">
      <span className="flex-1 truncate text-[11px]" title={one.label}>
        {one.label}
      </span>

      {one.kind === 'bool' ? (
        <select
          className="h-7 w-28 rounded border border-border bg-background px-1 text-[11px]"
          value={edited[one.key] ?? String(fallback ?? 'false')}
          onChange={(e) => onChange(one.key, e.target.value)}
          aria-describedby={helpId}
        >
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      ) : one.options && one.options.length > 0 ? (
        <select
          className="h-7 w-28 rounded border border-border bg-background px-1 text-[11px]"
          value={edited[one.key] ?? String(fallback ?? '')}
          onChange={(e) => onChange(one.key, e.target.value)}
          aria-describedby={helpId}
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
          aria-describedby={helpId}
        />
      )}
    </label>
  )
}
