/**
 * Compiles the trader's OpenScript sources and registers each one as a study.
 *
 * Called from `terminal.ts:loadIndicators` beside `loadCustomIndicators`, so
 * every path that can reach `chart.addIndicator` sees a compiled study before
 * it looks anything up, exactly as a custom indicator module is seen.
 *
 * **The difference from `customIndicators.ts` is what arrives over the wire.** A
 * custom indicator is a JavaScript module the page imports, so the page runs it
 * and it has the page's own authority. A source here is text. It is compiled to
 * a list of instructions, an engine walks that list, and a script can only name
 * what the instruction set gives it. There is no spelling for a network call, a
 * file or a reach into the page, so a study from a stranger can draw a wrong
 * line and cannot place an order.
 *
 * That is also why nothing here uses `import()` on a fetched URL and why the
 * route serves `text/plain`: a response the page could import would hand the
 * file the page's authority and undo the whole reason for the format. It is
 * what lets this run under a content security policy with no `unsafe-eval`,
 * which is the policy this application already sets.
 *
 * **Compiling is the trader's only feedback, so a failure has to be a sentence.**
 * There is no build step between saving a script and running it. A diagnostic
 * carries a code, a line, a column and a fix, and all four reach the caller
 * rather than a console nobody has open.
 */

import { idForScript } from './openscriptFiles'

/** One source the server is offering. `mtime` is what makes an edit reappear. */
interface StoredScript {
  file: string
  mtime: number
  bytes: number
}

export interface OpenScriptLoad {
  /** Scripts that compiled and registered, this call only. */
  loaded: string[]
  /** Per-script failures, already written for a trader to read. */
  errors: { file: string; message: string }[]
}

const INDEX_URL = '/openscript/index.json'

/**
 * Scripts already compiled, keyed by name and modification time.
 *
 * Module scope rather than per call, because `loadIndicators` runs on every
 * picker open, every layout restore and every symbol change. Keying on the
 * modification time is what makes an edited script recompile and an untouched
 * one cost nothing.
 */
const compiled = new Set<string>()

/** What a trader should read when something fails, never a status code. */
function messageOf(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  return String(error)
}

/**
 * Whether this program places orders, read off the program not off the file.
 *
 * **This used to decide whether to register the script at all, and now decides
 * how.** A program needing `orders` is registered like any study and run
 * against the language's own simulated venue, which is what `simulateOrders`
 * turns on at the call below; without it the engine refuses such a program at
 * load with OS6006, a message about capability tags shown to somebody who had
 * only pressed a button in a list.
 *
 * Read from the program's own `requires` rather than from whether the source
 * says `study` or `strategy`, because `requires` is the same fact the engine
 * tests. A strategy that placed no orders would need no simulation and a study
 * that somehow placed them would, and both would be right.
 */
function placesOrders(program: unknown): string | null {
  const requires = (program as { requires?: unknown })?.requires
  if (!Array.isArray(requires)) return null
  const beyond = requires.filter((tag) => tag === 'orders')
  return beyond.length > 0 ? String(beyond[0]) : null
}

/**
 * Compiles one source into the program an engine is handed.
 *
 * Throws with every diagnostic the compiler produced rather than the first.
 * A script usually has one mistake and sometimes has four, and reporting one
 * at a time turns a single read-through into four saves.
 */
async function programFor(file: string, text: string): Promise<unknown> {
  const { sourceFile, lex, parseTokens, check, emit, DiagnosticBag, renderDiagnostics } =
    await import('openalgo-script')

  const source = sourceFile(file, text)
  const bag = new DiagnosticBag()
  const tokens = lex(source, bag)
  const tree = parseTokens(source, tokens, bag)
  const checked = check(source, tree, bag)
  const result = emit(source, checked, bag, {})

  if (result.program === undefined) {
    const rendered = renderDiagnostics(source, bag.ordered())
    throw new Error(rendered || 'the script did not compile')
  }
  return result.program
}

/**
 * Fetches, compiles and registers every stored script that has changed.
 *
 * One script failing takes nothing else down: each is caught on its own and
 * reported by name, because a trader with four studies and one typo should
 * still see the other three.
 *
 * **There is no reporter for a problem found while a study runs**, which is the
 * one thing `customIndicators` needs and this does not. That reporter exists
 * there because a hand written `calc` returning a column one element short
 * draws nothing and throws nothing, so nothing else would ever say so. Here the
 * columns are built from the engine's own channels, and a study that stops on a
 * bar throws a named error carrying the catalogue's sentence, its code and its
 * fix, which the chart already puts in front of the trader.
 */
export async function loadOpenScriptStudies(): Promise<OpenScriptLoad> {
  const result: OpenScriptLoad = { loaded: [], errors: [] }

  let stored: StoredScript[]
  try {
    const response = await fetch(INDEX_URL, { headers: { Accept: 'application/json' } })
    if (!response.ok) return result
    stored = (await response.json()) as StoredScript[]
  } catch {
    // No scripts folder, or no session. Neither is a problem to report: the
    // trader did not ask for anything here.
    return result
  }
  if (!Array.isArray(stored) || stored.length === 0) return result

  const fresh = stored.filter((one) => !compiled.has(`${one.file}@${one.mtime}`))
  if (fresh.length === 0) return result

  const charts = await import('openalgo-charts')
  const { descriptorFor } = await import('openalgo-script/adapters/charts')

  for (const script of fresh) {
    compiled.add(`${script.file}@${script.mtime}`)
    try {
      const url = `/openscript/${encodeURIComponent(script.file)}?v=${script.mtime}`
      const response = await fetch(url)
      if (!response.ok) throw new Error('this script could not be read back from the server')
      const text = await response.text()

      const program = await programFor(script.file, text)

      // **A strategy is registered like a study, and draws like one.** It has
      // plots, a title and settings exactly as a study does, and until now none
      // of them reached the chart: a trader who saved a strategy opened the
      // indicator list and could not find it, so its lines came from a separate
      // study they had to keep in step by hand.
      //
      // `simulateOrders` is what makes that safe. Without it the engine refuses
      // a program that places orders, and with a destination that answered
      // nothing it would run while never learning it holds a position: every
      // close closing nothing, every entry allowed again on the next signal,
      // and the plots wrong wherever they read the position. The language runs
      // it against the venue its own backtest uses instead, so what is drawn
      // here and what a report of the same script says are one answer.
      //
      // **It places nothing.** The venue is a simulation inside the browser;
      // the chart has no route to the platform and is given none. Trading is
      // what the strategies panel is for, and the panel says so on screen.
      const trades = placesOrders(program) !== null

      const descriptor = descriptorFor(program as never, {
        id: idForScript(script.file),
        category: 'OpenScript',
        ...(trades ? { simulateOrders: true } : {}),
      })
      // `hasSource` puts a braces button on this study's legend row, which the
      // chart turns into an `indicatorSource` event and the terminal turns back
      // into this file. Set here rather than by the language's adapter: the
      // adapter compiles a program and has no opinion about whether the host
      // can show anybody a file, and this host can, because it is the one
      // serving them.
      // `markerAnchor` decides what a signal's "above" and "below" are measured
      // against. A script writes `at = "below"` meaning below the candle, and
      // the chart's default is the study's own first plot: a study that
      // declares an invisible mid-body column first, so its marks have a
      // series with a point on every bar, then draws every mark through the
      // middle of the candle it is about. Price is what the author meant.
      charts.registerIndicator({
        ...(descriptor as object),
        hasSource: true,
        markerAnchor: 'price',
      } as never)
      result.loaded.push(script.file)
    } catch (error) {
      // Forget the key so the next call tries again. A compile that failed
      // because the server was briefly unreachable should not stay failed for
      // the life of the page.
      compiled.delete(`${script.file}@${script.mtime}`)
      result.errors.push({ file: script.file, message: messageOf(error) })
    }
  }

  return result
}

/** Drops the compiled record, so the next call recompiles every script. */
export function forgetOpenScriptStudies(): void {
  compiled.clear()
}
