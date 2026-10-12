import { Navigate, Outlet, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import { AppError } from '@/core/http/AppError';
import { isJoinable } from '@/domain/session/session.types';
import { RouteState } from './RouteState';

export function RequireSession() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { session } = useServices();

  const query = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => session.getSession(sessionId as string, 'customer'),
    enabled: Boolean(sessionId),
  });

  if (query.isPending) {
    return <RouteState />;
  }

  // A failed re-read of a session already shown is kept unless the server's
  // answer is final: a network blip must not tear down a live conversation.
  const finalError = query.isError && !(query.error instanceof AppError && query.error.retryable);
  if (!query.data || !isJoinable(query.data) || finalError) {
    const taken = query.error instanceof AppError && query.error.kind === 'sessionHasGuest';
    return <Navigate to="/" replace state={taken ? { notice: 'sessionHasGuest' } : undefined} />;
  }

  return <Outlet />;
}
