import {
  AlertCircle,
  ArrowRight,
  Check,
  Copy,
  Eye,
  EyeOff,
  Info,
  Key,
  RefreshCw,
  Zap,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuthStore } from '@/stores/authStore'

async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', {
    credentials: 'include',
  })
  const data = await response.json()
  return data.csrf_token
}

export default function ApiKey() {
  const { user } = useAuthStore()
  const [apiKey, setApiKey] = useState<string | null>(null)
  const [hasApiKey, setHasApiKey] = useState(false)
  const [showApiKey, setShowApiKey] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isRegenerating, setIsRegenerating] = useState(false)
  const [showRegenerateDialog, setShowRegenerateDialog] = useState(false)

  // Order mode state
  const [orderMode, setOrderMode] = useState<'auto' | 'semi_auto'>('auto')
  const [isTogglingMode, setIsTogglingMode] = useState(false)

  useEffect(() => {
    fetchApiKeyData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const fetchApiKeyData = async () => {
    setIsLoading(true)
    try {
      const response = await fetch('/apikey', {
        credentials: 'include',
        headers: {
          Accept: 'application/json',
        },
      })

      if (response.ok) {
        const contentType = response.headers.get('content-type')
        if (contentType?.includes('application/json')) {
          const data = await response.json()
          setApiKey(data.api_key || null)
          setHasApiKey(!!data.api_key)
          setOrderMode(data.order_mode || 'auto')
        } else {
          // Backend returned HTML - this shouldn't happen now
          showToast.error('Failed to load API key - please refresh', 'system')
        }
      }
    } catch (error) {
      showToast.error('Failed to load API key', 'system')
    } finally {
      setIsLoading(false)
    }
  }

  const handleCopyApiKey = async () => {
    if (apiKey) {
      try {
        await navigator.clipboard.writeText(apiKey)
        showToast.success('API key copied to clipboard', 'clipboard')
      } catch {
        showToast.error('Failed to copy API key', 'clipboard')
      }
    }
  }

  const handleRegenerateApiKey = async () => {
    setIsRegenerating(true)
    setShowRegenerateDialog(false)

    try {
      const csrfToken = await fetchCSRFToken()

      const response = await fetch('/apikey', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
          user_id: user?.username,
        }),
      })

      const data = await response.json()

      if (data.api_key) {
        setApiKey(data.api_key)
        setHasApiKey(true)
        setShowApiKey(true)
        showToast.success('API key generated successfully', 'system')
      } else {
        showToast.error(data.error || 'Failed to generate API key', 'system')
      }
    } catch (error) {
      showToast.error('Failed to generate API key', 'system')
    } finally {
      setIsRegenerating(false)
    }
  }

  const handleToggleOrderMode = async () => {
    const newMode = orderMode === 'auto' ? 'semi_auto' : 'auto'
    setIsTogglingMode(true)

    try {
      const csrfToken = await fetchCSRFToken()

      const response = await fetch('/apikey/mode', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        body: JSON.stringify({
          user_id: user?.username,
          mode: newMode,
        }),
      })

      const data = await response.json()

      if (data.mode) {
        setOrderMode(data.mode)
        showToast.success(`Order mode updated to ${data.mode === 'semi_auto' ? 'Semi-Auto' : 'Auto'}`, 'system')
      } else {
        showToast.error(data.error || 'Failed to update order mode', 'system')
      }
    } catch (error) {
      showToast.error('Failed to update order mode', 'system')
    } finally {
      setIsTogglingMode(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
      </div>
    )
  }

  return (
    <div className="py-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* API Key Management Card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Key className="h-5 w-5" />
              API Key Management
            </CardTitle>
            <CardDescription>
              {hasApiKey
                ? 'Your API key was automatically generated during account creation. You can view it below or generate a new one if needed.'
                : 'Your API key could not be found. Please generate a new one.'}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* API Key Display */}
            <div className="flex items-center gap-2 p-3 bg-muted rounded-lg">
              <Key className="h-4 w-4 shrink-0 text-muted-foreground" />
              <code className="flex-1 font-mono text-sm truncate">
                {hasApiKey
                  ? showApiKey
                    ? apiKey
                    : `${apiKey?.slice(0, 8)}${'•'.repeat(32)}${apiKey?.slice(-8)}`
                  : 'No API key generated'}
              </code>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                onClick={() => setShowApiKey(!showApiKey)}
                disabled={!hasApiKey}
              >
                {showApiKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </Button>
            </div>

            {/* Action Buttons */}
            <div className="flex flex-wrap gap-2">
              <Button onClick={handleCopyApiKey} disabled={!hasApiKey} size="sm">
                <Copy className="h-4 w-4 mr-2" />
                Copy
              </Button>

              <Button
                variant="outline"
                size="sm"
                onClick={() => setShowRegenerateDialog(true)}
                disabled={isRegenerating}
              >
                <RefreshCw className={`h-4 w-4 mr-2 ${isRegenerating ? 'animate-spin' : ''}`} />
                {hasApiKey ? 'Regenerate' : 'Generate'}
              </Button>
            </div>

            {/* Divider */}
            <div className="border-t pt-6">
              {/* Order Mode Toggle */}
              <div className="space-y-4">
                <div>
                  <h3 className="font-semibold text-lg">Order Execution Mode</h3>
                  <p className="text-sm text-muted-foreground">
                    Choose between automatic execution or manual approval.
                  </p>
                </div>

                <div className="flex items-center gap-4 p-4 bg-muted rounded-lg">
                  <Button
                    variant={orderMode === 'auto' ? 'default' : 'outline'}
                    className={`flex-1 ${orderMode === 'auto' ? 'bg-green-600 hover:bg-green-700' : ''}`}
                    onClick={() => orderMode !== 'auto' && handleToggleOrderMode()}
                    disabled={isTogglingMode}
                  >
                    <Check className="h-4 w-4 mr-2" />
                    Auto Mode
                  </Button>

                  <Button
                    variant={orderMode === 'semi_auto' ? 'default' : 'outline'}
                    className={`flex-1 ${orderMode === 'semi_auto' ? 'bg-yellow-600 hover:bg-yellow-700' : ''}`}
                    onClick={() => orderMode !== 'semi_auto' && handleToggleOrderMode()}
                    disabled={isTogglingMode}
                  >
                    <AlertCircle className="h-4 w-4 mr-2" />
                    Semi-Auto
                  </Button>
                </div>
                <div className="flex justify-between text-xs text-muted-foreground px-4">
                  <span>Execute immediately</span>
                  <span>Queue for approval</span>
                </div>

                {/* Current Mode Status */}
                <Alert
                  variant={orderMode === 'semi_auto' ? 'default' : 'default'}
                  className={
                    orderMode === 'semi_auto'
                      ? 'border-yellow-500 bg-yellow-500/10'
                      : 'border-green-500 bg-green-500/10'
                  }
                >
                  <Info className="h-4 w-4" />
                  <AlertDescription>
                    Current mode:{' '}
                    <strong>{orderMode === 'semi_auto' ? 'Semi-Auto' : 'Auto'}</strong>
                    {orderMode === 'semi_auto' ? (
                      <span>
                        {' '}
                        - All orders will be queued in{' '}
                        <Link
                          to="/action-center"
                          className="font-bold underline hover:text-primary"
                        >
                          Action Center
                        </Link>{' '}
                        for approval
                      </span>
                    ) : (
                      <span> - All orders will execute immediately</span>
                    )}
                  </AlertDescription>
                </Alert>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* API Playground Card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-yellow-500 to-amber-600 flex items-center justify-center">
                <Zap className="h-4 w-4 text-white" />
              </div>
              API Playground
            </CardTitle>
            <CardDescription>
              Test and explore OpenAlgo REST APIs directly in your browser. Send requests, view
              responses, and experiment with all available endpoints without writing any code.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <h3 className="font-semibold mb-3">Features</h3>
              <ul className="text-sm text-muted-foreground space-y-2">
                <li className="flex items-start gap-2">
                  <Check className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
                  Send GET/POST requests to any endpoint
                </li>
                <li className="flex items-start gap-2">
                  <Check className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
                  Syntax highlighted JSON responses
                </li>
                <li className="flex items-start gap-2">
                  <Check className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
                  Copy response or cURL command
                </li>
              </ul>
            </div>

            <div>
              <h3 className="font-semibold mb-3">How it Works</h3>
              <ol className="text-sm text-muted-foreground space-y-2 list-decimal list-inside">
                <li>Select an endpoint from the sidebar</li>
                <li>Modify the request body as needed</li>
                <li>Click Send to execute the request</li>
                <li>View the JSON response instantly</li>
              </ol>
            </div>

            <div className="p-3 bg-muted rounded-lg">
              <p className="text-xs text-muted-foreground">
                <strong>Tip:</strong> Your API key is automatically injected into requests when you
                use the Playground. No need to copy it manually.
              </p>
            </div>

            <Button asChild className="w-full sm:w-auto">
              <Link to="/playground">
                <ArrowRight className="h-4 w-4 mr-2" />
                Open Playground
              </Link>
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Regenerate Confirmation Dialog */}
      <AlertDialog open={showRegenerateDialog} onOpenChange={setShowRegenerateDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {hasApiKey ? 'Regenerate API Key?' : 'Generate API Key?'}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {hasApiKey
                ? 'Are you sure you want to regenerate your API key? The current key will be invalidated and any applications using it will need to be updated.'
                : 'Generate a new API key for authenticating your API requests?'}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleRegenerateApiKey}>
              {hasApiKey ? 'Regenerate' : 'Generate'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
