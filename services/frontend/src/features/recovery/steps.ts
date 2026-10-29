import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import type { Bytes } from '@/core/crypto/bytes';
import {
  CeremonyCheckError,
  type CeremonyCrypto,
  type CertifiedTrust,
} from '@/core/crypto/ceremony-crypto.port';
import {
  type ApprovalFacts,
  RecoveryCheckError,
  type RecoveryCrypto,
  type RecoveryIntegrityStage,
} from '@/core/crypto/recovery-crypto.port';
import type { ArchiveRepository } from '@/domain/archive/archive.repository';
import {
  RecoveryRefusedError,
  type RecoveryRequestsRepository,
} from '@/domain/recovery/requests.repository';
import type {
  ApprovalDetail,
  RecoveryCandidate,
  RequestProgress,
} from '@/domain/recovery/requests.types';

export interface RecoveryDeps {
  archive: ArchiveRepository;
  ceremonyCrypto: CeremonyCrypto;
  recoveryCrypto: RecoveryCrypto;
  recoveryRequests: RecoveryRequestsRepository;
}

export interface Identity {
  tenantId: string;
  userSub: string;
}

/** The archive's trust route, certified in this browser for every use (spec §10.6, §9.5). */
async function certifiedTrust(
  deps: Readonly<RecoveryDeps>,
  tenantId: string
): Promise<CertifiedTrust> {
  const trust = await deps.archive.trust(tenantId);
  return deps.ceremonyCrypto.certifyTrust(trust.facts, trust.transcriptHash, trust.signatures);
}

/** Signs the scope the ticked conversations make up, then files it. */
export async function fileOnce(
  deps: Readonly<RecoveryDeps>,
  identity: Readonly<Identity>,
  keys: Readonly<UnlockedKeys>,
  input: Readonly<{ reason: string; candidates: readonly RecoveryCandidate[] }>
): Promise<void> {
  const trust = await certifiedTrust(deps, identity.tenantId);
  const requestId = crypto.randomUUID();
  const scope = input.candidates.flatMap((c) =>
    c.keyIds.map((keyId) => ({ conversationId: c.conversationId, keyId }))
  );
  const signature = await deps.recoveryCrypto.signRequest(
    {
      tenantId: identity.tenantId,
      requestId,
      recoveryKeyId: trust.recoveryKeyId,
      requesterSub: identity.userSub,
      reason: input.reason,
      scope,
    },
    keys.sigPrivate
  );
  await deps.recoveryRequests.file({
    requestId,
    reason: input.reason,
    conversationIds: input.candidates.map((c) => c.conversationId),
    signature,
  });
}

export type CombineOutcome =
  | { kind: 'done' }
  | { kind: 'waiting'; rejected: readonly number[] }
  | { kind: 'damaged'; stages: readonly (RecoveryIntegrityStage | 'trust')[] }
  | { kind: 'failed'; code: string };

async function report(
  deps: Readonly<RecoveryDeps>,
  requestId: string,
  stages: readonly (RecoveryIntegrityStage | 'trust')[]
): Promise<void> {
  // A report that does not arrive must not hide the outcome from the requester.
  await Promise.all(
    stages.map((stage) =>
      deps.recoveryRequests.reportIntegrity(requestId, stage).catch(() => undefined)
    )
  );
}

/** Partials in, own wraps out; every fault reported, named custodians only for theirs. */
export async function combineOnce(
  deps: Readonly<RecoveryDeps>,
  identity: Readonly<Identity>,
  keys: Readonly<UnlockedKeys>,
  requestId: string
): Promise<CombineOutcome> {
  let trust: CertifiedTrust;
  try {
    trust = await certifiedTrust(deps, identity.tenantId);
  } catch (error) {
    if (!(error instanceof CeremonyCheckError)) throw error;
    await report(deps, requestId, ['trust']);
    return { kind: 'damaged', stages: ['trust'] };
  }
  const served = await deps.recoveryRequests.partials(requestId);
  const result = await deps.recoveryCrypto.combine(
    { tenantId: identity.tenantId, requestId, requesterSub: identity.userSub, ...served },
    trust,
    keys
  );
  await Promise.all(
    result.rejections.map((r) => deps.recoveryRequests.reject(requestId, r).catch(() => undefined))
  );
  await report(deps, requestId, result.integrity);
  if (result.integrity.some((stage) => stage === 'wrap_signature' || stage === 'wrap_damaged')) {
    return { kind: 'damaged', stages: result.integrity };
  }
  if (result.wraps === null)
    return { kind: 'waiting', rejected: result.rejections.map((r) => r.holderIndex) };
  await deps.recoveryRequests.storeWraps(requestId, result.wraps);
  return { kind: 'done' };
}

function approvalFacts(
  detail: Readonly<ApprovalDetail>,
  tenantId: string,
  confirmed: Bytes
): ApprovalFacts {
  return {
    confirmedFingerprint: confirmed,
    tenantId,
    requestId: detail.requestId,
    recoveryKeyId: detail.recoveryKeyId,
    requesterSub: detail.requesterSub,
    requesterKeys: { encPub: detail.requesterEncPub, sigPub: detail.requesterSigPub },
    reason: detail.reason,
    requestSignature: detail.requestSignature,
    signedScope: detail.signedScope,
    keys: detail.keys.map((k) => ({
      conversationId: k.conversationId,
      keyId: k.keyId,
      ephemeral: k.ephemeral,
      signerKeyId: k.signerKeyId,
      signature: k.signature,
    })),
    holderIndex: detail.holderIndex,
    attempt: detail.attempt,
    encryptedShare: detail.encryptedShare,
  };
}

/** Every check of spec §9.5 in this browser, then the signed partials go to the gateway. */
export async function approveOnce(
  deps: Readonly<RecoveryDeps>,
  identity: Readonly<Identity>,
  keys: Readonly<UnlockedKeys>,
  detail: Readonly<ApprovalDetail>,
  confirmed: Bytes
): Promise<void> {
  const trust = await certifiedTrust(deps, identity.tenantId);
  const facts = approvalFacts(detail, identity.tenantId, confirmed);
  const result = await deps.recoveryCrypto.approve(facts, trust, keys, identity.userSub);
  await deps.recoveryRequests.approve(detail.requestId, result.partials, result.signature);
}

/** What the screen says about a failure: a check of ours, a refusal of the gateway's, or neither. */
export function faultOf(error: unknown): string {
  if (error instanceof RecoveryCheckError) return error.fault;
  if (error instanceof CeremonyCheckError) return 'trust';
  if (error instanceof RecoveryRefusedError) return `refused.${error.code}`;
  return 'unavailable';
}

/** Approvals that count: approved and not since rejected, one per custodian. */
export function validApprovals(progress: Readonly<RequestProgress>): number {
  const holders = progress.decisions
    .filter((d) => d.decision === 'approved' && !d.rejected)
    .map((d) => d.holderIndex);
  return new Set(holders).size;
}
