#!/usr/bin/env node
/**
 * Run a draft on real bars and say what it drew, before it is installed.
 *
 *   node .claude/skills/openscript/run.mjs <draft.oscript> <bars.json> [--interval 5m]
 *        [--symbol RELIANCE] [--exchange NSE] [--timezone Asia/Kolkata]
 *        [--session 09:15-15:30 | --session none]
 *
 * `bars.json` is what OpenAlgo's `/api/v1/history` answers: the whole reply or
 * its `data` array, each bar with `timestamp` in seconds. Fetch it from your own
 * server with your own key, for the instrument and interval the chart will show.
 *
 * `validate.mjs` proves the text compiles. It runs no bar, so it cannot see a
 * line that is absent on every bar, a label that never fires, a read whose
 * candles start at the wrong minute, or a level that stretches the price scale.
 * This runs the engine `/trading` ships on the bars given and prints, for each
 * plot, the first bar with a value and the last value, and every marker with
 * its bar. Compare them with what the study is meant to draw.
 *
 * It serves no bars beyond the ones given. A read of another instrument, or of
 * an interval that is not a whole multiple of `--interval`, is refused at load
 * here (OS6006, OS6015, OS6002) and draws on a chart, which fetches those bars.
 */
import { existsSync, readFileSync } from 'node:fs'
import { basename, join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const SKILL = import.meta.dirname
const REPO = resolve(SKILL, '..', '..', '..')
const COMPILER = join(REPO, 'frontend', 'node_modules', 'openalgo-script')
const ENTRY = join(COMPILER, 'dist', 'core', 'index.js')

const args = process.argv.slice(2)
const flag = (name, fallback) => {
  const at = args.indexOf(`--${name}`)
  return at === -1 ? fallback : args[at + 1]
}
const [draftPath, barsPath] = args.filter((one, i) => !one.startsWith('--') && !args[i - 1]?.startsWith('--'))
if (!draftPath || !barsPath) {
  console.error('usage: node run.mjs <draft.oscript> <bars.json> [--interval 5m] [--timezone Asia/Kolkata] [--session 09:15-15:30]')
  process.exit(2)
}
if (!existsSync(ENTRY)) {
  console.error('openalgo-script is not installed under frontend/node_modules. Run npm install in frontend first.')
  process.exit(2)
}
const engine = await import(pathToFileURL(ENTRY).href)

const timezone = flag('timezone', 'Asia/Kolkata')
const session = flag('session', '09:15-15:30')
const instrument = {
  symbol: flag('symbol', 'SYMBOL'),
  exchange: flag('exchange', 'NSE'),
  interval: flag('interval', '5m'),
  timezone,
  ...(session === 'none'
    ? {}
    : { session: { start: session.split('-')[0], end: session.split('-')[1], days: [1, 2, 3, 4, 5] } }),
}

// The same five calls the editor makes, so this is the program the chart runs.
const source = engine.normaliseSource(readFileSync(draftPath, 'utf8'))
const handle = engine.sourceFile(basename(draftPath), source)
const bag = new engine.DiagnosticBag()
const emitted = engine.emit(
  handle,
  engine.check(handle, engine.parseTokens(handle, engine.lex(handle, bag), bag), bag),
  bag,
  {}
)
const errors = bag.ordered().filter((one) => one.severity === 'error')
if (errors.length > 0) {
  for (const one of errors) console.log(`${one.code}  ${one.message}`)
  console.log('Does not compile. Run validate.mjs for the lines and the fixes.')
  process.exit(1)
}

const raw = JSON.parse(readFileSync(barsPath, 'utf8'))
const rows = Array.isArray(raw) ? raw : (raw.data ?? [])
const bars = rows.map((b) => ({
  time: b.timestamp !== undefined ? b.timestamp * 1000 : b.time < 1e12 ? b.time * 1000 : b.time,
  open: b.open,
  high: b.high,
  low: b.low,
  close: b.close,
  volume: b.volume ?? 0,
}))
if (bars.length === 0) {
  console.log(`No bars in ${barsPath}.`)
  process.exit(1)
}

const loaded = engine.loadText(engine.canonicalise(emitted.program), { host: { instrument } })
if (!loaded.ok) {
  console.log(`Refused at load: ${loaded.diagnostic.code}  ${loaded.diagnostic.message}`)
  process.exit(1)
}
const result = loaded.engine.run(bars, bars.map(() => ({ isConfirmed: true })))

const stamp = new Intl.DateTimeFormat('en-GB', {
  timeZone: timezone,
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})
const at = (bar) => stamp.format(new Date(bars[bar].time))
const shown = (value) => (typeof value === 'number' ? String(Math.round(value * 100) / 100) : 'absent')

console.log(`${bars.length} bars, ${at(0)} to ${at(bars.length - 1)}, ${instrument.interval}, ${timezone}`)
const outputs = emitted.program.outputs
for (const plot of outputs.plots) {
  const column = loaded.engine.column(plot.channel)
  const first = column.findIndex((one) => typeof one === 'number')
  const where = first === -1 ? 'absent on every bar' : `first value at ${at(first)} (bar ${first})`
  console.log(`plot   "${plot.title}": ${where}, last ${shown(column.at(-1))}`)
}
for (const marker of outputs.markers) {
  const column = loaded.engine.column(marker.channel)
  const fired = column.flatMap((one, bar) => (typeof one === 'string' ? [bar] : []))
  console.log(`marker ${marker.position}: ${fired.length === 0 ? 'never fired' : `${fired.length} time(s)`}`)
  for (const bar of fired) console.log(`         ${at(bar)}  close ${bars[bar].close}  ${column[bar]}`)
}
if (result.diagnostic) {
  console.log(`Stopped: ${result.diagnostic.code}  ${result.diagnostic.message}`)
  process.exit(1)
}
