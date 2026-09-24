/**
 * A code block in the conversation.
 *
 * The reference is ChatGPT, informed by ragz: syntax highlighting, a language
 * label, one copy button, and nothing else. Three decisions carry the file.
 *
 * **No line-number gutter.** Numbers earn their place in an editor, where they
 * are how a person says "line 42" to a colleague or a traceback. In a chat
 * answer nobody cites a line, the block is usually copied whole, and the gutter
 * competes with the code for the eye. The platform's own `PythonEditor` keeps
 * its numbers, because `/python` is a real editor and that is the right call
 * there; this is not that.
 *
 * **No height cap.** The block renders every line and the conversation scrolls,
 * which is what a reader expects. Capping the editor at a fixed number of rows
 * hid the rest of a longer script behind an inner scroll region nobody found:
 * the header said "37 lines" while the body stopped at 25, so the code looked
 * truncated rather than scrollable. A block that cannot be read whole cannot be
 * trusted whole.
 *
 * **Not CodeMirror.** Mounting an editor per block means an editor instance per
 * message, each with its own state, extensions and DOM, in a thread that only
 * grows. A highlighter renders once to static markup. The chat needs reading,
 * not editing, and the cheaper thing is also the better-behaved one.
 *
 * Only the languages the agent actually emits are registered. An unregistered
 * language falls through to plain monospace rather than being highlighted as
 * something it is not, which reads worse than no highlighting at all.
 */

import { Check, Copy } from 'lucide-react'
import { type ReactNode, useCallback, useMemo, useState } from 'react'
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash'
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript'
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json'
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python'
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript'
import oneDark from 'react-syntax-highlighter/dist/esm/styles/prism/one-dark'
import oneLight from 'react-syntax-highlighter/dist/esm/styles/prism/one-light'
import { Button } from '@/components/ui/button'
import { useThemeStore } from '@/stores/themeStore'

SyntaxHighlighter.registerLanguage('python', python)
SyntaxHighlighter.registerLanguage('json', json)
SyntaxHighlighter.registerLanguage('bash', bash)
SyntaxHighlighter.registerLanguage('javascript', javascript)
SyntaxHighlighter.registerLanguage('typescript', typescript)

/**
 * Fence info strings mapped onto a registered Prism language.
 *
 * The key is what a model writes after the opening backticks; the value is what
 * Prism was registered under. Anything absent renders unhighlighted.
 */
const LANGUAGE_ALIASES: Readonly<Record<string, string>> = {
  python: 'python',
  py: 'python',
  json: 'json',
  jsonc: 'json',
  json5: 'json',
  bash: 'bash',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  console: 'bash',
  javascript: 'javascript',
  js: 'javascript',
  typescript: 'typescript',
  ts: 'typescript',
}

/** The Prism language for a fence, or null to render plain monospace. */
function prismLanguage(raw: string | null | undefined): string | null {
  const key = (raw ?? '').trim().toLowerCase()
  return LANGUAGE_ALIASES[key] ?? null
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)

  const copy = useCallback(() => {
    const done = () => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    }
    // `navigator.clipboard` is missing on an insecure origin, which a
    // self-hosted install reached over plain http on a LAN address is.
    if (navigator.clipboard?.writeText) {
      navigator.clipboard
        .writeText(text)
        .then(done)
        .catch(() => undefined)
      return
    }
    const area = document.createElement('textarea')
    area.value = text
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    try {
      document.execCommand('copy')
      done()
    } catch {
      // Copying is a convenience. A browser that refuses it is not an error
      // worth interrupting the answer for.
    } finally {
      document.body.removeChild(area)
    }
  }, [text])

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={copy}
      aria-label={label}
      className="h-6 gap-1.5 px-2 text-[11px] text-muted-foreground hover:text-foreground"
    >
      {copied ? (
        <Check className="h-3 w-3" aria-hidden />
      ) : (
        <Copy className="h-3 w-3" aria-hidden />
      )}
      {copied ? 'Copied' : 'Copy'}
    </Button>
  )
}

export interface CodeArtifactProps {
  /** The block's contents, without the fences. */
  code: string
  /** The fence's info string, or null for a fence that named no language. */
  language: string | null
  /**
   * True while the fence is still open, mid-stream. Highlighting is skipped
   * until it closes, so a growing block is not re-tokenised on every token.
   */
  streaming?: boolean
}

/**
 * Render one fenced block.
 *
 * Args:
 *   code: The block's contents.
 *   language: The fence's info string.
 *   streaming: Whether the fence is still open.
 */
export function CodeArtifact({ code, language, streaming = false }: CodeArtifactProps) {
  const { mode, appMode } = useThemeStore()
  // Analyzer mode is always the dark purple theme, so it reads as dark here
  // regardless of the light and dark setting. This matches PythonEditor.
  const isDark = mode === 'dark' || appMode === 'analyzer'
  const prism = prismLanguage(language)
  const label = language?.trim() || 'text'

  // The highlighter owns the border and the rounding through the shell below,
  // so its own container styling is stripped rather than fought with.
  const highlighterStyle = useMemo(
    () => ({
      margin: 0,
      padding: '0.75rem',
      background: 'transparent',
      fontSize: '13px',
      lineHeight: '22px',
    }),
    []
  )

  // The theme paints a background on the inner <code> as well as on the <pre>,
  // and that <code> is `display: inline`. An inline background is painted once
  // per line box and ends at the last character of the line, so the block came
  // out as one ragged rectangle per line, reading as though every line were
  // selected. Clearing it lets the card behind show through as one flat panel,
  // which is what stripping the <pre> background above was already trying to do.
  const codeTagProps = useMemo(() => ({ style: { background: 'transparent' } }), [])

  let body: ReactNode
  if (streaming || prism === null) {
    // Plain monospace while the fence is open, and for a language Prism was not
    // registered for. `whitespace-pre` with a scrolling parent keeps a long line
    // on one line, matching the highlighted branch, so a block does not reflow
    // the moment its fence closes.
    body = (
      <pre className="overflow-x-auto p-3 font-mono text-[13px] leading-[22px] whitespace-pre text-foreground">
        {code}
      </pre>
    )
  } else {
    body = (
      <SyntaxHighlighter
        language={prism}
        style={isDark ? oneDark : oneLight}
        customStyle={highlighterStyle}
        codeTagProps={codeTagProps}
        // The gutter is deliberately absent. See the module docstring.
        showLineNumbers={false}
        wrapLines={false}
        PreTag="pre"
      >
        {code}
      </SyntaxHighlighter>
    )
  }

  return (
    <div className="my-3 overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex items-center gap-2 border-b border-border bg-muted/50 px-3 py-1.5">
        <span className="font-mono text-[11px] font-medium text-foreground">{label}</span>
        {streaming && <span className="text-[11px] text-muted-foreground">writing</span>}
        <div className="ml-auto">
          <CopyButton text={code} label={`Copy the ${label} block`} />
        </div>
      </div>
      {/* The one scrolling axis is horizontal. Vertically the block renders in
          full and the conversation scrolls, so nothing is hidden inside it. */}
      <div className="overflow-x-auto">{body}</div>
    </div>
  )
}
