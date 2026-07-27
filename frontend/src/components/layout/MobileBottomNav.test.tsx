import { render, screen } from '@testing-library/react'
import { axe, toHaveNoViolations } from 'jest-axe'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { bottomNavItems } from '@/config/navigation'
import { MobileBottomNav } from './MobileBottomNav'

expect.extend(toHaveNoViolations)

// Custom render with router that allows setting initial path
function renderWithRouter(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <MobileBottomNav />
    </MemoryRouter>
  )
}

describe('MobileBottomNav', () => {
  it('renders all navigation items', () => {
    renderWithRouter('/dashboard')

    bottomNavItems.forEach((item) => {
      expect(screen.getByText(item.label)).toBeInTheDocument()
    })
  })

  it('renders as a nav element', () => {
    renderWithRouter('/dashboard')

    const nav = screen.getByRole('navigation')
    expect(nav).toBeInTheDocument()
  })

  it('renders links for each nav item', () => {
    renderWithRouter('/dashboard')

    const links = screen.getAllByRole('link')
    expect(links).toHaveLength(bottomNavItems.length)
  })

  it('has correct link hrefs', () => {
    renderWithRouter('/dashboard')

    bottomNavItems.forEach((item) => {
      const link = screen.getByRole('link', { name: new RegExp(item.label, 'i') })
      expect(link).toHaveAttribute('href', item.href)
    })
  })

  describe('active state', () => {
    it('highlights Dashboard when on dashboard route', () => {
      renderWithRouter('/dashboard')

      const dashboardLink = screen.getByRole('link', { name: /dashboard/i })
      expect(dashboardLink).toHaveClass('text-primary')
    })

    it('highlights Positions when on positions route', () => {
      renderWithRouter('/positions')

      const positionsLink = screen.getByRole('link', { name: /positions/i })
      expect(positionsLink).toHaveClass('text-primary')
    })

    it('highlights Strategy when on strategy sub-routes', () => {
      renderWithRouter('/strategy/new')

      const strategyLink = screen.getByRole('link', { name: /strategy/i })
      expect(strategyLink).toHaveClass('text-primary')
    })

    it('non-active items have muted color', () => {
      renderWithRouter('/dashboard')

      const positionsLink = screen.getByRole('link', { name: /positions/i })
      expect(positionsLink).toHaveClass('text-muted-foreground')
    })
  })

  describe('responsive visibility', () => {
    it('has md:hidden class for mobile-only display', () => {
      renderWithRouter('/dashboard')

      const nav = screen.getByRole('navigation')
      expect(nav).toHaveClass('md:hidden')
    })
  })

  describe('touch targets', () => {
    it('has minimum touch target size of 44px', () => {
      renderWithRouter('/dashboard')

      const links = screen.getAllByRole('link')
      links.forEach((link) => {
        expect(link).toHaveClass('min-h-[44px]')
      })
    })

    it('has touch-manipulation class for better touch response', () => {
      renderWithRouter('/dashboard')

      const links = screen.getAllByRole('link')
      links.forEach((link) => {
        expect(link).toHaveClass('touch-manipulation')
      })
    })
  })

  describe('accessibility', () => {
    it('has no accessibility violations', async () => {
      const { container } = renderWithRouter('/dashboard')

      const results = await axe(container)
      expect(results).toHaveNoViolations()
    })

    it('has accessible names for all links', () => {
      renderWithRouter('/dashboard')

      bottomNavItems.forEach((item) => {
        const link = screen.getByRole('link', { name: new RegExp(item.label, 'i') })
        expect(link).toBeInTheDocument()
      })
    })
  })
})
