import { useState, useEffect, useCallback } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Save,
  RotateCcw,
  Download,
  Maximize2,
  Minimize2,
  Sun,
  Moon,
  AlertTriangle,
  FileCode,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { toast } from 'sonner';
import { pythonStrategyApi } from '@/api/python-strategy';
import type { PythonStrategy, PythonStrategyContent } from '@/types/python-strategy';

export default function EditPythonStrategy() {
  const { strategyId } = useParams<{ strategyId: string }>();
  const navigate = useNavigate();
  const [strategy, setStrategy] = useState<PythonStrategy | null>(null);
  const [content, setContent] = useState<PythonStrategyContent | null>(null);
  const [code, setCode] = useState('');
  const [originalCode, setOriginalCode] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [darkTheme, setDarkTheme] = useState(() => {
    return localStorage.getItem('editor-theme') === 'dark';
  });
  const [isFullscreen, setIsFullscreen] = useState(false);

  const hasChanges = code !== originalCode;
  const isRunning = strategy?.status === 'running';

  const fetchData = async () => {
    if (!strategyId) return;
    try {
      setLoading(true);
      const [strategyData, contentData] = await Promise.all([
        pythonStrategyApi.getStrategy(strategyId),
        pythonStrategyApi.getStrategyContent(strategyId),
      ]);
      setStrategy(strategyData);
      setContent(contentData);
      setCode(contentData.content);
      setOriginalCode(contentData.content);
    } catch (error) {
      console.error('Failed to fetch strategy:', error);
      toast.error('Failed to load strategy');
      navigate('/python');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [strategyId]);

  // Save theme preference
  useEffect(() => {
    localStorage.setItem('editor-theme', darkTheme ? 'dark' : 'light');
  }, [darkTheme]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        if (hasChanges && !isRunning) {
          handleSave();
        }
      }
      if (e.key === 'F11') {
        e.preventDefault();
        setIsFullscreen((prev) => !prev);
      }
      if (e.key === 'Escape' && isFullscreen) {
        setIsFullscreen(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [hasChanges, isRunning]);

  const handleSave = async () => {
    if (!strategyId || !hasChanges || isRunning) return;

    try {
      setSaving(true);
      const response = await pythonStrategyApi.saveStrategy(strategyId, code);

      if (response.status === 'success') {
        setOriginalCode(code);
        toast.success('Strategy saved');
      } else {
        toast.error(response.message || 'Failed to save strategy');
      }
    } catch (error) {
      console.error('Failed to save strategy:', error);
      toast.error('Failed to save strategy');
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setCode(originalCode);
    toast.info('Changes discarded');
  };

  const handleExport = async (version: 'saved' | 'current') => {
    if (!strategyId || !strategy) return;

    try {
      const blob = await pythonStrategyApi.exportStrategy(strategyId, version);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = strategy.file_name;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast.success('Strategy exported');
    } catch (error) {
      console.error('Failed to export strategy:', error);
      toast.error('Failed to export strategy');
    }
  };

  const handleTabKey = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const target = e.target as HTMLTextAreaElement;
      const start = target.selectionStart;
      const end = target.selectionEnd;

      if (e.shiftKey) {
        // Unindent: Remove leading spaces/tab
        const beforeCursor = code.substring(0, start);
        const lineStart = beforeCursor.lastIndexOf('\n') + 1;
        const lineContent = code.substring(lineStart, start);

        if (lineContent.startsWith('    ')) {
          const newCode = code.substring(0, lineStart) + code.substring(lineStart + 4);
          setCode(newCode);
          setTimeout(() => {
            target.selectionStart = target.selectionEnd = start - 4;
          }, 0);
        } else if (lineContent.startsWith('\t')) {
          const newCode = code.substring(0, lineStart) + code.substring(lineStart + 1);
          setCode(newCode);
          setTimeout(() => {
            target.selectionStart = target.selectionEnd = start - 1;
          }, 0);
        }
      } else {
        // Indent: Add 4 spaces
        const newCode = code.substring(0, start) + '    ' + code.substring(end);
        setCode(newCode);
        setTimeout(() => {
          target.selectionStart = target.selectionEnd = start + 4;
        }, 0);
      }
    }
  }, [code]);

  if (loading) {
    return (
      <div className="container mx-auto py-6 space-y-6">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-12" />
        <Skeleton className="h-[600px]" />
      </div>
    );
  }

  if (!strategy || !content) {
    return null;
  }

  const editorContent = (
    <div className={`relative ${isFullscreen ? 'fixed inset-0 z-50 bg-background p-4' : ''}`}>
      {isFullscreen && (
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">{strategy.name}</h2>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setDarkTheme(!darkTheme)}>
              {darkTheme ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setIsFullscreen(false)}>
              <Minimize2 className="h-4 w-4" />
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={!hasChanges || saving || isRunning}
              className={hasChanges && !isRunning ? 'animate-pulse' : ''}
            >
              <Save className="h-4 w-4 mr-2" />
              {saving ? 'Saving...' : 'Save'}
            </Button>
          </div>
        </div>
      )}

      <textarea
        value={code}
        onChange={(e) => setCode(e.target.value)}
        onKeyDown={handleTabKey}
        readOnly={isRunning}
        className={`w-full font-mono text-sm p-4 rounded-lg border focus:outline-none focus:ring-2 focus:ring-primary resize-none ${
          darkTheme
            ? 'bg-gray-900 text-gray-100 border-gray-700'
            : 'bg-white text-gray-900 border-gray-300'
        } ${isFullscreen ? 'h-[calc(100vh-120px)]' : 'min-h-[600px]'} ${
          isRunning ? 'opacity-75 cursor-not-allowed' : ''
        }`}
        spellCheck={false}
        placeholder="# Your Python strategy code here..."
      />

      {/* Line count footer */}
      <div className="flex items-center justify-between mt-2 text-xs text-muted-foreground">
        <span>
          Lines: {code.split('\n').length} • Size: {(new Blob([code]).size / 1024).toFixed(2)} KB
        </span>
        <span>
          {hasChanges ? (
            <Badge variant="outline" className="text-yellow-500 border-yellow-500">
              Unsaved Changes
            </Badge>
          ) : (
            <Badge variant="outline" className="text-green-500 border-green-500">
              Saved
            </Badge>
          )}
        </span>
      </div>
    </div>
  );

  return (
    <div className="container mx-auto py-6 space-y-6">
      {/* Back Button */}
      <Button variant="ghost" asChild>
        <Link to="/python">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Back to Python Strategies
        </Link>
      </Button>

      {/* Header */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-3">
            {isRunning ? 'View' : 'Edit'} Strategy
            {isRunning && (
              <Badge className="bg-green-500">Running</Badge>
            )}
          </h1>
          <p className="text-muted-foreground flex items-center gap-2">
            <FileCode className="h-4 w-4" />
            {strategy.name} • {content.file_name}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setDarkTheme(!darkTheme)}
          >
            {darkTheme ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setIsFullscreen(true)}
          >
            <Maximize2 className="h-4 w-4" />
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <Download className="h-4 w-4 mr-2" />
                Export
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem onClick={() => handleExport('saved')}>
                Saved Version
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => handleExport('current')}>
                Current Content
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button
            variant="outline"
            size="sm"
            onClick={handleReset}
            disabled={!hasChanges}
          >
            <RotateCcw className="h-4 w-4 mr-2" />
            Reset
          </Button>
          <Button
            size="sm"
            onClick={handleSave}
            disabled={!hasChanges || saving || isRunning}
            className={hasChanges && !isRunning ? 'animate-pulse' : ''}
          >
            <Save className="h-4 w-4 mr-2" />
            {saving ? 'Saving...' : 'Save'}
          </Button>
        </div>
      </div>

      {/* Running Warning */}
      {isRunning && (
        <Alert>
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>
            This strategy is currently running. The editor is in read-only mode.
            Stop the strategy to make changes.
          </AlertDescription>
        </Alert>
      )}

      {/* File Info */}
      <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
        <span>File: {content.file_name}</span>
        <span>•</span>
        <span>{content.line_count} lines</span>
        <span>•</span>
        <span>{content.size_kb.toFixed(2)} KB</span>
        <span>•</span>
        <span>Last modified: {new Date(content.last_modified).toLocaleString()}</span>
      </div>

      {/* Editor */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center justify-between">
            <span>Code Editor</span>
            <span className="font-normal text-xs text-muted-foreground">
              Ctrl+S to save • F11 for fullscreen • Tab to indent
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {editorContent}
        </CardContent>
      </Card>

      {/* Keyboard Shortcuts */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Keyboard Shortcuts</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            <div>
              <kbd className="px-2 py-1 bg-muted rounded">Ctrl+S</kbd> Save
            </div>
            <div>
              <kbd className="px-2 py-1 bg-muted rounded">Tab</kbd> Indent
            </div>
            <div>
              <kbd className="px-2 py-1 bg-muted rounded">Shift+Tab</kbd> Unindent
            </div>
            <div>
              <kbd className="px-2 py-1 bg-muted rounded">F11</kbd> Fullscreen
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
