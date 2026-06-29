import { Navigate } from 'react-router-dom';
import { readEnv } from '@/services/env';

interface DevRouteGateProps {
  children: React.ReactNode;
  fallback?: string;
}

export function DevRouteGate({ children, fallback = '/jobs' }: DevRouteGateProps) {
  if (readEnv('VITE_ENABLE_DEV_ROUTES') === '1') {
    return <>{children}</>;
  }
  return <Navigate to={fallback} replace />;
}
