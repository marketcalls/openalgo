import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * Words the terminal does not say to a trader.
 *
 * "Armed" was on the One-Click toggle and on the alert editor's checkbox, and
 * it reads as vocabulary chosen by something that had never placed an order.
 * A toggle only has to say which way it is thrown, and the capitals and the
 * red on One-Click are already what carry the warning; a trader should not
 * have to learn a second word for "on".
 *
 * Nothing pinned the wording, so it was free to come back the next time
 * somebody reached for a synonym. This is what pins it.
 *
 * Scoped to what a trader can read. The engine's own alert state is the string
 * `'armed'` and cannot change, `setArmed` is an identifier, and a comment
 * explaining why the word is gone has to be able to name it. So this looks for
 * the word as it would be written in a sentence: capitalised, or inside a
 * quoted string with spaces around it, and never inside a comment.
 */

const TRADING = [
  join(process.cwd(), 'src', 'components', 'trading'),
  join(process.cwd(), 'src', 'lib', 'trading'),
  join(process.cwd(), 'src', 'pages', 'Trading.tsx'),
]

/** Words banned from anything a trader reads, and what to say instead. */
const BANNED: readonly { word: RegExp; instead: string }[] = [
  { word: /\b(Armed|ARMED|armed)\b/, instead: 'on, active, or start and stop' },
  { word: /\b(Disarmed|DISARMED|disarmed)\b/, instead: 'off, or stopped' },
]

function sources(path: string): string[] {
  if (statSync(path).isFile()) return [path]
  return readdirSync(path, { withFileTypes: true }).flatMap((entry) => {
    const child = join(path, entry.name)
    if (entry.isDirectory()) return sources(child)
    if (!/\.(ts|tsx)$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) return []
    return [child]
  })
}

/**
 * The lines of a file with its comments taken out.
 *
 * Crude on purpose: it drops `//` tails, whole `/* *\/` blocks and JSX `{/* *\/}`
 * comments, and leaves everything else alone. A guard that tried to parse the
 * file properly would be a second compiler, and a false negative here costs a
 * word slipping back, not a broken build.
 */
function withoutComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .split('\n')
    .map((line) => line.replace(/\/\/.*$/, ''))
    .join('\n')
}

/** Every quoted string on the line that reads as prose rather than as a key. */
function prose(line: string): string[] {
  const quoted = line.match(/'[^']*'|"[^"]*"|`[^`]*`/g) ?? []
  // A string with no space in it is an identifier, a class name or an enum
  // value. `'armed'` is the engine's state; `'is armed: a click'` is a sentence.
  return quoted.filter((text) => text.includes(' '))
}

/** JSX text: what is left between a `>` and a `<` on the same line. */
function jsxText(line: string): string[] {
  return (line.match(/>[^<>{}]+</g) ?? []).map((text) => text.slice(1, -1))
}

describe('the words the terminal uses', () => {
  const files = TRADING.flatMap(sources)

  it('reads more than a handful of files, or it is guarding nothing', () => {
    // A guard whose file list silently emptied would pass forever.
    expect(files.length).toBeGreaterThan(20)
  })

  for (const { word, instead } of BANNED) {
    it(`never says ${word.source.replace(/\\b|[()]/g, '').split('|')[0]} to a trader`, () => {
      const found: string[] = []
      for (const file of files) {
        const lines = withoutComments(readFileSync(file, 'utf8')).split('\n')
        lines.forEach((line, index) => {
          const visible = [...prose(line), ...jsxText(line)]
          // Capitals anywhere outside a comment count on their own: the only
          // reason to capitalise it is that it starts a sentence somebody
          // reads. Lowercase counts only inside prose.
          const shouted = /\b(ARMED|Armed)\b/.test(line)
          if (shouted || visible.some((text) => word.test(text))) {
            found.push(`${file.split(/[\\/]/).slice(-2).join('/')}:${index + 1}  ${line.trim()}`)
          }
        })
      }
      expect(found, `Say ${instead} instead:\n${found.join('\n')}`).toEqual([])
    })
  }
})
