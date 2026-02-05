import { useState, useEffect } from 'react'
import { useWebSocketTester } from '@/hooks/useWebSocketTester'
import { ConnectionPanel } from './ConnectionPanel'
import { MessageComposer } from './MessageComposer'
import { MessageLog } from './MessageLog'
import { showToast } from '@/utils/toast'

interface WebSocketTesterPanelProps {
  apiKey?: string
  initialMessage?: string
}

export function WebSocketTesterPanel({ apiKey, initialMessage }: WebSocketTesterPanelProps) {
  const [messageBody, setMessageBody] = useState('')

  // Update message body when initialMessage changes
  useEffect(() => {
    if (initialMessage) {
      setMessageBody(initialMessage)
    }
  }, [initialMessage])

  const {
    isConnected,
    isConnecting,
    isAuthenticated,
    wsUrl,
    error,
    connect,
    disconnect,
    sendMessage,
    messages,
    clearMessages,
    exportMessages,
    ping,
    lastLatency,
    averageLatency,
    autoReconnect,
    setAutoReconnect,
  } = useWebSocketTester(apiKey)

  const handleSendMessage = (message: string) => {
    const success = sendMessage(message)
    if (success) {
      showToast.success('Message sent')
    }
  }

  return (
    <div className="flex h-full w-full">
      {/* Left Panel - Connection and Composer */}
      <div className="w-[450px] flex flex-col gap-3 p-3 border-r border-border">
        {/* Connection Panel */}
        <ConnectionPanel
          isConnected={isConnected}
          isConnecting={isConnecting}
          isAuthenticated={isAuthenticated}
          wsUrl={wsUrl}
          lastLatency={lastLatency}
          averageLatency={averageLatency}
          autoReconnect={autoReconnect}
          onConnect={connect}
          onDisconnect={disconnect}
          onAutoReconnectChange={setAutoReconnect}
          onPing={ping}
        />

        {/* Error Display */}
        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-2 text-xs text-red-400">
            {error}
          </div>
        )}

        {/* Message Composer */}
        <div className="flex-1 min-h-0">
          <MessageComposer
            value={messageBody}
            onChange={setMessageBody}
            onSend={handleSendMessage}
            disabled={!isAuthenticated}
            apiKey={apiKey}
          />
        </div>
      </div>

      {/* Right Panel - Message Log */}
      <div className="flex-1 min-w-0">
        <MessageLog messages={messages} onClear={clearMessages} onExport={exportMessages} />
      </div>
    </div>
  )
}
