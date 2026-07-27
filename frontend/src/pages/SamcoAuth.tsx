import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  ExternalLink,
  Key,
  Loader2,
  Lock,
  Mail,
  Network,
  Shield,
  Smartphone,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { fetchCSRFToken } from '@/api/client'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuthStore } from '@/stores/authStore'

// Steps in the wizard
type Step = 'otp' | 'secret-key' | 'ip' | 'login'

interface IpStatus {
  primary_ip: string | null
  secondary_ip: string | null
  editable: boolean
  ip_updated_at: string | null
  next_editable_date: string | null
  has_secret_key: boolean
}

export default function SamcoAuth() {
  const navigate = useNavigate()
  const { login } = useAuthStore()

  const [currentStep, setCurrentStep] = useState<Step>('otp')
  const [isLoading, setIsLoading] = useState(false)
  const [isInitLoading, setIsInitLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  // Form state
  const [otp, setOtp] = useState('')
  const [secretApiKey, setSecretApiKey] = useState('')
  const [primaryIp, setPrimaryIp] = useState('')
  const [secondaryIp, setSecondaryIp] = useState('')

  // IP status
  const [ipStatus, setIpStatus] = useState<IpStatus | null>(null)
  const [showIpConfirm, setShowIpConfirm] = useState(false)

  // Step completion tracking
  const [otpSent, setOtpSent] = useState(false)
  const [secretKeySent, setSecretKeySent] = useState(false)

  // Load initial state - check if secret key exists
  useEffect(() => {
    loadIpStatus()
  }, [])

  async function loadIpStatus() {
    try {
      setIsInitLoading(true)
      const response = await fetch('/samco/ip-status', { credentials: 'include' })
      const data = await response.json()

      if (data.status === 'success') {
        setIpStatus(data)
        if (data.primary_ip) {
          setPrimaryIp(data.primary_ip)
          setSecondaryIp(data.secondary_ip || '')
        }
        // If secret key exists, skip to IP step
        if (data.has_secret_key) {
          setCurrentStep('ip')
        }
      }
    } catch {
      // If not logged in or error, start from beginning
    } finally {
      setIsInitLoading(false)
    }
  }

  // Step 1: Generate OTP
  async function handleGenerateOtp() {
    setIsLoading(true)
    setError(null)
    setSuccessMessage(null)

    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/samco/generate-otp', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
      })

      const data = await response.json()

      if (data.status === 'success') {
        setOtpSent(true)
        setSuccessMessage(data.message || 'OTP sent to your registered mobile and email')
        showToast.success('OTP sent successfully')
      } else {
        setError(data.message || 'Failed to generate OTP')
      }
    } catch {
      setError('Failed to generate OTP. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }

  // Step 2: Generate Secret Key using OTP
  async function handleGenerateSecretKey() {
    if (!otp.trim()) {
      setError('Please enter the OTP')
      return
    }

    setIsLoading(true)
    setError(null)
    setSuccessMessage(null)

    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/samco/generate-secret', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({ otp: otp.trim() }),
      })

      const data = await response.json()

      if (data.status === 'success') {
        setSecretKeySent(true)
        setSuccessMessage(
          data.message || 'Secret API key has been sent to your registered email'
        )
        setCurrentStep('secret-key')
        showToast.success('Secret key sent to your email')
      } else {
        setError(data.message || 'Failed to generate secret key')
      }
    } catch {
      setError('Failed to generate secret key. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }

  // Step 3: Save Secret Key
  async function handleSaveSecretKey() {
    if (!secretApiKey.trim()) {
      setError('Please enter the secret API key from your email')
      return
    }

    setIsLoading(true)
    setError(null)

    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/samco/save-secret', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({ secretApiKey: secretApiKey.trim() }),
      })

      const data = await response.json()

      if (data.status === 'success') {
        showToast.success('Secret API key saved successfully')
        setCurrentStep('ip')
        // Reload IP status
        await loadIpStatus()
      } else {
        setError(data.message || 'Failed to save secret key')
      }
    } catch {
      setError('Failed to save secret key. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }

  // Step 4: Update IP
  async function handleUpdateIp() {
    if (!primaryIp.trim()) {
      setError('Primary IP address is required')
      return
    }

    setIsLoading(true)
    setError(null)

    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/samco/update-ip', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({
          primaryIp: primaryIp.trim(),
          secondaryIp: secondaryIp.trim() || undefined,
        }),
      })

      const data = await response.json()

      if (data.status === 'success') {
        showToast.success(data.message || 'IP updated successfully')
        setShowIpConfirm(false)
        // Reload IP status to reflect new lock state
        await loadIpStatus()
      } else {
        setError(data.message || 'Failed to update IP')
      }
    } catch {
      setError('Failed to update IP. Please try again.')
    } finally {
      setIsLoading(false)
    }
  }

  // Step 5: Login
  async function handleLogin() {
    setIsLoading(true)
    setError(null)

    try {
      const csrfToken = await fetchCSRFToken()
      const form = new FormData()
      form.append('csrf_token', csrfToken)

      const response = await fetch('/samco/callback', {
        method: 'POST',
        body: form,
        credentials: 'include',
      })

      const data = await response.json()

      if (data.status === 'success') {
        login('', 'samco')
        showToast.success('Authentication successful')
        navigate('/dashboard')
      } else {
        setError(data.message || 'Authentication failed. Please try again.')
      }
    } catch {
      setError('Authentication failed. Please check your credentials and try again.')
    } finally {
      setIsLoading(false)
    }
  }

  const steps: { key: Step; label: string; icon: React.ReactNode }[] = [
    { key: 'otp', label: 'Generate OTP', icon: <Smartphone className="h-4 w-4" /> },
    { key: 'secret-key', label: 'Secret Key', icon: <Key className="h-4 w-4" /> },
    { key: 'ip', label: 'IP Management', icon: <Network className="h-4 w-4" /> },
    { key: 'login', label: 'Login', icon: <Shield className="h-4 w-4" /> },
  ]

  // Determine which steps are completed
  function isStepCompleted(step: Step): boolean {
    if (step === 'otp') return ipStatus?.has_secret_key || secretKeySent
    if (step === 'secret-key') return ipStatus?.has_secret_key === true
    if (step === 'ip') return false
    return false
  }

  // Determine which steps are accessible
  function isStepAccessible(step: Step): boolean {
    if (step === 'otp') return true
    if (step === 'secret-key') return otpSent || secretKeySent
    if (step === 'ip') return ipStatus?.has_secret_key === true
    if (step === 'login') return ipStatus?.has_secret_key === true
    return false
  }

  if (isInitLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center py-8 px-4">
      <div className="container max-w-lg">
        <Card className="shadow-xl">
          <CardHeader className="text-center relative">
            <Button
              variant="ghost"
              size="sm"
              className="absolute left-4 top-4"
              onClick={() => navigate('/broker')}
            >
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back
            </Button>
            <div className="flex justify-center mb-4 pt-6">
              <div className="h-16 w-16 rounded-full bg-primary/10 flex items-center justify-center">
                <Shield className="h-8 w-8 text-primary" />
              </div>
            </div>
            <CardTitle className="text-2xl">Samco Login</CardTitle>
            <CardDescription>Two-Factor Authentication</CardDescription>
          </CardHeader>

          <CardContent>
            {/* Step Indicator */}
            <div className="flex items-center justify-between mb-6">
              {steps.map((step, index) => {
                const completed = isStepCompleted(step.key)
                const active = currentStep === step.key
                const accessible = isStepAccessible(step.key)

                return (
                  <div key={step.key} className="flex items-center flex-1">
                    <button
                      onClick={() => accessible && setCurrentStep(step.key)}
                      disabled={!accessible}
                      className={`flex flex-col items-center gap-1 flex-1 ${
                        accessible ? 'cursor-pointer' : 'cursor-not-allowed opacity-50'
                      }`}
                    >
                      <div
                        className={`h-8 w-8 rounded-full flex items-center justify-center text-xs font-medium transition-colors ${
                          completed
                            ? 'bg-green-500 text-white'
                            : active
                              ? 'bg-primary text-primary-foreground'
                              : 'bg-muted text-muted-foreground'
                        }`}
                      >
                        {completed ? <Check className="h-4 w-4" /> : step.icon}
                      </div>
                      <span
                        className={`text-xs ${active ? 'text-primary font-medium' : 'text-muted-foreground'}`}
                      >
                        {step.label}
                      </span>
                    </button>
                    {index < steps.length - 1 && (
                      <div
                        className={`h-px w-4 mt-[-16px] ${completed ? 'bg-green-500' : 'bg-muted'}`}
                      />
                    )}
                  </div>
                )
              })}
            </div>

            {/* Error Alert */}
            {error && (
              <Alert variant="destructive" className="mb-4">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            {/* Success Alert */}
            {successMessage && (
              <Alert className="mb-4 border-green-500/50 bg-green-50 dark:bg-green-950/20">
                <Check className="h-4 w-4 text-green-600" />
                <AlertDescription className="text-green-700 dark:text-green-400">
                  {successMessage}
                </AlertDescription>
              </Alert>
            )}

            {/* Step 1: Generate OTP */}
            {currentStep === 'otp' && (
              <div className="space-y-4">
                {ipStatus?.has_secret_key ? (
                  <Alert variant="warning" className="mb-2">
                    <AlertTriangle className="h-4 w-4" />
                    <AlertDescription>
                      A Secret API Key is already saved. If you generate a new OTP and create a new
                      secret key, you must also update the saved key here.
                    </AlertDescription>
                  </Alert>
                ) : (
                  <div className="text-sm text-muted-foreground bg-muted/50 rounded-lg p-3">
                    <p className="font-medium mb-1">One-time setup</p>
                    <p>
                      Generate an OTP to create your permanent Secret API Key. This only needs to
                      be done once.
                    </p>
                  </div>
                )}

                {!otpSent ? (
                  <Button onClick={handleGenerateOtp} className="w-full" disabled={isLoading}>
                    {isLoading ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        Sending OTP...
                      </>
                    ) : (
                      <>
                        <Smartphone className="mr-2 h-4 w-4" />
                        Send OTP
                      </>
                    )}
                  </Button>
                ) : (
                  <div className="space-y-3">
                    <div className="space-y-2">
                      <Label htmlFor="otp">Enter OTP</Label>
                      <Input
                        id="otp"
                        type="text"
                        inputMode="numeric"
                        placeholder="Enter OTP from mobile/email"
                        value={otp}
                        onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))}
                        disabled={isLoading}
                        maxLength={8}
                      />
                      <p className="text-xs text-muted-foreground">
                        OTP sent to your registered mobile and email
                      </p>
                    </div>

                    <Button
                      onClick={handleGenerateSecretKey}
                      className="w-full"
                      disabled={isLoading || !otp.trim()}
                    >
                      {isLoading ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          Generating Secret Key...
                        </>
                      ) : (
                        <>
                          <Key className="mr-2 h-4 w-4" />
                          Generate Secret Key
                        </>
                      )}
                    </Button>

                    <Button
                      variant="ghost"
                      size="sm"
                      className="w-full"
                      onClick={() => {
                        setOtpSent(false)
                        setOtp('')
                        setSuccessMessage(null)
                        setError(null)
                      }}
                    >
                      Resend OTP
                    </Button>
                  </div>
                )}
              </div>
            )}

            {/* Step 2: Save Secret Key */}
            {currentStep === 'secret-key' && (
              <div className="space-y-4">
                <div className="text-sm text-muted-foreground bg-muted/50 rounded-lg p-3">
                  <Mail className="h-4 w-4 inline mr-1" />
                  <span className="font-medium">Check your email</span>
                  <p className="mt-1">
                    Your Secret API Key has been sent to your registered email. Copy it and paste it
                    below.
                  </p>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="secretApiKey">Secret API Key</Label>
                  <Input
                    id="secretApiKey"
                    type="password"
                    placeholder="Paste secret API key from email"
                    value={secretApiKey}
                    onChange={(e) => setSecretApiKey(e.target.value)}
                    disabled={isLoading}
                  />
                  <p className="text-xs text-muted-foreground">
                    This key never expires. Keep it secure and do not share it.
                  </p>
                </div>

                <Button
                  onClick={handleSaveSecretKey}
                  className="w-full"
                  disabled={isLoading || !secretApiKey.trim()}
                >
                  {isLoading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Saving...
                    </>
                  ) : (
                    <>
                      <Check className="mr-2 h-4 w-4" />
                      Save Secret Key
                    </>
                  )}
                </Button>
              </div>
            )}

            {/* Step 3: IP Management */}
            {currentStep === 'ip' && (
              <div className="space-y-4">
                {ipStatus && !ipStatus.editable && (
                  <Alert variant="warning">
                    <Lock className="h-4 w-4" />
                    <AlertDescription>
                      IP was updated this week. Next edit available:{' '}
                      <strong>{ipStatus.next_editable_date}</strong>
                    </AlertDescription>
                  </Alert>
                )}

                <div className="space-y-3">
                  <div className="space-y-2">
                    <Label htmlFor="primaryIp">Primary IP Address</Label>
                    <Input
                      id="primaryIp"
                      type="text"
                      placeholder="e.g. 203.0.113.10"
                      value={primaryIp}
                      onChange={(e) => setPrimaryIp(e.target.value)}
                      disabled={isLoading || (ipStatus !== null && !ipStatus.editable && ipStatus.primary_ip !== null)}
                      pattern="[0-9.]+"
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="secondaryIp">
                      Secondary IP Address <span className="text-muted-foreground">(optional)</span>
                    </Label>
                    <Input
                      id="secondaryIp"
                      type="text"
                      placeholder="e.g. 203.0.113.11"
                      value={secondaryIp}
                      onChange={(e) => setSecondaryIp(e.target.value)}
                      disabled={isLoading || (ipStatus !== null && !ipStatus.editable && ipStatus.secondary_ip !== null)}
                      pattern="[0-9.]+"
                    />
                  </div>

                  <p className="text-xs text-muted-foreground">
                    Only IPv4 addresses allowed. API access will be restricted to these IPs.
                    Updates allowed once per calendar week.
                  </p>
                </div>

                <div className="flex gap-2">
                  {(ipStatus?.editable || !ipStatus?.primary_ip || !ipStatus?.secondary_ip) && (
                    <Button
                      onClick={() => {
                        if (!primaryIp.trim()) {
                          setError('Primary IP address is required')
                          return
                        }
                        setError(null)
                        setShowIpConfirm(true)
                      }}
                      className="flex-1"
                      disabled={isLoading || !primaryIp.trim()}
                    >
                      <Network className="mr-2 h-4 w-4" />
                      {ipStatus?.primary_ip ? 'Update IP' : 'Register IP'}
                    </Button>
                  )}

                  <Button
                    variant="outline"
                    onClick={() => setCurrentStep('login')}
                    className="flex-1"
                  >
                    {ipStatus?.primary_ip ? 'Continue to Login' : 'Skip for Now'}
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}

            {/* Step 4: Login */}
            {currentStep === 'login' && (
              <div className="space-y-4">
                <div className="text-sm text-muted-foreground bg-muted/50 rounded-lg p-3">
                  <p>
                    This will generate an access token using your stored Secret API Key and log you
                    in with your configured credentials.
                  </p>
                </div>

                <Button onClick={handleLogin} className="w-full" disabled={isLoading}>
                  {isLoading ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Authenticating...
                    </>
                  ) : (
                    <>
                      <Shield className="mr-2 h-4 w-4" />
                      Login to Samco
                    </>
                  )}
                </Button>
              </div>
            )}

            <div className="mt-6 space-y-3 text-center text-sm text-muted-foreground">
              <p>Your credentials are securely transmitted and encrypted.</p>
              <div className="flex items-center justify-center gap-4">
                <Link
                  to="/broker"
                  className="text-primary hover:underline inline-flex items-center gap-1"
                >
                  <ArrowLeft className="h-3 w-3" />
                  Back to Broker Selection
                </Link>
                <a
                  href="https://docs.openalgo.in"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline inline-flex items-center gap-1"
                >
                  Documentation
                  <ExternalLink className="h-3 w-3" />
                </a>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* IP Update Confirmation Dialog */}
        <AlertDialog open={showIpConfirm} onOpenChange={setShowIpConfirm}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>
                <AlertTriangle className="h-5 w-5 inline mr-2 text-amber-500" />
                Confirm IP {ipStatus?.primary_ip ? 'Update' : 'Registration'}
              </AlertDialogTitle>
              <AlertDialogDescription asChild>
                <div className="space-y-2">
                  <span className="block">You can only change your IP once per calendar week.</span>
                  <span className="block bg-muted rounded-md p-3 text-sm mt-2">
                    <span className="block">
                      <strong>Primary IP:</strong> {primaryIp}
                    </span>
                    {secondaryIp && (
                      <span className="block">
                        <strong>Secondary IP:</strong> {secondaryIp}
                      </span>
                    )}
                  </span>
                  <span className="block">Are you sure you want to proceed?</span>
                </div>
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={isLoading}>Cancel</AlertDialogCancel>
              <AlertDialogAction onClick={handleUpdateIp} disabled={isLoading}>
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Updating...
                  </>
                ) : (
                  'Confirm'
                )}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </div>
  )
}
