// pages/flow/FlowKeyboardShortcuts.tsx
// Keyboard shortcuts reference page for Flow Editor

import { ArrowLeft } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'

interface ShortcutItem {
  keys: string[]
  description: string
}

interface ShortcutSection {
  title: string
  shortcuts: ShortcutItem[]
}

const shortcutSections: ShortcutSection[] = [
  {
    title: 'General',
    shortcuts: [
      { keys: ['Ctrl', 'S'], description: 'Save workflow' },
      { keys: ['Escape'], description: 'Deselect node/edge' },
      { keys: ['?'], description: 'Open keyboard shortcuts' },
    ],
  },
  {
    title: 'Canvas Navigation',
    shortcuts: [
      { keys: ['Scroll'], description: 'Zoom in/out' },
      { keys: ['Drag'], description: 'Pan canvas' },
      { keys: ['Ctrl', 'Scroll'], description: 'Zoom in/out (precise)' },
    ],
  },
  {
    title: 'Node Operations',
    shortcuts: [
      { keys: ['Click'], description: 'Select node' },
      { keys: ['Delete'], description: 'Delete selected node' },
      { keys: ['Backspace'], description: 'Delete selected node' },
      { keys: ['Drag from palette'], description: 'Add new node' },
    ],
  },
  {
    title: 'Edge Operations',
    shortcuts: [
      { keys: ['Click edge'], description: 'Select edge' },
      { keys: ['Delete'], description: 'Delete selected edge' },
      { keys: ['Backspace'], description: 'Delete selected edge' },
      { keys: ['Drag from handle'], description: 'Create connection' },
    ],
  },
  {
    title: 'Selection',
    shortcuts: [
      { keys: ['Click node'], description: 'Select single node' },
      { keys: ['Click edge'], description: 'Select single edge' },
      { keys: ['Click canvas'], description: 'Clear selection' },
    ],
  },
  {
    title: 'Workflow Controls',
    shortcuts: [
      { keys: ['Ctrl', 'S'], description: 'Save changes' },
      { keys: ['Run Now'], description: 'Execute workflow immediately' },
    ],
  },
]

function KeyBadge({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex h-6 min-w-[24px] items-center justify-center rounded border border-border bg-muted px-1.5 font-mono text-xs font-medium text-muted-foreground">
      {children}
    </kbd>
  )
}

export default function FlowKeyboardShortcuts() {
  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <div className="mb-8 flex items-center gap-4">
        <Button variant="ghost" size="icon" asChild>
          <Link to="/flow">
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <div>
          <h1 className="text-2xl font-bold">Keyboard Shortcuts</h1>
          <p className="text-muted-foreground">
            Quick reference for all available keyboard shortcuts
          </p>
        </div>
      </div>

      <div className="space-y-8">
        {shortcutSections.map((section) => (
          <div key={section.title}>
            <h2 className="mb-4 text-lg font-semibold">{section.title}</h2>
            <div className="rounded-lg border border-border">
              {section.shortcuts.map((shortcut, index) => (
                <div
                  key={shortcut.description}
                  className={`flex items-center justify-between px-4 py-3 ${
                    index !== section.shortcuts.length - 1
                      ? 'border-b border-border'
                      : ''
                  }`}
                >
                  <span className="text-sm">{shortcut.description}</span>
                  <div className="flex items-center gap-1">
                    {shortcut.keys.map((key, keyIndex) => (
                      <span key={key} className="flex items-center gap-1">
                        <KeyBadge>{key}</KeyBadge>
                        {keyIndex < shortcut.keys.length - 1 && (
                          <span className="text-muted-foreground">+</span>
                        )}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-8 rounded-lg border border-border bg-muted/50 p-4">
        <h3 className="mb-2 font-medium">Tips</h3>
        <ul className="space-y-1 text-sm text-muted-foreground">
          <li>On Mac, use Cmd instead of Ctrl for keyboard shortcuts</li>
          <li>Click the + button on edges to insert a new node between existing nodes</li>
          <li>Drag nodes to reposition them on the canvas</li>
          <li>Use the minimap in the bottom-right corner for quick navigation</li>
          <li>Right-click nodes for context menu options</li>
        </ul>
      </div>
    </div>
  )
}
