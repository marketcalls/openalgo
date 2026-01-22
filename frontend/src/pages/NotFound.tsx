import { BookOpen, Download, HelpCircle, Home, LogIn } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'

export default function NotFound() {
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
              // Hide image if not found
              e.currentTarget.style.display = 'none'
            }}
          />
        </div>

        <h1 className="text-5xl font-bold mb-4">
          <span className="text-primary">404</span> - Page Not Found
        </h1>

        <p className="text-xl text-muted-foreground mb-8">
          The page you're looking for doesn't exist or has been moved. Don't worry, let's get you
          back on track.
        </p>

        <div className="flex flex-wrap justify-center gap-4 mb-8">
          <Button asChild>
            <Link to="/">
              <Home className="h-4 w-4 mr-2" />
              Back to Home
            </Link>
          </Button>

          <Button variant="outline" asChild>
            <Link to="/login">
              <LogIn className="h-4 w-4 mr-2" />
              Login
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
