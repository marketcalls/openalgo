/**
 * Writing in the Scripts panel: the Tab key, and what happens to an edit that
 * has not been saved.
 *
 * Tab used to leave the editor, which in a language whose blocks are their
 * indentation is the one key an author cannot do without. And an unsaved edit
 * was dropped without a word whenever the trader opened another script or
 * closed the panel. Both are tested through the panel itself, with a real
 * compiler and a real highlighter behind it and only the server faked.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { forgetDraftsInPage } from '@/lib/trading/openscriptDrafts'
import { starterFor } from '@/lib/trading/openscriptFiles'
import { act, render, screen, userEvent, waitFor } from '@/test/test-utils'
import { KIND_HINT, ScriptPanel } from './ScriptPanel'

/** The server's copy of every script, which the faked routes read and write. */
const server = vi.hoisted(() => ({ files: new Map<string, string>() }))

vi.mock('@/lib/trading/openscriptFiles', async (importOriginal) => {
  const real = await importOriginal<typeof import('@/lib/trading/openscriptFiles')>()
  return {
    ...real,
    listScripts: vi.fn(async () =>
      [...server.files.keys()].map((file) => ({ file, mtime: 1, bytes: 1, program: true }))
    ),
    readScript: vi.fn(async (file: string) => {
      const text = server.files.get(file)
      if (text === undefined) throw new Error(`${file} could not be opened.`)
      return text
    }),
    saveScript: vi.fn(async (file: string, source: string) => {
      server.files.set(file, source)
      return { file, mtime: 2, bytes: source.length, program: true }
    }),
    deleteScript: vi.fn(async (file: string) => {
      server.files.delete(file)
    }),
  }
})

const A = 'alpha.oscript'
const B = 'beta.oscript'
const SOURCE_A = starterFor('alpha', 'strategy')
const SOURCE_B = starterFor('beta', 'study')

beforeEach(() => {
  localStorage.clear()
  forgetDraftsInPage()
  server.files.clear()
  server.files.set(A, SOURCE_A)
  server.files.set(B, SOURCE_B)
})

afterEach(() => {
  vi.clearAllMocks()
})

function panel(openFile: string | null = A) {
  return <ScriptPanel onAddToChart={() => true} openFile={openFile} />
}

async function editorFor(file: string): Promise<HTMLTextAreaElement> {
  return (await screen.findByLabelText(`Source of ${file}`)) as HTMLTextAreaElement
}

/** The coloured layer drawn behind the text, which must show the same text. */
function overlayOf(area: HTMLTextAreaElement): string {
  return area.parentElement?.querySelector('pre')?.textContent ?? ''
}

describe('the new script form', () => {
  it('says a strategy can be backtested, since it can', async () => {
    server.files.clear()
    const user = userEvent.setup()
    render(panel(null))
    await user.click(await screen.findByRole('button', { name: 'New script' }))
    await user.click(screen.getByRole('button', { name: 'strategy' }))
    expect(screen.getByText(KIND_HINT.strategy)).toBeInTheDocument()
    expect(screen.queryByText(/not built/i)).toBeNull()
    expect(KIND_HINT.strategy).toMatch(/Backtest/)
    expect(KIND_HINT.strategy).toMatch(/Strategies panel/)
  })
})

describe('Tab in the editor', () => {
  it('indents with spaces and keeps the editor focused', async () => {
    const user = userEvent.setup()
    render(panel())
    const area = await editorFor(A)
    const line = SOURCE_A.indexOf('fast = ema')
    area.focus()
    area.setSelectionRange(line, line)

    await user.keyboard('{Tab}')

    expect(document.activeElement).toBe(area)
    expect(area.value).toBe(`${SOURCE_A.slice(0, line)}    ${SOURCE_A.slice(line)}`)
    expect(area.selectionStart).toBe(line + 4)
    // The colours are drawn from the same text, or they would sit a level
    // to the left of the letters they belong to.
    await waitFor(() => expect(overlayOf(area)).toBe(area.value))
  })

  it('takes an indent back out with Shift+Tab', async () => {
    const user = userEvent.setup()
    render(panel())
    const area = await editorFor(A)
    const body = SOURCE_A.indexOf('    buy(qty')
    area.focus()
    area.setSelectionRange(body + 6, body + 6)

    await user.keyboard('{Shift>}{Tab}{/Shift}')

    expect(document.activeElement).toBe(area)
    expect(area.value).toBe(SOURCE_A.replace('    buy(qty', 'buy(qty'))
    await waitFor(() => expect(overlayOf(area)).toBe(area.value))
  })

  it('lets Escape and then Tab leave the editor, and says so', async () => {
    const user = userEvent.setup()
    render(panel())
    const area = await editorFor(A)
    act(() => area.focus())
    expect(screen.getByText('Esc then Tab to leave')).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(screen.getByText('Tab now leaves the editor')).toBeInTheDocument()
    await user.keyboard('{Tab}')

    expect(document.activeElement).not.toBe(area)
    expect(area.value).toBe(SOURCE_A)
  })

  it('goes back to indenting once any other key follows Escape', async () => {
    const user = userEvent.setup()
    render(panel())
    const area = await editorFor(A)
    area.focus()
    area.setSelectionRange(0, 0)

    await user.keyboard('{Escape}{ArrowRight}{Tab}')

    expect(document.activeElement).toBe(area)
    expect(area.value.startsWith('v   ersion')).toBe(true)
  })
})

describe('an unsaved edit', () => {
  it('comes back after switching to another script and back again', async () => {
    const user = userEvent.setup()
    const { rerender } = render(panel(A))
    const area = await editorFor(A)
    await user.click(area)
    area.setSelectionRange(area.value.length, area.value.length)
    await user.keyboard('// not saved yet')
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument()

    rerender(panel(B))
    expect((await editorFor(B)).value).toBe(SOURCE_B)

    rerender(panel(A))
    await waitFor(async () => expect((await editorFor(A)).value).toContain('// not saved yet'))
    expect(screen.getByText('Unsaved changes')).toBeInTheDocument()
    // Kept, not saved: the server still holds what it held.
    expect(server.files.get(A)).toBe(SOURCE_A)

    // And once saved it is let go: the next visit opens the saved text, clean.
    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(server.files.get(A)).toContain('// not saved yet'))
    rerender(panel(B))
    await editorFor(B)
    rerender(panel(A))
    await waitFor(async () => expect((await editorFor(A)).value).toBe(server.files.get(A)))
    expect(screen.queryByText('Unsaved changes')).toBeNull()
  })

  it('survives the panel closing and opening again', async () => {
    const user = userEvent.setup()
    const first = render(panel(A))
    const area = await editorFor(A)
    await user.click(area)
    area.setSelectionRange(area.value.length, area.value.length)
    await user.keyboard('// still here')
    first.unmount()

    // Reopened the way the rail reopens it: no request, only the memory of
    // which script was last open.
    render(panel(null))
    await waitFor(async () => expect((await editorFor(A)).value).toContain('// still here'))
  })

  it('is thrown away only after the panel asks, and the saved copy comes back', async () => {
    const user = userEvent.setup()
    render(panel(A))
    const area = await editorFor(A)
    await user.click(area)
    area.setSelectionRange(area.value.length, area.value.length)
    await user.keyboard('// throw me away')

    await user.click(screen.getByRole('button', { name: 'Script actions' }))
    await user.click(await screen.findByRole('menuitem', { name: 'Discard unsaved changes' }))
    const question = await screen.findByRole('alertdialog')
    expect(question).toHaveTextContent('Discard your unsaved changes to alpha?')
    // Nothing is gone until the answer is given.
    expect(area.value).toContain('// throw me away')

    await user.click(screen.getByRole('button', { name: 'Discard changes' }))
    await waitFor(() => expect(area.value).toBe(SOURCE_A))
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('says so when the saved copy changed underneath it', async () => {
    const user = userEvent.setup()
    const first = render(panel(A))
    const area = await editorFor(A)
    await user.click(area)
    area.setSelectionRange(area.value.length, area.value.length)
    await user.keyboard('// mine')
    first.unmount()

    // Another tab saves the same script in the meantime.
    await act(async () => {
      server.files.set(A, `${SOURCE_A}// theirs\n`)
    })
    render(panel(A))
    expect(await screen.findByText(/the saved copy of alpha has changed since/)).toBeInTheDocument()
    expect((await editorFor(A)).value).toContain('// mine')
  })
})
