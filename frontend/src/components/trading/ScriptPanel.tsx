/**
 * The OpenScript panel: write a study, save it, put it on the chart.
 *
 * Sits in the right rail beside the watchlist and the objects panel and wears
 * the same clothes: `PanelShell` owns the width and the drag handle,
 * `PANEL_HEADER` lands the header rule on the same line as the pane toolbar's,
 * and every control is a shadcn token so the panel cannot drift from the app
 * around it.
 *
 * Three things make a script editor feel like one rather than like a text box,
 * and all three are here:
 *
 * - **A numbered gutter.** A diagnostic that says line 7 is worth nothing if
 *   counting to 7 is the reader's job. The gutter scrolls with the text and
 *   marks the line the compiler stopped on.
 * - **A console that names the line.** Compiler output sits under the editor
 *   rather than in a toast that has already gone by the time the author looks
 *   up, and each entry carries its code, its position and its fix.
 * - **One action from written to drawn.** A study is added to the chart from
 *   here, so the loop is write, save, see. Hunting the indicator picker for
 *   something written thirty seconds ago is the step that makes people stop
 *   writing studies.
 *
 * **The text area is deliberate, not a placeholder to feel bad about.** The
 * language ships its editor intelligence, highlighting, completion, hover and
 * inline diagnostics, as headless functions in a later release, designed to
 * plug into a real code editor component. Installing one now would mean wiring
 * it twice and carrying a large dependency in between. The affordances that
 * matter today are here: a monospace face, no spell check, a gutter, save on
 * Ctrl+S, and the compiler's own words underneath.
 *
 * **Compiling is the whole feedback loop.** There is no build step between
 * saving a script and the chart running it, so a mistake either appears in this
 * panel or the study is quietly missing from the picker with nothing anywhere
 * to say why. Every save compiles first, and a script that will not compile is
 * still saved: a trader half way through a thought should not lose it because
 * it does not parse yet.
 */

import { AlertTriangle, Check, FileCode2, Loader2, Plus, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  type CompileResult,
  compileSource,
  deleteScript,
  fileNameFor,
  idForScript,
  listScripts,
  nameProblem,
  readScript,
  STARTER_SOURCE,
  type StoredScript,
  saveScript,
} from '@/lib/trading/openscriptFiles'
import { type HighlightedSpan, highlight, SPAN_CLASS } from '@/lib/trading/openscriptHighlight'
import { cn } from '@/lib/utils'
import { PANEL_HEADER, PanelShell } from './panelShell'

/** A small header control, matching the objects panel's own. */
const CHIP =
  'inline-flex items-center gap-1 rounded border border-border px-1.5 py-1 text-[11px] leading-none text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40'

/** The editor's line box. Shared so the gutter and the text cannot drift. */
const LINE_HEIGHT = 18

/**
 * Every metric the coloured layer and the text area must agree on.
 *
 * One string rather than two copies: a font, a size, a padding or a wrap rule
 * that differs between them puts the caret a character away from the letter it
 * belongs to, and the drift grows across the line.
 */
const EDITOR_TEXT =
  'whitespace-pre-wrap break-words px-2 py-2 font-mono text-[12px] tracking-normal'

/** Where the caret is, counted the way the diagnostics count: from one. */
function caretAt(area: HTMLTextAreaElement): { line: number; column: number } {
  const upto = area.value.slice(0, area.selectionStart)
  const lines = upto.split('\n')
  return { line: lines.length, column: (lines[lines.length - 1]?.length ?? 0) + 1 }
}

interface Props {
  /**
   * Puts a study on the focused chart.
   *
   * The terminal recompiles and re-registers before it adds, so a script saved
   * a moment ago is the version that arrives.
   */
  onAddToChart: (indicatorId: string) => void
}

export function ScriptPanel({ onAddToChart }: Props) {
  const [scripts, setScripts] = useState<StoredScript[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [source, setSource] = useState('')
  const [saved, setSaved] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<CompileResult | null>(null)
  const [naming, setNaming] = useState(false)
  const [newName, setNewName] = useState('')
  const [scrolled, setScrolled] = useState({ top: 0, left: 0 })
  const [caret, setCaret] = useState({ line: 1, column: 1 })
  const [spans, setSpans] = useState<HighlightedSpan[]>([])

  const dirty = open !== null && source !== saved
  const nameError = naming ? nameProblem(newName) : null
  const runnable = open !== null && !dirty && result?.ok === true

  /** One entry per line, so the gutter is exactly as tall as the text. */
  const lines = useMemo(() => source.split('\n').length, [source])

  /**
   * Recolour whenever the text changes.
   *
   * The lexer arrives through a dynamic import, so a fast typist can have two
   * of these in flight at once and the slower one can land last. `stale` is
   * what stops an older colouring painting over a newer one, which shows up as
   * colours that lag a character behind the text.
   */
  useEffect(() => {
    let stale = false
    void highlight(source).then((next) => {
      if (!stale) setSpans(next)
    })
    return () => {
      stale = true
    }
  }, [source])

  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const found = await listScripts(signal)
      setScripts(found)
      setListError(null)
    } catch (error) {
      if (signal?.aborted) return
      setScripts([])
      setListError(error instanceof Error ? error.message : String(error))
    }
  }, [])

  // The abort matters: a panel closed while the list is in flight would
  // otherwise set state on a component that is gone.
  useEffect(() => {
    const controller = new AbortController()
    void refresh(controller.signal)
    return () => controller.abort()
  }, [refresh])

  const openScript = useCallback(async (file: string) => {
    setBusy(true)
    setResult(null)
    try {
      const text = await readScript(file)
      setOpen(file)
      setSource(text)
      setSaved(text)
      setResult(await compileSource(file, text))
    } catch (error) {
      setResult({ ok: false, problem: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy(false)
    }
  }, [])

  const store = useCallback(async () => {
    if (open === null || busy) return
    setBusy(true)
    try {
      // Compiled before the write so the panel can say what is wrong, and
      // written whatever it says so a half finished thought is never lost.
      const compiled = await compileSource(open, source)
      setResult(compiled)
      await saveScript(open, source)
      setSaved(source)
      await refresh()
    } catch (error) {
      setResult({ ok: false, problem: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy(false)
    }
  }, [open, source, busy, refresh])

  const remove = useCallback(async () => {
    if (open === null || busy) return
    setBusy(true)
    try {
      await deleteScript(open)
      setOpen(null)
      setSource('')
      setSaved('')
      setResult(null)
      await refresh()
    } catch (error) {
      setResult({ ok: false, problem: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy(false)
    }
  }, [open, busy, refresh])

  const create = useCallback(async () => {
    if (nameProblem(newName) !== null) return
    const file = fileNameFor(newName)
    setNaming(false)
    setNewName('')
    setBusy(true)
    try {
      await saveScript(file, STARTER_SOURCE)
      setOpen(file)
      setSource(STARTER_SOURCE)
      setSaved(STARTER_SOURCE)
      setResult(await compileSource(file, STARTER_SOURCE))
      await refresh()
    } catch (error) {
      setResult({ ok: false, problem: error instanceof Error ? error.message : String(error) })
    } finally {
      setBusy(false)
    }
  }, [newName, refresh])

  // Ctrl+S is what anyone editing text reaches for, and without it the browser
  // opens its own save dialog over the panel.
  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        void store()
      }
    },
    [store]
  )

  return (
    <PanelShell
      id="trading-scripts-panel"
      label="Scripts"
      storageKey="trading.panel.scripts.width"
      defaultWidth={480}
      minWidth={320}
      // Wider than the shared ceiling, and the one panel that earns it: while a
      // trader is writing a study the panel is the thing being worked on and
      // the chart beside it is the reference. Code also wraps, and a wrapped
      // line in a numbered gutter is where a reader loses their place.
      maxWidth={760}
    >
      <div className={PANEL_HEADER}>
        <FileCode2 className="h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.5} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-medium">Scripts</div>
          <div className="truncate text-[10px] text-muted-foreground">
            {open ?? 'OpenScript studies'}
          </div>
        </div>
        <button type="button" className={CHIP} onClick={() => setNaming(true)} disabled={busy}>
          <Plus className="h-3 w-3" strokeWidth={1.5} />
          New
        </button>
        <button type="button" className={CHIP} onClick={remove} disabled={busy || open === null}>
          <Trash2 className="h-3 w-3" strokeWidth={1.5} />
          Delete
        </button>
      </div>

      {naming && (
        <div className="shrink-0 space-y-1.5 border-b px-2 py-2">
          <label className="block text-[11px] text-muted-foreground" htmlFor="new-script-name">
            Name
          </label>
          <input
            id="new-script-name"
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void create()
              if (event.key === 'Escape') setNaming(false)
            }}
            className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs outline-none placeholder:text-muted-foreground focus-visible:ring-1 focus-visible:ring-ring"
            placeholder="range-breakout"
          />
          {nameError && <p className="text-[11px] text-destructive">{nameError}</p>}
          <div className="flex gap-1.5">
            <button type="button" className={CHIP} onClick={create} disabled={nameError !== null}>
              Create
            </button>
            <button type="button" className={CHIP} onClick={() => setNaming(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* The list. Capped so the editor always has room: a trader with twenty
          scripts should still see the one they are writing. */}
      <div className="max-h-[26%] shrink-0 overflow-y-auto border-b">
        {scripts === null && (
          // Shaped like the rows it will become, so the panel does not jump
          // when they arrive.
          <div className="space-y-1 p-2" aria-hidden>
            <div className="h-6 animate-pulse rounded bg-muted" />
            <div className="h-6 w-2/3 animate-pulse rounded bg-muted" />
          </div>
        )}
        {listError && <p className="px-2 py-4 text-center text-xs text-destructive">{listError}</p>}
        {scripts !== null && !listError && scripts.length === 0 && (
          <p className="px-3 py-6 text-center text-xs text-muted-foreground">
            No scripts yet. Choose New to write one.
          </p>
        )}
        {scripts?.map((script) => (
          <button
            key={script.file}
            type="button"
            onClick={() => openScript(script.file)}
            className={cn(
              'flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring active:translate-y-px',
              open === script.file && 'bg-accent text-foreground'
            )}
          >
            <span className="min-w-0 flex-1 truncate">{script.file}</span>
            <span className="shrink-0 text-[10px] text-muted-foreground">
              {Math.max(1, Math.round(script.bytes / 1024))} kB
            </span>
          </button>
        ))}
      </div>

      {open === null ? (
        <div className="flex flex-1 items-center justify-center px-6 text-center text-xs text-muted-foreground">
          Choose a script to edit it, or write a new one.
        </div>
      ) : (
        <>
          {/* Gutter, colours and text share one scroll position and one line
              box. The gutter is not focusable and carries no text a reader
              needs, so it is hidden from assistive technology: the diagnostics
              below already say which line they mean. */}
          <div className="relative flex min-h-0 flex-1 overflow-hidden">
            <div
              aria-hidden
              className="shrink-0 select-none overflow-hidden border-r bg-muted/30 py-2 pl-2 pr-1.5 text-right font-mono text-[12px] text-muted-foreground"
              style={{ lineHeight: `${LINE_HEIGHT}px` }}
            >
              <div style={{ transform: `translateY(${-scrolled.top}px)` }}>
                {Array.from({ length: lines }, (_, index) => (
                  <div
                    key={index}
                    className={cn(
                      result?.line === index + 1 && !result.ok && 'font-medium text-destructive'
                    )}
                  >
                    {index + 1}
                  </div>
                ))}
              </div>
            </div>

            {/* The colours sit behind a text area whose own text is
                transparent, so the caret, the selection and every native
                editing behaviour stay exactly where the browser puts them. The
                two layers share a font, a line box and padding to the pixel,
                because one character of drift is a caret that no longer sits
                on its letter. */}
            <div className="relative min-w-0 flex-1">
              <pre
                aria-hidden
                className={cn(EDITOR_TEXT, 'pointer-events-none absolute inset-0 overflow-hidden')}
                style={{
                  lineHeight: `${LINE_HEIGHT}px`,
                  transform: `translate(${-scrolled.left}px, ${-scrolled.top}px)`,
                }}
              >
                {spans.map((span, index) => (
                  // The index is the identity here: spans are a positional
                  // rendering of one string, never reordered and never keyed
                  // across renders.
                  <span key={index} className={SPAN_CLASS[span.kind]}>
                    {span.text}
                  </span>
                ))}
              </pre>
              <textarea
                value={source}
                onChange={(event) => setSource(event.target.value)}
                onKeyDown={onKeyDown}
                onSelect={(event) => setCaret(caretAt(event.currentTarget))}
                onScroll={(event) =>
                  setScrolled({
                    top: event.currentTarget.scrollTop,
                    left: event.currentTarget.scrollLeft,
                  })
                }
                spellCheck={false}
                autoComplete="off"
                autoCorrect="off"
                autoCapitalize="off"
                aria-label={`Source of ${open}`}
                className={cn(
                  EDITOR_TEXT,
                  'absolute inset-0 h-full w-full resize-none bg-transparent text-transparent caret-foreground outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring'
                )}
                style={{ lineHeight: `${LINE_HEIGHT}px` }}
              />
            </div>
          </div>

          <div className="shrink-0 border-t">
            {result?.problem && (
              <pre
                className={cn(
                  'max-h-32 overflow-auto whitespace-pre-wrap px-2 py-2 font-mono text-[11px] leading-[1.45]',
                  result.ok ? 'text-muted-foreground' : 'text-destructive'
                )}
              >
                {result.problem}
              </pre>
            )}
            <div className="flex items-center gap-1.5 px-2 py-1.5">
              {/* Where the caret is, in the same counting the diagnostics use,
                  so "line 7, column 12" in the console and the readout here
                  mean the same place. */}
              <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
                {caret.line}:{caret.column}
              </span>
              <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
                {busy ? (
                  <span className="inline-flex items-center gap-1.5">
                    <Loader2 className="h-3 w-3 animate-spin" strokeWidth={1.5} />
                    Working
                  </span>
                ) : dirty ? (
                  'Unsaved changes'
                ) : result?.ok === false ? (
                  <span className="inline-flex items-center gap-1.5 text-destructive">
                    <AlertTriangle className="h-3 w-3" strokeWidth={1.5} />
                    Saved, and it will not run yet
                  </span>
                ) : result?.ok ? (
                  <span className="inline-flex items-center gap-1.5">
                    <Check className="h-3 w-3" strokeWidth={1.5} />
                    Ready to add
                  </span>
                ) : (
                  'Ready'
                )}
              </span>
              <button
                type="button"
                onClick={() => open && onAddToChart(idForScript(open))}
                disabled={!runnable}
                title={
                  runnable
                    ? undefined
                    : 'Save a script that compiles, and it can be added to the chart.'
                }
                className={CHIP}
              >
                Add to chart
              </button>
              <button
                type="button"
                onClick={store}
                disabled={busy || !dirty}
                className="inline-flex shrink-0 items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-[11px] font-medium leading-none text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring active:translate-y-px disabled:pointer-events-none disabled:opacity-40"
              >
                Save
              </button>
            </div>
          </div>
        </>
      )}
    </PanelShell>
  )
}
