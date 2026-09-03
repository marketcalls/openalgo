/**
 * The prefill end of the composer, and the one thing it must never do.
 *
 * A Buy or Sell control on an instrument card writes a request into this box.
 * That is the entire mechanism, and it is a safety property rather than a
 * convenience: every order in this product pauses at a human approval gate, so
 * a control wired to an order tool would be the one path around it. The first
 * test here is that `onSend` is not called. If a future change makes a prefill
 * submit, it fails before anything reaches a broker.
 *
 * The second is smaller and still worth pinning: a prefill must not throw away
 * a half-written message. Losing what somebody was typing because they clicked
 * a button beside the answer is the kind of thing nobody reports and everybody
 * remembers.
 */

import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { prefillComposer } from '@/lib/agent/composer'
import { Composer } from './Composer'

const REQUEST = 'Buy 1 share of RELIANCE on NSE at market.'

describe('Composer prefill', () => {
  it('fills the box and sends nothing', () => {
    const onSend = vi.fn()
    render(<Composer onSend={onSend} onStop={vi.fn()} running={false} />)

    act(() => {
      expect(prefillComposer(REQUEST)).toBe(true)
    })

    const box = screen.getByLabelText('Message the agent') as HTMLTextAreaElement
    expect(box.value).toBe(REQUEST)
    expect(onSend).not.toHaveBeenCalled()
    // The send button is now live, because that is the operator's action and
    // theirs alone.
    expect(screen.getByRole('button', { name: 'Send the message' })).toBeEnabled()
  })

  it('keeps what the operator was already writing', async () => {
    render(<Composer onSend={vi.fn()} onStop={vi.fn()} running={false} />)
    const box = screen.getByLabelText('Message the agent') as HTMLTextAreaElement
    await userEvent.type(box, 'is this a good entry')

    act(() => {
      prefillComposer(REQUEST)
    })

    expect(box.value).toBe(`is this a good entry\n${REQUEST}`)
  })

  it('reports that nothing received it when no composer is mounted', () => {
    expect(prefillComposer(REQUEST)).toBe(false)
  })
})
