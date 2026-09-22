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

import {
  AlertTriangle,
  Check,
  ChevronDown,
  Loader2,
  MoreHorizontal,
  Play,
  Plus,
  TerminalSquare,
  Trash2,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  type CompileResult,
  compileSource,
  deleteScript,
  fileNameFor,
  idForScript,
  kindOf,
  listScripts,
  nameProblem,
  readScript,
  type ScriptKind,
  type StoredScript,
  saveScript,
  starterFor,
} from '@/lib/trading/openscriptFiles'
import { type HighlightedSpan, highlight, SPAN_CLASS } from '@/lib/trading/openscriptHighlight'
import {
  forgetScript,
  noteOpened,
  readLastOpened,
  readRecents,
  writeLastOpened,
} from '@/lib/trading/openscriptSession'
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
 *
 * **Nothing here may wrap, and the gutter is why.** The gutter draws one row
 * per line of source at a fixed line box, because that is what a line number
 * is. A wrapped line occupies two rows of text and one row of gutter, so the
 * two columns are different heights, the same scroll offset moves them by
 * different fractions of their own content, and the numbers slide out of step
 * with the lines they name. It looked like the file was being cut short: the
 * gutter reached 48 while the text was still at 34.
 *
 * So a long line scrolls sideways instead, which is what a code editor does
 * anyway. The text area also needs `wrap="off"`, because a textarea soft wraps
 * on its own attribute and will ignore this.
 */
export const EDITOR_TEXT = 'whitespace-pre px-2 py-2 font-mono text-[12px] tracking-normal'

/**
 * The text with carriage returns taken out.
 *
 * The editor works in the language's own normal form, so that the characters on
 * screen, the offsets the compiler reports and the colours drawn behind them
 * all count the same way. A paste from a file written on a machine that ends
 * lines with a carriage return would otherwise put the compiler one character
 * ahead per line, and both the colouring and every reported position would
 * drift further down the file. The scan is over a few kilobytes and only
 * rewrites when there is something to rewrite.
 */
function withoutCarriageReturns(text: string): string {
  return text.includes('\r') ? text.replace(/\r\n?/g, '\n') : text
}

/**
 * A file name without its extension, which is what a person calls a script.
 *
 * Every script in the directory ends the same way, so the suffix is four
 * characters of nothing repeated on every row of a menu and in a header that is
 * short of room. The full name is still the title attribute, because it is what
 * the server, the chart's indicator id and any error message will say.
 */
function stemOf(file: string): string {
  return file.replace(/\.oscript$/, '')
}

/** Where the caret is, counted the way the diagnostics count: from one. */
function caretAt(area: HTMLTextAreaElement): { line: number; column: number } {
  const upto = area.value.slice(0, area.selectionStart)
  const lines = upto.split('\n')
  return { line: lines.length, column: (lines[lines.length - 1]?.length ?? 0) + 1 }
}

interface Props {
  /**
   * Puts a study on the chart, and says whether there was one to put it on.
   *
   * The terminal recompiles and re-registers before it adds, so a script saved
   * a moment ago is the version that arrives, and it reports its own failures.
   * The one thing it cannot report is having no chart to reach, which is why
   * this answers false rather than nothing: a button that does nothing and says
   * nothing is the failure this panel keeps being caught by.
   */
  onAddToChart: (indicatorId: string) => boolean
  /**
   * Test this strategy over the chart's history and mark what it did.
   *
   * Answers a boolean for the same reason `onAddToChart` does: a button that
   * does nothing and says nothing is the failure this panel keeps being caught
   * by. False means there was no chart to test against.
   */
  onBacktest?: (file: string) => boolean
  /**
   * A script to open as soon as the panel is up, from the braces button on a
   * study's legend row.
   *
   * A request rather than a setting: the panel opens it once and calls
   * `onOpened`, and from then on the trader is driving. Left as state the page
   * held, clicking away to another script and back to this panel would drag you
   * to the one the chart asked for weeks ago.
   */
  openFile?: string | null
  /** Called once `openFile` has been acted on, so the page can clear it. */
  onOpened?: () => void
}

export function ScriptPanel({ onAddToChart, onBacktest, openFile = null, onOpened }: Props) {
  const [scripts, setScripts] = useState<StoredScript[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [source, setSource] = useState('')
  const [saved, setSaved] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<CompileResult | null>(null)
  const [naming, setNaming] = useState(false)
  const [newName, setNewName] = useState('')
  /**
   * Whether the name field has been used yet.
   *
   * Without it the row opens already complaining that the script has no name,
   * which is true and useless: nobody has typed anything. A form that is red
   * before it is touched teaches people to ignore the red.
   */
  const [nameTouched, setNameTouched] = useState(false)
  const [newKind, setNewKind] = useState<ScriptKind>('study')
  /**
   * What each listed script declares itself to be, keyed by name and time.
   *
   * Filled in after the list arrives rather than returned with it: the route
   * that lists files serves text and knows nothing about the language, and
   * teaching it to peek inside for a keyword would put language knowledge in
   * the one place that must never need updating when the language changes.
   */
  const [kinds, setKinds] = useState<Record<string, ScriptKind>>({})
  const [scrolled, setScrolled] = useState({ top: 0, left: 0 })
  const [caret, setCaret] = useState({ line: 1, column: 1 })
  const [spans, setSpans] = useState<HighlightedSpan[]>([])
  /** The scripts opened most recently, newest first, across sessions. */
  const [recents, setRecents] = useState<string[]>(readRecents)
  /**
   * Whether the console drawer is down.
   *
   * Closed by default, because the panel's whole problem was spending its
   * height on things nobody was reading. Nothing is hidden by it: the status
   * bar says how many errors there are in words, and the button that opens
   * this carries the count, so a script that will not run says so whether the
   * drawer is up or down.
   */
  const [consoleOpen, setConsoleOpen] = useState(false)
  const nameRef = useRef<HTMLInputElement>(null)
  /**
   * Whether the naming form was opened from a menu, and so is owed focus.
   *
   * A menu puts focus back on its trigger when it closes, which is right for
   * every item in it except the one that opens a form: there it takes focus
   * straight off the field the form exists for, and the trader types into
   * nothing and watches the panel ignore them. A ref rather than state because
   * it is read inside the close handler on the way past, and re-rendering to
   * record it would be a render for a fact nothing draws.
   */
  const wantsNameFocus = useRef(false)

  const dirty = open !== null && source !== saved
  const nameFault = naming ? nameProblem(newName) : null
  const nameError = nameTouched ? nameFault : null
  const runnable = open !== null && !dirty && result?.ok === true
  const errorCount = result?.diagnostics.filter((one) => one.severity === 'error').length ?? 0
  const warningCount = result?.diagnostics.filter((one) => one.severity === 'warning').length ?? 0
  const noteCount = result?.diagnostics.length ?? 0

  /**
   * What the open script declares itself to be.
   *
   * The compiler's answer while one is open, falling back to what the list was
   * told when it looked. Without the fallback the badge blinks off for the
   * moment between opening a script and its first compile, which reads as the
   * panel losing track of what it is holding.
   */
  const kind: ScriptKind | null =
    result?.kind ??
    (open === null
      ? null
      : (scripts
          ?.filter((script) => script.file === open)
          .map((script) => kinds[`${script.file}@${script.mtime}`])
          .find((one) => one !== undefined) ?? null))

  /**
   * The recents, filtered to scripts that still exist, and the rest after them.
   *
   * Filtered against the server's list rather than trusted, because the stored
   * list is this browser's memory and the directory is the truth: a script
   * deleted from another tab would otherwise sit at the top of the menu
   * offering to open a file that is gone.
   */
  const recentlyOpened = useMemo(
    () => (scripts === null ? [] : recents.filter((file) => scripts.some((s) => s.file === file))),
    [recents, scripts]
  )
  const others = useMemo(
    () => (scripts ?? []).filter((script) => !recentlyOpened.includes(script.file)),
    [scripts, recentlyOpened]
  )

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

  /**
   * Work out what each listed script is, once per script per edit.
   *
   * Keyed by name and modification time, so an edited script is asked again and
   * an untouched one costs nothing. One small fetch each, and a trader has a
   * handful of scripts rather than a directory of them.
   */
  useEffect(() => {
    if (!scripts || scripts.length === 0) return
    const controller = new AbortController()
    void (async () => {
      for (const script of scripts) {
        const key = `${script.file}@${script.mtime}`
        if (kinds[key] !== undefined) continue
        try {
          const found = await kindOf(await readScript(script.file, controller.signal))
          if (controller.signal.aborted || found === null) continue
          setKinds((previous) => ({ ...previous, [key]: found }))
        } catch {
          // A script that cannot be read gets no badge. It is a label, not a
          // feature, and failing to draw one is not worth a message.
        }
      }
    })()
    return () => controller.abort()
  }, [scripts, kinds])

  const openScript = useCallback(async (file: string) => {
    setBusy(true)
    setResult(null)
    try {
      const text = await readScript(file)
      setOpen(file)
      setSource(text)
      setSaved(text)
      // Remembered only once the read succeeded. A name that could not be
      // opened must not become the one the panel returns to next time.
      setRecents(noteOpened(file))
      setResult(await compileSource(file, text))
    } catch (error) {
      setResult({
        ok: false,
        diagnostics: [],
        problem: error instanceof Error ? error.message : String(error),
      })
    } finally {
      setBusy(false)
    }
  }, [])

  /**
   * Honour a script the chart asked for.
   *
   * Once per request, and it clears the request whether the read worked or
   * not: `openScript` puts its own failure in the console, and leaving the
   * request standing would retry it on every render of a panel that is already
   * showing why it could not.
   */
  useEffect(() => {
    if (openFile === null || openFile === undefined) return
    // Not if it is already the one on screen. Re-reading would replace what
    // the trader has typed with the last saved text, and losing an edit to a
    // button that was supposed to show you the file is the worst way to find
    // out this runs twice.
    if (openFile !== open) void openScript(openFile)
    onOpened?.()
  }, [openFile, open, openScript, onOpened])

  /**
   * Reopen whatever was last being edited.
   *
   * The panel is unmounted while another one is up, so without this every
   * glance at the watchlist costs the trader their place. Runs once, and only
   * when nothing else has already claimed the editor: a chart asking to show a
   * study's source wins, because that request is about the thing on screen now
   * rather than about the last time the panel was open.
   *
   * The file is checked against the server's list first. A script deleted from
   * another tab would otherwise be asked for on every load and answer with a
   * failure the trader had no part in causing.
   */
  useEffect(() => {
    if (open !== null || scripts === null || busy) return
    if (openFile !== null && openFile !== undefined) return
    const last = readLastOpened()
    if (last === null) return
    if (!scripts.some((script) => script.file === last)) {
      writeLastOpened(null)
      return
    }
    void openScript(last)
    // `scripts` arriving is the trigger, once. `open` is in the list so the
    // guard above sees the file it just opened rather than a stale null, and
    // that same guard is what keeps this from running a second time.
  }, [scripts, open, busy, openFile, openScript])

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
      setResult({
        ok: false,
        diagnostics: [],
        problem: error instanceof Error ? error.message : String(error),
      })
    } finally {
      setBusy(false)
    }
  }, [open, source, busy, refresh])

  const remove = useCallback(async () => {
    if (open === null || busy) return
    setBusy(true)
    try {
      await deleteScript(open)
      setRecents(forgetScript(open))
      setOpen(null)
      setSource('')
      setSaved('')
      setResult(null)
      await refresh()
    } catch (error) {
      setResult({
        ok: false,
        diagnostics: [],
        problem: error instanceof Error ? error.message : String(error),
      })
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
      const starter = starterFor(newName, newKind)
      await saveScript(file, starter)
      setOpen(file)
      setSource(starter)
      setSaved(starter)
      setRecents(noteOpened(file))
      setResult(await compileSource(file, starter))
      await refresh()
    } catch (error) {
      setResult({
        ok: false,
        diagnostics: [],
        problem: error instanceof Error ? error.message : String(error),
      })
    } finally {
      setBusy(false)
    }
  }, [newName, newKind, refresh])

  const startNaming = useCallback(() => {
    setNewName('')
    setNameTouched(false)
    setNaming(true)
  }, [])

  /** The same, from a menu, which has to hand the field its focus. */
  const startNamingFromMenu = useCallback(() => {
    wantsNameFocus.current = true
    startNaming()
  }, [startNaming])

  /**
   * Takes the focus a closing menu was about to put back on its trigger.
   *
   * Deferred a frame because the form is mounted by the same state change that
   * closes the menu, and on the tick this runs the field may not exist yet.
   */
  const keepNameFocus = useCallback((event: Event) => {
    if (!wantsNameFocus.current) return
    wantsNameFocus.current = false
    event.preventDefault()
    requestAnimationFrame(() => nameRef.current?.focus())
  }, [])

  /**
   * Put the open script on the chart.
   *
   * The one thing it cannot report is having no chart to reach, which is why
   * `onAddToChart` answers a boolean: a button that does nothing and says
   * nothing is the failure this panel keeps being caught by. The console is
   * opened with the complaint, because the drawer is shut by default and a
   * refusal nobody can see is the same as no refusal at all.
   */
  const applyToChart = useCallback(() => {
    if (open === null) return

    // Applying a strategy means testing it over the chart's history and marking
    // what it did, which is the only thing "apply" can honestly mean for a
    // script that trades: the chart tier draws and does not trade, so a
    // strategy is not in the indicator list and adding it there was refused by
    // the engine with OS6006. Handed to the backtest instead of refused.
    if (kind === 'strategy') {
      if (onBacktest?.(open)) return
      setResult((previous) => ({
        ok: previous?.ok ?? false,
        diagnostics: previous?.diagnostics ?? [],
        problem: 'There is no chart open to test this strategy against.',
      }))
      setConsoleOpen(true)
      return
    }

    if (onAddToChart(idForScript(open))) return
    setResult((previous) => ({
      ok: previous?.ok ?? false,
      diagnostics: previous?.diagnostics ?? [],
      problem: 'There is no chart open to add this study to.',
    }))
    setConsoleOpen(true)
  }, [kind, onBacktest, open, onAddToChart])

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
      {/* The header is the whole navigation. It replaced a title row that
          repeated the panel's own name and a list of every script pinned under
          it, which together spent a third of the panel's height on things
          nobody reads while writing: the title says what the rail button
          already said, and the list shows twenty files to choose the one you
          are already in. The name is a menu instead, the scripts you actually
          move between sit at the top of it, and the height goes to the code. */}
      <div className={PANEL_HEADER}>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="flex min-w-0 max-w-[55%] items-center gap-1.5 rounded px-1.5 py-1 text-left transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              title={open ?? 'Choose a script'}
            >
              <span className="truncate text-sm font-medium">
                {open === null ? 'No script' : stemOf(open)}
              </span>
              {kind !== null && (
                <span
                  className={cn(
                    'shrink-0 rounded px-1 py-px text-[9px] font-medium uppercase tracking-wide',
                    kind === 'strategy'
                      ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400'
                      : 'bg-primary/15 text-primary'
                  )}
                >
                  {kind}
                </span>
              )}
              <ChevronDown
                className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                strokeWidth={1.5}
              />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            className="max-h-80 w-64 overflow-y-auto"
            onCloseAutoFocus={keepNameFocus}
          >
            {recentlyOpened.length > 0 && (
              <>
                <DropdownMenuLabel className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  Recent
                </DropdownMenuLabel>
                {recentlyOpened.map((file) => (
                  <DropdownMenuItem
                    key={`recent-${file}`}
                    onSelect={() => void openScript(file)}
                    className={cn('text-xs', file === open && 'text-primary')}
                  >
                    <span className="truncate">{stemOf(file)}</span>
                  </DropdownMenuItem>
                ))}
                {others.length > 0 && <DropdownMenuSeparator />}
              </>
            )}
            {others.map((script) => (
              <DropdownMenuItem
                key={script.file}
                onSelect={() => void openScript(script.file)}
                className="text-xs"
              >
                <span className="truncate">{stemOf(script.file)}</span>
              </DropdownMenuItem>
            ))}
            {scripts !== null && scripts.length === 0 && (
              <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
                No scripts yet.
              </DropdownMenuLabel>
            )}
            {listError !== null && (
              <DropdownMenuLabel className="text-xs font-normal text-destructive">
                {listError}
              </DropdownMenuLabel>
            )}
            <DropdownMenuSeparator />
            <DropdownMenuItem className="text-xs" onSelect={startNamingFromMenu}>
              <Plus className="mr-1.5 h-3.5 w-3.5" strokeWidth={1.5} />
              New script
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Put it on the chart. An icon rather than a labelled button because
            it is the one control pressed over and over while writing, it sits
            beside the name of the thing it will run, and the words cost the
            room the name needs. It still says what it does on hover and to a
            screen reader, which is what a bare glyph owes a reader. */}
        <button
          type="button"
          onClick={applyToChart}
          disabled={!runnable}
          aria-label={open === null ? 'Apply to chart' : `Apply ${stemOf(open)} to the chart`}
          title={
            runnable
              ? 'Apply to chart'
              : 'Save a script that compiles, and it can be applied to the chart.'
          }
          className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40"
        >
          <Play className="h-3.5 w-3.5" strokeWidth={1.5} />
        </button>

        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={store}
            disabled={busy || !dirty}
            className="inline-flex shrink-0 items-center gap-1 rounded-md bg-primary px-2.5 py-1.5 text-[11px] font-medium leading-none text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring active:translate-y-px disabled:pointer-events-none disabled:opacity-40"
          >
            Save
          </button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label="Script actions"
                className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                <MoreHorizontal className="h-4 w-4" strokeWidth={1.5} />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-48" onCloseAutoFocus={keepNameFocus}>
              <DropdownMenuItem className="text-xs" onSelect={startNamingFromMenu}>
                <Plus className="mr-1.5 h-3.5 w-3.5" strokeWidth={1.5} />
                New script
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-xs text-destructive focus:text-destructive"
                disabled={busy || open === null}
                onSelect={() => void remove()}
              >
                <Trash2 className="mr-1.5 h-3.5 w-3.5" strokeWidth={1.5} />
                Delete script
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {naming && (
        <div className="shrink-0 space-y-1.5 border-b px-2 py-2">
          <label className="block text-[11px] text-muted-foreground" htmlFor="new-script-name">
            Name
          </label>
          <input
            ref={nameRef}
            id="new-script-name"
            // Focused on open, so a trader who chose New can simply type. It is
            // the only field in a row that was summoned by a button, so taking
            // focus steals it from nothing.
            // biome-ignore lint/a11y/noAutofocus: see above
            autoFocus
            value={newName}
            onChange={(event) => {
              setNewName(event.target.value)
              setNameTouched(true)
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                setNameTouched(true)
                void create()
              }
              if (event.key === 'Escape') setNaming(false)
            }}
            className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs outline-none placeholder:text-muted-foreground focus-visible:ring-1 focus-visible:ring-ring"
            placeholder="range-breakout"
          />
          {nameError && <p className="text-[11px] text-destructive">{nameError}</p>}

          {/* Which of the two it is, chosen before it is written rather than
              discovered from line two. They are different things: a study
              computes and draws, a strategy does that and also places orders,
              and the starter each one opens with is different because of it. */}
          <fieldset className="space-y-1">
            <legend className="mb-1 text-[11px] text-muted-foreground">Kind</legend>
            <div className="flex gap-1.5">
              {(['study', 'strategy'] as const).map((kind) => (
                <button
                  key={kind}
                  type="button"
                  aria-pressed={newKind === kind}
                  onClick={() => setNewKind(kind)}
                  className={cn(
                    CHIP,
                    'capitalize',
                    newKind === kind && 'border-primary/70 bg-primary/15 text-foreground'
                  )}
                >
                  {kind}
                </button>
              ))}
            </div>
            <p className="text-[10px] leading-snug text-muted-foreground">
              {newKind === 'study'
                ? 'Computes and draws on the chart.'
                : 'Draws, and places orders. Backtesting is not built yet.'}
            </p>
          </fieldset>

          <div className="flex gap-1.5">
            <button
              type="button"
              className={CHIP}
              onClick={() => {
                setNameTouched(true)
                void create()
              }}
              // The real fault, not the one the reader has been shown yet: a
              // button that is enabled and does nothing is worse than one that
              // is disabled with a reason beside it.
              disabled={nameFault !== null || busy}
            >
              Create
            </button>
            <button type="button" className={CHIP} onClick={() => setNaming(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {open === null ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-4 text-center">
          {/* A failure with no script open used to land in a console that only
              renders beside an open one, so a create that was refused closed
              the row and did nothing visible. That is the worst shape a
              failure can take: the trader concludes the button is broken and
              there is nothing anywhere to correct them. */}
          {result?.problem && !result.ok && (
            <pre className="max-h-40 w-full overflow-auto whitespace-pre-wrap rounded border border-destructive/40 bg-destructive/5 px-2 py-2 text-left font-mono text-[11px] leading-[1.45] text-destructive">
              {result.problem}
            </pre>
          )}
          {/* The list used to be the answer to "how do I open one", pinned
              under the header at all times. It is a menu now, so the empty
              state has to say where it went: an instruction that names a
              control the reader can see beats one that assumes they will
              find it. */}
          <p className="max-w-[16rem] text-xs leading-relaxed text-muted-foreground">
            {scripts !== null && scripts.length > 0
              ? 'Open one from the name at the top of this panel, or write a new one.'
              : 'Nothing written yet.'}
          </p>
          <button
            type="button"
            onClick={startNaming}
            disabled={busy}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border px-2.5 py-1.5 text-[11px] font-medium leading-none transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40"
          >
            <Plus className="h-3.5 w-3.5" strokeWidth={1.5} />
            New script
          </button>
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
            {/* This is what clips the coloured layer, and it has to be this
                element rather than the layer itself. A layer that clipped its
                own overflow would only ever hold one viewport of text: the
                content past its box is cut before the transform moves it, so
                scrolling down revealed the cut edge as empty space and the file
                looked truncated. The layer is therefore its full natural
                height and this box is the window onto it. */}
            <div className="relative min-w-0 flex-1 overflow-hidden">
              <pre
                aria-hidden
                className={cn(EDITOR_TEXT, 'pointer-events-none absolute left-0 top-0 min-w-full')}
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
                // A paste can bring carriage returns in, and the editor works
                // in the language's own normal form so the text, the compiler's
                // positions and the colours behind them all count characters
                // the same way. Cheap: it is a scan of a few kilobytes and it
                // only rewrites when there was something to rewrite.
                onChange={(event) => setSource(withoutCarriageReturns(event.target.value))}
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
                // A textarea soft wraps on this attribute and ignores the CSS,
                // so turning it off here is what actually keeps one line of
                // source on one row. See EDITOR_TEXT for why that matters.
                wrap="off"
                aria-label={`Source of ${open}`}
                className={cn(
                  EDITOR_TEXT,
                  'absolute inset-0 h-full w-full resize-none bg-transparent text-transparent caret-foreground outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring'
                )}
                style={{ lineHeight: `${LINE_HEIGHT}px` }}
              />
            </div>
          </div>

          {/* The console, in a drawer. It carries the same parts it always
              did, because a reader scanning compiler output wants the severity
              first, the place second and the words third, and a single string
              can only be one colour. What changed is that it is no longer
              always down: it was taking a third of the panel to say what the
              status bar says in a sentence, on a panel whose whole problem was
              having no room for the code. */}
          {consoleOpen && (
            <div className="max-h-[38%] shrink-0 overflow-auto border-t bg-muted/20">
              {noteCount === 0 && result?.problem === undefined && (
                <p className="px-2 py-3 text-center text-[11px] text-muted-foreground">
                  Nothing to report.
                </p>
              )}
              {noteCount > 0 && (
                <div className="space-y-2 px-2 py-2">
                  {result?.diagnostics.map((one) => {
                    const bad = one.severity === 'error'
                    return (
                      <div
                        key={`${one.code}:${one.line}:${one.column}`}
                        className="font-mono text-[11px] leading-[1.45]"
                      >
                        <div className="flex items-baseline gap-1.5">
                          <span
                            className={cn(
                              'shrink-0 rounded px-1 py-px text-[10px] font-medium',
                              bad
                                ? 'bg-destructive/15 text-destructive'
                                : 'bg-amber-500/15 text-amber-600 dark:text-amber-400'
                            )}
                          >
                            {one.code}
                          </span>
                          <span className="text-muted-foreground">
                            line {one.line}, column {one.column}
                          </span>
                        </div>
                        {/* The offending line, with the span underlined beneath
                            it. The gutter marks which line; this marks where. */}
                        {one.sourceLine !== '' && (
                          <pre className="mt-1 overflow-x-auto whitespace-pre text-foreground">
                            {one.sourceLine}
                            {'\n'}
                            <span className={bad ? 'text-destructive' : 'text-amber-500'}>
                              {' '.repeat(Math.max(0, one.column - 1))}
                              {'^'.repeat(one.length)}
                            </span>
                          </pre>
                        )}
                        <p
                          className={cn(
                            'mt-1',
                            bad ? 'text-destructive' : 'text-amber-600 dark:text-amber-400'
                          )}
                        >
                          {one.message}
                        </p>
                        {one.fix && (
                          <p className="mt-0.5 text-muted-foreground">
                            <span className="font-medium">Fix: </span>
                            {one.fix}
                          </p>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
              {result?.problem && (
                <pre className="whitespace-pre-wrap px-2 py-2 font-mono text-[11px] leading-[1.45] text-destructive">
                  {result.problem}
                </pre>
              )}
            </div>
          )}

          {/* The status bar: one row, always there, never more than one row.
              The console button on the left is the way in to the detail and
              carries the count so a script that will not run says so with the
              drawer shut. The caret sits on the right in the same counting the
              diagnostics use, so "line 7, column 12" there and "7:12" here
              mean the same place. */}
          <div className="flex h-7 shrink-0 items-center gap-2 border-t px-1.5">
            <button
              type="button"
              onClick={() => setConsoleOpen((down) => !down)}
              aria-expanded={consoleOpen}
              aria-label={consoleOpen ? 'Hide the console' : 'Show the console'}
              title={consoleOpen ? 'Hide the console' : 'Show the console'}
              className={cn(
                'inline-flex h-5 shrink-0 items-center gap-1 rounded px-1 text-[10px] leading-none transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
                consoleOpen ? 'bg-accent text-foreground' : 'text-muted-foreground',
                errorCount > 0 && 'text-destructive'
              )}
            >
              <TerminalSquare className="h-3.5 w-3.5" strokeWidth={1.5} />
              {noteCount > 0 && <span className="tabular-nums">{noteCount}</span>}
            </button>
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
                  {errorCount === 1 ? '1 error' : `${errorCount} errors`}, so it will not run yet
                </span>
              ) : result?.ok ? (
                <span className="inline-flex items-center gap-1.5">
                  <Check className="h-3 w-3" strokeWidth={1.5} />
                  {warningCount > 0
                    ? `Ready, with ${warningCount === 1 ? '1 warning' : `${warningCount} warnings`}`
                    : 'Ready'}
                </span>
              ) : (
                'Ready'
              )}
            </span>
            <span className="shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
              Ln {caret.line}, Col {caret.column}
            </span>
          </div>
        </>
      )}
    </PanelShell>
  )
}
