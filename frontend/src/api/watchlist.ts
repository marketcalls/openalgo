/**
 * Watchlist API for the charting terminal.
 *
 * Served by blueprints/watchlist.py under the root path (not /api/v1), so this
 * uses webClient, which carries the session cookie and the CSRF token. The
 * lists belong to the signed-in user, so no API key appears in any of these
 * calls.
 *
 * Prices are deliberately absent: the panel gets them from the app's shared
 * market-data feed via useLivePrice, not from this module.
 */

import { webClient } from './client'

export interface WatchlistItem {
  id: number
  symbol: string
  exchange: string
  position: number
}

export interface Watchlist {
  id: number
  name: string
  position: number
  items: WatchlistItem[]
}

interface Envelope<T> {
  status: 'success' | 'error'
  data: T
  message?: string
}

export const watchlistApi = {
  list: async (): Promise<Watchlist[]> => {
    const res = await webClient.get<Envelope<Watchlist[]>>('/watchlist/api/lists')
    return res.data.data ?? []
  },

  /** `items` duplicates a list in one call: used by "make a copy" and import. */
  create: async (
    name: string,
    items?: Array<{ symbol: string; exchange: string }>
  ): Promise<Watchlist> => {
    const res = await webClient.post<Envelope<Watchlist>>('/watchlist/api/lists', {
      name,
      ...(items ? { items } : {}),
    })
    return res.data.data
  },

  rename: async (id: number, name: string): Promise<void> => {
    await webClient.patch(`/watchlist/api/lists/${id}`, { name })
  },

  remove: async (id: number): Promise<void> => {
    await webClient.delete(`/watchlist/api/lists/${id}`)
  },

  clear: async (id: number): Promise<void> => {
    await webClient.post(`/watchlist/api/lists/${id}/clear`)
  },

  addItem: async (id: number, symbol: string, exchange: string): Promise<WatchlistItem> => {
    const res = await webClient.post<Envelope<WatchlistItem>>(`/watchlist/api/lists/${id}/items`, {
      symbol,
      exchange,
    })
    return res.data.data
  },

  removeItem: async (id: number, itemId: number): Promise<void> => {
    await webClient.delete(`/watchlist/api/lists/${id}/items/${itemId}`)
  },

  reorderItems: async (id: number, order: number[]): Promise<void> => {
    await webClient.put(`/watchlist/api/lists/${id}/items/order`, { order })
  },
}

/**
 * Turn an axios failure into the message the server actually sent.
 *
 * The blueprint answers a name clash and a full list with a 409 carrying a
 * sentence written for the user ("A list named X already exists"). Axios throws
 * on that, and its own message is "Request failed with status code 409", which
 * tells the user nothing they can act on.
 */
export function watchlistError(error: unknown, fallback: string): string {
  const message = (error as { response?: { data?: { message?: string } } })?.response?.data?.message
  return message || fallback
}
