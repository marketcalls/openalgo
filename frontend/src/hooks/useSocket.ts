import { useEffect, useRef, useCallback } from 'react';
import { io, Socket } from 'socket.io-client';
import { toast } from 'sonner';
import { useAuthStore } from '@/stores/authStore';

// Audio throttling configuration
const AUDIO_THROTTLE_MS = 1000;

interface OrderEventData {
  symbol: string;
  action: string;
  orderid: string;
  batch_order?: boolean;
  is_last_order?: boolean;
}

interface CancelOrderEventData {
  orderid: string;
  batch_order?: boolean;
}

interface ModifyOrderEventData {
  orderid: string;
  status: string;
}

interface ClosePositionEventData {
  message: string;
  status: string;
}

interface MasterContractData {
  message: string;
}

interface AnalyzerUpdateData {
  request: {
    api_type: string;
    symbol?: string;
    action?: string;
    quantity?: string;
    orderid?: string;
    position_size?: string;
  };
  response: {
    status: string;
    message?: string;
    orderid?: string;
    canceled_orders?: string[];
  };
}

export function useSocket() {
  const { isAuthenticated } = useAuthStore();
  const socketRef = useRef<Socket | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const lastAudioTimeRef = useRef<number>(0);
  const audioEnabledRef = useRef<boolean>(false);

  const playAlertSound = useCallback(() => {
    const now = Date.now();
    const timeSinceLastAttempt = now - lastAudioTimeRef.current;

    if (timeSinceLastAttempt < AUDIO_THROTTLE_MS && lastAudioTimeRef.current !== 0) {
      console.log('[Audio] Throttled - too soon since last sound');
      return;
    }

    lastAudioTimeRef.current = now;

    if (audioRef.current) {
      console.log('[Audio] Attempting to play alert sound...');
      audioRef.current.play()
        .then(() => {
          console.log('[Audio] Sound played successfully');
          audioEnabledRef.current = true;
        })
        .catch((error) => {
          console.error('[Audio] Failed to play:', error);
        });
    } else {
      console.warn('[Audio] No audio element available');
    }
  }, []);

  const enableAudio = useCallback(() => {
    if (!audioEnabledRef.current && audioRef.current) {
      const audio = audioRef.current;
      const originalVolume = audio.volume;
      audio.volume = 0;
      audio.play()
        .then(() => {
          audio.pause();
          audio.currentTime = 0;
          audio.volume = originalVolume;
          audioEnabledRef.current = true;
        })
        .catch(() => {
          audio.volume = originalVolume;
        });
    }
  }, []);

  useEffect(() => {
    // Only connect when authenticated
    if (!isAuthenticated) {
      console.log('[Socket] Not authenticated, skipping socket connection');
      return;
    }

    console.log('[Socket] Initializing socket connection...');

    // Create audio element - use Flask static path
    audioRef.current = new Audio('/static/sounds/alert.mp3');
    audioRef.current.preload = 'auto';
    console.log('[Socket] Audio element created');

    // Enable audio on user interaction
    const handleInteraction = () => {
      enableAudio();
    };

    ['click', 'touchstart', 'keydown'].forEach(eventType => {
      document.addEventListener(eventType, handleInteraction, { once: true, passive: true });
    });

    // Connect to socket server
    const protocol = window.location.protocol;
    const host = window.location.hostname;
    const port = window.location.port;

    socketRef.current = io(`${protocol}//${host}:${port}`, {
      transports: ['websocket', 'polling'],
    });

    const socket = socketRef.current;

    socket.on('connect', () => {
      console.log('[Socket] Connected successfully');
    });

    socket.on('disconnect', () => {
      console.log('[Socket] Disconnected');
    });

    socket.on('connect_error', (error) => {
      console.error('[Socket] Connection error:', error);
    });

    // Password change notification
    socket.on('password_change', (data: { message: string }) => {
      console.log('[Socket] password_change event:', data);
      playAlertSound();
      toast.info(data.message);
    });

    // Master contract download notification
    socket.on('master_contract_download', (data: MasterContractData) => {
      console.log('[Socket] master_contract_download event:', data);
      playAlertSound();
      toast.info(`Master Contract: ${data.message}`);
    });

    // Cancel order notification - only play sound, UI handles toast
    socket.on('cancel_order_event', (data: CancelOrderEventData) => {
      if (!data.batch_order) {
        playAlertSound();
      }
    });

    // Modify order notification - only play sound, UI handles toast
    socket.on('modify_order_event', (_data: ModifyOrderEventData) => {
      playAlertSound();
    });

    // Close position notification - only play sound, UI handles toast
    socket.on('close_position_event', (_data: ClosePositionEventData) => {
      playAlertSound();
    });

    // Order placement notification
    socket.on('order_event', (data: OrderEventData) => {
      console.log('[Socket] order_event received:', data);
      const shouldPlayAudio = !data.batch_order || data.is_last_order;
      if (shouldPlayAudio) {
        console.log('[Socket] Playing alert sound for order');
        playAlertSound();
      }

      const message = `${data.action.toUpperCase()} Order Placed for Symbol: ${data.symbol}, Order ID: ${data.orderid}`;
      if (data.action.toUpperCase() === 'BUY') {
        toast.success(message);
      } else {
        toast.error(message);
      }
    });

    // Generic order notification handler
    socket.on('order_notification', (data: { symbol?: string; status?: string; message?: string }) => {
      playAlertSound();

      let type: 'success' | 'error' | 'warning' | 'info' = 'info';
      if (data.status && typeof data.status === 'string') {
        if (data.status.toLowerCase().includes('success')) {
          type = 'success';
        } else if (data.status.toLowerCase().includes('error') || data.status.toLowerCase().includes('reject')) {
          type = 'error';
        } else if (data.status.toLowerCase().includes('pending')) {
          type = 'warning';
        }
      }

      let message = '';
      if (data.symbol) {
        message += `${data.symbol}: `;
      }
      if (data.status) {
        message += data.status;
      }
      if (data.message) {
        message += data.message;
      }

      toast[type](message);
    });

    // Analyzer update notification
    socket.on('analyzer_update', (data: AnalyzerUpdateData) => {
      const passiveApiTypes = ['orderstatus', 'openposition', 'orderbook', 'tradebook', 'positions', 'holdings'];
      const isPassiveMonitoring = passiveApiTypes.includes(data.request.api_type);

      if (!isPassiveMonitoring) {
        playAlertSound();
      }

      let message = '';
      let type: 'success' | 'error' | 'info' = data.response.status === 'success' ? 'success' : 'error';

      // Skip toast for cancelorder/modifyorder/cancelallorder/closeposition - UI handles these
      if (data.request.api_type === 'cancelorder' ||
          data.request.api_type === 'modifyorder' ||
          data.request.api_type === 'cancelallorder' ||
          data.request.api_type === 'closeposition') {
        return;
      } else {
        const action = data.request.action || '';
        const symbol = data.request.symbol || '';
        const quantity = data.request.quantity || '';
        const orderid = data.response.orderid || '';

        if (data.response.status === 'error') {
          message = `Error: ${data.response.message}`;
          if (symbol) message = `${symbol} - ${message}`;
        } else if (
          data.request.api_type === 'placesmartorder' &&
          data.response.message &&
          (data.response.message.includes('Positions Already Matched') ||
            data.response.message.includes('No OpenPosition Found'))
        ) {
          message = data.response.message;
          type = 'info';
        } else {
          if (!action && !symbol && !orderid) {
            return;
          }

          if (action && symbol) {
            message = `${action} Order Placed for Symbol: ${symbol}`;
            if (quantity) message += `, Qty: ${quantity}`;
            if (orderid) message += `, Order ID: ${orderid}`;

            if (data.request.api_type === 'placesmartorder' && data.request.position_size) {
              message += `, Size: ${data.request.position_size}`;
            }
          } else if (orderid) {
            message = `Order Placed - ID: ${orderid}`;
          } else {
            return;
          }
        }
      }

      if (message) {
        toast[type](message);
      }
    });

    return () => {
      socket.disconnect();
      ['click', 'touchstart', 'keydown'].forEach(eventType => {
        document.removeEventListener(eventType, handleInteraction);
      });
    };
  }, [isAuthenticated, playAlertSound, enableAudio]);

  return {
    socket: socketRef.current,
    playAlertSound,
  };
}
