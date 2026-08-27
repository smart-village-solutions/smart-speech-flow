import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';

interface ProtectedRouteProps {
  children: ReactNode;
}

export default function ProtectedRoute({ children }: Readonly<ProtectedRouteProps>) {
  const location = useLocation();
  const isAuthenticated = sessionStorage.getItem('authenticated') === 'true';

  // Hand the intended path to the password gate so it can forward there once
  // the password is accepted, instead of dropping the visitor on the chooser.
  if (!isAuthenticated) {
    return <Navigate to="/legacy" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}
