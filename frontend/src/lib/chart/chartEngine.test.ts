import { readdirSync, readFileSync } from 'node:fs'
import { join, sep } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * One charting engine: openalgo-charts.
 *
 * Every chart in the app draws with the engine /trading uses, so one theme
 * bridge (`buildChartTheme`) gives every chart the same light, dark and
 * analyzer looks, and one engine upgrade reaches every chart at once.
 * lightweight-charts was the second library that broke that: the scalper,
 * the straddle, IV, P&L and health charts each carried a palette of their own
 * and never took the analyzer look. It was removed once every page had moved.
 *
 * Both halves are pinned. An import would fail the build anyway once the
 * package is gone, but only after someone had added the package back to make
 * it compile, and that is the step this test exists to stop.
 */
const SRC_DIR = join(process.cwd(), 'src')
const REMOVED = 'lightweight-charts'

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return /\.(ts|tsx)$/.test(entry.name) ? [path] : []
  })
}

describe('chart engine', () => {
  it('is not a dependency', () => {
    const pkg = JSON.parse(readFileSync(join(process.cwd(), 'package.json'), 'utf8'))
    expect(Object.keys({ ...pkg.dependencies, ...pkg.devDependencies })).not.toContain(REMOVED)
  })

  it('is imported nowhere in the app', () => {
    // A static import, a re-export or a dynamic import of the package.
    const pattern = new RegExp(`(from|import)\\s*\\(?\\s*['"]${REMOVED}['"]`)
    const offenders = sourceFiles(SRC_DIR)
      .filter((file) => pattern.test(readFileSync(file, 'utf8')))
      .map((file) =>
        file
          .slice(SRC_DIR.length + 1)
          .split(sep)
          .join('/')
      )
    expect(offenders).toEqual([])
  })
})
