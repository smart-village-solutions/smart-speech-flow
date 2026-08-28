import type { SessionInfoDto } from '@/domain/session/session.mapper';
import type { AdminSession, AdminSessionStatus, CreatedSession } from './admin.types';

/**
 * A history row is `Session.to_dict()` — the same payload `GET /api/session/{id}`
 * returns, plus the termination fields. Both arrays of the history response use
 * this shape.
 */
export interface AdminSessionDto extends SessionInfoDto {
  terminated_at?: string | null;
  termination_reason?: string | null;
}

/** POST /api/admin/session/create. */
export interface SessionCreateDto {
  session_id: string;
  client_url: string;
  status: string;
  created_at: string;
  message?: string;
}

/** GET /api/admin/session/history — both arrays default server-side. */
export interface SessionHistoryDto {
  sessions?: AdminSessionDto[];
  active_sessions?: AdminSessionDto[];
}

/**
 * Total by construction: anything not demonstrably live is inert. An unknown
 * status must not render as re-enterable, so `completed` is the default rather
 * than a thrown error on a payload the UI cannot fix.
 */
function toStatus(raw: string): AdminSessionStatus {
  if (raw === 'active') {
    return 'connected';
  }
  if (raw === 'pending') {
    return 'open';
  }
  return 'completed';
}

export function toCreatedSession(dto: SessionCreateDto): CreatedSession {
  return {
    id: dto.session_id,
    clientUrl: dto.client_url,
    createdAt: dto.created_at,
  };
}

function toAdminSession(dto: AdminSessionDto): AdminSession {
  return {
    id: dto.id,
    status: toStatus(dto.status),
    customerLanguage: dto.customer_language,
    createdAt: dto.created_at,
    terminatedAt: dto.terminated_at ?? null,
  };
}

/**
 * History carries terminated sessions only; the live one arrives separately.
 * They are merged into one list ordered by start time, because that is the
 * timestamp the list's own column shows — ordering by termination would leave
 * the visible column looking unsorted. The id breaks ties so the order is
 * total: two sessions can share a second, and a partial order would let the
 * list reshuffle between refetches. Timestamps are compared as strings rather
 * than with `localeCompare`, since ISO 8601 at a fixed offset sorts
 * lexicographically and collation has no business here.
 */
export function toAdminSessions(dto: SessionHistoryDto): AdminSession[] {
  return [...(dto.sessions ?? []), ...(dto.active_sessions ?? [])]
    .map(toAdminSession)
    .sort((a, b) => {
      if (a.createdAt !== b.createdAt) {
        return a.createdAt < b.createdAt ? 1 : -1;
      }
      return a.id < b.id ? -1 : 1;
    });
}
