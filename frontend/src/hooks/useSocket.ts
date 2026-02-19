import { useCallback, useEffect, useRef } from 'react'
import { io, type Socket } from 'socket.io-client'
import { toast } from 'sonner'
import { useAlertStore, type AlertCategories } from '@/stores/alertStore'
import { useAuthStore } from '@/stores/authStore'

// Audio throttling configuration
const AUDIO_THROTTLE_MS = 1000

interface OrderEventData {
  symbol: string
  action: string
  orderid: string
  batch_order?: boolean
  is_last_order?: boolean
}

interface CancelOrderEventData {
  orderid: string
  batch_order?: boolean
}

interface ModifyOrderEventData {
  orderid: string
  status: string
}

interface ClosePositionEventData {
  message: string
  status: string
}

interface MasterContractData {
  message: string
}

interface AnalyzerUpdateData {
  request: {
    api_type: string
    symbol?: string
    action?: string
    quantity?: string
    orderid?: string
    position_size?: string
  }
  response: {
    status: string
    message?: string
    orderid?: string
    canceled_orders?: string[]
  }
}

// Helper to show toast only if enabled for category
const showCategoryToast = (
  type: 'success' | 'error' | 'warning' | 'info',
  message: string,
  category?: keyof AlertCategories
) => {
  const { shouldShowToast } = useAlertStore.getState()
  if (shouldShowToast(category)) {
    toast[type](message)
  }
}

export function useSocket() {
  const { isAuthenticated } = useAuthStore()
  const socketRef = useRef<Socket | null>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const lastAudioTimeRef = useRef<number>(0)
  const audioEnabledRef = useRef<boolean>(false)

  const playAlertSound = useCallback((category?: keyof AlertCategories) => {
    // Check if sound should play based on alert settings
    const { shouldPlaySound, shouldShowToast } = useAlertStore.getState()
    if (!shouldPlaySound()) return
    // If category specified, also check category is enabled
    if (category && !shouldShowToast(category)) return

    const now = Date.now()
    const timeSinceLastAttempt = now - lastAudioTimeRef.current

    if (timeSinceLastAttempt < AUDIO_THROTTLE_MS && lastAudioTimeRef.current !== 0) {
      return
    }

    lastAudioTimeRef.current = now

    if (audioRef.current) {
      audioRef.current
        .play()
        .then(() => {
          audioEnabledRef.current = true
        })
        .catch(() => {})
    }
  }, [])

  const enableAudio = useCallback(() => {
    if (!audioEnabledRef.current && audioRef.current) {
      const audio = audioRef.current
      const originalVolume = audio.volume
      audio.volume = 0
      audio
        .play()
        .then(() => {
          audio.pause()
          audio.currentTime = 0
          audio.volume = originalVolume
          audioEnabledRef.current = true
        })
        .catch(() => {
          audio.volume = originalVolume
        })
    }
  }, [])

  useEffect(() => {
    // Only connect when authenticated
    if (!isAuthenticated) {
      return
    }

    // Create audio element
    audioRef.current = new Audio('/sounds/alert.mp3')
    audioRef.current.preload = 'auto'

    // Enable audio on user interaction
    const handleInteraction = () => {
      enableAudio()
    }

    ;['click', 'touchstart', 'keydown'].forEach((eventType) => {
      document.addEventListener(eventType, handleInteraction, { once: true, passive: true })
    })

    // Connect to socket server
    const protocol = window.location.protocol
    const host = window.location.hostname
    const port = window.location.port

    // Use polling transport only - WebSocket upgrade fails with threading async mode
    // Polling is still real-time via HTTP long-polling
    socketRef.current = io(`${protocol}//${host}:${port}`, {
      transports: ['polling'],
      upgrade: false,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
      timeout: 20000,
      forceNew: true, // Always create new session to avoid "Invalid session" errors on reconnect
    })

    const socket = socketRef.current

    // Password change notification
    socket.on('password_change', (data: { message: string }) => {
      playAlertSound('system')
      showCategoryToast('info', data.message, 'system')
    })

    // Master contract download notification
    socket.on('master_contract_download', (data: MasterContractData) => {
      playAlertSound('system')
      showCategoryToast('info', `Master Contract: ${data.message}`, 'system')
    })

    // Cancel order notification - only play sound, UI handles toast
    socket.on('cancel_order_event', (data: CancelOrderEventData) => {
      if (!data.batch_order) {
        playAlertSound('orders')
      }
    })

    // Modify order notification - only play sound, UI handles toast
    socket.on('modify_order_event', (_data: ModifyOrderEventData) => {
      playAlertSound('orders')
    })

    // Close position notification
    socket.on('close_position_event', (data: ClosePositionEventData) => {
      playAlertSound('orders')
      showCategoryToast(
        'success',
        data.message || 'All Open Positions Squared Off',
        'positions'
      )
    })

    // Order placement notification
    socket.on('order_event', (data: OrderEventData) => {
      const shouldPlayAudio = !data.batch_order || data.is_last_order
      if (shouldPlayAudio) {
        playAlertSound('orders')
      }

      const message = `${data.action.toUpperCase()} Order Placed for Symbol: ${data.symbol}, Order ID: ${data.orderid}`
      if (data.action.toUpperCase() === 'BUY') {
        showCategoryToast('success', message, 'orders')
      } else {
        showCategoryToast('error', message, 'orders')
      }
    })

    // Generic order notification handler
    socket.on(
      'order_notification',
      (data: { symbol?: string; status?: string; message?: string }) => {
        playAlertSound('orders')

        let type: 'success' | 'error' | 'warning' | 'info' = 'info'
        if (data.status && typeof data.status === 'string') {
          if (data.status.toLowerCase().includes('success')) {
            type = 'success'
          } else if (
            data.status.toLowerCase().includes('error') ||
            data.status.toLowerCase().includes('reject')
          ) {
            type = 'error'
          } else if (data.status.toLowerCase().includes('pending')) {
            type = 'warning'
          }
        }

        let message = ''
        if (data.symbol) {
          message += `${data.symbol}: `
        }
        if (data.status) {
          message += data.status
        }
        if (data.message) {
          message += data.message
        }

        showCategoryToast(type, message, 'orders')
      }
    )

    // Analyzer update notification
    socket.on('analyzer_update', (data: AnalyzerUpdateData) => {
      const passiveApiTypes = [
        'orderstatus',
        'openposition',
        'orderbook',
        'tradebook',
        'positions',
        'holdings',
      ]
      const isPassiveMonitoring = passiveApiTypes.includes(data.request.api_type)

      if (!isPassiveMonitoring) {
        playAlertSound('analyzer')
      }

      let message = ''
      let type: 'success' | 'error' | 'info' =
        data.response.status === 'success' ? 'success' : 'error'

      const action = data.request.action || ''
      const symbol = data.request.symbol || ''
      const quantity = data.request.quantity || ''
      const orderid = data.response.orderid || data.request.orderid || ''
      const apiType = data.request.api_type || ''

      if (data.response.status === 'error') {
        message = `Error: ${data.response.message}`
        if (symbol) message = `${symbol} - ${message}`
      } else if (apiType === 'cancelorder') {
        message = orderid ? `Order Cancelled - ID: ${orderid}` : 'Order Cancelled'
      } else if (apiType === 'cancelallorder') {
        message = data.response.message || 'All Orders Cancelled'
      } else if (apiType === 'modifyorder') {
        message = orderid ? `Order Modified - ID: ${orderid}` : 'Order Modified'
      } else if (apiType === 'closeposition') {
        message = data.response.message || 'Position Closed'
      } else if (
        apiType === 'placesmartorder' &&
        data.response.message &&
        (data.response.message.includes('Positions Already Matched') ||
          data.response.message.includes('No OpenPosition Found'))
      ) {
        message = data.response.message
        type = 'info'
      } else {
        if (!action && !symbol && !orderid) {
          return
        }

        if (action && symbol) {
          message = `${action} Order Placed for Symbol: ${symbol}`
          if (quantity) message += `, Qty: ${quantity}`
          if (orderid) message += `, Order ID: ${orderid}`

          if (apiType === 'placesmartorder' && data.request.position_size) {
            message += `, Size: ${data.request.position_size}`
          }
        } else if (orderid) {
          message = `Order Placed - ID: ${orderid}`
        } else {
          return
        }
      }

      if (message) {
        showCategoryToast(type, message, 'analyzer')
      }
    })

    return () => {
      socket.disconnect()
      ;['click', 'touchstart', 'keydown'].forEach((eventType) => {
        document.removeEventListener(eventType, handleInteraction)
      })
    }
  }, [isAuthenticated, playAlertSound, enableAudio])

  return {
    socket: socketRef.current,
    playAlertSound,
  }
}
