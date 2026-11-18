import { z } from 'zod';
import type { AxiosInstance } from 'axios';
import { summary } from '@/domain/archive/verification.mapper';

const identifier = z.string().min(1);
const row = z
  .object({
    id: identifier,
    session_id: identifier.nullable(),
    recording_id: identifier.nullable(),
    origin: z.enum(['own', 'transferred']),
    started_at: z.string(),
    ended_at: z.string().nullable(),
    conversation_status: z.enum(['pending', 'active', 'ended']),
    recording_status: z.enum(['none', 'available', 'incomplete', 'unavailable']),
    recording_access: z.enum(['none', 'unlock_required', 'available', 'transfer_required']),
    customer_language: z.string().nullable(),
    language_visibility: z.enum(['clear', 'encrypted', 'unknown']),
    verification: summary.nullable(),
    actions: z.array(z.enum(['resume', 'open_recording', 'open_details'])),
  })
  .transform((row) => ({
    ...row,
    customer_language:
      row.language_visibility === 'clear' && row.recording_status === 'none'
        ? row.customer_language
        : null,
  }));
const page = z.object({ items: z.array(row), next_cursor: identifier.nullable() });
const result = z.object({
  verification_id: identifier,
  status: z.enum(['approved', 'not_approved']),
  outcome: z.enum(['approved', 'not_approved']),
  requested_at: z.string(),
  decided_at: z.string(),
  requested_by_name: z.string().nullable().optional(),
});
export type ConversationRow = z.infer<typeof row>;
export function createDashboardRepository(http: AxiosInstance) {
  return {
    async conversations(cursor: string | null, signal?: AbortSignal) {
      const params = cursor ? { limit: 50, cursor } : { limit: 50 };
      return page.parse(
        (await http.get<unknown>('/api/admin/dashboard/conversations', { params, signal })).data
      );
    },
    async result(id: string, signal?: AbortSignal) {
      const value = result.parse(
        (
          await http.get<unknown>(
            `/api/admin/recording/verifications/${encodeURIComponent(id)}/result`,
            { signal }
          )
        ).data
      );
      if (value.verification_id !== id || value.status !== value.outcome)
        throw new Error('Unexpected decision');
      return value;
    },
  };
}
