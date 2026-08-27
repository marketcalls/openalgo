import axios from 'axios'
import type { ApiResponse } from '@/types/trading'
import { webClient } from './client'

export const pythonStrategyCustomApi = {
  forceStartStrategy: async (strategyId: string): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(
      `/python-custom/start-force/${strategyId}`
    )
    return response.data
  },

  addStrategyFromPath: async (
    name: string,
    strategyPath: string,
    schedule: {
      start_time: string
      stop_time: string
      days: string[]
      exchange?: string
      working_dir?: string
    }
  ): Promise<ApiResponse<{ strategy_id: string }>> => {
    const payload = {
      strategy_name: name,
      strategy_path: strategyPath,
      exchange: schedule.exchange || 'NSE',
      schedule_start: schedule.start_time,
      schedule_stop: schedule.stop_time,
      schedule_days: schedule.days,
      working_dir: schedule.working_dir,
    }
    try {
      const response = await webClient.post<ApiResponse<{ strategy_id: string }>>(
        '/python-custom/new-path',
        payload
      )
      return response.data
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 404) {
        const fallback = await webClient.post<ApiResponse<{ strategy_id: string }>>(
          '/python/new-path',
          payload
        )
        return fallback.data
      }
      throw error
    }
  },

  uploadStrategy: async (
    name: string,
    file: File,
    schedule: {
      start_time: string
      stop_time: string
      days: string[]
      exchange?: string
    }
  ): Promise<ApiResponse<{ strategy_id: string }>> => {
    const formData = new FormData()
    formData.append('strategy_name', name)
    formData.append('strategy_file', file)
    formData.append('exchange', schedule.exchange || 'NSE')
    formData.append('schedule_start', schedule.start_time)
    formData.append('schedule_stop', schedule.stop_time)
    formData.append('schedule_days', JSON.stringify(schedule.days))

    try {
      const response = await webClient.post<ApiResponse<{ strategy_id: string }>>(
        '/python-custom/new',
        formData,
        {
          headers: {
            'Content-Type': 'multipart/form-data',
          },
        }
      )
      return response.data
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 404) {
        const fallback = await webClient.post<ApiResponse<{ strategy_id: string }>>(
          '/python/new',
          formData,
          {
            headers: {
              'Content-Type': 'multipart/form-data',
            },
          }
        )
        return fallback.data
      }
      throw error
    }
  },
}
