import { Navigate, Outlet, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import { isJoinable } from '@/domain/session/session.types';

export function RequireSession() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { session } = useServices();

  const query = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => session.getSession(sessionId as string),
    enabled: Boolean(sessionId),
  });

  if (query.isPending) {
    return null;
  }

  if (query.isError || !query.data || !isJoinable(query.data)) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
