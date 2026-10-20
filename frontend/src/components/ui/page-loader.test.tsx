import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@/test/test-utils'
import { ANNOUNCE_DELAY_MS, PageLoader } from './page-loader'

describe('PageLoader', () => {
  it('renders the loading spinner', () => {
    render(<PageLoader />)

    // Check for loading text
    expect(screen.getByText('Loading...')).toBeInTheDocument()
  })

  it('has correct styling classes', () => {
    const { container } = render(<PageLoader />)

    // Check main container has correct classes
    const mainDiv = container.firstChild as HTMLElement
    expect(mainDiv).toHaveClass('min-h-screen')
    expect(mainDiv).toHaveClass('flex')
    expect(mainDiv).toHaveClass('items-center')
    expect(mainDiv).toHaveClass('justify-center')
  })

  it('renders the animated spinner icon', () => {
    const { container } = render(<PageLoader />)

    // Check for animate-spin class on the loader icon
    const spinner = container.querySelector('.animate-spin')
    expect(spinner).toBeInTheDocument()
  })

  describe('accessibility', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })
    afterEach(() => {
      vi.useRealTimers()
    })

    it('announces the loading message as a status once the region is in place', () => {
      render(<PageLoader />)

      // The region exists before it has anything to say: a screen reader that
      // only announces changes would stay silent if it appeared already full.
      const status = screen.getByRole('status')
      expect(status).toBeEmptyDOMElement()

      act(() => {
        vi.advanceTimersByTime(ANNOUNCE_DELAY_MS)
      })
      expect(status).toHaveTextContent('Loading...')
    })

    it('says nothing for a load that finishes before the delay', () => {
      const view = render(<PageLoader />)
      act(() => {
        vi.advanceTimersByTime(ANNOUNCE_DELAY_MS - 1)
      })
      expect(screen.getByRole('status')).toBeEmptyDOMElement()
      // Unmounting clears the timer rather than setting state on a gone component.
      view.unmount()
      act(() => {
        vi.advanceTimersByTime(ANNOUNCE_DELAY_MS)
      })
    })

    it('keeps the visible text and spinner out of the accessibility tree', () => {
      const { container } = render(<PageLoader />)

      expect(screen.getByText('Loading...')).toHaveAttribute('aria-hidden', 'true')
      expect(container.querySelector('.animate-spin')).toHaveAttribute('aria-hidden', 'true')
    })
  })
})
