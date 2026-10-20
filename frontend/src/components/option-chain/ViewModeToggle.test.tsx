import { describe, expect, it, vi } from 'vitest'
import { render, screen, userEvent } from '@/test/test-utils'
import { ViewModeToggle } from './ViewModeToggle'

describe('ViewModeToggle', () => {
  it.each([
    {
      initialMode: 'price' as const,
      selectedLabel: 'Price',
      otherLabel: 'Greeks',
      expectedMode: 'greeks' as const,
    },
    {
      initialMode: 'greeks' as const,
      selectedLabel: 'Greeks',
      otherLabel: 'Price',
      expectedMode: 'price' as const,
    },
  ])(
    'shows $initialMode as selected and changes to $expectedMode',
    async ({ initialMode, selectedLabel, otherLabel, expectedMode }) => {
      const onViewModeChange = vi.fn()
      const user = userEvent.setup()

      render(
        <ViewModeToggle
          viewMode={initialMode}
          onViewModeChange={onViewModeChange}
        />
      )

      expect(
        screen.getByRole('group', { name: 'Chain view mode' })
      ).toBeInTheDocument()

      const selectedButton = screen.getByRole('button', { name: selectedLabel })
      const otherButton = screen.getByRole('button', { name: otherLabel })

      expect(selectedButton).toHaveAttribute('aria-pressed', 'true')
      expect(otherButton).toHaveAttribute('aria-pressed', 'false')

      await user.click(otherButton)

      expect(onViewModeChange).toHaveBeenCalledTimes(1)
      expect(onViewModeChange).toHaveBeenCalledWith(expectedMode)
    }
  )
})
