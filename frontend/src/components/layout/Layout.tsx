import { Outlet, Navigate } from 'react-router-dom';
import { Navbar } from './Navbar';
import { Footer } from './Footer';
import { useAuthStore } from '@/stores/authStore';
import { Toaster } from '@/components/ui/sonner';

export function Layout() {
  const { isAuthenticated, user } = useAuthStore();

  // AuthSync has already synced Flask session with Zustand store
  // So we just need to check the Zustand store state
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  // If logged in but no broker selected, redirect to broker selection
  if (!user?.broker) {
    return <Navigate to="/broker" replace />;
  }

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <Navbar />
      <main className="container mx-auto px-4 py-6 flex-1">
        <Outlet />
      </main>
      <Footer />
      <Toaster position="top-right" richColors />
    </div>
  );
}

export function PublicLayout() {
  return (
    <div className="min-h-screen bg-background">
      <Outlet />
      <Toaster position="top-right" richColors />
    </div>
  );
}
