import type {
  AddFreezeQtyRequest,
  AddHolidayRequest,
  AdminStats,
  FreezeQty,
  Holiday,
  HolidaysResponse,
  TimingsResponse,
  TodayTiming,
  UpdateFreezeQtyRequest,
  UpdateTimingRequest,
} from '@/types/admin'
import { webClient } from './client'

interface ApiResponse<T = void> {
  status: string
  message?: string
  data?: T
}

export const adminApi = {
  // ============================================================================
  // Admin Stats
  // ============================================================================

  /**
   * Get admin dashboard stats
   */
  getStats: async (): Promise<AdminStats> => {
    const response = await webClient.get<ApiResponse<void> & AdminStats>('/admin/api/stats')
    return {
      freeze_count: response.data.freeze_count,
      holiday_count: response.data.holiday_count,
    }
  },

  // ============================================================================
  // Freeze Quantity APIs
  // ============================================================================

  /**
   * Get all freeze quantities
   */
  getFreezeList: async (): Promise<FreezeQty[]> => {
    const response = await webClient.get<ApiResponse<FreezeQty[]>>('/admin/api/freeze')
    return response.data.data || []
  },

  /**
   * Add a new freeze quantity entry
   */
  addFreeze: async (data: AddFreezeQtyRequest): Promise<ApiResponse<FreezeQty>> => {
    const response = await webClient.post<ApiResponse<FreezeQty>>('/admin/api/freeze', data)
    return response.data
  },

  /**
   * Edit a freeze quantity entry
   */
  editFreeze: async (id: number, data: UpdateFreezeQtyRequest): Promise<ApiResponse<FreezeQty>> => {
    const response = await webClient.put<ApiResponse<FreezeQty>>(`/admin/api/freeze/${id}`, data)
    return response.data
  },

  /**
   * Delete a freeze quantity entry
   */
  deleteFreeze: async (id: number): Promise<ApiResponse> => {
    const response = await webClient.delete<ApiResponse>(`/admin/api/freeze/${id}`)
    return response.data
  },

  /**
   * Upload CSV file to update freeze quantities
   */
  uploadFreezeCSV: async (
    file: File,
    exchange: string
  ): Promise<ApiResponse<{ count: number }>> => {
    const formData = new FormData()
    formData.append('csv_file', file)
    formData.append('exchange', exchange)

    const response = await webClient.post<ApiResponse<{ count: number }>>(
      '/admin/api/freeze/upload',
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      }
    )
    return response.data
  },

  // ============================================================================
  // Holiday APIs
  // ============================================================================

  /**
   * Get holidays for a specific year
   */
  getHolidays: async (year?: number): Promise<HolidaysResponse> => {
    const params = year ? `?year=${year}` : ''
    const response = await webClient.get<HolidaysResponse>(`/admin/api/holidays${params}`)
    return response.data
  },

  /**
   * Add a new holiday
   */
  addHoliday: async (data: AddHolidayRequest): Promise<ApiResponse<Holiday>> => {
    const response = await webClient.post<ApiResponse<Holiday>>('/admin/api/holidays', data)
    return response.data
  },

  /**
   * Delete a holiday
   */
  deleteHoliday: async (id: number): Promise<ApiResponse> => {
    const response = await webClient.delete<ApiResponse>(`/admin/api/holidays/${id}`)
    return response.data
  },

  // ============================================================================
  // Market Timings APIs
  // ============================================================================

  /**
   * Get all market timings
   */
  getTimings: async (): Promise<TimingsResponse> => {
    const response = await webClient.get<TimingsResponse>('/admin/api/timings')
    return response.data
  },

  /**
   * Edit market timing for an exchange
   */
  editTiming: async (exchange: string, data: UpdateTimingRequest): Promise<ApiResponse> => {
    const response = await webClient.put<ApiResponse>(`/admin/api/timings/${exchange}`, data)
    return response.data
  },

  /**
   * Check market timings for a specific date
   */
  checkTimings: async (date: string): Promise<{ date: string; timings: TodayTiming[] }> => {
    const response = await webClient.post<ApiResponse & { date: string; timings: TodayTiming[] }>(
      '/admin/api/timings/check',
      { date }
    )
    return { date: response.data.date, timings: response.data.timings }
  },
}
