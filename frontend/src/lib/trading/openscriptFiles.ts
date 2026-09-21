/**
 * Reading, writing and deleting the trader's OpenScript sources.
 *
 * The panel's data layer, kept out of the component so that what the routes
 * answer and what the panel draws can be tested apart. `openscriptStudies.ts`
 * is the other half: it compiles what is stored here and puts it on the chart.
 *
 * Every message here is written for a trader. A status code tells them nothing
 * they can act on, and putting one in front of them reads as a fault they
 * caused, which sends them looking through their own settings for something
 * that was never wrong.
 */

import { fetchCSRFToken } from '@/api/client'

export interface StoredScript {
  file: string
  mtime: number
  bytes: number
  /**
   * Whether a compiled program is stored beside this source.
   *
   * The same question as whether anything server side could run this script.
   * The compiler is in the browser and nowhere else, so a script the browser
   * has never compiled cleanly has no program stored for it, and a runner has
   * nothing to walk.
   */
  program: boolean
}

/**
 * One thing the compiler has to say, in the pieces a console can colour.
 *
 * Returned in parts rather than as a rendered block, because a reader scanning
 * a console is looking for the severity first, the place second and the words
 * third, and a single string can only be one colour. The catalogue already
 * separates the message from the fix; throwing that apart and re-joining it
 * into one line would be undoing work the language did.
 */
export interface EditorDiagnostic {
  code: string
  severity: 'error' | 'warning'
  line: number
  column: number
  length: number
  message: string
  fix: string
  /** The line of source it points at, so the console can show the offence. */
  sourceLine: string
}

/** A compile result the panel can draw: either a program, or what is wrong. */
export interface CompileResult {
  /**
   * Whether this script would actually run.
   *
   * **Read from the severities, never from whether a program came out.** The
   * emitter recovers, so a script with an undefined name still produces a
   * program while the checker files an error against it. Treating that as
   * success is how the panel came to say "ready to add" over a red diagnostic
   * and offer to put a study on the chart that cannot compute.
   */
  ok: boolean
  diagnostics: EditorDiagnostic[]
  /** What the script declares itself to be, when it got far enough to say. */
  kind?: ScriptKind
  /**
   * A failure that is not a diagnostic: a save refused, a network fault.
   *
   * Kept apart from the diagnostics because it is not about the script and a
   * reader should not have to work out which of the two they are looking at.
   */
  problem?: string
  /**
   * The line the first error sits on, for the editor's gutter to mark.
   *
   * One line rather than all of them: the gutter is four characters wide and a
   * column of marks would say less than one does. The console underneath
   * carries every diagnostic in full.
   */
  line?: number
  /**
   * The compiled program, in the canonical encoding, when the script compiles.
   *
   * Text rather than an object, and that is the point. The canonical encoding
   * is what a program's hash is taken over and what an engine loading a program
   * from text insists on, so those are the bytes that have to travel and be
   * stored. Handing the object to JSON.stringify on the way out would produce
   * different bytes, and the stored program would be refused when an engine
   * came to load it.
   *
   * Present only when `ok`. The emitter recovers, so a script with an error in
   * it still produces a program, and storing that one would leave a program
   * that cannot compute where a runner will find it.
   */
  program?: string
}

const BASE = '/openscript'

/** The one place a name is checked, so the panel and the server agree. */
export const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/

/** What the server will store, as the route states it. */
export const MAX_SOURCE_BYTES = 256 * 1024

/** Turns a name a trader typed into the file name the routes use. */
export function fileNameFor(typed: string): string {
  const trimmed = typed.trim().replace(/\.oscript$/i, '')
  return `${trimmed}.oscript`
}

/** Why a name will not be accepted, or null when it will. */
export function nameProblem(typed: string): string | null {
  const stem = typed.trim().replace(/\.oscript$/i, '')
  if (!stem) return 'Give the script a name.'
  if (!NAME_PATTERN.test(stem)) {
    return 'A name can hold letters, digits, dots, dashes and underscores, and starts with a letter or a digit.'
  }
  return null
}

async function readMessage(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json()
    if (body && typeof body.message === 'string') return body.message
  } catch {
    // The body was not the JSON this route sends. Nothing to add.
  }
  return fallback
}

/** Every script the server is holding, newest name order as it lists them. */
export async function listScripts(signal?: AbortSignal): Promise<StoredScript[]> {
  const response = await fetch(`${BASE}/index.json`, {
    headers: { Accept: 'application/json' },
    signal,
  })
  if (!response.ok) throw new Error('Your scripts could not be listed. Try again in a moment.')
  const body = await response.json()
  if (!Array.isArray(body)) return []
  // Read field by field rather than cast, for the sake of `program`: an
  // installation whose backend predates compiled programs answers without it,
  // and a panel asking whether a script is runnable has to read false there
  // rather than undefined.
  return body.map((entry) => ({
    file: String(entry?.file ?? ''),
    mtime: Number(entry?.mtime) || 0,
    bytes: Number(entry?.bytes) || 0,
    program: entry?.program === true,
  }))
}

/**
 * Normalises line endings the way the compiler does.
 *
 * The editor works in the language's own normal form so that the text on
 * screen, the offsets the compiler reports and the colours drawn behind it all
 * count characters the same way. A file written on a machine that ends lines
 * with a carriage return would otherwise put the compiler one character ahead
 * per line, and every diagnostic position and every colour would drift down the
 * file. Taken from the compiler rather than written here, because it is the
 * language's rule and a second copy of it is a second answer.
 */
export async function normalise(source: string): Promise<string> {
  const { normaliseSource } = await import('openalgo-script')
  return normaliseSource(source)
}

/** One script's source, in the normal form the editor and the compiler share. */
export async function readScript(file: string, signal?: AbortSignal): Promise<string> {
  const response = await fetch(`${BASE}/${encodeURIComponent(file)}?v=${Date.now()}`, { signal })
  if (!response.ok) throw new Error(`${file} could not be opened.`)
  return normalise(await response.text())
}

/**
 * The headers a write needs.
 *
 * Every method that changes something carries a CSRF token: Flask-WTF protects
 * POST, PUT, PATCH and DELETE, and `api/client.ts` states that set once. Without
 * the token the write is refused before it reaches the route, which looks from
 * the panel exactly like a save that did nothing.
 */
async function writeHeaders(): Promise<HeadersInit> {
  return {
    'Content-Type': 'application/json',
    'X-CSRFToken': await fetchCSRFToken(),
  }
}

/**
 * Creates or replaces one script, with the compiled program beside it.
 *
 * **The program travels with the save, and this is the only place it can come
 * from.** The compiler is TypeScript, the engine that will run a strategy on
 * the server is Python with no compiler in it, and the server has no JavaScript
 * runtime to fall back on. The browser is therefore the one place in the whole
 * deployment where a program can be produced, and a save carrying only the
 * source would leave nothing server side able to run the script, ever.
 *
 * `compiled` is the result a caller already has. The panel compiles before it
 * writes so it can say what is wrong, and handing that result over saves
 * compiling the same text twice; a caller with nothing gets a compile of its
 * own, so this is correct either way and no caller has to remember. A stale
 * result is not a silent failure either: a program records the hash of the
 * source it was built from, and the server refuses a pair that disagrees.
 *
 * A script that does not compile is still saved. Being half way through a
 * thought is not a reason to lose it, and the server reads a source with no
 * program as exactly that: kept, editable, and not runnable.
 */
export async function saveScript(
  file: string,
  source: string,
  compiled?: CompileResult,
): Promise<StoredScript> {
  const result = compiled ?? (await compileSource(file, source))
  const response = await fetch(`${BASE}/${encodeURIComponent(file)}`, {
    method: 'POST',
    credentials: 'include',
    headers: await writeHeaders(),
    body: JSON.stringify({ source, program: result.program ?? null }),
  })
  if (!response.ok) {
    throw new Error(await readMessage(response, `${file} could not be saved.`))
  }
  const body = await response.json()
  return {
    file,
    mtime: Number(body.mtime) || 0,
    bytes: Number(body.bytes) || 0,
    program: body.program === true,
  }
}

/** Removes one script and the backup taken of it. */
export async function deleteScript(file: string): Promise<void> {
  const response = await fetch(`${BASE}/${encodeURIComponent(file)}`, {
    method: 'DELETE',
    credentials: 'include',
    headers: await writeHeaders(),
  })
  if (!response.ok) {
    throw new Error(await readMessage(response, `${file} could not be deleted.`))
  }
}

/**
 * Compiles a source in the browser and says whether it would run.
 *
 * This is the whole of the feedback loop: there is no build step between saving
 * a script and the chart running it, so a mistake either arrives here or the
 * study is silently absent from the picker with nothing anywhere to say why.
 *
 * Every diagnostic is returned rather than the first. A script usually has one
 * mistake and sometimes four, and reporting them one at a time turns a single
 * read-through into four saves.
 */
export async function compileSource(file: string, source: string): Promise<CompileResult> {
  const { sourceFile, lex, parseTokens, check, emit, canonicalise, DiagnosticBag } = await import(
    'openalgo-script'
  )

  const handle = sourceFile(file, source)
  const bag = new DiagnosticBag()
  const tokens = lex(handle, bag)
  const tree = parseTokens(handle, tokens, bag)
  const checked = check(handle, tree, bag)
  const emitted = emit(handle, checked, bag, {})

  const lines = source.split('\n')
  const diagnostics: EditorDiagnostic[] = bag.ordered().map((one) => ({
    code: one.code,
    severity: one.severity,
    line: one.span?.line ?? 1,
    column: one.span?.column ?? 1,
    length: Math.max(1, one.span?.length ?? 1),
    message: one.message,
    fix: one.fix,
    sourceLine: lines[(one.span?.line ?? 1) - 1] ?? '',
  }))

  const errors = diagnostics.filter((one) => one.severity === 'error')
  const ok = errors.length === 0 && emitted.program !== undefined
  const firstError = errors[0] ?? diagnostics[0]

  return {
    ok,
    diagnostics,
    // The canonical encoding, taken from the language rather than from
    // JSON.stringify, and only for a script that would actually run. The
    // encoder is the one a program's hash is defined over; a host that wrote
    // its own would agree with it until the first number that reads back two
    // ways.
    program: ok ? canonicalText(canonicalise, emitted.program) : undefined,
    // Taken from the compiled program, which is the language's own answer,
    // falling back to the declaration the lexer found when nothing compiled.
    kind:
      (emitted.program?.meta?.kind as ScriptKind | undefined) ??
      (await kindOf(source)) ??
      undefined,
    line: firstError?.line,
    // A program that did not come out, with nothing filed against the script,
    // is the compiler's own fault rather than the author's, and saying nothing
    // at all would leave them staring at a panel with no opinion.
    problem:
      emitted.program === undefined && diagnostics.length === 0
        ? 'This script did not compile, and the compiler gave no reason. Please report it.'
        : undefined,
  }
}

/**
 * The canonical encoding of a program, or nothing when it cannot be written.
 *
 * The encoder refuses a value the format cannot hold, a number that is not
 * finite being the one that exists, and it refuses by throwing. None of that is
 * the author's doing and none of it is a diagnostic, so it must not take the
 * save down with it: the script is written, no program is stored, and the
 * script reads as not runnable, which is the truth.
 */
function canonicalText(encode: (value: unknown) => string, program: unknown): string | undefined {
  if (program === undefined) return undefined
  try {
    return encode(program)
  } catch {
    return undefined
  }
}

/** The prefix that marks a chart indicator as one of the trader's own scripts. */
const ID_PREFIX = 'openscript:'

/**
 * The id a study is registered and saved under.
 *
 * Stated here once and imported by the loader that registers the study, so the
 * panel's Add to chart and the chart's own registry can never name different
 * things. The file name rather than a hash of the source: the trader is editing
 * their own study in the panel beside the chart, and a new id on every save
 * would drop the study off the layout each time. Namespaced so it can never
 * collide with one of the chart's built-in ids.
 */
export function idForScript(file: string): string {
  return `${ID_PREFIX}${file.replace(/\.oscript$/, '')}`
}

/**
 * The script an indicator id names, or null when the id is not one of ours.
 *
 * The exact inverse of `idForScript`, and it lives beside it so the pair cannot
 * drift: the chart hands back an indicator id when somebody asks to see the
 * code behind a study, and a second place that took the prefix apart by hand
 * would keep working right up to the day the prefix changed.
 *
 * Null for a built-in study, which is the honest answer: the chart ships a
 * hundred of them and none was written in a file anybody can open.
 */
export function fileForScriptId(indicatorId: string): string | null {
  if (!indicatorId.startsWith(ID_PREFIX)) return null
  const stem = indicatorId.slice(ID_PREFIX.length)
  if (!NAME_PATTERN.test(stem)) return null
  return `${stem}.oscript`
}

/**
 * What a script declares itself to be.
 *
 * A study computes and draws. A strategy does that and also places orders, so
 * the two are different things to write and different things to run, and a
 * panel that does not say which is which leaves a trader to read line two.
 */
export type ScriptKind = 'study' | 'strategy'

/**
 * Which kind a source declares, asked of the language rather than guessed.
 *
 * The lexer already tells a reserved word from a name, so the declaration is
 * the first token that is one of the two. A regular expression over the text
 * would be a second, worse implementation of the language: it would find the
 * word inside a comment or a string and be wrong in a way nobody would think
 * to test.
 */
export async function kindOf(source: string): Promise<ScriptKind | null> {
  try {
    const { sourceFile, lex, DiagnosticBag } = await import('openalgo-script')
    const tokens = lex(sourceFile('kind.oscript', source), new DiagnosticBag())
    for (const token of tokens) {
      if (token.kind === 'study' || token.kind === 'strategy') return token.kind
    }
  } catch {
    // A source that will not lex has no kind to report, which the caller draws
    // as no badge rather than as a wrong one.
  }
  return null
}

/**
 * The title a new script declares, from the name the trader typed.
 *
 * A file name cannot hold a space and a chart legend should, so the separators
 * become spaces. Capitalised because it is a title and a legend reads better
 * for it. It sits on line two of a file the trader is already looking at, so
 * anything this gets slightly wrong is one edit away.
 */
function titleFrom(name: string): string {
  const words = name
    .trim()
    .replace(/\.oscript$/i, '')
    .replace(/[-_]+/g, ' ')
    .trim()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/**
 * The starting point a new script is created with, so nothing opens blank.
 *
 * It declares the name the trader typed rather than a placeholder. A study
 * called "My study" on every chart is the kind of small wrongness that makes a
 * tool feel like it is not really theirs, and the legend is where they meet it.
 */
export function starterFor(name: string, kind: ScriptKind): string {
  const title = titleFrom(name)
  if (kind === 'strategy') {
    return [
      'version 1',
      `strategy("${title}", overlay = true, qty = 1)`,
      '',
      'fast = ema(close, 9)',
      'slow = ema(close, 21)',
      '',
      'plot(fast, "Fast", aqua)',
      'plot(slow, "Slow", orange)',
      '',
      'if crossUp(fast, slow)',
      '    buy(qty = 1)',
      '',
      'if crossDown(fast, slow)',
      '    close()',
      '',
    ].join('\n')
  }
  return [
    'version 1',
    `study("${title}", overlay = true)`,
    '',
    'length = input(20, "Length")',
    'average = sma(close, length)',
    '',
    'plot(average, "Average", aqua)',
    '',
  ].join('\n')
}
