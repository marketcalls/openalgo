import { describe, expect, it } from 'vitest'
import { render, screen } from '@/test/test-utils'
import { PageLoader } from './page-loader'

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
    it('has accessible loading indicator', () => {
      render(<PageLoader />)

      // Check for text content that screen readers can announce
      expect(screen.getByText('Loading...')).toBeInTheDocument()
    })
  })
})
