import type { Session, SessionStatus } from './session.types';

/** `Session.to_dict()`, as in the admin history rows — the field is `id`, not `session_id`. */
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

/**
 * GET /api/admin/session/{id}/status and GET /api/customer/session/{id}. Unlike
 * `Session.to_dict()`, both answer with `session_id`, neither sends the admin
 * language, and only the admin variant counts messages.
 */
export interface SessionStatusDto {
  session_id: string;
  status: SessionStatus;
  customer_language: string | null;
  admin_connected: boolean;
  customer_connected: boolean;
  created_at: string;
  message_count?: number;
}

/** The gateway fixes every session's admin language at German and does not report it. */
const GATEWAY_ADMIN_LANGUAGE = 'de';

export function statusToSession(dto: SessionStatusDto): Session {
  return {
    id: dto.session_id,
    status: dto.status,
    customerLanguage: dto.customer_language,
    adminLanguage: GATEWAY_ADMIN_LANGUAGE,
    createdAt: dto.created_at,
    messageCount: dto.message_count ?? 0,
    adminConnected: dto.admin_connected,
    customerConnected: dto.customer_connected,
  };
}

export function activationToSession(dto: ActivateSessionDto, previous?: Session): Session {
  return {
    id: dto.session_id,
    status: dto.status,
    customerLanguage: dto.customer_language,
    adminLanguage: previous?.adminLanguage ?? GATEWAY_ADMIN_LANGUAGE,
    createdAt: previous?.createdAt ?? dto.timestamp,
    messageCount: previous?.messageCount ?? 0,
    adminConnected: previous?.adminConnected ?? false,
    customerConnected: true,
  };
}

/**
 * The activation response carries only what activation decides: the status and
 * the customer's language. It says nothing about the admin's language, the
 * history count or who else is connected, so an earlier read of the session
 * stands for those rather than being replaced by a default.
 */
export function mergeActivatedSession(activated: Session, previous?: Session): Session {
  if (previous === undefined) {
    return activated;
  }

  return {
    ...previous,
    id: activated.id,
    status: activated.status,
    customerLanguage: activated.customerLanguage,
    customerConnected: activated.customerConnected,
  };
}
