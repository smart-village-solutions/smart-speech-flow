/** The three states the dashboard list distinguishes, as the export names them. */
export type AdminSessionStatus = 'connected' | 'open' | 'completed';

export interface AdminSession {
  id: string;
  status: AdminSessionStatus;
  customerLanguage: string | null;
  createdAt: string;
  terminatedAt: string | null;
}

export interface CreatedSession {
  id: string;
  /** The gateway's own join URL. Displayed verbatim; never rebuilt here. */
  clientUrl: string;
  createdAt: string;
}

/** A completed session has no conversation left to re-enter, so its row is inert. */
export function isReenterable(session: AdminSession): boolean {
  return session.status !== 'completed';
}
