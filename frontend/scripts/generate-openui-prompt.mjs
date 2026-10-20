/**
 * Write the OpenUI Lang system prompt the agent's chat surface injects.
 *
 * Run from `frontend/`:
 *
 *     node scripts/generate-openui-prompt.mjs
 *
 * The prompt is generated from the library object the browser renders with, in
 * `src/lib/agent/openuiLibrary.ts`, so it cannot describe a component the
 * renderer does not have. It is committed rather than built on demand because
 * the backend reads it: a production server has no Node.js, and a plain
 * `git pull` has to be enough to upgrade the UI.
 *
 * `openuiLibrary.test.ts` regenerates and compares, so an `@openuidev` upgrade
 * that changes the prompt fails CI here instead of silently sending the model
 * a description of a library it is no longer being given.
 *
 * The module is TypeScript and this script is not. Node 24 strips the types on
 * import, which is what lets one definition serve the browser, the test and
 * this script without a build step or a second copy of the component list.
 */

import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  AGENT_UI_COMPONENTS,
  AGENT_UI_PROMPT_MAX_CHARS,
  AGENT_UI_PROMPT_PATH,
  buildAgentUiPrompt,
  missingAgentUiComponents,
  renderAgentUiPromptFile,
} from '../src/lib/agent/openuiLibrary.ts'

const scriptDir = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(scriptDir, '..', '..')
const target = join(repoRoot, AGENT_UI_PROMPT_PATH)

const missing = missingAgentUiComponents()
if (missing.length > 0) {
  console.error(`Components missing from the installed package: ${missing.join(', ')}`)
  process.exit(1)
}

const prompt = buildAgentUiPrompt()
const undefinedCount = (prompt.match(/undefined/g) || []).length
if (undefinedCount > 0) {
  // The failure mode this guards is silent: a wrong generation call produces a
  // plausible prompt in which every component name is the literal `undefined`.
  console.error(`Generation produced ${undefinedCount} literal "undefined" component names.`)
  process.exit(1)
}

const contents = renderAgentUiPromptFile()
await mkdir(dirname(target), { recursive: true })
await writeFile(target, contents, 'utf8')

const fits = contents.length <= AGENT_UI_PROMPT_MAX_CHARS
console.log(`Wrote ${AGENT_UI_PROMPT_PATH}`)
console.log(`  components: ${AGENT_UI_COMPONENTS.length}`)
console.log(`  prompt:     ${prompt.length} chars`)
console.log(`  file:       ${contents.length} chars`)
console.log(`  budget:     ${AGENT_UI_PROMPT_MAX_CHARS} chars (${fits ? 'fits' : 'OVER'})`)
if (!fits) process.exit(1)
