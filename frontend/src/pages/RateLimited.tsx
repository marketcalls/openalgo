import { Clock, Home, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'

export default function RateLimited() {
  const [countdown, setCountdown] = useState(60)
  const [canRetry, setCanRetry] = useState(false)

  useEffect(() => {
    if (countdown > 0) {
      const timer = setTimeout(() => setCountdown(countdown - 1), 1000)
      return () => clearTimeout(timer)
    } else {
      setCanRetry(true)
    }
  }, [countdown])

  const handleRetry = () => {
    // Go back to previous page or dashboard
    const referrer = document.referrer
    if (referrer?.includes(window.location.origin)) {
      window.location.href = referrer
    } else {
      window.location.href = '/dashboard'
    }
  }

  return (
    <div className="min-h-[calc(100vh-16rem)] flex items-center justify-center p-4">
      <div className="text-center max-w-md">
        {/* Floating yoga illustration */}
        <div className="mb-8">
          <img
            src="/images/yoga.png"
            alt="Meditation illustration"
            className="w-64 h-64 mx-auto animate-float"
            onError={(e) => {
              e.currentTarget.style.display = 'none'
            }}
          />
        </div>

        <h1 className="text-5xl font-bold mb-4">
          <span className="text-orange-500">429</span> - Too Many Requests
        </h1>

        <p className="text-xl text-muted-foreground mb-6">
          You've made too many requests in a short period. Please take a moment and try again.
        </p>

        {/* Rate Limit Info */}
        <Alert variant="warning" className="mb-8 text-left">
          <Clock className="h-5 w-5" />
          <AlertTitle>Rate Limit Exceeded</AlertTitle>
          <AlertDescription>
            To ensure fair usage and protect the system, request limits are enforced.
            <br />
            <br />
            <strong>Common limits:</strong>
            <ul className="list-disc list-inside mt-2 space-y-1">
              <li>Login: 5 attempts per minute</li>
              <li>Orders: 10 per second</li>
              <li>API calls: 50 per second</li>
            </ul>
          </AlertDescription>
        </Alert>

        {/* Countdown Timer */}
        <div className="mb-8">
          {!canRetry ? (
            <div className="text-center">
              <div className="text-4xl font-mono font-bold text-orange-500 mb-2">{countdown}s</div>
              <p className="text-muted-foreground">Wait before retrying</p>
            </div>
          ) : (
            <p className="text-green-600 dark:text-green-400 font-medium">You can retry now!</p>
          )}
        </div>

        <div className="flex flex-wrap justify-center gap-4 mb-8">
          <Button
            variant={canRetry ? 'default' : 'outline'}
            onClick={handleRetry}
            disabled={!canRetry}
          >
            <RefreshCw className={`h-4 w-4 mr-2 ${!canRetry ? 'animate-spin' : ''}`} />
            {canRetry ? 'Retry Now' : 'Please Wait...'}
          </Button>

          <Button variant="outline" asChild>
            <Link to="/">
              <Home className="h-4 w-4 mr-2" />
              Back to Home
            </Link>
          </Button>
        </div>

        {/* Tips */}
        <div className="text-sm text-muted-foreground">
          <p className="mb-2">
            <strong>Tips to avoid rate limits:</strong>
          </p>
          <ul className="list-disc list-inside text-left space-y-1">
            <li>Space out your API requests</li>
            <li>Use batch endpoints when available</li>
            <li>Cache responses locally when possible</li>
          </ul>
        </div>
      </div>

      <style>{`
        @keyframes float {
          0% { transform: translateY(0px); }
          50% { transform: translateY(-10px); }
          100% { transform: translateY(0px); }
        }
        .animate-float {
          animation: float 3s ease-in-out infinite;
        }
      `}</style>
    </div>
  )
}
