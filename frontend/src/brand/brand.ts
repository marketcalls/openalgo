/**
 * The FastAlgo brand: every product name, link and logo the UI shows comes from here.
 *
 * Spec: docs/design/brand/design-language.md. Change a value here and every
 * screen that reads BRAND follows.
 *
 * Per-instance white-label: the server can override `displayName`, `logoUrl`
 * and `supportTelegramUrl` for one client's installation
 * (custom_brand/brand.json, served as /brand-config.js, see
 * blueprints/react_app.py). Only those fields can be overridden. The product
 * name, attribution and source link never change, because AGPL attribution
 * must stay intact.
 */

import type { LogoWatermarkOptions } from 'openalgo-charts'

export interface BrandOverride {
  displayName?: string
  logoUrl?: string
  supportTelegramUrl?: string
}

declare global {
  interface Window {
    __FASTALGO_BRAND__?: BrandOverride
  }
}

/** Fixed product identity. */
const PRODUCT = {
  /** Always written this way: one word, capital F and A. */
  productName: 'FastAlgo',
  /** For very tight spaces only. */
  initials: 'FA',
  tagline: 'Automate your trading strategy. Take fast trades.',
  description: 'FastAlgo: algorithmic trading for Indian markets, set up and supported for you.',

  /** The maker. Changes with the freelance brand and domain, never with the product. */
  makerName: 'TinyCompute',
  makerUrl: 'https://www.tinycompute.site',
  productUrl: 'https://fastalgo.tinycompute.site',
  /** Where "Help" and "Support" lead (Q3, Q4). */
  supportUrl: 'https://www.tinycompute.site',
  /** Shown in the footer, below the attribution line. */
  supportEmail: 'rthorat99@gmail.com',
  /** Telegram contact for support. Overridable per installation in brand.json. */
  supportTelegramUrl: 'https://t.me/RanjT55',

  /** AGPL attribution and source offer (section 13). Never remove. */
  attribution: 'Based on OpenAlgo, licensed under AGPL-3.0',
  upstreamName: 'OpenAlgo',
  upstreamUrl: 'https://github.com/marketcalls/openalgo',
  sourceUrl: 'https://github.com/ranjeetthorat/ai-algo',
  licenseName: 'AGPL-3.0',

  logoUrl: '/logo.png',
  themeColor: '#162537',
} as const

const NAME_MAX = 60
/** Same rule as utils/brand.py: https, t.me, and a valid Telegram username. */
const TELEGRAM_URL = /^https:\/\/t\.me\/[A-Za-z0-9_]{5,32}$/

/** Accept only well-formed override values; anything else falls back to the default. */
export function sanitizeOverride(raw: unknown): BrandOverride {
  if (!raw || typeof raw !== 'object') return {}
  const source = raw as Record<string, unknown>
  const override: BrandOverride = {}
  if (typeof source.displayName === 'string' && source.displayName.trim()) {
    override.displayName = source.displayName.trim().slice(0, NAME_MAX)
  }
  // Same-origin paths only, so an override can never point the logo at another site.
  if (typeof source.logoUrl === 'string' && /^\/custom-brand\/[^/]+$/.test(source.logoUrl)) {
    override.logoUrl = source.logoUrl
  }
  if (
    typeof source.supportTelegramUrl === 'string' &&
    TELEGRAM_URL.test(source.supportTelegramUrl.trim())
  ) {
    override.supportTelegramUrl = source.supportTelegramUrl.trim()
  }
  return override
}

export function buildBrand(override: BrandOverride = {}) {
  const displayName = override.displayName ?? PRODUCT.productName
  const isWhiteLabel = displayName !== PRODUCT.productName
  return {
    ...PRODUCT,
    /** The name shown in the UI: the client's name when white-labelled, otherwise FastAlgo. */
    displayName,
    logoUrl: override.logoUrl ?? PRODUCT.logoUrl,
    supportTelegramUrl: override.supportTelegramUrl ?? PRODUCT.supportTelegramUrl,
    isWhiteLabel,
    /** Footer and About line: "FastAlgo by TinyCompute", or "Client, powered by FastAlgo". */
    endorsement: isWhiteLabel
      ? `${displayName}, powered by ${PRODUCT.productName}`
      : `${PRODUCT.productName} by ${PRODUCT.makerName}`,
  }
}

export type Brand = ReturnType<typeof buildBrand>

export const BRAND: Brand = buildBrand(
  sanitizeOverride(typeof window !== 'undefined' ? window.__FASTALGO_BRAND__ : undefined)
)

/**
 * Corner mark for every openalgo-charts chart. The library draws its own
 * OpenAlgo mark unless a host passes `branding`, so every createChart call
 * passes this. The glyph file keeps its upstream name but holds FastAlgo
 * artwork; a white-labelled install shows the client's logo instead.
 */
export const CHART_BRANDING: LogoWatermarkOptions = {
  src: BRAND.isWhiteLabel ? BRAND.logoUrl : '/images/openalgo-glyph.svg',
  label: `Chart by ${BRAND.displayName}`,
  opacity: 0.7,
}
