/**
 * The identity tile that sits beside a provider name.
 *
 * There is no bundled logo set here and none is wanted. A company logo is
 * somebody else's mark, the catalog carries around 150 providers and grows with
 * every LiteLLM release, so a logo directory would be a licensing question
 * attached to a maintenance chore, for an asset whose only job is helping the
 * eye find a card in a grid. The tile is a monogram on a stable per-provider
 * colour instead: a provider a future LiteLLM release adds gets its own tile
 * with nothing to update in this file.
 *
 * The colour is looked up for the brands an operator recognises and hashed from
 * the id for everything else, so it is stable across renders and across
 * sessions, never random. The text colour is picked from the background's
 * relative luminance so a light brand colour keeps a legible monogram.
 *
 * The tile is decorative. It is always rendered next to the provider name in
 * text, so it carries `aria-hidden` rather than reading the same name twice.
 */

import { cn } from '@/lib/utils'

/**
 * Accent colours for the brands worth recognising at a glance.
 *
 * Keyed by both the LiteLLM provider id and the icon slug the catalog serves
 * beside it, because a caller reasonably passes either. These are plain
 * background colours for a letter tile, not a reproduction of any logo.
 */
const BRAND_COLOR: Record<string, string> = {
  ai21: '#e0234e',
  alibaba: '#ff6a00',
  anthropic: '#cc785c',
  anthropic_text: '#cc785c',
  aws: '#ff9900',
  azure: '#0078d4',
  azure_ai: '#0078d4',
  azure_text: '#0078d4',
  baseten: '#6366f1',
  bedrock: '#ff9900',
  cerebras: '#ea580c',
  clarifai: '#1c60ff',
  cloudflare: '#f38020',
  codestral: '#fa5310',
  cohere: '#39594d',
  dashscope: '#ff6a00',
  databricks: '#ff3621',
  deepinfra: '#4f46e5',
  deepseek: '#4d6bfe',
  digitalocean: '#0069ff',
  docker: '#2496ed',
  featherless: '#0ea5e9',
  fireworks: '#8b5cf6',
  fireworks_ai: '#8b5cf6',
  friendliai: '#3b82f6',
  gemini: '#1a73e8',
  github: '#24292f',
  github_copilot: '#24292f',
  google: '#1a73e8',
  gradient_ai: '#0069ff',
  groq: '#f55036',
  hosted_vllm: '#12b981',
  huggingface: '#ff9d00',
  ibm: '#0f62fe',
  inception: '#0f766e',
  lambda: '#4028a0',
  lambda_ai: '#4028a0',
  litellm: '#6366f1',
  litellm_proxy: '#6366f1',
  llamafile: '#0f766e',
  lm_studio: '#7c3aed',
  lmstudio: '#7c3aed',
  meta: '#0668e1',
  meta_llama: '#0668e1',
  mistral: '#fa5310',
  modelscope: '#624aff',
  moonshot: '#111827',
  nebius: '#1d4ed8',
  novita: '#10b981',
  nvidia: '#76b900',
  nvidia_nim: '#76b900',
  oci: '#c74634',
  ollama: '#111827',
  ollama_chat: '#111827',
  openai: '#10a37f',
  openai_like: '#10a37f',
  openrouter: '#6467f2',
  oracle: '#c74634',
  perplexity: '#20808d',
  replicate: '#ef4444',
  sagemaker: '#ff9900',
  sambanova: '#ee3124',
  tencent: '#1476ff',
  together: '#0f6fff',
  together_ai: '#0f6fff',
  triton: '#76b900',
  v0: '#111827',
  vercel: '#111827',
  vertex_ai: '#1a73e8',
  vllm: '#12b981',
  volcengine: '#1664ff',
  wandb: '#ffbe00',
  watsonx: '#0f62fe',
  xai: '#111827',
}

/**
 * The fallback palette for a provider with no curated colour.
 *
 * Chosen from the id by hash rather than at random, so a provider keeps the
 * same tile every time the grid renders.
 */
const PALETTE = [
  '#2563eb',
  '#7c3aed',
  '#db2777',
  '#dc2626',
  '#ea580c',
  '#d97706',
  '#16a34a',
  '#0891b2',
  '#4f46e5',
  '#9333ea',
  '#0d9488',
  '#c026d3',
]

/**
 * Pick a stable palette entry for an id with no curated colour.
 *
 * @param id - The provider id or icon slug.
 * @returns A hex colour, the same one for the same id on every render.
 */
function paletteFor(id: string): string {
  let hash = 0
  for (let index = 0; index < id.length; index += 1) {
    hash = (hash * 31 + id.charCodeAt(index)) >>> 0
  }
  return PALETTE[hash % PALETTE.length] ?? PALETTE[0]
}

/**
 * Choose a legible text colour for a background.
 *
 * @param hex - A six digit hex colour, with or without the leading hash.
 * @returns Near black on a light background, white on a dark one.
 */
function textOn(hex: string): string {
  const value = hex.replace('#', '')
  const channel = (start: number): number =>
    Number.parseInt(value.slice(start, start + 2), 16) / 255
  const linear = (c: number): number => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  const luminance =
    0.2126 * linear(channel(0)) + 0.7152 * linear(channel(2)) + 0.0722 * linear(channel(4))
  return luminance > 0.5 ? '#111827' : '#ffffff'
}

/**
 * The first letter to show, skipping any leading punctuation or digits.
 *
 * @param id - The provider id or icon slug.
 * @returns One uppercase character, or a question mark when there is none.
 */
function monogramFor(id: string): string {
  const letter = id.replace(/[^a-zA-Z0-9]/g, '').slice(0, 1)
  return letter ? letter.toUpperCase() : '?'
}

export interface ProviderIconProps {
  /** A LiteLLM provider id such as `together_ai`, or the catalog icon slug. */
  provider: string
  className?: string
}

/**
 * A provider's monogram tile.
 *
 * @param provider - The provider id or its icon slug. Both are accepted because
 *   the catalog serves both and either identifies the same brand.
 * @param className - Sizing and shape. Defaults to a 32 pixel rounded square.
 */
export function ProviderIcon({ provider, className }: ProviderIconProps) {
  const key = (provider || '').trim().toLowerCase()
  const background = BRAND_COLOR[key] ?? paletteFor(key)

  return (
    <span
      aria-hidden="true"
      data-provider={key}
      style={{ backgroundColor: background, color: textOn(background) }}
      className={cn(
        'inline-flex size-8 shrink-0 items-center justify-center rounded-lg text-sm font-semibold',
        className
      )}
    >
      {monogramFor(key)}
    </span>
  )
}
