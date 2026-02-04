import { AlertTriangle, BookOpen, Download, HelpCircle, Home, LogOut } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { fetchCSRFToken } from '@/api/client'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'

export default function ServerError() {
  const [isLoggingOut, setIsLoggingOut] = useState(false)

  const handleLogout = async () => {
    setIsLoggingOut(true)
    try {
      const csrfToken = await fetchCSRFToken()
      const response = await fetch('/auth/logout', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
      })

      if (response.ok) {
        window.location.href = '/login'
      } else {
        showToast.error('Failed to logout. Please try again.')
      }
    } catch {
      // If logout fails, redirect to login anyway
      window.location.href = '/login'
    } finally {
      setIsLoggingOut(false)
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
          <span className="text-destructive">500</span> - Internal Server Error
        </h1>

        <p className="text-xl text-muted-foreground mb-6">
          Oops! Something went wrong. Don't worry, we're here to help you resolve this.
        </p>

        {/* API Key Warning */}
        <Alert variant="warning" className="mb-8 text-left">
          <AlertTriangle className="h-5 w-5" />
          <AlertTitle>Common Cause</AlertTitle>
          <AlertDescription>
            Please check if your <strong>API Key</strong> or <strong>API Secret</strong> is valid.
            <br />
            If you updated the <strong>.env</strong> file while logged in,{' '}
            <span className="text-red-600 font-bold">logout</span> and{' '}
            <span className="text-green-600 font-bold">login again</span> to refresh credentials.
          </AlertDescription>
        </Alert>

        <div className="flex flex-wrap justify-center gap-4 mb-8">
          <Button variant="destructive" onClick={handleLogout} disabled={isLoggingOut}>
            <LogOut className="h-4 w-4 mr-2" />
            {isLoggingOut ? 'Logging out...' : 'Logout & Fix Issue'}
          </Button>

          <Button variant="outline" asChild>
            <Link to="/">
              <Home className="h-4 w-4 mr-2" />
              Back to Home
            </Link>
          </Button>
        </div>

        {/* Divider */}
        <div className="relative my-8">
          <div className="absolute inset-0 flex items-center">
            <span className="w-full border-t" />
          </div>
          <div className="relative flex justify-center text-xs uppercase">
            <span className="bg-background px-2 text-muted-foreground">Quick Links</span>
          </div>
        </div>

        {/* Quick Links */}
        <div className="flex flex-wrap justify-center gap-4">
          <Button variant="ghost" size="sm" asChild>
            <a href="https://docs.openalgo.in" target="_blank" rel="noopener noreferrer">
              <BookOpen className="h-4 w-4 mr-2" />
              Documentation
            </a>
          </Button>
          <Button variant="ghost" size="sm" asChild>
            <Link to="/faq">
              <HelpCircle className="h-4 w-4 mr-2" />
              FAQ
            </Link>
          </Button>
          <Button variant="ghost" size="sm" asChild>
            <Link to="/download">
              <Download className="h-4 w-4 mr-2" />
              Download
            </Link>
          </Button>
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
