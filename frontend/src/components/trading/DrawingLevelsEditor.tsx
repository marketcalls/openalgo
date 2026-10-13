/**
 * The levels of a ladder drawing (Fibonacci retracement and extension, the
 * fans, the time zone, the Gann pair), one row each: shown or not, the ratio,
 * the colour and the label, plus Add level and Reset.
 *
 * The draw tier works out the levels, their default ladder, the conventional
 * colour of a ratio and the text a level prints; the terminal hands those over
 * through `DrawLevels`. This component only edits a copy and passes the whole
 * list back on every change, which the terminal writes to every selected ladder
 * drawing as one undo step.
 */
import { X } from 'lucide-react'
import type { FibLevel } from 'openalgo-charts/draw'
import { useState } from 'react'
import { type DrawLevels, nextLevelRatio } from '@/lib/trading/drawingActions'

interface Props {
  levels: DrawLevels
  onChange(levels: FibLevel[]): void
  onLabels(on: boolean): void
}

/** A colour an `<input type="color">` takes: six-digit hex, lower case. */
function hexOf(color: string | undefined): string | null {
  return typeof color === 'string' && /^#[0-9a-f]{6}$/i.test(color) ? color.toLowerCase() : null
}

const copy = (levels: readonly FibLevel[]): FibLevel[] => levels.map((level) => ({ ...level }))

const field =
  'h-7 w-full rounded border border-input bg-background px-1.5 text-xs outline-none focus-visible:ring-1 focus-visible:ring-ring'

export function DrawingLevelsEditor({ levels: source, onChange, onLabels }: Props) {
  const [list, setList] = useState<FibLevel[]>(() => copy(source.levels))
  // Rows are keyed by a counter, not by ratio: two levels may share a ratio
  // while one is being retyped, and React must not merge them.
  const [keys, setKeys] = useState<number[]>(() => source.levels.map((_, i) => i))
  const [labels, setLabels] = useState(source.showLabels)

  const commit = (next: FibLevel[], nextKeys = keys) => {
    setList(next)
    setKeys(nextKeys)
    onChange(copy(next))
  }
  const edit = (i: number, change: (level: FibLevel) => void) => {
    const next = copy(list)
    change(next[i])
    commit(next)
  }

  return (
    <div className="w-[19rem] max-w-[calc(100cqw-12px)]">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-xs font-medium">Levels</span>
        {labels !== null && (
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={labels}
              onChange={(e) => {
                setLabels(e.target.checked)
                onLabels(e.target.checked)
              }}
            />
            Show labels
          </label>
        )}
      </div>
      <div className="grid max-h-[46vh] gap-1 overflow-y-auto">
        {list.length === 0 && (
          <p className="py-1 text-xs text-muted-foreground">
            No levels. Add one, or reset to the defaults.
          </p>
        )}
        {list.map((level, i) => {
          const name = level.label || source.label(level.ratio)
          return (
            <div
              key={keys[i]}
              className={`grid grid-cols-[16px_64px_26px_1fr_22px] items-center gap-1.5 ${
                level.enabled === false ? 'opacity-50' : ''
              }`}
            >
              <input
                type="checkbox"
                aria-label={`Show level ${name}`}
                checked={level.enabled !== false}
                onChange={(e) =>
                  edit(i, (l) => {
                    // Shown is the default, so a shown level carries no flag.
                    if (e.target.checked) delete l.enabled
                    else l.enabled = false
                  })
                }
              />
              <input
                type="number"
                step="0.001"
                aria-label={`Level ${name} ratio`}
                defaultValue={level.ratio}
                className={field}
                onBlur={(e) => {
                  const value = Number(e.target.value)
                  // A blank or unreadable ratio keeps the last good one.
                  if (e.target.value.trim() === '' || !Number.isFinite(value)) {
                    e.target.value = String(level.ratio)
                    return
                  }
                  if (value !== level.ratio)
                    edit(i, (l) => {
                      l.ratio = value
                    })
                }}
              />
              <input
                type="color"
                aria-label={`Level ${name} colour`}
                value={hexOf(level.color) ?? hexOf(source.color(level.ratio)) ?? '#787b86'}
                className="h-6 w-6 cursor-pointer rounded border border-input bg-transparent p-0"
                onChange={(e) =>
                  edit(i, (l) => {
                    l.color = e.target.value
                  })
                }
              />
              <input
                type="text"
                aria-label={`Level ${name} label`}
                defaultValue={level.label ?? ''}
                placeholder={source.label(level.ratio)}
                spellCheck={false}
                className={field}
                onBlur={(e) => {
                  const value = e.target.value.trim()
                  if (value === (level.label ?? '')) return
                  edit(i, (l) => {
                    if (value === '') delete l.label
                    else l.label = value
                  })
                }}
              />
              <button
                type="button"
                aria-label={`Remove level ${name}`}
                className="flex h-6 w-6 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground"
                onClick={() =>
                  commit(
                    list.filter((_, j) => j !== i),
                    keys.filter((_, j) => j !== i)
                  )
                }
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )
        })}
      </div>
      <div className="mt-2 flex gap-1.5">
        <button
          type="button"
          className="rounded border border-border px-2 py-1 text-xs hover:bg-accent"
          onClick={() => {
            const ratio = nextLevelRatio(list)
            commit(
              [...list, { ratio, color: source.color(ratio) }],
              [...keys, Math.max(-1, ...keys) + 1]
            )
          }}
        >
          Add level
        </button>
        <button
          type="button"
          className="ml-auto rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
          onClick={() => {
            const base = Math.max(-1, ...keys) + 1
            commit(
              copy(source.defaults),
              source.defaults.map((_, i) => base + i)
            )
          }}
        >
          Reset
        </button>
      </div>
    </div>
  )
}
