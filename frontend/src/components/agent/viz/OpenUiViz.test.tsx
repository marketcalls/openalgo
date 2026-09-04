/**
 * What the OpenUI block has to survive.
 *
 * The string it is given is **incomplete for most of a turn**: the model writes
 * it a piece at a time and the component is re-rendered after every flush. So
 * the tests here are about the half-written cases rather than the finished one,
 * plus the one piece of isolation that protects the rest of the product.
 *
 * - A statement cut mid-string must render what has resolved and hold the rest,
 *   with no throw and no error text where an answer should be.
 * - The whole accumulated string goes in every time. Feeding the delta renders
 *   one fragment and loses everything before it, which is a mistake that looks
 *   like a rendering bug rather than a wiring one.
 * - `--openui-*` is written to this block's own selector. `ThemeProvider`
 *   defaults to `body`, which would put a second design system's variables on
 *   every page in OpenAlgo.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { OpenUiViz } from './OpenUiViz'

const FINISHED = [
  'root = Card([title, note])',
  'title = TextContent("Position sizes", "large-heavy")',
  'note = TextContent("Three open positions.")',
].join('\n')

/** Every `--openui-*` rule this render injected, by the selector it targets. */
function openuiStyleSelectors(): string[] {
  return [...document.head.querySelectorAll('style[data-openui-theme]')].map((node) =>
    (node.textContent ?? '').split('{')[0].trim()
  )
}

describe('OpenUiViz', () => {
  it('renders nothing at all before the first token', () => {
    const { container } = render(<OpenUiViz markup="" />)
    expect(container).toBeEmptyDOMElement()
    const { container: blank } = render(<OpenUiViz markup={'   \n  '} />)
    expect(blank).toBeEmptyDOMElement()
  })

  it('renders a finished block', () => {
    render(<OpenUiViz markup={FINISHED} />)
    expect(screen.getByText('Position sizes')).toBeInTheDocument()
    expect(screen.getByText('Three open positions.')).toBeInTheDocument()
  })

  it('survives markup cut at every character', () => {
    // The stream can be flushed after any character, so every prefix is a real
    // input rather than a hypothetical one. A throw at any of them takes the
    // whole conversation off the screen.
    for (let length = 1; length <= FINISHED.length; length += 1) {
      const partial = FINISHED.slice(0, length)
      expect(() => render(<OpenUiViz markup={partial} streaming />).unmount()).not.toThrow()
    }
  })

  it('takes the whole accumulated string on each render, not the delta', () => {
    const { rerender } = render(<OpenUiViz markup="root = Card([title])" streaming />)
    rerender(<OpenUiViz markup={`root = Card([title])\ntitle = TextContent("Posi`} streaming />)
    rerender(<OpenUiViz markup={FINISHED} streaming={false} />)

    // The first statement was sent once and never repeated, so a renderer fed
    // deltas would have lost the Card the later text hangs off.
    expect(screen.getByText('Position sizes')).toBeInTheDocument()
    expect(screen.getByText('Three open positions.')).toBeInTheDocument()
  })

  it('keeps its theme variables out of the rest of the app', () => {
    render(<OpenUiViz markup={FINISHED} />)
    const selectors = openuiStyleSelectors()
    expect(selectors.length).toBeGreaterThan(0)
    for (const selector of selectors) {
      expect(selector).toContain('.openalgo-openui-scope')
      expect(selector.split(',').map((part) => part.trim())).not.toContain('body')
    }
  })
})
