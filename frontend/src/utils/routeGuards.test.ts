import { describe, expect, it } from 'vitest'

import { BROKER_AUTH_EXEMPT_PATHS, isBrokerAuthExempt } from './routeGuards'

describe('isBrokerAuthExempt', () => {
  it('exempts the broker settings page', () => {
    expect(isBrokerAuthExempt('/profile')).toBe(true)
  })

  it('does not exempt trading or auth pages', () => {
    for (const path of ['/dashboard', '/orderbook', '/broker', '/login', '/']) {
      expect(isBrokerAuthExempt(path)).toBe(false)
    }
  })

  it('keeps the exempt list explicit', () => {
    expect(BROKER_AUTH_EXEMPT_PATHS).toEqual(['/profile'])
  })
})
