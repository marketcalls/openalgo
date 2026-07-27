import CodeMirror, { type ReactCodeMirrorRef } from '@uiw/react-codemirror'
import { StreamLanguage } from '@codemirror/language'
import { EditorView } from '@codemirror/view'
import type { Extension } from '@codemirror/state'
import { tags as t } from '@lezer/highlight'
import { createTheme } from '@uiw/codemirror-themes'
import { useThemeStore } from '@/stores/themeStore'
import { useMemo, useRef, useEffect, useCallback } from 'react'

interface LogViewerProps {
  value: string
  className?: string
  height?: string
  followTail?: boolean // Auto-scroll to bottom on new content
  reverseOrder?: boolean // Show latest logs at top (reverse chronological)
}

// Simple log highlighting mode
const logMode = StreamLanguage.define({
  token(stream) {
    if (stream.match(/ERROR|error|Error|CRITICAL|critical|FATAL|fatal/)) {
      return 'invalid'
    }
    if (stream.match(/WARNING|warning|Warning|WARN|warn/)) {
      return 'keyword'
    }
    if (stream.match(/SUCCESS|success|Success/)) {
      return 'string'
    }
    if (stream.match(/INFO|info|Info/)) {
      return 'comment'
    }
    if (stream.match(/DEBUG|debug|Debug/)) {
      return 'meta'
    }
    // Match timestamps like 2024-01-15 10:30:45
    if (stream.match(/\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}/)) {
      return 'number'
    }
    // Match time only HH:MM:SS
    if (stream.match(/\d{2}:\d{2}:\d{2}/)) {
      return 'number'
    }
    stream.next()
    return null
  },
})

// Custom theme for log viewing
const createLogTheme = (isDark: boolean): Extension => {
  return createTheme({
    theme: isDark ? 'dark' : 'light',
    settings: {
      background: isDark ? '#111827' : '#f8fafc',
      foreground: isDark ? '#d1d5db' : '#334155',
      caret: isDark ? '#38bdf8' : '#0284c7',
      selection: isDark ? 'rgba(56, 189, 248, 0.2)' : 'rgba(2, 132, 199, 0.2)',
      selectionMatch: isDark ? 'rgba(56, 189, 248, 0.1)' : 'rgba(2, 132, 199, 0.1)',
      lineHighlight: isDark ? 'rgba(255, 255, 255, 0.03)' : 'rgba(0, 0, 0, 0.02)',
      gutterBackground: 'transparent',
      gutterForeground: isDark ? 'rgba(255, 255, 255, 0.3)' : 'rgba(0, 0, 0, 0.3)',
      gutterBorder: 'transparent',
    },
    styles: [
      // Errors - red
      { tag: t.invalid, color: isDark ? '#f87171' : '#dc2626', fontWeight: 'bold' },
      // Warnings - yellow/amber
      { tag: t.keyword, color: isDark ? '#fbbf24' : '#d97706' },
      // Success - green
      { tag: t.string, color: isDark ? '#34d399' : '#059669' },
      // Info - blue
      { tag: t.comment, color: isDark ? '#60a5fa' : '#2563eb' },
      // Debug - gray
      { tag: t.meta, color: isDark ? '#9ca3af' : '#64748b' },
      // Timestamps - cyan
      { tag: t.number, color: isDark ? '#22d3ee' : '#0891b2' },
    ],
  })
}

// Editor base styling
const createBaseTheme = (isDark: boolean): Extension => {
  const borderColor = isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)'
  const gutterBg = isDark ? 'rgba(255, 255, 255, 0.02)' : 'rgba(0, 0, 0, 0.02)'

  return EditorView.theme({
    '&': {
      fontSize: '12px',
      fontFamily: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace',
      height: '100%',
      backgroundColor: isDark ? '#111827' : '#f8fafc',
    },
    '&.cm-editor': {
      height: '100%',
    },
    '.cm-scroller': {
      overflow: 'auto',
      height: '100%',
    },
    '.cm-content': {
      padding: '12px 0',
      lineHeight: '20px',
    },
    '.cm-line': {
      padding: '0 12px',
    },
    '.cm-gutters': {
      backgroundColor: gutterBg,
      borderRight: `1px solid ${borderColor}`,
      paddingRight: '4px',
    },
    '.cm-gutter': {
      minWidth: '48px',
    },
    '.cm-gutterElement': {
      padding: '0 8px 0 12px',
      lineHeight: '20px',
    },
    '&.cm-focused': {
      outline: 'none',
    },
    '.cm-activeLine': {
      backgroundColor: isDark ? 'rgba(255, 255, 255, 0.03)' : 'rgba(0, 0, 0, 0.02)',
    },
    '.cm-activeLineGutter': {
      backgroundColor: isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.03)',
    },
  })
}

export function LogViewer({
  value,
  className = '',
  height = '500px',
  followTail = false,
  reverseOrder = false,
}: LogViewerProps) {
  const { mode, appMode } = useThemeStore()
  // Dark mode when: explicit dark theme OR analyzer mode (always dark purple theme)
  const isDark = mode === 'dark' || appMode === 'analyzer'

  const editorRef = useRef<ReactCodeMirrorRef>(null)
  const scrollPositionRef = useRef<number>(0)
  const isUserScrolledRef = useRef<boolean>(false)
  const prevValueRef = useRef<string>(value)

  // Reverse log content if reverseOrder is true (latest logs at top)
  const displayValue = useMemo(() => {
    if (!reverseOrder || !value) return value
    const lines = value.split('\n')
    return lines.reverse().join('\n')
  }, [value, reverseOrder])

  const extensions = useMemo(() => {
    return [
      logMode,
      createLogTheme(isDark),
      createBaseTheme(isDark),
      EditorView.lineWrapping,
      EditorView.editable.of(false),
    ]
  }, [isDark])

  // Track user scroll position
  const handleScroll = useCallback(() => {
    const view = editorRef.current?.view
    if (view) {
      const scrollDOM = view.scrollDOM
      scrollPositionRef.current = scrollDOM.scrollTop

      // Check if user is near bottom (within 50px)
      const isAtBottom = scrollDOM.scrollHeight - scrollDOM.scrollTop - scrollDOM.clientHeight < 50
      isUserScrolledRef.current = !isAtBottom
    }
  }, [])

  // Restore scroll position or scroll to bottom after content update
  useEffect(() => {
    const view = editorRef.current?.view
    if (!view) return

    const scrollDOM = view.scrollDOM

    // Add scroll listener
    scrollDOM.addEventListener('scroll', handleScroll)

    return () => {
      scrollDOM.removeEventListener('scroll', handleScroll)
    }
  }, [handleScroll])

  // Handle content changes - restore scroll or follow tail
  useEffect(() => {
    if (displayValue === prevValueRef.current) return
    prevValueRef.current = displayValue

    // Use requestAnimationFrame to ensure DOM is updated
    requestAnimationFrame(() => {
      const view = editorRef.current?.view
      if (!view) return

      const scrollDOM = view.scrollDOM

      if (reverseOrder) {
        // In reverse mode, keep at top (latest logs are already at top)
        if (!isUserScrolledRef.current) {
          scrollDOM.scrollTop = 0
        }
      } else if (followTail && !isUserScrolledRef.current) {
        // Auto-scroll to bottom for live logs if user hasn't scrolled up
        scrollDOM.scrollTop = scrollDOM.scrollHeight
      } else if (isUserScrolledRef.current) {
        // Preserve scroll position if user has scrolled
        scrollDOM.scrollTop = scrollPositionRef.current
      }
    })
  }, [displayValue, followTail, reverseOrder])

  return (
    <div className={`rounded-lg overflow-hidden ${className}`}>
      <CodeMirror
        ref={editorRef}
        value={displayValue}
        extensions={extensions}
        readOnly={true}
        height={height}
        theme={isDark ? 'dark' : 'light'}
        basicSetup={{
          lineNumbers: true,
          highlightActiveLineGutter: true,
          highlightActiveLine: true,
          foldGutter: false,
          dropCursor: false,
          allowMultipleSelections: false,
          indentOnInput: false,
          bracketMatching: false,
          closeBrackets: false,
          autocompletion: false,
          rectangularSelection: false,
          crosshairCursor: false,
          highlightSelectionMatches: true,
          searchKeymap: true,
          tabSize: 2,
        }}
      />
    </div>
  )
}
