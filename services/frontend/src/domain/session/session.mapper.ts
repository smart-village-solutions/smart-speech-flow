import type { Session, SessionStatus } from './session.types';

/** GET /api/session/{id} — note the field is `id`, not `session_id`. */
export interface SessionInfoDto {
  id: string;
  customer_language: string | null;
  admin_language: string;
  status: SessionStatus;
  created_at: string;
  message_count: number;
  admin_connected: boolean;
  customer_connected: boolean;
}

/** POST /api/customer/session/activate. */
export interface ActivateSessionDto {
  session_id: string;
  status: SessionStatus;
  customer_language: string;
  message: string;
  timestamp: string;
}

export function toSession(dto: SessionInfoDto): Session {
  return {
    id: dto.id,
    status: dto.status,
    customerLanguage: dto.customer_language,
    adminLanguage: dto.admin_language,
    createdAt: dto.created_at,
    messageCount: dto.message_count,
    adminConnected: dto.admin_connected,
    customerConnected: dto.customer_connected,
  };
}

export function activationToSession(dto: ActivateSessionDto, previous?: Session): Session {
  return {
    id: dto.session_id,
    status: dto.status,
    customerLanguage: dto.customer_language,
    adminLanguage: previous?.adminLanguage ?? 'de',
    createdAt: previous?.createdAt ?? dto.timestamp,
    messageCount: previous?.messageCount ?? 0,
    adminConnected: previous?.adminConnected ?? false,
    customerConnected: true,
  };
}
