#!/usr/bin/env node
/**
 * Hold this skill to the compiler the app ships, in both directions.
 *
 * Three things are checked, and the third is the one that stops the skill being
 * a list of names nobody can use:
 *
 *   NAMED         every name the compiler describes appears in the reference
 *   NOT INVENTED  every name the reference teaches exists in the compiler
 *   DEMONSTRATED  the shapes an author actually asks for are shown in an
 *                 example that compiles, not described in a sentence
 *
 * The second direction matters as much as the first. A reference that teaches a
 * call the language does not have sends an author to write a script that cannot
 * compile, and they will believe the skill before they believe the error.
 *
 * The third exists because "mentioned" and "teachable" are not the same. A
 * strategy that reverses is the case where knowing the name of `buy` is not
 * enough: the size has to be `lots + abs(pos.size)` or the position flattens
 * instead of turning, and no list of names says that.
 *
 * Usage: node .claude/skills/openscript/coverage.mjs
 */

import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const SKILL = import.meta.dirname
const REPO = resolve(SKILL, '..', '..', '..')
const DEV_ROOT = join(REPO, 'frontend', 'node_modules', 'openalgo-script')
const CACHE_ROOT = join(SKILL, '.cache')

function entryPoint(root) {
  return join(root, 'dist', 'core', 'index.js')
}

function pinnedVersion() {
  try {
    const pkg = JSON.parse(readFileSync(join(REPO, 'frontend', 'package.json'), 'utf8'))
    const spec = pkg.dependencies?.['openalgo-script'] ?? pkg.devDependencies?.['openalgo-script']
    return typeof spec === 'string' ? spec.replace(/^[\^~]/, '') : null
  } catch {
    return null
  }
}

function findCompiler() {
  if (existsSync(entryPoint(DEV_ROOT))) return DEV_ROOT
  const want = pinnedVersion()
  const cached = join(CACHE_ROOT, `v${want ?? 'latest'}`, 'node_modules', 'openalgo-script')
  if (existsSync(entryPoint(cached))) return cached
  throw new Error(
    'openalgo-script is not in frontend/node_modules or the skill cache. Run validate.mjs once, ' +
      'which fetches it, then run this again.'
  )
}

const root = findCompiler()
const engine = await import(pathToFileURL(entryPoint(root)).href)
const version = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).version

const REFERENCE = join(SKILL, 'reference')
const EXAMPLES = join(SKILL, 'examples')

const pages = readdirSync(REFERENCE)
  .filter((one) => one.endsWith('.md'))
  .map((one) => ({ name: one, text: readFileSync(join(REFERENCE, one), 'utf8') }))
const skillText = existsSync(join(SKILL, 'SKILL.md'))
  ? readFileSync(join(SKILL, 'SKILL.md'), 'utf8')
  : ''
const examples = readdirSync(EXAMPLES)
  .filter((one) => one.endsWith('.oscript'))
  .map((one) => ({ name: one, text: readFileSync(join(EXAMPLES, one), 'utf8') }))

const everything = pages.map((one) => one.text).join('\n') + '\n' + skillText
const exampleText = examples.map((one) => one.text).join('\n')

let failures = 0
const say = (line) => console.log(line)

// ---------------------------------------------------------------------------
// 1. NAMED: every name the compiler describes is in the reference
// ---------------------------------------------------------------------------

const described = engine.describedNames()
const colours = engine.libraryNames().filter((one) => !described.includes(one))

/** A name is present when it appears in backticks, which is how the page prints one. */
function present(name, haystack) {
  return haystack.includes('`' + name + '`')
}

const missing = described.filter((one) => !present(one, everything))
say(`NAMED         ${described.length - missing.length}/${described.length} described names`)
if (missing.length > 0) {
  failures += missing.length
  for (const one of missing.slice(0, 20)) say(`  missing: ${one}`)
  if (missing.length > 20) say(`  ... and ${missing.length - 20} more`)
  say('  Run generate-reference.mjs. The page is generated and should not be edited by hand.')
}

const missingColours = colours.filter((one) => !present(one, everything))
say(`              ${colours.length - missingColours.length}/${colours.length} colours`)
if (missingColours.length > 0) {
  failures += missingColours.length
  for (const one of missingColours) say(`  missing colour: ${one}`)
}

// ---------------------------------------------------------------------------
// 2. NOT INVENTED: every name the reference teaches exists in the compiler
// ---------------------------------------------------------------------------
//
// Only the generated table's own Name column is checked, because prose is full
// of backticked words that are not library names: file names, keywords, codes.
// The table is where a reader looks a call up, and a wrong row there is the one
// that sends somebody to write a call the language does not have.

const known = new Set([...described, ...colours])
const invented = []
for (const page of pages) {
  for (const line of page.text.split('\n')) {
    const row = line.match(/^\| `([A-Za-z_][A-Za-z0-9_.]*)` \|/)
    if (row && !known.has(row[1])) invented.push(`${page.name}: ${row[1]}`)
  }
}
say(`NOT INVENTED  ${invented.length === 0 ? 'every table row is a real name' : invented.length + ' rows name nothing'}`)
if (invented.length > 0) {
  failures += invented.length
  for (const one of invented.slice(0, 20)) say(`  not in the compiler: ${one}`)
}

// The prose, not just the tables, for the namespaced names.
//
// A table row is checked above; a sentence was not, and a sentence is where the
// teaching is. `band` reached the pitfalls page in a list of names said to be
// taken by the library. It is not a library name, and nothing here noticed,
// because it was in prose.
//
// Only DOTTED names are checked, because they are the unambiguous ones: a
// backticked `pos.equity` in these pages is always a library reference, while a
// bare backticked word may be a keyword, an argument, a file or an ordinary
// noun. That leaves the bare names unchecked, which is honest rather than
// complete: the namespaced surface is where a plausible wrong name does the
// most damage, since `pos.` and `order.` are exactly where a script reaches for
// something the version does not have.

// Scoped to the compiler's own namespaces, read from it rather than listed
// here. `openalgo.ta` is a Python module named in the sentence that says which
// of the three skills this is, and it is not a library reference; `pos.equity`
// is. The namespace list is what tells them apart, and it cannot go stale.
const NAMESPACES = new Set(engine.NAMESPACES)
const dotted = new Map()
for (const page of [...pages, { name: 'SKILL.md', text: skillText }]) {
  for (const hit of page.text.matchAll(/`([a-z][A-Za-z0-9]*\.[A-Za-z][A-Za-z0-9]*)`/g)) {
    const name = hit[1]
    if (!NAMESPACES.has(name.slice(0, name.indexOf('.')))) continue
    if (!dotted.has(name)) dotted.set(name, page.name)
  }
}
const proseInvented = [...dotted].filter(([name]) => !known.has(name))
say(
  `              ${dotted.size - proseInvented.length}/${dotted.size} namespaced names in prose are real`
)
if (proseInvented.length > 0) {
  failures += proseInvented.length
  for (const [name, page] of proseInvented.slice(0, 20)) say(`  not in the compiler: ${page}: ${name}`)
}

// ---------------------------------------------------------------------------
// 3. PLANNED MARKED: the page marks exactly the names the compiler refuses
// ---------------------------------------------------------------------------
//
// A name in the library is not a promise that it compiles. Ninety five of them
// are planned, and reaching for one is OS2020 at the call. An unmarked page
// sends an author to write `order.qtyForRisk(risk, entry, stop)`, which reads
// exactly like the call they want and does not exist in this version.
//
// Checked against the compiler rather than against a list here, so this gate
// does not need editing when a version implements one: the day `pos.equity`
// arrives, the flag drops, the page regenerates, and a page that was not
// regenerated fails here.

const plannedNow = described.filter((one) => engine.libraryEntries(one).some((e) => e.planned))
const MARK = '**(planned, not implemented)**'

const LINES = new RegExp(String.raw`\r?\n`)

/** The row for a name in the generated table, or undefined. */
function rowFor(name) {
  const at = '| `' + name + '` |'
  for (const page of pages) {
    for (const line of page.text.split(LINES)) if (line.startsWith(at)) return line
  }
  return undefined
}

const unmarked = plannedNow.filter((one) => !(rowFor(one) ?? '').includes(MARK))
const overmarked = described
  .filter((one) => !plannedNow.includes(one))
  .filter((one) => (rowFor(one) ?? '').includes(MARK))

say(
  `PLANNED       ${plannedNow.length - unmarked.length}/${plannedNow.length} planned names marked` +
    (overmarked.length > 0 ? `, ${overmarked.length} marked that are implemented` : '')
)
if (unmarked.length > 0 || overmarked.length > 0) {
  failures += unmarked.length + overmarked.length
  for (const one of unmarked.slice(0, 10)) say(`  unmarked, but OS2020 today: ${one}`)
  for (const one of overmarked.slice(0, 10)) say(`  marked, but it compiles: ${one}`)
  say('  Run generate-reference.mjs.')
}

// An example that reaches for a planned name compiles up to the point the
// checker refuses it, so this is caught by the compile above; but an example
// that merely TALKS about one in a comment should name it as planned, or the
// next author copies the comment.

// ---------------------------------------------------------------------------
// 4. DEMONSTRATED: the shapes an author asks for are shown, and they compile
// ---------------------------------------------------------------------------
//
// Each entry is a shape somebody asks for by name. `needs` are the calls that
// shape is made of: being able to write it means having seen them together in
// something that compiles, not having read their rows in a table.

const SHAPES = [
  {
    what: 'a study that plots',
    needs: ['study(', 'plot('],
    // `kind` is checked against the compiled program rather than the text, so a
    // file that merely mentions the word does not count.
    kind: 'study',
  },
  {
    what: 'a long only strategy',
    needs: ['strategy(', 'buy(', 'close(', 'pos.isFlat', 'pos.isLong'],
    kind: 'strategy',
  },
  {
    what: 'a short only strategy',
    needs: ['strategy(', 'sell(', 'close(', 'pos.isFlat', 'pos.isShort'],
    kind: 'strategy',
  },
  {
    what: 'a stop and reverse strategy',
    // The size is the whole lesson: a reversal sent at `lots` alone flattens
    // rather than turning. If this string goes, the example has lost the point.
    needs: ['strategy(', 'buy(', 'sell(', 'abs(pos.size)'],
    kind: 'strategy',
  },
  {
    what: 'an entry with a stop and a target',
    // `loss` and `profit` rather than `stop` and `target`: the call has no
    // arguments by those names, and writing them is OS3002. An example that
    // lost this has lost the only thing it was teaching.
    needs: ['strategy(', 'order.bracket(', 'loss =', 'profit ='],
    kind: 'strategy',
  },
  {
    what: 'an intraday strategy that is flat by the close',
    // `session.isLastBar` with no parentheses: it is a value, not a call.
    needs: ['strategy(', 'session.isIn(', 'session.isLastBar', 'close()'],
    kind: 'strategy',
  },
  { what: 'inputs a trader can change', needs: ['input('], kind: null },
  { what: 'shading between two plots', needs: ['fill('], kind: null },
]

/** Compile one example and answer its kind, or null when it will not compile. */
function kindOf(text, name) {
  const bag = new engine.DiagnosticBag()
  const handle = engine.sourceFile(name, engine.normaliseSource(text))
  const emitted = engine.emit(
    handle,
    engine.check(handle, engine.parseTokens(handle, engine.lex(handle, bag), bag), bag),
    bag,
    {}
  )
  const errors = bag.ordered().filter((one) => one.severity === 'error')
  if (errors.length > 0) return { kind: null, errors }
  return { kind: emitted.program?.meta?.kind ?? null, errors: [] }
}

const compiled = new Map()
let broken = 0
for (const one of examples) {
  const result = kindOf(one.text, one.name)
  compiled.set(one.name, result)
  if (result.errors.length > 0) {
    broken += 1
    failures += 1
    say(`EXAMPLE       ${one.name} does not compile:`)
    for (const e of result.errors.slice(0, 3)) say(`  ${e.code} line ${e.span?.line}: ${e.message}`)
  }
}
say(`EXAMPLES      ${examples.length - broken}/${examples.length} compile`)

let shown = 0
for (const shape of SHAPES) {
  const found = examples.find((one) => {
    if (!shape.needs.every((need) => one.text.includes(need))) return false
    if (shape.kind === null) return true
    return compiled.get(one.name)?.kind === shape.kind
  })
  if (found) {
    shown += 1
  } else {
    failures += 1
    say(`  NOT SHOWN: ${shape.what}`)
    say(`    no example compiles as ${shape.kind ?? 'anything'} and contains: ${shape.needs.join(', ')}`)
  }
}
say(`DEMONSTRATED  ${shown}/${SHAPES.length} shapes shown in an example that compiles`)

say('')
say(`openalgo-script ${version}`)
if (failures === 0) {
  say('COVERAGE COMPLETE')
  process.exit(0)
}
say(`GAPS: ${failures}`)
process.exit(1)
