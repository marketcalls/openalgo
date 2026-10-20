/**
 * Which keystrokes the chart may take. Every one of these is a place a trader
 * types or decides something, and a chart that answered there would delete a
 * drawing from inside the order ticket or paste a trend line over a quantity.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { clipboardMessage, drawingClipboardPort } from './drawingClipboard'
import { chartMayTakeKey, pageHasTextSelection } from './drawingKeys'

afterEach(() => {
  document.body.innerHTML = ''
  window.getSelection()?.removeAllRanges()
  vi.useRealTimers()
})

function keyOn(target: EventTarget | null) {
  return { target } as Pick<KeyboardEvent, 'target'>
}

describe('chartMayTakeKey', () => {
  it('takes a key pressed with nothing focused', () => {
    expect(chartMayTakeKey(keyOn(document.body))).toBe(true)
    expect(chartMayTakeKey(keyOn(document))).toBe(true)
  })

  it.each([
    '<input />',
    '<textarea></textarea>',
    '<select></select>',
    '<div contenteditable="true"></div>',
    '<div role="textbox"></div>',
  ])('refuses a key typed into %s', (html) => {
    document.body.innerHTML = html
    expect(chartMayTakeKey(keyOn(document.body.firstElementChild))).toBe(false)
  })

  it('refuses a key pressed on a button inside a dialog, such as the order ticket', () => {
    document.body.innerHTML = '<div role="dialog"><button>Buy</button></div>'
    expect(chartMayTakeKey(keyOn(document.querySelector('button')))).toBe(false)
  })

  it('refuses every key while a pane dialog or a menu is open, wherever focus is', () => {
    document.body.innerHTML = '<section data-trading-dialog-open="true"></section>'
    expect(chartMayTakeKey(keyOn(document.body))).toBe(false)
    document.body.innerHTML = '<div role="menu" data-state="open"></div>'
    expect(chartMayTakeKey(keyOn(document.body))).toBe(false)
    document.body.innerHTML = '<div role="alertdialog"></div>'
    expect(chartMayTakeKey(keyOn(document.body))).toBe(false)
  })

  it('takes a key again once that menu has closed', () => {
    document.body.innerHTML = '<div role="menu" data-state="closed"></div>'
    expect(chartMayTakeKey(keyOn(document.body))).toBe(true)
  })
})

describe('pageHasTextSelection', () => {
  it('sees highlighted text and ignores a bare caret', () => {
    document.body.innerHTML = '<p>Order 260930000123</p>'
    expect(pageHasTextSelection()).toBe(false)
    window.getSelection()?.selectAllChildren(document.querySelector('p') as Node)
    expect(pageHasTextSelection()).toBe(true)
  })
})

describe('the clipboard port', () => {
  it('stops waiting on a system clipboard that never answers', async () => {
    vi.useFakeTimers()
    const port = drawingClipboardPort({
      readText: () => new Promise<string>(() => {}),
      writeText: async () => {},
    })
    const read = port?.readText()
    const settled = expect(read).rejects.toThrow()
    await vi.advanceTimersByTimeAsync(1200)
    await settled
  })

  it('passes a prompt answer straight through', async () => {
    const port = drawingClipboardPort({
      readText: async () => 'payload',
      writeText: async () => {},
    })
    await expect(port?.readText()).resolves.toBe('payload')
  })

  it('is absent where the browser has no clipboard', () => {
    expect(drawingClipboardPort(null)).toBeNull()
  })

  it('says when a copy only reaches this tab', () => {
    expect(clipboardMessage('copied', 1, false)).toBe('Drawing copied.')
    expect(clipboardMessage('cut', 3, true)).toBe('3 drawings cut. Paste on any chart in this tab.')
  })
})
