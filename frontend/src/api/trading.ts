import { apiClient } from './client';
import type {
  Position,
  Order,
  Trade,
  Holding,
  PortfolioStats,
  MarginData,
  OrderStats,
  PlaceOrderRequest,
  ApiResponse,
} from '@/types/trading';

export const tradingApi = {
  /**
   * Get margin/funds data
   */
  getFunds: async (apiKey: string): Promise<ApiResponse<MarginData>> => {
    const response = await apiClient.post<ApiResponse<MarginData>>('/api/v1/funds', {
      apikey: apiKey,
    });
    return response.data;
  },

  /**
   * Get positions
   */
  getPositions: async (apiKey: string): Promise<ApiResponse<Position[]>> => {
    const response = await apiClient.post<ApiResponse<Position[]>>('/api/v1/positionbook', {
      apikey: apiKey,
    });
    return response.data;
  },

  /**
   * Get order book
   */
  getOrders: async (apiKey: string): Promise<ApiResponse<{ orders: Order[]; statistics: OrderStats }>> => {
    const response = await apiClient.post<ApiResponse<{ orders: Order[]; statistics: OrderStats }>>('/api/v1/orderbook', {
      apikey: apiKey,
    });
    return response.data;
  },

  /**
   * Get trade book
   */
  getTrades: async (apiKey: string): Promise<ApiResponse<Trade[]>> => {
    const response = await apiClient.post<ApiResponse<Trade[]>>('/api/v1/tradebook', {
      apikey: apiKey,
    });
    return response.data;
  },

  /**
   * Get holdings
   */
  getHoldings: async (apiKey: string): Promise<ApiResponse<{ holdings: Holding[]; statistics: PortfolioStats }>> => {
    const response = await apiClient.post<ApiResponse<{ holdings: Holding[]; statistics: PortfolioStats }>>('/api/v1/holdings', {
      apikey: apiKey,
    });
    return response.data;
  },

  /**
   * Place order
   */
  placeOrder: async (order: PlaceOrderRequest): Promise<ApiResponse<{ orderid: string }>> => {
    const response = await apiClient.post<ApiResponse<{ orderid: string }>>('/api/v1/place_order', order);
    return response.data;
  },

  /**
   * Modify order
   */
  modifyOrder: async (
    apiKey: string,
    orderid: string,
    updates: Partial<PlaceOrderRequest>
  ): Promise<ApiResponse<{ orderid: string }>> => {
    const response = await apiClient.post<ApiResponse<{ orderid: string }>>('/api/v1/modify_order', {
      apikey: apiKey,
      orderid,
      ...updates,
    });
    return response.data;
  },

  /**
   * Cancel order
   */
  cancelOrder: async (apiKey: string, orderid: string, strategy: string): Promise<ApiResponse<void>> => {
    const response = await apiClient.post<ApiResponse<void>>('/api/v1/cancel_order', {
      apikey: apiKey,
      orderid,
      strategy,
    });
    return response.data;
  },

  /**
   * Close a specific position
   */
  closePosition: async (
    symbol: string,
    exchange: string,
    product: string
  ): Promise<ApiResponse<void>> => {
    // Uses the web route which handles session-based auth
    const response = await apiClient.post<ApiResponse<void>>('/close_position', {
      symbol,
      exchange,
      product,
    });
    return response.data;
  },

  /**
   * Close all positions
   */
  closeAllPositions: async (): Promise<ApiResponse<void>> => {
    const response = await apiClient.post<ApiResponse<void>>('/close_all_positions', {});
    return response.data;
  },

  /**
   * Cancel all orders
   */
  cancelAllOrders: async (apiKey: string, strategy: string): Promise<ApiResponse<void>> => {
    const response = await apiClient.post<ApiResponse<void>>('/api/v1/cancel_all_orders', {
      apikey: apiKey,
      strategy,
    });
    return response.data;
  },
};
