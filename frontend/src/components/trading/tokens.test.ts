import { readdirSync, readFileSync } from 'node:fs'
import { join, sep } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * `hsl(var(--x))` is not a colour in this app, and the failure is silent.
 *
 * Two token systems ship side by side: an early `@layer base` block defining
 * HSL channel triplets, and a later unlayered `:root` / `.dark` pair redefining
 * the same names as complete `oklch(...)` colours. The later block wins, so
 * `hsl(var(--primary))` expands to `hsl(oklch(...))`, which is invalid, and the
 * browser drops the whole declaration. Nothing errors. The element simply never
 * paints what you wrote.
 *
 * This has now cost the terminal twice: once in TickBox, whose header comment
 * is the long-form account, and once in WatchlistPanel, where a charted-row
 * marker and a drag drop indicator were both written, reviewed, unit-tested and
 * shipped without ever appearing on screen. A test asserting the class string
 * cannot catch it, because in jsdom there is no Tailwind and no cascade.
 *
 * Tailwind v4's `@theme` maps `--color-primary` to whichever system is live, so
 * `var(--color-primary)` and the plain `bg-primary` utilities are correct under
 * both. Use those.
 */
const SRC_DIR = join(process.cwd(), 'src')

/**
 * Offenders that predate this guard.
 *
 * Listed rather than fixed here because each sits on a surface this change does
 * not touch, and the visible symptom differs per call site. Recorded so the
 * count cannot grow: a new one fails this test, and removing one of these
 * fails it too, which is what forces the list down rather than letting it rot.
 */
const KNOWN = new Set([
  'components/flow/nodes/BaseNode.tsx',
  'components/ui/sidebar.tsx',
  'pages/flow/FlowEditor.tsx',
])

/** The comments in TickBox and WatchlistPanel exist to explain the ban. */
const PROSE = /^\s*(\*|\/\/)/

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return /\.tsx?$/.test(entry.name) && !entry.name.includes('.test.') ? [path] : []
  })
}

describe('theme tokens in the charting terminal', () => {
  it('never wraps a raw token in hsl(), which silently drops the declaration', () => {
    const offenders: string[] = []

    for (const path of sourceFiles(SRC_DIR)) {
      const rel = path
        .slice(SRC_DIR.length + 1)
        .split(sep)
        .join('/')
      if (KNOWN.has(rel)) continue
      readFileSync(path, 'utf8')
        .split('\n')
        .forEach((line, index) => {
          if (PROSE.test(line)) return
          if (line.includes('hsl(var(')) offenders.push(`${rel}:${index + 1}`)
        })
    }

    expect(offenders).toEqual([])
  })

  it('keeps the pre-existing offender list honest', () => {
    // If one of these is cleaned up, this fails and the entry comes out. If a
    // path is renamed away, it fails too rather than silently exempting nothing.
    const stillOffending = [...KNOWN].filter((rel) =>
      readFileSync(join(SRC_DIR, rel), 'utf8')
        .split('\n')
        .some((line) => !PROSE.test(line) && line.includes('hsl(var('))
    )
    expect(stillOffending.sort()).toEqual([...KNOWN].sort())
  })
})
