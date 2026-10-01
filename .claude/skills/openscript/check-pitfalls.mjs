#!/usr/bin/env node
/**
 * Hold every diagnostic code `reference/pitfalls.md` names to the compiler.
 *
 * ## Why this is a script and not a careful read
 *
 * The page teaches by naming codes: "writing `stop` on `order.bracket` is
 * OS3002". An author trusts that, and a page whose codes have drifted is worse
 * than no page, because it sends somebody looking for the wrong mistake.
 *
 * Every entry below is the wrong version and the right version of one snippet.
 * The wrong one must produce the code the page claims; the right one must
 * compile clean. Both halves matter: a page that says a spelling is refused,
 * against a compiler that accepts it, is wrong in the direction that costs a
 * position, and a suggested fix that does not itself compile is worse than the
 * mistake it replaces.
 *
 * `order.qtyForRisk` is why this exists. It is described, it reads exactly like
 * the call you want, and it does not exist in this version. It reached a draft
 * example before the compiler was asked.
 *
 * Usage: node .claude/skills/openscript/check-pitfalls.mjs
 */

import { existsSync, readFileSync } from 'node:fs'
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
  throw new Error('openalgo-script is not installed. Run validate.mjs once, which fetches it.')
}

const root = findCompiler()
const engine = await import(pathToFileURL(entryPoint(root)).href)
const version = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).version

const NL = String.fromCharCode(10)

/** Compile one whole file and answer the error codes it produced. */
function codesFor(lines) {
  const bag = new engine.DiagnosticBag()
  const handle = engine.sourceFile('probe.oscript', engine.normaliseSource(lines.join(NL) + NL))
  try {
    engine.emit(
      handle,
      engine.check(handle, engine.parseTokens(handle, engine.lex(handle, bag), bag), bag),
      bag,
      {}
    )
  } catch (error) {
    return { codes: ['THREW'], errors: ['THREW'], threw: String(error?.message ?? error) }
  }
  const all = bag.ordered()
  return {
    codes: all.map((one) => one.code),
    errors: all.filter((one) => one.severity === 'error').map((one) => one.code),
    threw: null,
  }
}

const STRATEGY = ['version 1', 'lots = input(1, "Quantity", min = 1)', 'strategy("Probe", qty = lots)']
const STUDY = ['version 1', 'study("Probe")']

/**
 * Each case: the code the page names, the file that must produce it, and the
 * file the page offers as the fix, which must compile clean.
 */
const CASES = [
  {
    page: 'order.bracket has no stop or target',
    code: 'OS3002',
    wrong: [...STRATEGY, 'plot(close, "c", aqua)', 'if bar.isLast', '    order.bracket("B", stop = close, target = close)'],
    right: [...STRATEGY, 'plot(close, "c", aqua)', 'if bar.isLast', '    order.bracket("B", loss = 10, profit = 20)'],
  },
  {
    page: 'session.isLastBar is a value, not a function',
    code: 'OS2010',
    wrong: [...STRATEGY, 'plot(close, "c", aqua)', 'if session.isLastBar()', '    close()'],
    right: [...STRATEGY, 'plot(close, "c", aqua)', 'if session.isLastBar', '    close()'],
  },
  {
    page: 'a close tag must name a tag an order was placed with',
    code: 'OS7016',
    wrong: [...STRATEGY, 'plot(close, "c", aqua)', 'if bar.isLast', '    close(tag = "Square off")'],
    right: [...STRATEGY, 'plot(close, "c", aqua)', 'if bar.isLast', '    close()'],
  },
  {
    page: 'order.qtyForRisk is planned',
    code: 'OS2020',
    wrong: [...STRATEGY, 'plot(close, "c", aqua)', 'if bar.isLast', '    buy(qty = order.qtyForRisk(2000, close, close - 10))'],
    right: [...STRATEGY, 'plot(close, "c", aqua)', 'if bar.isLast', '    buy(qty = max(1, floor(2000 / 10)))'],
  },
  {
    page: 'do not write leg in a file that declares none',
    code: 'OS3023',
    wrong: [...STRATEGY, 'plot(close, "c", aqua)', 'if bar.isLast', '    buy(qty = lots, leg = "main")'],
    right: [...STRATEGY, 'plot(close, "c", aqua)', 'if bar.isLast', '    buy(qty = lots)'],
  },
  {
    page: 'fill is top level only',
    code: 'OS3006',
    wrong: [
      ...STUDY,
      'show = input(true, "Show")',
      'u = plot(high, "U", blue)',
      'l = plot(low, "L", blue)',
      'if show',
      '    fill(u, l, blue)',
    ],
    // The value carries `none`, not the declaration a colour. There is no
    // transparent colour: the first draft of the page offered one, and this
    // check is what found that it does not exist.
    right: [
      ...STUDY,
      'show = input(true, "Show")',
      'u = plot(show ? high : none, "U", blue)',
      'l = plot(show ? low : none, "L", blue)',
      'fill(u, l, blue)',
    ],
  },
  {
    page: 'transparent is not one of the nineteen colours',
    code: 'OS2001',
    wrong: [...STUDY, 'plot(close, "c", transparent)'],
    right: [...STUDY, 'plot(close, "c", aqua)'],
  },
  {
    page: 'input is top level only',
    code: 'OS3007',
    wrong: [...STUDY, 'plot(close, "c", aqua)', 'if bar.isLast', '    n = input(5, "N")'],
    right: [...STUDY, 'n = input(5, "N")', 'plot(close, "c", aqua)'],
  },
  {
    page: 'fill takes plot handles, not titles',
    code: 'OS3020',
    wrong: [...STUDY, 'u = plot(high, "U", blue)', 'l = plot(low, "L", blue)', 'fill("U", "L", blue)'],
    right: [...STUDY, 'u = plot(high, "U", blue)', 'l = plot(low, "L", blue)', 'fill(u, l, blue)'],
  },
  {
    // A WARNING, so the script compiles, emits a program and installs. The
    // page says so, because "the compiler will catch it" is false here.
    page: 'a stateful call inside a branch is a warning, not a refusal',
    code: 'OS8001',
    wrong: [
      ...STUDY,
      'plot(close, "c", aqua)',
      'if close > open',
      '    trendLine = sma(close, 20)',
      '    x = trendLine',
    ],
    right: [
      ...STUDY,
      'trendLine = sma(close, 20)',
      'plot(close, "c", aqua)',
      'plot(close > open ? trendLine : none, "t", red)',
    ],
  },
  {
    // `avg` is a library name. Shadowing it was an accident in a draft of the
    // OS8001 case above, which is how it got onto the page.
    page: 'the library already has that name',
    code: 'OS2002',
    wrong: [...STUDY, 'avg = sma(close, 20)', 'plot(avg, "a", aqua)'],
    right: [...STUDY, 'trendLine = sma(close, 20)', 'plot(trendLine, "a", aqua)'],
  },
  {
    page: 'a declaration option cannot be an expression over an input',
    code: 'OS6018',
    wrong: [...STUDY, 'n = input(2, "N")', 'plot(close, "c", aqua, width = n + 1)'],
    right: [...STUDY, 'n = input(3, "N")', 'plot(close, "c", aqua, width = n)'],
  },
  {
    // Reported beside OS2002 on the same line: the shadowed name then being
    // used where a value was expected. Two codes, one mistake.
    page: 'the shadowed library name is then used as a value',
    code: 'OS2014',
    wrong: [...STUDY, 'avg = sma(close, 20)', 'plot(avg, "a", aqua)'],
    right: [...STUDY, 'trendLine = sma(close, 20)', 'plot(trendLine, "a", aqua)'],
  },
  {
    page: 'an exit may state a level absolutely or as a distance, not both',
    code: 'OS3010',
    wrong: [...STRATEGY, 'plot(close, "c", aqua)', 'if bar.isLast', '    exit("B", stop = close - 10, loss = 10)'],
    right: [...STRATEGY, 'plot(close, "c", aqua)', 'if bar.isLast', '    exit("B", loss = 10)'],
  },
  {
    page: 'an input declared and never read still reaches the settings dialog',
    code: 'OS8018',
    wrong: [...STUDY, 'n = input(5, "N")', 'plot(close, "c", aqua)'],
    right: [...STUDY, 'n = input(5, "N")', 'plot(sma(close, n), "c", aqua)'],
  },
  {
    page: 'assigned and never read',
    code: 'OS8010',
    wrong: [...STUDY, 'trendLine = sma(close, 20)', 'plot(close, "c", aqua)'],
    right: [...STUDY, 'trendLine = sma(close, 20)', 'plot(trendLine, "c", aqua)'],
  },
  {
    page: 'log is the natural logarithm, and there is no logging call',
    code: 'OS3011',
    wrong: [...STUDY, 'log("entered long")', 'plot(close, "c", aqua)'],
    right: [...STUDY, 'plot(log(close), "c", aqua)'],
  },
  {
    page: 'pos and the order calls need a strategy',
    code: 'OS7001',
    wrong: [...STUDY, 'plot(pos.size, "size", aqua)'],
    right: [...STRATEGY, 'plot(pos.size, "size", aqua)'],
  },
]

let failures = 0
console.log(`Checking the codes reference/pitfalls.md names, against openalgo-script ${version}.`)
console.log('')

// ---------------------------------------------------------------------------
// The page and this file have to be talking about the same codes
// ---------------------------------------------------------------------------
//
// Everything below proves that OS3002 behaves as described. None of it proves
// the page says OS3002. Without this, the page could drift to a code that does
// not exist and every case here would still pass, which is the failure this
// whole file exists to prevent, one level up.

const pageText = readFileSync(join(SKILL, 'reference', 'pitfalls.md'), 'utf8')
const onThePage = new Set(pageText.match(/OS\d{4}/g) ?? [])
const covered = new Set(CASES.map((one) => one.code))

const uncovered = [...onThePage].filter((one) => !covered.has(one)).sort()
const unmentioned = [...covered].filter((one) => !onThePage.has(one)).sort()

if (uncovered.length > 0 || unmentioned.length > 0) {
  failures += uncovered.length + unmentioned.length
  for (const one of uncovered) console.log(`  FAIL  ${one}  named on the page, no case here proves it`)
  for (const one of unmentioned) console.log(`  FAIL  ${one}  proved here, the page never names it`)
  console.log('')
} else {
  console.log(`  Every one of the ${covered.size} codes is both named on the page and proved here.`)
  console.log('')
}

for (const one of CASES) {
  const wrong = codesFor(one.wrong)
  const right = codesFor(one.right)
  const produced = wrong.codes.includes(one.code)
  const clean = right.errors.length === 0 && !right.codes.includes(one.code)

  if (produced && clean) {
    const severity = engine.entryFor(one.code)?.severity ?? '?'
    console.log(`  ok    ${one.code}  [${severity}]  ${one.page}`)
    continue
  }
  failures += 1
  console.log(`  FAIL  ${one.code}  ${one.page}`)
  if (!produced) {
    console.log(`        the wrong spelling did not produce ${one.code}; it produced: ${wrong.codes.join(', ') || 'nothing'}`)
    if (wrong.threw) console.log(`        it threw: ${wrong.threw}`)
  }
  if (!clean) {
    console.log(`        the fix the page offers does not come out clean: ${right.codes.join(', ')}`)
    if (right.threw) console.log(`        it threw: ${right.threw}`)
  }
}

console.log('')
if (failures === 0) {
  console.log(`PITFALLS VERIFIED: ${CASES.length} codes, each refused as written and each fix compiling.`)
  process.exit(0)
}
console.log(`${failures} of ${CASES.length} claims do not match this compiler. Correct the page, not the check.`)
process.exit(1)
