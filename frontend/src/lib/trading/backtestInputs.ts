/**
 * A strategy's own inputs and declared settings, read off the compiled program.
 *
 * **What a trader may change here and what they may not is decided by the
 * language, not by this panel.** A script's `input()` declarations are exactly
 * what a host is allowed to set for a run: the engine resolves them against the
 * settings it is loaded with, which is what makes a parameter sweep possible
 * without editing the script. Everything else in a `strategy()` declaration is
 * the script's own statement about itself: the capital it assumes, the size it
 * trades, what it pays in commission. A host cannot override those, and a
 * commission supplied beside a declared one is refused outright (OS6023, two
 * cost models describing the same money).
 *
 * So the declared settings are shown and not offered. A box that silently does
 * nothing is worse than no box, and a reader still needs to know what capital
 * the figures in front of them rest on.
 */

/**
 * One setting, as the engine reads it: the plain value and nothing around it.
 *
 * **Not the language's tagged value.** A compiled program writes a constant as a
 * two element array tagged by kind, and a settings map looks like it should be
 * carried the same way. It is not: an engine resolves a supplied setting by
 * validating it against the declaration it belongs to, which already says the
 * kind, so what it wants is the value itself. A tagged value arrives as an
 * object where a number was declared and the whole run is refused (OS6019),
 * which is a run that never starts for a trader who typed a perfectly good
 * number. Both engines agree on this, and it is checked against a real one in
 * `backtestEngine.test.ts` rather than against a mock that would take anything.
 */
export type InputValue = boolean | number | string

/** One `input()` declaration, as the compiled program records it. */
export interface InputDeclaration {
  key: string
  kind: string
  label: string
  default: unknown
  min: number | null
  max: number | null
  step: number | null
  options: readonly unknown[] | null
  group: string
  tooltip: string | null
}

/** What a `strategy()` declaration states about itself. */
export interface DeclaredSettings {
  capital: number
  currency: string
  qty: number
  qtyType: string
  product: string
  fillOn: string
  slippage: number
  commission: number
  commissionType: string
  pyramiding: number
  closeOnSessionEnd: boolean
}

/**
 * The declarations a program carries, or nothing.
 *
 * Read defensively: the program is JSON that arrived from a compiler, and a
 * panel that threw on an unexpected shape would take the whole run down over a
 * settings list.
 */
export function inputsOf(program: unknown): InputDeclaration[] {
  const raw = (program as { inputs?: unknown })?.inputs
  if (!Array.isArray(raw)) return []
  return raw
    .filter((one): one is Record<string, unknown> => typeof one === 'object' && one !== null)
    .map((one) => ({
      key: String(one.key ?? ''),
      kind: String(one.kind ?? ''),
      label: String(one.label || one.key || ''),
      default: one.default,
      min: typeof one.min === 'number' ? one.min : null,
      max: typeof one.max === 'number' ? one.max : null,
      step: typeof one.step === 'number' ? one.step : null,
      options: Array.isArray(one.options) ? one.options : null,
      group: String(one.group ?? ''),
      tooltip: one.tooltip === null || one.tooltip === undefined ? null : String(one.tooltip),
    }))
    .filter((one) => one.key !== '')
}

export function declaredOf(program: unknown): DeclaredSettings | null {
  const meta = (program as { meta?: { strategy?: unknown } })?.meta?.strategy
  if (typeof meta !== 'object' || meta === null) return null
  const held = meta as Record<string, unknown>
  const number = (name: string, fallback: number) =>
    typeof held[name] === 'number' ? (held[name] as number) : fallback
  return {
    capital: number('capital', 0),
    currency: String(held.currency ?? ''),
    qty: number('qty', 0),
    qtyType: String(held.qtyType ?? 'units'),
    product: String(held.product ?? ''),
    fillOn: String(held.fillOn ?? ''),
    slippage: number('slippage', 0),
    commission: number('commission', 0),
    commissionType: String(held.commissionType ?? ''),
    pyramiding: number('pyramiding', 0),
    closeOnSessionEnd: held.closeOnSessionEnd === true,
  }
}

/**
 * A declaration's default, as a plain value a form field can hold.
 *
 * The program writes a value as a two element array tagged by kind, `["n", 10]`
 * for a number and `["s", "x"]` for a string, which is the compiled program's
 * own encoding and not something to guess at. An object form is accepted too,
 * because a reader of this should not have to care which the compiler emitted.
 */
export function defaultValueOf(declared: InputDeclaration): string | number | boolean | null {
  const raw = declared.default
  if (Array.isArray(raw) && raw.length >= 2) {
    const value = raw[1]
    if (typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean') {
      return value
    }
    return null
  }
  if (raw && typeof raw === 'object' && 'value' in (raw as Record<string, unknown>)) {
    const value = (raw as { value: unknown }).value
    if (typeof value === 'number' || typeof value === 'string' || typeof value === 'boolean') {
      return value
    }
  }
  if (typeof raw === 'number' || typeof raw === 'string' || typeof raw === 'boolean') return raw
  return null
}

/**
 * What the form holds, as the settings the engine is loaded with.
 *
 * Only a field the trader actually changed is sent. An input left alone is
 * absent from the map, so the engine resolves the declaration's own default,
 * which is the one value guaranteed to be the right type and inside the
 * declared bounds. Sending every field back would make this panel the authority
 * on defaults, and the first divergence would be a run whose inputs the script
 * never agreed to.
 *
 * Every value is plain: see `InputValue` for why an engine refuses a tagged one.
 */
export function settingsFromForm(
  declarations: readonly InputDeclaration[],
  edited: Readonly<Record<string, string>>
): Record<string, InputValue> {
  const out: Record<string, InputValue> = {}

  for (const declared of declarations) {
    const typed = edited[declared.key]
    if (typed === undefined || typed === '') continue

    if (declared.kind === 'bool') {
      out[declared.key] = typed === 'true'
      continue
    }
    if (declared.kind === 'number') {
      const value = Number(typed)
      if (!Number.isFinite(value)) continue
      // The bounds are the script's own and are not this panel's to widen: a
      // value outside them is refused by the engine before the first bar, and
      // sending it anyway turns a typo into a refused run rather than a field
      // that will not take it.
      if (declared.min !== null && value < declared.min) continue
      if (declared.max !== null && value > declared.max) continue
      out[declared.key] = value
      continue
    }
    out[declared.key] = typed
  }

  return out
}
