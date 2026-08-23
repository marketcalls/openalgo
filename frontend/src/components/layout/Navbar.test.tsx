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

function renderNavbar(pathname: string) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <Navbar />
    </MemoryRouter>
  )
}

function currentLinks(container: HTMLElement) {
  return within(container)
    .getAllByRole('link')
    .filter((link) => link.getAttribute('aria-current') === 'page')
}

describe('Navbar', () => {
  it('marks only the nested Strategy route as current in desktop navigation', () => {
    renderNavbar('/strategy/builder')

    const strategy = screen.getByRole('link', { name: 'Strategy' })
    const dashboard = screen.getByRole('link', { name: 'Dashboard' })

    expect(strategy).toHaveAttribute('aria-current', 'page')
    expect(dashboard).not.toHaveAttribute('aria-current')
    expect(currentLinks(document.body)).toEqual([strategy])
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
