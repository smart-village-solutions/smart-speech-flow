import { z } from 'zod';
import { toOpened } from '@/domain/archive/archive.mapper';
import { record, toRecord } from '@/domain/archive/verification.mapper';
import { base64Url, sized } from '@/domain/recovery/recovery.mapper';
import type { InboxRow, ReviewOpened } from './review.types';

const uuid = z.string().uuid();

const inboxRow = z.object({
  verification_id: uuid,
  status: z.enum(['awaiting', 'in_review', 'approved', 'not_approved', 'declined', 'withdrawn']),
  requested_at: z.string(),
  requested_by: z.string(),
  started_at: z.string(),
  ended_at: z.string().nullable(),
  messages: z.number().int().min(0),
  openable: z.boolean(),
  requested_by_name: z.string().nullable().optional(),
});

const review = z.object({
  review: z.object({
    record,
    draft: z.object({
      overall: base64Url.nullable(),
      notes: z.array(z.object({ entry_id: uuid, key_id: uuid, ciphertext: base64Url })),
    }),
    requester: z
      .object({
        sub: z.string(),
        key_version: z.number().int().min(1),
        fingerprint: sized(32),
        enc_pub: sized(65),
        sig_pub: sized(65),
      })
      .nullable(),
    requester_name: z.string().nullable().optional(),
  }),
});

export function toInbox(body: unknown): InboxRow[] {
  return z
    .object({ reviews: z.array(inboxRow) })
    .parse(body)
    .reviews.map((row) => ({
      verificationId: row.verification_id,
      status: row.status,
      requestedAt: row.requested_at,
      requestedBy: row.requested_by,
      startedAt: row.started_at,
      endedAt: row.ended_at,
      messages: row.messages,
      openable: row.openable,
      requestedByName: row.requested_by_name ?? null,
    }));
}

export function toReviewOpened(body: unknown): ReviewOpened {
  const { review: r } = review.parse(body);
  return {
    opened: toOpened(body),
    record: toRecord(r.record),
    draft: {
      overall: r.draft.overall,
      notes: r.draft.notes.map((n) => ({
        entryId: n.entry_id,
        keyId: n.key_id,
        ciphertext: n.ciphertext,
      })),
    },
    requester: r.requester
      ? {
          sub: r.requester.sub,
          keyVersion: r.requester.key_version,
          fingerprint: r.requester.fingerprint,
          encPub: r.requester.enc_pub,
          sigPub: r.requester.sig_pub,
        }
      : null,
    requesterName: r.requester_name ?? null,
  };
}

export function toStarted(body: unknown) {
  return toRecord(record.parse(body));
}
