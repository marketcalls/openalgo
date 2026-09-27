import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { Navbar } from './Navbar'

vi.mock('@/hooks/useProfileMenuItems', () => ({
  useProfileMenuItems: () => [
    {
      href: '/profile',
      label: 'Profile',
      icon: () => null,
    },
  ],
}))

function renderNavbar(pathname: string, props: { fluid?: boolean } = {}) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <Navbar {...props} />
    </MemoryRouter>
  )
}

function currentLinks(container: HTMLElement) {
  return within(container)
    .getAllByRole('link')
    .filter((link) => link.getAttribute('aria-current') === 'page')
}

describe('Navbar', () => {
  it('marks only the active route as current in desktop navigation', () => {
    renderNavbar('/positions')

    const positions = screen.getByRole('link', { name: 'Positions' })
    const dashboard = screen.getByRole('link', { name: 'Dashboard' })

    expect(positions).toHaveAttribute('aria-current', 'page')
    expect(dashboard).not.toHaveAttribute('aria-current')
    const desktopNav = screen
      .getAllByRole('navigation')
      .find((nav) => nav.classList.contains('md:flex'))

    expect(desktopNav).toBeDefined()
    expect(currentLinks(desktopNav!)).toEqual([positions])
  })

  it('marks only the active sheet navigation link as current', async () => {
    const user = userEvent.setup()
    renderNavbar('/trading')

    await user.click(screen.getByRole('button', { name: 'Toggle menu' }))

    const sheet = await screen.findByRole('dialog', { name: 'Navigation Menu' })
    const trading = within(sheet).getByRole('link', { name: 'Trading' })
    const platforms = within(sheet).getByRole('link', { name: 'Platforms' })

    expect(trading).toHaveAttribute('aria-current', 'page')
    expect(platforms).not.toHaveAttribute('aria-current')
    expect(currentLinks(sheet)).toEqual([trading])
  })

  it('marks the active quick-access sheet link as current', async () => {
    const user = userEvent.setup()
    renderNavbar('/profile')

    await user.click(screen.getByRole('button', { name: 'Toggle menu' }))

    const sheet = await screen.findByRole('dialog', { name: 'Navigation Menu' })
    const profile = within(sheet).getByRole('link', { name: 'Profile' })
    const trading = within(sheet).getByRole('link', { name: 'Trading' })

    expect(profile).toHaveAttribute('aria-current', 'page')
    expect(trading).not.toHaveAttribute('aria-current')
    expect(currentLinks(sheet)).toEqual([profile])
  })
})

describe('Navbar width', () => {
  /**
   * The bar itself is always w-full; what changes is the inner wrapper. Pages
   * under Layout share its `container mx-auto`, so the default has to keep
   * that or every ordinary page's nav stops lining up with its content.
   * Full-bleed pages like /trading render this navbar themselves with no such
   * container, and a capped nav floats inset above an edge-to-edge chart.
   */
  function innerWrapper(container: HTMLElement) {
    const nav = container.querySelector('nav')
    if (!nav) throw new Error('no nav element rendered')
    return nav.firstElementChild as HTMLElement
  }

  it('is centred and width-capped by default, matching Layout', () => {
    const { container } = renderNavbar('/dashboard')
    const inner = innerWrapper(container)

    expect(inner.className).toContain('container')
    expect(inner.className).toContain('mx-auto')
    expect(inner.className).not.toContain('w-full')
  })

  it('spans the viewport when fluid, for full-bleed pages', () => {
    const { container } = renderNavbar('/trading', { fluid: true })
    const inner = innerWrapper(container)

    expect(inner.className).toContain('w-full')
    expect(inner.className).not.toContain('container')
    expect(inner.className).not.toContain('mx-auto')
  })
})
