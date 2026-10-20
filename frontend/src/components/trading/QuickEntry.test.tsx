import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SEARCH_INPUT_ATTR } from '@/lib/trading/quickEntry'
import { act, cleanup, fireEvent, render } from '@/test/test-utils'
import { QuickIntervalBox, useSeedBuffer } from './QuickEntry'

afterEach(cleanup)

const BROKER = ['1m', '5m', '15m', '1h', 'D']

describe('QuickIntervalBox', () => {
  it('opens holding the digit typed, focused, and applies a broker interval on Enter', () => {
    const onApply = vi.fn()
    const view = render(
      <QuickIntervalBox initial="1" available={BROKER} onApply={onApply} onClose={() => {}} />
    )
    const box = view.getByLabelText('Interval') as HTMLInputElement
    expect(box.value).toBe('1')
    expect(document.activeElement).toBe(box)
    fireEvent.change(box, { target: { value: '15' } })
    fireEvent.keyDown(box, { key: 'Enter' })
    expect(onApply).toHaveBeenCalledWith('15m')
  })

  it('refuses an interval the broker does not serve and says why', () => {
    const onApply = vi.fn()
    const view = render(
      <QuickIntervalBox initial="7" available={BROKER} onApply={onApply} onClose={() => {}} />
    )
    fireEvent.keyDown(view.getByLabelText('Interval'), { key: 'Enter' })
    expect(onApply).not.toHaveBeenCalled()
    expect(view.getByRole('alert')).toHaveTextContent('Your broker does not offer 7m')
  })

  it('closes on Escape without applying anything', () => {
    const onApply = vi.fn()
    const onClose = vi.fn()
    const view = render(
      <QuickIntervalBox initial="5" available={BROKER} onApply={onApply} onClose={onClose} />
    )
    fireEvent.keyDown(view.getByLabelText('Interval'), { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
    expect(onApply).not.toHaveBeenCalled()
  })
})

function SeedHarness() {
  const [seed, setSeed] = useState({ text: 'S', live: true })
  const [box, setBox] = useState(false)
  useSeedBuffer(
    seed.live,
    (update) => setSeed((current) => ({ ...current, text: update(current.text) })),
    () => setSeed((current) => ({ ...current, live: false }))
  )
  return (
    <>
      <output>{seed.text}</output>
      <button type="button" onClick={() => setBox(true)}>
        ready
      </button>
      {box && <input aria-label="box" {...{ [SEARCH_INPUT_ATTR]: '' }} />}
    </>
  )
}

describe('useSeedBuffer', () => {
  it('keeps keys typed before the search box exists, and stops once it has focus', () => {
    const view = render(<SeedHarness />)
    fireEvent.keyDown(document.body, { key: 'B' })
    fireEvent.keyDown(document.body, { key: 'I' })
    fireEvent.keyDown(document.body, { key: 'X' })
    fireEvent.keyDown(document.body, { key: 'Backspace' })
    expect(view.getByRole('status')).toHaveTextContent('SBI')

    fireEvent.click(view.getByRole('button', { name: 'ready' }))
    act(() => (view.getByLabelText('box') as HTMLInputElement).focus())
    // Focus moves away again: the seed is final, so nothing typed now replaces it.
    act(() => view.getByRole('button', { name: 'ready' }).focus())
    fireEvent.keyDown(document.body, { key: 'Z' })
    expect(view.getByRole('status')).toHaveTextContent('SBI')
  })

  it('leaves chords alone', () => {
    const view = render(<SeedHarness />)
    fireEvent.keyDown(document.body, { key: 'c', ctrlKey: true })
    expect(view.getByRole('status')).toHaveTextContent('S')
  })
})
