import {
  AlertCircle,
  ArrowLeft,
  Check,
  CheckCircle,
  ChevronRight,
  Info,
  Lock,
  Mail,
  Shield,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { fetchCSRFToken } from '@/api/client'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Progress } from '@/components/ui/progress'

type Step = 'email' | 'method' | 'totp' | 'email_sent' | 'password'

interface PasswordRequirements {
  length: boolean
  uppercase: boolean
  lowercase: boolean
  number: boolean
  special: boolean
}

export default function ResetPassword() {
  const [searchParams] = useSearchParams()
  const [step, setStep] = useState<Step>('email')
  const [email, setEmail] = useState('')
  const [totpCode, setTotpCode] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [token, setToken] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  // Password validation
  const [requirements, setRequirements] = useState<PasswordRequirements>({
    length: false,
    uppercase: false,
    lowercase: false,
    number: false,
    special: false,
  })
  const [passwordStrength, setPasswordStrength] = useState(0)
  const [passwordsMatch, setPasswordsMatch] = useState<boolean | null>(null)

  // Check URL params for email link verification
  useEffect(() => {
    const urlToken = searchParams.get('token')
    const urlEmail = searchParams.get('email')
    const verified = searchParams.get('verified')
    const urlError = searchParams.get('error')

    // Handle errors from email link validation
    if (urlError) {
      const errorMessages: Record<string, string> = {
        invalid_link: 'Invalid reset link. Please request a new one.',
        expired_link: 'This reset link has expired. Please request a new one.',
        session_expired: 'Your session has expired. Please start the reset process again.',
        processing_error: 'An error occurred. Please try again.',
      }
      setError(errorMessages[urlError] || 'An error occurred.')
      return
    }

    // If coming from email link with valid token, skip to password step
    if (urlToken && urlEmail && verified === 'true') {
      setToken(urlToken)
      setEmail(urlEmail)
      setStep('password')
    }
  }, [searchParams])

  // Check password requirements
  useEffect(() => {
    const newReqs = {
      length: password.length >= 8,
      uppercase: /[A-Z]/.test(password),
      lowercase: /[a-z]/.test(password),
      number: /[0-9]/.test(password),
      special: /[!@#$%^&*]/.test(password),
    }
    setRequirements(newReqs)

    // Calculate strength
    let score = 0
    if (password.length >= 8) score += 20
    if (password.length >= 12) score += 10
    if (password.length >= 16) score += 10
    if (newReqs.uppercase) score += 15
    if (newReqs.lowercase) score += 15
    if (newReqs.number) score += 15
    if (newReqs.special) score += 15
    setPasswordStrength(score)
  }, [password])

  // Check password match
  useEffect(() => {
    if (confirmPassword === '') {
      setPasswordsMatch(null)
    } else {
      setPasswordsMatch(password === confirmPassword)
    }
  }, [password, confirmPassword])

  const allRequirementsMet = Object.values(requirements).every(Boolean)
  const canSubmitPassword = allRequirementsMet && passwordsMatch === true

  const getStrengthLabel = () => {
    if (passwordStrength >= 80) return { label: 'Strong', color: 'text-green-500' }
    if (passwordStrength >= 50) return { label: 'Medium', color: 'text-yellow-500' }
    if (passwordStrength > 0) return { label: 'Weak', color: 'text-red-500' }
    return { label: '', color: '' }
  }

  const handleEmailSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')

    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/auth/reset-password', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({ step: 'email', email }),
      })

      const data = await response.json()

      if (data.status === 'success') {
        setStep('method')
      } else {
        setError(data.message || 'Email not found')
      }
    } catch {
      setError('Failed to process request')
    } finally {
      setLoading(false)
    }
  }

  const handleMethodSelect = async (method: 'totp' | 'email') => {
    setLoading(true)
    setError('')

    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/auth/reset-password', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({ step: `select_${method}`, email }),
      })

      const data = await response.json()

      if (data.status === 'success') {
        if (method === 'totp') {
          setStep('totp')
        } else {
          setStep('email_sent')
        }
      } else {
        setError(data.message || 'Failed to select method')
      }
    } catch {
      setError('Failed to process request')
    } finally {
      setLoading(false)
    }
  }

  const handleTotpSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')

    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/auth/reset-password', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({ step: 'totp', email, totp_code: totpCode }),
      })

      const data = await response.json()

      if (data.status === 'success') {
        setToken(data.token || '')
        setStep('password')
      } else {
        setError(data.message || 'Invalid TOTP code')
      }
    } catch {
      setError('Failed to verify code')
    } finally {
      setLoading(false)
    }
  }

  const handlePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmitPassword) return

    setLoading(true)
    setError('')

    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/auth/reset-password', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({
          step: 'password',
          email,
          token,
          password,
          confirm_password: confirmPassword,
        }),
      })

      const data = await response.json()

      if (data.status === 'success') {
        setSuccess('Password reset successfully! Redirecting to login...')
        showToast.success('Password reset successfully!')
        setTimeout(() => {
          window.location.href = '/login'
        }, 2000)
      } else {
        setError(data.message || 'Failed to reset password')
      }
    } catch {
      setError('Failed to reset password')
    } finally {
      setLoading(false)
    }
  }

  const RequirementItem = ({ met, label }: { met: boolean; label: string }) => (
    <div
      className={`flex items-center gap-2 text-sm transition-colors ${met ? 'text-green-500' : 'text-muted-foreground'}`}
    >
      <Check className={`h-4 w-4 ${met ? 'opacity-100' : 'opacity-0'}`} />
      <span>{label}</span>
    </div>
  )

  return (
    <div className="min-h-[calc(100vh-8rem)] flex items-center justify-center p-4">
      <div className="w-full max-w-lg">
        <Card>
          <CardHeader>
            <CardTitle className="text-2xl">Reset Password</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {error && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            {success && (
              <Alert className="border-green-500 bg-green-50 dark:bg-green-950">
                <CheckCircle className="h-4 w-4 text-green-500" />
                <AlertDescription className="text-green-700 dark:text-green-300">
                  {success}
                </AlertDescription>
              </Alert>
            )}

            {/* Step 1: Email Form */}
            {step === 'email' && (
              <form onSubmit={handleEmailSubmit} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="email">Email Address</Label>
                  <Input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="Enter your email"
                    required
                    autoFocus
                  />
                  <p className="text-sm text-muted-foreground">
                    Enter the email address associated with your account
                  </p>
                </div>
                <Button type="submit" className="w-full" disabled={loading}>
                  {loading ? 'Processing...' : 'Continue'}
                </Button>
              </form>
            )}

            {/* Step 2: Choose Verification Method */}
            {step === 'method' && (
              <div className="space-y-4">
                <div className="text-center mb-6">
                  <h3 className="text-lg font-semibold">Choose Verification Method</h3>
                  <p className="text-muted-foreground text-sm mt-2">
                    How would you like to verify your identity?
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => handleMethodSelect('totp')}
                  disabled={loading}
                  className="w-full p-4 rounded-lg border bg-muted/50 hover:bg-muted transition-colors text-left"
                >
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-full bg-primary flex items-center justify-center">
                      <Shield className="h-6 w-6 text-primary-foreground" />
                    </div>
                    <div className="flex-1">
                      <h4 className="font-semibold">Authenticator App (TOTP)</h4>
                      <p className="text-sm text-muted-foreground">
                        Use your authenticator app to generate a verification code
                      </p>
                    </div>
                    <ChevronRight className="h-5 w-5 text-muted-foreground" />
                  </div>
                </button>

                <button
                  type="button"
                  onClick={() => handleMethodSelect('email')}
                  disabled={loading}
                  className="w-full p-4 rounded-lg border bg-muted/50 hover:bg-muted transition-colors text-left"
                >
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-full bg-secondary flex items-center justify-center">
                      <Mail className="h-6 w-6 text-secondary-foreground" />
                    </div>
                    <div className="flex-1">
                      <h4 className="font-semibold">Email Reset Link</h4>
                      <p className="text-sm text-muted-foreground">
                        Receive a password reset link via email
                      </p>
                    </div>
                    <ChevronRight className="h-5 w-5 text-muted-foreground" />
                  </div>
                </button>
              </div>
            )}

            {/* Step 3a: TOTP Verification */}
            {step === 'totp' && (
              <form onSubmit={handleTotpSubmit} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="totp">TOTP Code</Label>
                  <Input
                    id="totp"
                    type="text"
                    value={totpCode}
                    onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    placeholder="000000"
                    pattern="[0-9]{6}"
                    maxLength={6}
                    className="text-center text-2xl tracking-widest"
                    required
                    autoFocus
                  />
                  <p className="text-sm text-muted-foreground">
                    Enter the 6-digit code from your authenticator app
                  </p>
                </div>
                <Button
                  type="submit"
                  className="w-full"
                  disabled={loading || totpCode.length !== 6}
                >
                  {loading ? 'Verifying...' : 'Verify Code'}
                </Button>
              </form>
            )}

            {/* Step 3b: Email Sent Confirmation */}
            {step === 'email_sent' && (
              <div className="text-center space-y-4">
                <div className="flex justify-center">
                  <div className="w-16 h-16 rounded-full bg-green-500 flex items-center justify-center">
                    <Mail className="h-8 w-8 text-white" />
                  </div>
                </div>
                <h3 className="text-lg font-semibold">Check Your Email</h3>
                <p className="text-muted-foreground">
                  We've sent a password reset link to <strong>{email}</strong>. Click the link in
                  the email to continue resetting your password.
                </p>
                <Alert>
                  <Info className="h-4 w-4" />
                  <AlertDescription>
                    <strong>Didn't receive the email?</strong>
                    <ul className="list-disc list-inside mt-2 space-y-1 text-sm">
                      <li>Check your spam/junk folder</li>
                      <li>Make sure {email} is correct</li>
                      <li>The link expires in 1 hour</li>
                    </ul>
                  </AlertDescription>
                </Alert>
                <div className="flex gap-2 justify-center">
                  <Button variant="outline" size="sm" onClick={() => setStep('method')}>
                    Try Different Method
                  </Button>
                  <Button size="sm" asChild>
                    <Link to="/login">Back to Login</Link>
                  </Button>
                </div>
              </div>
            )}

            {/* Step 4: New Password */}
            {step === 'password' && (
              <form onSubmit={handlePasswordSubmit} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="password">New Password</Label>
                  <Input
                    id="password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Enter new password"
                    required
                    autoFocus
                  />
                  <Progress value={passwordStrength} className="h-2" />
                  {password && (
                    <p className={`text-sm font-medium ${getStrengthLabel().color}`}>
                      {getStrengthLabel().label}
                    </p>
                  )}
                </div>

                <div className="space-y-2">
                  <Label htmlFor="confirmPassword">Confirm New Password</Label>
                  <Input
                    id="confirmPassword"
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Confirm new password"
                    required
                  />
                  {passwordsMatch !== null && (
                    <p className={`text-sm ${passwordsMatch ? 'text-green-500' : 'text-red-500'}`}>
                      {passwordsMatch ? 'Passwords match' : 'Passwords do not match'}
                    </p>
                  )}
                </div>

                <div className="bg-muted rounded-lg p-4 space-y-2">
                  <RequirementItem met={requirements.length} label="Minimum 8 characters" />
                  <RequirementItem
                    met={requirements.uppercase}
                    label="At least 1 uppercase letter (A-Z)"
                  />
                  <RequirementItem
                    met={requirements.lowercase}
                    label="At least 1 lowercase letter (a-z)"
                  />
                  <RequirementItem met={requirements.number} label="At least 1 number (0-9)" />
                  <RequirementItem
                    met={requirements.special}
                    label="At least 1 special character (!@#$%^&*)"
                  />
                </div>

                <Button type="submit" className="w-full" disabled={loading || !canSubmitPassword}>
                  <Lock className="h-4 w-4 mr-2" />
                  {loading ? 'Resetting...' : 'Reset Password'}
                </Button>
              </form>
            )}

            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-background px-2 text-muted-foreground">OR</span>
              </div>
            </div>

            <div className="text-center">
              <Link
                to="/login"
                className="text-sm text-primary hover:underline inline-flex items-center gap-1"
              >
                <ArrowLeft className="h-4 w-4" />
                Back to Login
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
