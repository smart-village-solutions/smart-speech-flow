import type { ArchiveCrypto, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { equalBytes } from '@/core/crypto/bytes';
import { fingerprint } from '@/core/crypto/transcript';
import { noteAddress } from '@/core/crypto/verification';
import type { OpenedConversation, VerificationRecord } from '@/domain/archive/archive.types';
import { type Finding, parseFindings, parseOverall } from '@/domain/review/findings';
import type { ReviewRepository } from '@/domain/review/review.repository';
import type { RequesterKey, ReviewOpened } from '@/domain/review/review.types';
import type { IntegrityStage } from '@/domain/archive/archive.repository';
import { type OpenDeps, type Opened, finishOpening } from '@/features/archive/openConversation';
import { verifyConversation } from '@/features/archive/verifyConversation';

type Ready = Extract<Opened, { status: 'ready' }>;

export interface DraftState {
  findings: Map<string, Finding[]>;
  overall: string;
}

export type ReviewState =
  | { status: 'checking' }
  | { status: 'unavailable' }
  | { status: 'broken'; stage: string }
  | { status: 'ready'; review: ReviewOpened; ready: Ready; draft: DraftState };

export interface ReviewDeps extends OpenDeps {
  reviews: ReviewRepository;
}

/** The overall note sits under the reviewed head's entry and key (A.3a). */
export function headEntry(opened: OpenedConversation, record: VerificationRecord) {
  const head = record.reviewedHead;
  return head === null ? undefined : opened.entries.find((entry) => equalBytes(entry.hash, head));
}

// Consistent with the fingerprint the server serves, not confirmed out of band (spec D11).
async function trustedRequester(
  tenantId: string,
  record: VerificationRecord,
  requester: RequesterKey | null
) {
  if (requester === null || requester.sub !== record.requestedBy) return null;
  const owner = await fingerprint(tenantId, requester.sub, requester.encPub, requester.sigPub);
  return equalBytes(owner, requester.fingerprint) ? requester : null;
}

/** Drafts are the reviewer's own notes; one that does not open is simply not shown. */
async function openDraft(
  crypto: ArchiveCrypto,
  tenantId: string,
  review: ReviewOpened,
  keys: ReadonlyMap<string, CryptoKey>
) {
  const { record, opened, draft } = review;
  const scope = {
    tenantId,
    conversationId: opened.conversation.conversationId,
    verificationId: record.verificationId,
  };
  const findings = new Map<string, Finding[]>();
  for (const note of draft.notes) {
    const key = keys.get(note.keyId);
    if (key === undefined) continue;
    try {
      const at = noteAddress(scope, 'note', note.entryId, note.keyId);
      findings.set(
        note.entryId,
        parseFindings(
          await crypto.openNote(key, at, note.ciphertext),
          record.verificationId,
          note.entryId
        )
      );
    } catch {
      // unreadable: the reviewer writes it again
    }
  }
  let overall = '';
  const head = headEntry(opened, record);
  const key = head ? keys.get(head.keyId) : undefined;
  if (draft.overall !== null && head && key) {
    try {
      const at = noteAddress(scope, 'overall', head.entryId, head.keyId);
      overall = parseOverall(await crypto.openNote(key, at, draft.overall), record.verificationId);
    } catch {
      overall = '';
    }
  }
  return { findings, overall };
}

function refused(
  deps: Readonly<ReviewDeps>,
  conversationId: string,
  stage: IntegrityStage
): ReviewState {
  deps.archive.reportIntegrity(conversationId, stage).catch(() => undefined);
  return { status: 'broken', stage };
}

/** §10.6's checks, with the record's assigner accepted as the signer of the reviewer's wraps. */
export async function openReview(
  deps: Readonly<ReviewDeps>,
  verificationId: string,
  unlocked: UnlockedKeys
): Promise<ReviewState> {
  const { tenantId, userSub } = deps.identity;
  const [review, trust] = await Promise.all([
    deps.reviews.open(verificationId),
    deps.archive.trust(tenantId),
  ]);
  const conversationId = review.opened.conversation.conversationId;
  if (review.record.verificationId !== verificationId || review.record.reviewerSub !== userSub) {
    return refused(deps, conversationId, 'chain');
  }
  const requester = await trustedRequester(tenantId, review.record, review.requester);
  if (requester === null) return refused(deps, conversationId, 'wrap');
  const verified = await verifyConversation({
    ...deps,
    ...deps.identity,
    opened: review.opened,
    trust,
    unlocked,
    wrapSigners: new Map([[requester.sub, requester.sigPub]]),
  });
  if (!verified.ok) return refused(deps, conversationId, verified.stage);
  const ready = await finishOpening(deps, review.opened, verified);
  if (ready.status !== 'ready') return { status: 'unavailable' };
  return {
    status: 'ready',
    review,
    ready,
    draft: await openDraft(deps.archiveCrypto, tenantId, review, ready.keys),
  };
}
