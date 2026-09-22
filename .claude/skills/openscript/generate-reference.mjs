#!/usr/bin/env node
/**
 * Write `reference/library.md` from the compiler this app ships.
 *
 * ## Why this is generated
 *
 * The language has 350 described names across twelve namespaces, and a hand
 * written list of them is wrong the day one is added. It is also the thing an
 * author most needs complete: reaching for a name the language does not have is
 * the ordinary way a script fails, and reaching for a neighbouring name that
 * computes something else is the dangerous way.
 *
 * The compiler carries the descriptions itself, so they are read from it rather
 * than copied. `coverage.mjs` then holds the page to the compiler in both
 * directions, which is what makes "complete" a check instead of a claim.
 *
 * **The warmup is the part worth generating.** Every stateful call has a bar
 * before which it answers nothing, and an author who assumes a value on bar
 * zero writes a script that is quietly wrong for its first `len` bars. The
 * compiler states each one, so each is printed.
 *
 * Usage:
 *   node .claude/skills/openscript/generate-reference.mjs           # write it
 *   node .claude/skills/openscript/generate-reference.mjs --check   # CI: is it stale?
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'

import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const SKILL = import.meta.dirname
const REPO = resolve(SKILL, '..', '..', '..')
const DEV_ROOT = join(REPO, 'frontend', 'node_modules', 'openalgo-script')
const CACHE_ROOT = join(SKILL, '.cache')
const OUT = join(SKILL, 'reference', 'library.md')

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

/** Every name the compiler describes, and the colours, which it does not. */
const described = engine.describedNames()
const colours = engine.libraryNames().filter((one) => !described.includes(one))

/**
 * Group by namespace, with the bare names first.
 *
 * `bar.close` belongs under `bar`; `sma` belongs under the group of names that
 * have no namespace, which is most of the library and all of the arithmetic.
 */
const groups = new Map()
for (const name of described) {
  const at = name.indexOf('.')
  const key = at === -1 ? '' : name.slice(0, at)
  if (!groups.has(key)) groups.set(key, [])
  groups.get(key).push(name)
}

const NAMESPACE_NOTE = {
  '': 'Called bare. Most of the library, including every average, oscillator, band and comparison.',
  bar: 'Where this bar sits in the run, and what kind of bar it is. **Not the prices**: `open`, `high`, `low`, `close` and `volume` are bare names, and this namespace has no spelling of them.',
  chart: 'What the chart this is running on is showing.',
  session: 'Where this bar sits in the trading day.',
  date: 'Calendar facts about the bar, in the instrument\'s own zone.',
  str: 'Text. Used in labels, tables and log lines rather than in arithmetic.',
  math: 'Arithmetic beyond the bare names. Some of these have no portable reference yet: see the warning below.',
  pos: 'The position this strategy holds. A strategy only; a study has no position.',
  order: 'Orders this strategy has placed.',
  leg: 'One part of a position, for a strategy that holds more than one.',
  book: 'The strategy\'s own ledger of what it has done.',
  draw: 'Drawing on the chart: lines, boxes, labels.',
  req: 'Reading another instrument or another timeframe.',
}

/**
 * The calls with no portable reference algorithm.
 *
 * `spec/stdlib.md` section 20.11 in the language repository: the transcendental
 * family is computed by the host's own maths library, which differs in the last
 * bit between platforms. A script may call them and they compute what they
 * always did; what they do not carry is a guarantee that two engines agree.
 * Worth saying beside the names rather than in a note nobody reaches.
 */
const UNPORTABLE = new Set([
  'exp', 'log', 'log10', 'pow', 'hypot', 'alma', 'hv', 'chop',
  'math.log2', 'math.hypot', 'math.sin', 'math.cos', 'math.tan',
  'math.asin', 'math.acos', 'math.atan', 'math.atan2',
])

/**
 * Which names the compiler will refuse as planned but not implemented.
 *
 * **Measured, not listed.** The library describes a name whether or not a
 * version implements it, and `proseFor` says nothing about the difference, so a
 * page built from the descriptions alone tells an author to reach for a call
 * that is refused the moment they use it. That happened while these examples
 * were being written: `order.qtyForRisk` reads exactly like the call you want
 * for sizing from risk, and it does not exist yet.
 *
 * Two independent answers, and they have to agree:
 *
 *   the flag    `libraryEntries(name)` carries `planned`, which is the field
 *               `check/calls.js` itself tests before it reports OS2020
 *   the probe   each name put to this compiler in the four positions one can
 *               appear in, marked by an actual OS2020 coming back
 *
 * The flag is the answer, because it is what the checker reads. The probe is
 * here because the flag is only useful if it is still carried: an entry shape
 * that stops exposing it would leave every `planned` undefined, mark nothing,
 * and send the page quietly back to lying. A disagreement stops the
 * generation rather than being reconciled, since there is no reading of one
 * where the other is safe to ignore. Both cost about a quarter of a second.
 */
function flaggedPlanned(names) {
  return new Set(names.filter((name) => engine.libraryEntries(name).some((one) => one.planned)))
}

function probedPlanned(names) {
  const codesFor = (expr, inStrategy) => {
    const head = inStrategy ? 'strategy("p", qty = 1)' : 'study("p")'
    const text = `version 1
${head}
x = ${expr}
plot(close, "c", aqua)
`
    const bag = new engine.DiagnosticBag()
    const handle = engine.sourceFile('p.oscript', text)
    try {
      engine.emit(
        handle,
        engine.check(handle, engine.parseTokens(handle, engine.lex(handle, bag), bag), bag),
        bag,
        {}
      )
    } catch {
      // A name that makes the compiler throw tells us nothing about planned.
    }
    return bag.ordered().map((one) => one.code)
  }
  const out = new Set()
  for (const name of names) {
    for (const inStrategy of [false, true]) {
      for (const expr of [name, `${name}()`]) {
        if (codesFor(expr, inStrategy).includes('OS2020')) {
          out.add(name)
          break
        }
      }
      if (out.has(name)) break
    }
  }
  return out
}

const planned = flaggedPlanned(described)
const probed = probedPlanned(described)
const disagree = [
  ...[...planned].filter((one) => !probed.has(one)).map((one) => `${one}: flagged, no OS2020`),
  ...[...probed].filter((one) => !planned.has(one)).map((one) => `${one}: OS2020, not flagged`),
]
if (disagree.length > 0) {
  console.error('The planned flag and the compiler disagree, so neither can be trusted:')
  for (const one of disagree) console.error(`  ${one}`)
  console.error('Nothing was written. Read check/calls.js before changing this.')
  process.exit(1)
}


const out = []
out.push('<!-- Generated by generate-reference.mjs. Do not edit by hand. -->')
out.push('')
out.push('# The OpenScript library, every name')
out.push('')
out.push(`Read from \`openalgo-script@${version}\`, the compiler this app ships, so it is`)
out.push('what the browser will actually accept. `coverage.mjs` holds this page to the')
out.push('compiler in both directions: a name the compiler has and this page lacks fails,')
out.push('and so does a name here the compiler does not have.')
out.push('')
out.push(`**${described.length} names across ${groups.size} groups, and ${colours.length} colours.**`)
out.push('')
out.push(`${planned.size} of them are **planned and not implemented in this version**, and are`)
out.push('marked. The library describes a name whether or not a version implements it, so')
out.push('a name being here is not a promise that it compiles: reaching for one is OS2020,')
out.push('which names it and says so. These were measured by putting every name to this')
out.push('compiler rather than by keeping a list beside it.')
out.push('')
out.push('## How to read the warmup column')
out.push('')
out.push('A stateful call answers nothing until it has seen enough bars. `sma(close, 20)`')
out.push('is absent on bars 0 to 18 and first answers on bar 19. That absence propagates:')
out.push('arithmetic on an absent value is absent, and it is **not** zero. A script that')
out.push('assumes a number during warmup is quietly wrong for its first stretch of bars,')
out.push('which is the single most common way a ported study disagrees with its original.')
out.push('')
out.push('`bar 0` means it answers from the first bar and has no warmup.')
out.push('')

const order = ['', 'bar', 'chart', 'session', 'date', 'math', 'str', 'pos', 'order', 'leg', 'book', 'draw', 'req']
const seen = new Set()
for (const key of [...order, ...[...groups.keys()].filter((one) => !order.includes(one))]) {
  if (!groups.has(key) || seen.has(key)) continue
  seen.add(key)
  const names = groups.get(key).sort()
  out.push(`## ${key === '' ? 'Bare names' : '`' + key + '.`'}`)
  out.push('')
  if (NAMESPACE_NOTE[key]) {
    out.push(NAMESPACE_NOTE[key])
    out.push('')
  }
  out.push(`${names.length} names.`)
  out.push('')
  out.push('| Name | What it answers | Warmup |')
  out.push('|---|---|---|')
  for (const name of names) {
    const prose = engine.proseFor(name) ?? {}
    const summary = (prose.summary ?? '').replace(/\|/g, '\\|')
    const warmup = (prose.warmup ?? '').replace(/\|/g, '\\|')
    const flags =
      (planned.has(name) ? ' **(planned, not implemented)**' : '') +
      (UNPORTABLE.has(name) ? ' **(not portable)**' : '')
    out.push(`| \`${name}\` | ${summary}${flags} | ${planned.has(name) ? 'n/a' : warmup || 'bar 0'} |`)
  }
  out.push('')
}

out.push('## Colours')
out.push('')
out.push('Named constants, usable anywhere a colour is taken. A colour carries its own')
out.push('transparency, so these can be faded rather than replaced.')
out.push('')
out.push(colours.map((one) => `\`${one}\``).join(', ') + '.')
out.push('')
out.push('## The calls marked not portable')
out.push('')
out.push('The transcendental family is computed by the host\'s own maths library, which is')
out.push('correct to about one unit in the last place and differs between platforms in')
out.push('that last bit. The language specification has no reference algorithm for them')
out.push('yet, so two engines running the same script may differ in the final digit of a')
out.push('result that reaches one.')
out.push('')
out.push('They work, and they compute what they have always computed. What they do not')
out.push('carry is a guarantee that a backtest run on one machine and a live run on')
out.push('another agree to the last bit. For most scripts that is irrelevant; for one')
out.push('whose signal turns on a comparison at that precision, it is not.')
out.push('')

const page = out.join('\n')

// `--check` is what CI runs. The page is committed, so it can be stale in a way
// nothing else notices: the day a version adds a name or implements a planned
// one, the file in the tree describes a compiler that is no longer installed,
// and an author reads it and believes it. Bumping the pin and regenerating this
// are one change, and this is what makes that true rather than remembered.
if (process.argv.includes('--check')) {
  const current = existsSync(OUT) ? readFileSync(OUT, 'utf8') : null
  if (current === page) {
    console.log(
      `reference/library.md is current: ${described.length} names, ${colours.length} colours, ` +
        `${planned.size} of them planned, from openalgo-script ${version}.`
    )
    process.exit(0)
  }
  console.error('reference/library.md does not match the installed compiler.')
  console.error(
    current === null
      ? '  The file is missing.'
      : `  Committed: ${current.split('\n').length} lines. Generated now: ${page.split('\n').length} lines.`
  )
  console.error('  Run: node .claude/skills/openscript/generate-reference.mjs')
  console.error('  Then read the upstream changelog and update the prose the generator does not own.')
  process.exit(1)
}

mkdirSync(join(SKILL, 'reference'), { recursive: true })
writeFileSync(OUT, page, 'utf8')
console.log(
  `Wrote ${OUT}: ${described.length} names, ${groups.size} groups, ${colours.length} colours, ` +
    `${planned.size} of them planned, from openalgo-script ${version}.`
)
