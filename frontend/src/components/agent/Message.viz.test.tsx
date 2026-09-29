/**
 * Where a turn's visualizations land in the answer.
 *
 * The defect this pins is subtle and only shows on a turn that draws more than
 * once: with the blocks appended after the prose, the answer reads "chart one,
 * chart two, then the sentence about chart one". Each item records how much
 * prose had been written when its frame arrived, and the prose is cut there, so
 * a chart sits where the model drew it.
 *
 * The second concern is the open code fence. A streaming artifact is
 * deliberately kept out of the markdown parser until its fence closes, so a cut
 * taken inside it would hand markdown two unterminated fences to parse. Anchors
 * are clamped to the end of the finished markdown instead.
 */

import { render, screen } from '@testing-library/react'
import { beforeAll, describe, expect, it } from 'vitest'
import { createAgentMessage } from '@/lib/agent/useAgentStream'
import { type AgentVizItem, OPENUI_VIZ, openUiSpec } from '@/lib/agent/viz'
import { Message, splitByViz } from './Message'

function block(text: string, at: number): AgentVizItem {
  return {
    kind: OPENUI_VIZ,
    spec: openUiSpec(`root = Card([t])\nt = TextContent(${JSON.stringify(text)})`),
    title: '',
    source: '',
    at,
  }
}

describe('splitByViz', () => {
  it('returns the prose alone when the turn drew nothing', () => {
    expect(splitByViz('An answer.', [])).toEqual([
      { key: 'prose-0', text: 'An answer.', viz: null },
    ])
    expect(splitByViz('', [])).toEqual([])
  })

  it('cuts the prose at each anchor, in order', () => {
    const viz = [block('one', 6), block('two', 13)]
    expect(splitByViz('First second third', viz).map((part) => part.text)).toEqual([
      'First ',
      'second ',
      'third',
    ])
  })

  it('keeps the parts ordered whatever the anchors say', () => {
    // Anchors come off the wire, so an out-of-order or oversized one has to
    // produce a readable answer rather than a negative slice.
    const parts = splitByViz('Short', [block('a', 4), block('b', 1), block('c', 900)])
    expect(parts.map((part) => part.text)).toEqual(['Shor', '', 't'])
    expect(parts.map((part) => part.key)).toEqual(['viz-0', 'viz-1', 'viz-2'])
  })
})

/**
 * Render a turn and wait for its blocks, which arrive on a lazily fetched
 * chunk rather than with the page.
 *
 * @param message - The turn to render.
 * @param settled - A string from the last block, so the wait covers them all.
 * @returns The rendered text, in DOM order.
 */
async function renderedText(
  message: Parameters<typeof Message>[0]['message'],
  settled: string
): Promise<string> {
  const { container } = render(<Message message={message} />)
  await screen.findByText(settled)
  return container.textContent ?? ''
}

describe('Message visualizations', () => {
  beforeAll(async () => {
    // See VizBlock.test.tsx: the OpenUI branch is a lazy import, and the first
    // resolution pulls in the whole component library.
    await import('./viz/OpenUiViz')
  }, 30000)

  it('puts a block between the prose that came before it and after it', async () => {
    const message = createAgentMessage('assistant', 'Before the chart.After the chart.', {
      viz: [block('THE CHART', 'Before the chart.'.length)],
    })
    const text = await renderedText(message, 'THE CHART')

    expect(text.indexOf('Before the chart.')).toBeGreaterThanOrEqual(0)
    expect(text.indexOf('THE CHART')).toBeGreaterThan(text.indexOf('Before the chart.'))
    expect(text.indexOf('After the chart.')).toBeGreaterThan(text.indexOf('THE CHART'))
  })

  it('keeps three blocks in the order they were drawn', async () => {
    const message = createAgentMessage('assistant', 'AABBCC', {
      viz: [block('FIRST', 2), block('SECOND', 4), block('THIRD', 6)],
    })
    const text = await renderedText(message, 'THIRD')

    expect(text.indexOf('FIRST')).toBeLessThan(text.indexOf('SECOND'))
    expect(text.indexOf('SECOND')).toBeLessThan(text.indexOf('THIRD'))
  })

  it('never cuts the prose inside a fence that has not closed', async () => {
    // The chart arrived while the strategy was still being written. It belongs
    // before the artifact, not inside it.
    const content = 'Here it is.\n```python\nprint("half a file")'
    const message = createAgentMessage('assistant', content, {
      viz: [block('THE CHART', content.length)],
      streaming: true,
    })
    const text = await renderedText(message, 'THE CHART')

    expect(text.indexOf('THE CHART')).toBeGreaterThan(text.indexOf('Here it is.'))
    expect(text.indexOf('THE CHART')).toBeLessThan(text.indexOf('half a file'))
  })

  it('shows the thinking indicator until something arrives, block or token', () => {
    const empty = createAgentMessage('assistant', '', { streaming: true })
    expect(render(<Message message={empty} />).container.textContent).toContain('Thinking')

    const drawing = createAgentMessage('assistant', '', {
      streaming: true,
      viz: [block('A CHART', 0)],
    })
    expect(render(<Message message={drawing} />).container.textContent).not.toContain('Thinking')
  })
})
