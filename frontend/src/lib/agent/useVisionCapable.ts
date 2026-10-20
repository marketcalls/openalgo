/**
 * Whether the model this turn will run on can read an image.
 *
 * The composer needs this before a file is picked, because an image on a
 * text-only model is refused by `build_agent` with a 400 that names the model,
 * and a menu that offers "Attach files" and then fails on send has spent the
 * operator's time to tell them something it already knew.
 *
 * **It is not the `supports_vision` column.** That column is an operator
 * checkbox, and `services/agent/providers.vision_capable` overrules it in both
 * directions before a run: LiteLLM decides for any model it ships metadata for,
 * and the checkbox is the fallback only for one it has never heard of. The
 * models route resolves `supports_reasoning` that way before answering and does
 * **not** yet do the same for vision, so a client reading the row alone would
 * disable attaching on a model that can see (both models configured on this
 * instance are exactly that case: the column says no, LiteLLM says yes, and an
 * image works) and offer it on one that cannot.
 *
 * So the answer is assembled from the two things the API does expose, using the
 * server's own rule and the server's own data:
 *
 *   catalog knows this model  ->  the catalog's answer
 *   catalog has never heard   ->  the row's checkbox
 *
 * `GET /agent/api/catalog/models` is built from `litellm.model_cost`, which is
 * the same table `_litellm_opinion` consults, and `in_catalog` is the same
 * membership test that separates "LiteLLM says no" from "LiteLLM has no
 * opinion". The two therefore agree for the same reason rather than by
 * coincidence, and where they somehow do not, the server's 400 is still there
 * and still names the model.
 *
 * **Unknown is treated as capable.** A models call that has not answered yet, a
 * catalog the server cannot build because LiteLLM is not installed, a provider
 * it does not list: none of those is evidence that a model cannot see. Refusing
 * to let the operator attach anything on a maybe is the worse failure, and the
 * turn would be refused server-side with a message written for them.
 *
 * The catalogue is package data that changes when `litellm` is bumped, and both
 * queries share their keys with the model picker and the config page, so this
 * usually costs no request at all.
 */

import { useQuery } from '@tanstack/react-query'
import {
  type AgentModel,
  agentQueryKeys,
  listCatalogModels,
  listModels,
  type ProviderKind,
} from '@/api/agent'

/**
 * The LiteLLM provider prefix each kind resolves to.
 *
 * Mirrors `PROVIDER_KINDS` in `services/agent/providers.py`: an
 * `openai_compatible` row is addressed as `openai/{name}` and is looked up in
 * OpenAI's table, and a `litellm` row carries its own prefix, which is why it
 * has none here.
 */
const PROVIDER_PREFIX: Record<ProviderKind, string> = {
  openai: 'openai',
  anthropic: 'anthropic',
  ollama: 'ollama',
  openai_compatible: 'openai',
  litellm: '',
}

/** Which catalogue entry answers for a configured model. */
interface CatalogTarget {
  /** The LiteLLM provider id, which is what the catalogue route is keyed by. */
  provider: string
  /** The model name as the catalogue lists it, without a provider prefix. */
  name: string
}

/**
 * Where to look this model up.
 *
 * @param model - The configured row.
 * @returns The provider and bare model name, or null when the row names
 *   neither, which is a `litellm` row whose model name carries no prefix.
 */
function catalogTarget(model: AgentModel): CatalogTarget | null {
  const name = (model.model_name || '').trim()
  if (!name) return null
  const prefix = PROVIDER_PREFIX[model.provider_kind] ?? ''
  if (prefix) {
    return {
      provider: prefix,
      name: name.startsWith(`${prefix}/`) ? name.slice(prefix.length + 1) : name,
    }
  }
  const cut = name.indexOf('/')
  if (cut <= 0) return null
  return { provider: name.slice(0, cut), name: name.slice(cut + 1) }
}

export interface VisionCapability {
  /** True when an image may be attached. True while the answer is unknown. */
  canSee: boolean
  /** The model the answer is about, for a message that names it. */
  label: string
}

/**
 * Whether the selected model can read an image.
 *
 * @param modelId - The picked model, or null to ask about the configured
 *   default, which is what a surface with no picker runs on.
 * @returns Whether an image may be attached, and the model's own name.
 */
export function useVisionCapable(modelId: number | null | undefined): VisionCapability {
  const models = useQuery({
    queryKey: agentQueryKeys.models(),
    queryFn: listModels,
    staleTime: 60_000,
  })

  const rows = models.data ?? []
  const row =
    rows.find((model) => model.id === modelId) ?? rows.find((model) => model.is_default) ?? null
  const target = row ? catalogTarget(row) : null

  const catalog = useQuery({
    queryKey: agentQueryKeys.catalogModels(target?.provider ?? '', true),
    queryFn: () => listCatalogModels(target?.provider ?? '', true),
    enabled: target !== null,
    staleTime: 10 * 60_000,
  })

  if (!row) return { canSee: true, label: '' }

  const label = row.display_name || row.model_name

  // Nothing to check against yet, so nothing is refused. The row's own column
  // is **not** the fallback here: it is the fallback for a model the catalogue
  // has answered about and does not carry, which is a different question from
  // a catalogue that has not answered. Reading the column while the request is
  // still in flight disables attaching for a second on every model whose
  // checkbox is unticked, which is all of them.
  if (!target || !catalog.isSuccess || catalog.data.available !== true) {
    return { canSee: true, label }
  }

  const entry = catalog.data.data.find(
    (model) => model.id === target.name || model.qualified_id === row.model_name
  )

  // The server's rule, in the server's order: the catalogue decides for a model
  // it carries metadata for, and the operator's checkbox is the fallback for
  // one it has never heard of.
  const canSee = entry?.in_catalog ? entry.supports_vision === true : Boolean(row.supports_vision)
  return { canSee, label }
}
