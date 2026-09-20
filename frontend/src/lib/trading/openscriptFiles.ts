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
}

/** A compile result the panel can draw: either a program, or what is wrong. */
export interface CompileResult {
  ok: boolean
  /** The whole diagnostic text, code and line and fix included, when it failed. */
  problem?: string
  /**
   * The line the first diagnostic sits on, for the editor's gutter to mark.
   *
   * One line rather than all of them: the gutter is four characters wide and a
   * column of marks would say less than one does. The console underneath
   * carries every diagnostic in full.
   */
  line?: number
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
  return Array.isArray(body) ? (body as StoredScript[]) : []
}

/** One script's source, exactly as it was saved. */
export async function readScript(file: string, signal?: AbortSignal): Promise<string> {
  const response = await fetch(`${BASE}/${encodeURIComponent(file)}?v=${Date.now()}`, { signal })
  if (!response.ok) throw new Error(`${file} could not be opened.`)
  return response.text()
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

/** Creates or replaces one script, and answers with what the server stored. */
export async function saveScript(file: string, source: string): Promise<StoredScript> {
  const response = await fetch(`${BASE}/${encodeURIComponent(file)}`, {
    method: 'POST',
    credentials: 'include',
    headers: await writeHeaders(),
    body: JSON.stringify({ source }),
  })
  if (!response.ok) {
    throw new Error(await readMessage(response, `${file} could not be saved.`))
  }
  const body = await response.json()
  return { file, mtime: Number(body.mtime) || 0, bytes: Number(body.bytes) || 0 }
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
  const { sourceFile, lex, parseTokens, check, emit, DiagnosticBag, renderDiagnostics } =
    await import('openalgo-script')

  const handle = sourceFile(file, source)
  const bag = new DiagnosticBag()
  const tokens = lex(handle, bag)
  const tree = parseTokens(handle, tokens, bag)
  const checked = check(handle, tree, bag)
  const result = emit(handle, checked, bag, {})

  const found = bag.ordered()
  const firstLine = found.length > 0 ? found[0].span?.line : undefined

  if (result.program === undefined) {
    const rendered = renderDiagnostics(handle, found)
    return {
      ok: false,
      problem: rendered || 'This script did not compile.',
      line: firstLine,
    }
  }
  // A program that compiled may still carry warnings worth reading, and the
  // renderer already formats them the way the catalogue writes them.
  if (found.length > 0) {
    return { ok: true, problem: renderDiagnostics(handle, found), line: firstLine }
  }
  return { ok: true }
}

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
  return `openscript:${file.replace(/\.oscript$/, '')}`
}

/** The starting point a new script is created with, so nothing opens blank. */
export const STARTER_SOURCE = [
  'version 1',
  'study("My study", overlay = true)',
  '',
  'length = input(20, "Length")',
  'average = sma(close, length)',
  '',
  'plot(average, "Average", aqua)',
  '',
].join('\n')
