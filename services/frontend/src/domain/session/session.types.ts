export type SessionStatus = 'inactive' | 'pending' | 'active' | 'terminated';

export interface Session {
  id: string;
  status: SessionStatus;
  customerLanguage: string | null;
  adminLanguage: string;
  createdAt: string;
  messageCount: number;
  adminConnected: boolean;
  customerConnected: boolean;
}

/** A customer may join a session that is waiting or already running. */
export function isJoinable(session: Session): boolean {
  return session.status === 'pending' || session.status === 'active';
}
