import { create } from 'zustand'

interface BrokerCapabilities {
  broker_name: string
  broker_type: 'IN_stock' | 'crypto'
  supported_exchanges: string[]
  leverage_config: boolean
}

interface BrokerStore {
  capabilities: BrokerCapabilities | null
  isLoaded: boolean

  fetchCapabilities: () => Promise<void>
  clearCapabilities: () => void
}

// The navbar and its account controls both ask at mount, before either has an
// answer; they share the request in flight instead of sending two.
let inflight: Promise<void> | null = null

export const useBrokerStore = create<BrokerStore>()((set) => ({
  capabilities: null,
  isLoaded: false,

  fetchCapabilities: () => {
    inflight ??= (async () => {
      try {
        const response = await fetch('/api/broker/capabilities', {
          credentials: 'include',
        })

        if (response.ok) {
          const data = await response.json()
          if (data.status === 'success' && data.data) {
            set({ capabilities: data.data, isLoaded: true })
          }
        }
      } catch {
        // Silently fail — capabilities will be null, pages fall back to showing all exchanges
      } finally {
        inflight = null
      }
    })()
    return inflight
  },

  clearCapabilities: () => set({ capabilities: null, isLoaded: false }),
}))
