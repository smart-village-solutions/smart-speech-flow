import type { KeyVault, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import type { Bytes } from '@/core/crypto/bytes';
import {
  CeremonyCheckError,
  type CeremonyCrypto,
  type CertifiedTrust,
} from '@/core/crypto/ceremony-crypto.port';
import {
  type ApprovalFacts,
  type OnProgress,
  RecoveryCheckError,
  type RecoveryCrypto,
  type RecoveryIntegrityStage,
  type RequestKind,
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
  keyVault: KeyVault;
  archive: ArchiveRepository;
  ceremonyCrypto: CeremonyCrypto;
  recoveryCrypto: RecoveryCrypto;
  recoveryRequests: RecoveryRequestsRepository;
}

export interface Identity {
  tenantId: string;
  userSub: string;
}

/** Long computations may outlive the key hold that authorized them. */
function guardKey(vault: KeyVault, keys: Readonly<UnlockedKeys>): () => void {
  const generation = vault.generation();
  return () => {
    if (vault.generation() !== generation || vault.current() !== keys) {
      throw new Error('Recovery key is no longer unlocked');
    }
  };
}

/** The archive's trust route, certified in this browser for every use (spec §10.6, §9.5). */
async function certifiedTrust(
  deps: Readonly<RecoveryDeps>,
  tenantId: string
): Promise<CertifiedTrust> {
  const trust = await deps.archive.trust(tenantId);
  return deps.ceremonyCrypto.certifyChain(trust);
}

export interface FileInput {
  kind: RequestKind;
  reason: string;
  candidates: readonly RecoveryCandidate[];
}

/** Signs the scope the chosen conversations make up, then files it. */
export async function fileOnce(
  deps: Readonly<RecoveryDeps>,
  identity: Readonly<Identity>,
  keys: Readonly<UnlockedKeys>,
  input: Readonly<FileInput>
): Promise<void> {
  const checkKey = guardKey(deps.keyVault, keys);
  const trust = await certifiedTrust(deps, identity.tenantId);
  const requestId = crypto.randomUUID();
  const scope = input.candidates.flatMap((c) =>
    c.keyIds.map((keyId) => ({ conversationId: c.conversationId, keyId }))
  );
  const signature = await deps.recoveryCrypto.signRequest(
    {
      tenantId: identity.tenantId,
      requestId,
      kind: input.kind,
      recoveryKeyId: trust.recoveryKeyId,
      requesterSub: identity.userSub,
      reason: input.reason,
      scope,
    },
    keys.sigPrivate
  );
  checkKey();
  await deps.recoveryRequests.file({
    requestId,
    kind: input.kind,
    reason: input.reason,
    conversationIds: input.candidates.map((c) => c.conversationId),
    signature,
  });
}

export type CombineOutcome =
  | { kind: 'done'; unrecoverable: number }
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
  requestId: string,
  onProgress?: OnProgress
): Promise<CombineOutcome> {
  const checkKey = guardKey(deps.keyVault, keys);
  let trust: CertifiedTrust;
  try {
    trust = await certifiedTrust(deps, identity.tenantId);
  } catch (error) {
    if (!(error instanceof CeremonyCheckError)) throw error;
    await report(deps, requestId, ['trust']);
    return { kind: 'damaged', stages: ['trust'] };
  }
  const served = await deps.recoveryRequests.partials(requestId);
  // Approvals of other holders cannot combine with these; nobody is to blame (§9.7).
  if (served.holdersCeremonyId !== trust.holdersCeremonyId) throw new RecoveryCheckError('custodians_changed');
  const result = await deps.recoveryCrypto.combine(
    { tenantId: identity.tenantId, requestId, requesterSub: identity.userSub, ...served },
    trust,
    keys,
    onProgress
  );
  checkKey();
  await Promise.all(
    result.rejections.map((r) => deps.recoveryRequests.reject(requestId, r).catch(() => undefined))
  );
  await report(deps, requestId, result.integrity);
  if (result.wraps === null)
    return { kind: 'waiting', rejected: result.rejections.map((r) => r.holderIndex) };
  // One call: the gateway records the unusable keys with the wraps, or nothing at all (§9.6).
  checkKey();
  await deps.recoveryRequests.storeWraps(requestId, result.wraps, result.unrecoverable);
  return { kind: 'done', unrecoverable: result.unrecoverable.length };
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
    kind: detail.kind,
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
  confirmed: Bytes,
  onProgress?: OnProgress
): Promise<void> {
  const checkKey = guardKey(deps.keyVault, keys);
  const trust = await certifiedTrust(deps, identity.tenantId);
  const facts = approvalFacts(detail, identity.tenantId, confirmed);
  const result = await deps.recoveryCrypto.approve(
    facts,
    trust,
    keys,
    identity.userSub,
    onProgress
  );
  checkKey();
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
