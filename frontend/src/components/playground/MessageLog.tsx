import { useState, useMemo, useRef, useCallback } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Trash2, Download, Search, ChevronDown, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { WebSocketMessage } from '@/types/websocket'

interface SyntaxToken {
  text: string
  type: 'key' | 'string' | 'number' | 'boolean' | 'null' | 'plain'
}

function tokenizeJson(json: string): SyntaxToken[] {
  if (json.length > 100 * 1024) {
    return [{ text: json, type: 'plain' }]
  }

  const tokens: SyntaxToken[] = []
  const regex =
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g
  let lastIndex = 0
  let match = regex.exec(json)

  while (match !== null) {
    if (match.index > lastIndex) {
      tokens.push({ text: json.slice(lastIndex, match.index), type: 'plain' })
    }

    const text = match[0]
    let type: SyntaxToken['type'] = 'number'

    if (/^"/.test(text)) {
      type = /:$/.test(text) ? 'key' : 'string'
    } else if (/true|false/.test(text)) {
      type = 'boolean'
    } else if (/null/.test(text)) {
      type = 'null'
    }

    tokens.push({ text, type })
    lastIndex = regex.lastIndex
    match = regex.exec(json)
  }

  if (lastIndex < json.length) {
    tokens.push({ text: json.slice(lastIndex), type: 'plain' })
  }

  return tokens
}

function getTokenClassName(type: SyntaxToken['type']): string {
  switch (type) {
    case 'key':
      return 'text-sky-400'
    case 'string':
      return 'text-emerald-400'
    case 'number':
      return 'text-orange-400'
    case 'boolean':
      return 'text-purple-400'
    case 'null':
      return 'text-red-400'
    default:
      return ''
  }
}

function formatTimestamp(timestamp: number): string {
  const date = new Date(timestamp)
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')
  const millis = String(date.getMilliseconds()).padStart(3, '0')
  return `${hours}:${minutes}:${seconds}.${millis}`
}

interface MessageLogProps {
  messages: WebSocketMessage[]
  onClear: () => void
  onExport: () => void
}

export function MessageLog({ messages, onClear, onExport }: MessageLogProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(new Set())
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to top when new messages arrive
  const prevMessagesLengthRef = useRef(messages.length)

  // Filter messages by search query
  const filteredMessages = useMemo(() => {
    if (!searchQuery.trim()) return messages

    const query = searchQuery.toLowerCase()
    return messages.filter((msg) => {
      const jsonStr = JSON.stringify(msg.data).toLowerCase()
      return jsonStr.includes(query)
    })
  }, [messages, searchQuery])

  // Auto-scroll to top when new messages are added
  if (messages.length !== prevMessagesLengthRef.current && scrollRef.current) {
    prevMessagesLengthRef.current = messages.length
    // Scroll to top to show newest messages
    if (scrollRef.current.scrollTop === 0) {
      scrollRef.current.scrollTop = 0
    }
  }

  const toggleExpanded = useCallback((id: string) => {
    setExpandedMessages((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }, [])

  const getDirectionBadge = (direction: WebSocketMessage['direction']) => {
    switch (direction) {
      case 'sent':
        return (
          <Badge variant="outline" className="bg-sky-500/20 text-sky-400 border-sky-500/30 text-[10px] px-1.5 h-5">
            SENT
          </Badge>
        )
      case 'received':
        return (
          <Badge variant="outline" className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-[10px] px-1.5 h-5">
            RECEIVED
          </Badge>
        )
      case 'error':
        return (
          <Badge variant="outline" className="bg-red-500/20 text-red-400 border-red-500/30 text-[10px] px-1.5 h-5">
            ERROR
          </Badge>
        )
      case 'system':
        return (
          <Badge variant="outline" className="bg-purple-500/20 text-purple-400 border-purple-500/30 text-[10px] px-1.5 h-5">
            SYSTEM
          </Badge>
        )
    }
  }

  const renderMessageContent = (msg: WebSocketMessage) => {
    const jsonStr = msg.rawData || JSON.stringify(msg.data, null, 2)
    const isExpanded = expandedMessages.has(msg.id)

    // Truncate for collapsed view
    const preview = jsonStr.length > 100 ? `${jsonStr.slice(0, 100)}...` : jsonStr

    return (
      <div className="relative group">
        <div
          className={cn(
            'cursor-pointer transition-all',
            !isExpanded && 'truncate'
          )}
          onClick={() => toggleExpanded(msg.id)}
        >
          <span className="text-[10px] text-muted-foreground mr-2">
            {formatTimestamp(msg.timestamp)}
          </span>
          {isExpanded ? (
            <pre className="text-xs font-mono whitespace-pre-wrap break-words leading-5 mt-1">
              {tokenizeJson(jsonStr).map((token, i) => (
                <span key={i} className={getTokenClassName(token.type)}>
                  {token.text}
                </span>
              ))}
            </pre>
          ) : (
            <span className="text-xs font-mono">{preview}</span>
          )}
        </div>
        {/* Expand/collapse button */}
        {jsonStr.length > 100 && (
          <button
            type="button"
            className={cn(
              'absolute right-2 top-0 p-0.5 rounded bg-secondary/50 opacity-0 group-hover:opacity-100 transition-opacity',
              'hover:bg-accent'
            )}
            onClick={() => toggleExpanded(msg.id)}
          >
            {isExpanded ? (
              <ChevronDown className="h-3 w-3 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-3 w-3 text-muted-foreground" />
            )}
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full w-full bg-card/50 rounded-lg border border-border overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border bg-card/30">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium">Message Log</span>
          <Badge variant="outline" className="text-[10px] px-1.5 h-5 bg-muted/50">
            {filteredMessages.length}
          </Badge>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 text-muted-foreground hover:text-foreground"
            onClick={onClear}
            disabled={messages.length === 0}
            title="Clear messages"
          >
            <Trash2 className="h-3 w-3" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6 text-muted-foreground hover:text-foreground"
            onClick={onExport}
            disabled={messages.length === 0}
            title="Export messages"
          >
            <Download className="h-3 w-3" />
          </Button>
        </div>
      </div>

      {/* Search */}
      <div className="p-2 border-b border-border bg-card/30">
        <div className="relative">
          <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Filter messages..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="h-7 pl-8 text-xs bg-secondary/50 border-border"
          />
        </div>
      </div>

      {/* Messages list */}
      <ScrollArea className="flex-1">
        <div ref={scrollRef} className="p-2 space-y-1.5">
          {filteredMessages.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="text-muted-foreground/30 text-4xl mb-3">⋄</div>
              <p className="text-sm text-muted-foreground">
                {searchQuery ? 'No messages match your search' : 'No messages yet'}
              </p>
              {!searchQuery && (
                <p className="text-xs text-muted-foreground/70 mt-1">
                  Send a message to see it here
                </p>
              )}
            </div>
          ) : (
            filteredMessages.map((msg) => (
              <div
                key={msg.id}
                className={cn(
                  'p-2 rounded bg-secondary/30 border border-border/50',
                  'hover:bg-secondary/50 transition-colors'
                )}
              >
                <div className="flex items-start gap-2">
                  {getDirectionBadge(msg.direction)}
                  <div className="flex-1 min-w-0">{renderMessageContent(msg)}</div>
                </div>
              </div>
            ))
          )}
        </div>
      </ScrollArea>
    </div>
  )
}
