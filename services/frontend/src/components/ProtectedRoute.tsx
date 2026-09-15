import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';

interface ProtectedRouteProps {
  children: ReactNode;
}

export default function ProtectedRoute({ children }: Readonly<ProtectedRouteProps>) {
  const location = useLocation();
  const isAuthenticated = sessionStorage.getItem('authenticated') === 'true';

  if (!isAuthenticated) {
    return <Navigate to="/" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}
