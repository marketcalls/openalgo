import { describe, expect, it } from 'vitest'
import { buildBrand, sanitizeOverride } from './brand'

describe('buildBrand', () => {
  it('uses the FastAlgo defaults with no override', () => {
    const brand = buildBrand()
    expect(brand.displayName).toBe('FastAlgo')
    expect(brand.logoUrl).toBe('/logo.png')
    expect(brand.isWhiteLabel).toBe(false)
    expect(brand.endorsement).toBe('FastAlgo by TinyCompute')
    expect(brand.supportTelegramUrl).toBe('https://t.me/RanjT55')
  })

  it('lets one installation point the Telegram contact elsewhere', () => {
    const brand = buildBrand({ supportTelegramUrl: 'https://t.me/SharmaDesk' })
    expect(brand.supportTelegramUrl).toBe('https://t.me/SharmaDesk')
    expect(brand.displayName).toBe('FastAlgo')
  })

  it('white-labels the display name and logo but never the product identity', () => {
    const brand = buildBrand({ displayName: 'Sharma Capital', logoUrl: '/custom-brand/sharma.png' })
    expect(brand.displayName).toBe('Sharma Capital')
    expect(brand.logoUrl).toBe('/custom-brand/sharma.png')
    expect(brand.isWhiteLabel).toBe(true)
    expect(brand.endorsement).toBe('Sharma Capital, powered by FastAlgo')
    expect(brand.productName).toBe('FastAlgo')
    expect(brand.attribution).toContain('OpenAlgo')
    expect(brand.sourceUrl).toBe('https://github.com/ranjeetthorat/ai-algo')
  })
})

describe('sanitizeOverride', () => {
  it('ignores anything that is not an object', () => {
    expect(sanitizeOverride(undefined)).toEqual({})
    expect(sanitizeOverride('FastAlgo')).toEqual({})
    expect(sanitizeOverride(null)).toEqual({})
  })

  it('trims and caps the display name, and drops a blank one', () => {
    expect(sanitizeOverride({ displayName: '  Sharma Capital  ' })).toEqual({
      displayName: 'Sharma Capital',
    })
    expect(sanitizeOverride({ displayName: '   ' })).toEqual({})
    expect(sanitizeOverride({ displayName: 'x'.repeat(100) }).displayName).toHaveLength(60)
  })

  it('accepts only a t.me username link as the Telegram contact', () => {
    expect(sanitizeOverride({ supportTelegramUrl: ' https://t.me/SharmaDesk ' })).toEqual({
      supportTelegramUrl: 'https://t.me/SharmaDesk',
    })
    for (const bad of [
      'http://t.me/SharmaDesk',
      'https://t.me/abc',
      'https://t.me.evil.example/SharmaDesk',
      'https://evil.example/t.me/SharmaDesk',
      'https://t.me/SharmaDesk/extra',
      'javascript:alert(1)',
      42,
    ]) {
      expect(sanitizeOverride({ supportTelegramUrl: bad })).toEqual({})
    }
  })

  it('accepts only same-origin custom-brand logo paths', () => {
    expect(sanitizeOverride({ logoUrl: '/custom-brand/a.png' })).toEqual({
      logoUrl: '/custom-brand/a.png',
    })
    for (const bad of [
      'https://evil.example/logo.png',
      '//evil.example/logo.png',
      '/custom-brand/../secret.png',
      '/images/logo.png',
      'javascript:alert(1)',
    ]) {
      expect(sanitizeOverride({ logoUrl: bad })).toEqual({})
    }
  })
})
