import type { UnlockedKeys } from './archive-crypto.port';
import { type Bytes, bytesToBigInt, concat, equalBytes, scalarToBytes, utf8 } from './bytes';
import type { CertifiedTrust } from './ceremony-crypto.port';
import { publicPoint, randomScalar } from './curve';
import {
  contexts,
  openWithPrivateKey,
  openWithSharedX,
  parseSealed,
  seal,
  sealedToJson,
} from './ecies';
import { combinePartials, dleqProve, verifyDleq } from './proofs';
import {
  type ApprovalFacts,
  type CombineFacts,
  type NewRecoveredWrap,
  RecoveryCheckError,
  type RecoveryCrypto,
  type RecoveryFault,
  type RecoveryIntegrityStage,
  type RecoveryWrapRef,
  type Rejection,
  type RejectionFault,
  type ServedApproval,
  type ServedRecoveryWrap,
} from './recovery-crypto.port';
import {
  approvalFields,
  requestFields,
  sha256,
  signFields,
  verifyFields,
  wrapFields,
} from './signatures';
import { TAGS } from './tags';
import { fingerprint } from './transcript';

/** P_i ‖ c ‖ s (spec A.4, A.7). */
const PARTIAL_BYTES = 65 + 32 + 32;

function fail(fault: RecoveryFault): never {
  throw new RecoveryCheckError(fault);
}

/** A recovery wrap signed by a gateway key the transcript lists, for this recovery key (A.6). */
function recoveryWrapSigned(
  trust: Readonly<CertifiedTrust>,
  tenantId: string,
  wrap: Readonly<RecoveryWrapRef>
): Promise<boolean> {
  const signer = trust.gatewayKeys.get(wrap.signerKeyId);
  if (signer === undefined) return Promise.resolve(false);
  const signed = wrapFields({
    tenantId,
    conversationId: wrap.conversationId,
    keyId: wrap.keyId,
    ephemeral: wrap.ephemeral,
    recipientKind: 'recovery',
    recipientRef: trust.recoveryKeyId,
    recipientFingerprint: trust.transcriptHash,
  });
  return verifyFields(signer, wrap.signature, TAGS.wrapSig, signed);
}

/** The served wrap as the approver saw it: its R, or null when it is not a ck-wrap at all. */
function servedRef(wrap: Readonly<ServedRecoveryWrap>): RecoveryWrapRef | null {
  try {
    return { ...wrap, ephemeral: parseSealed(wrap.blob, TAGS.ckWrap).ephemeral };
  } catch {
    return null;
  }
}

/** The caller must be the custodian the transcript lists at this index, with these very keys. */
function checkListed(
  trust: Readonly<CertifiedTrust>,
  facts: Readonly<ApprovalFacts>,
  keys: Readonly<UnlockedKeys>,
  callerSub: string
): void {
  const listed = trust.participants.find((p) => p.holderIndex === facts.holderIndex);
  const ours =
    listed?.kind === 'custodian' &&
    listed.holderRef === callerSub &&
    equalBytes(listed.fingerprint, keys.fingerprint);
  if (!ours || facts.recoveryKeyId !== trust.recoveryKeyId) fail('not_listed');
}

async function checkRequest(facts: Readonly<ApprovalFacts>): Promise<void> {
  const signed = requestFields({
    tenantId: facts.tenantId,
    requestId: facts.requestId,
    kind: 'access',
    recoveryKeyId: facts.recoveryKeyId,
    requesterSub: facts.requesterSub,
    reasonHash: await sha256(utf8(facts.reason)),
    scope: facts.signedScope,
  });
  if (
    !(await verifyFields(
      facts.requesterKeys.sigPub,
      facts.requestSignature,
      TAGS.requestSig,
      signed
    ))
  ) {
    fail('request_signature');
  }
  const inScope = (key: Readonly<RecoveryWrapRef>) =>
    facts.signedScope.some(
      (pair) => pair.keyId === key.keyId && pair.conversationId === key.conversationId
    );
  if (!facts.keys.every(inScope)) fail('out_of_scope');
}

async function openShare(
  facts: Readonly<ApprovalFacts>,
  trust: Readonly<CertifiedTrust>,
  keys: Readonly<UnlockedKeys>,
  callerSub: string
): Promise<bigint> {
  const context = contexts.share(facts.tenantId, facts.recoveryKeyId, facts.holderIndex, callerSub);
  const sealed = parseSealed(facts.encryptedShare, TAGS.share);
  const share = bytesToBigInt(
    await openWithPrivateKey(sealed, keys.encPrivate, keys.encPub, context)
  );
  const expected = trust.holderShares.get(facts.holderIndex);
  if (expected === undefined || !equalBytes(publicPoint(share), expected)) fail('share_mismatch');
  return share;
}

async function sealPartial(
  facts: Readonly<ApprovalFacts>,
  requesterFingerprint: Bytes,
  share: bigint,
  key: Readonly<RecoveryWrapRef>
): Promise<string> {
  const scope = [facts.tenantId, facts.requestId, key.keyId, facts.holderIndex] as const;
  const { partial, proof } = await dleqProve(scope, share, key.ephemeral, randomScalar());
  const plaintext = concat(partial, scalarToBytes(proof.c), scalarToBytes(proof.s));
  const context = contexts.partial(
    facts.tenantId,
    facts.requestId,
    key.keyId,
    facts.holderIndex,
    facts.requesterSub,
    requesterFingerprint
  );
  return sealedToJson(await seal(TAGS.partial, facts.requesterKeys.encPub, plaintext, context));
}

interface ValidPartials {
  holderIndex: number;
  /** Key ID -> P_i, proof checked. */
  points: Map<string, Bytes>;
}

type Checked =
  | { valid: ValidPartials }
  | { rejection: Rejection }
  | { integrity: RecoveryIntegrityStage }
  | null;

/** The served data matches what the custodian signed; otherwise the fault is not theirs. */
async function signedAsServed(
  approval: Readonly<ServedApproval>,
  facts: Readonly<CombineFacts>,
  sigPub: Bytes
): Promise<RecoveryIntegrityStage | null> {
  const signed = approvalFields({
    tenantId: facts.tenantId,
    requestId: facts.requestId,
    holderIndex: approval.holderIndex,
    attempt: approval.attempt,
    partials: approval.signedPartials,
  });
  if (!(await verifyFields(sigPub, approval.signature, TAGS.approvalSig, signed)))
    return 'approval_signature';
  for (const wrap of facts.wraps) {
    const blob = approval.partials.get(wrap.keyId);
    const listed = approval.signedPartials.find((item) => item.keyId === wrap.keyId);
    if (
      blob === undefined ||
      listed === undefined ||
      !equalBytes(await sha256(utf8(blob)), listed.hash)
    ) {
      return 'partial_hash';
    }
  }
  return null;
}

async function openPartial(
  facts: Readonly<CombineFacts>,
  keys: Readonly<UnlockedKeys>,
  approval: Readonly<ServedApproval>,
  keyId: string
): Promise<Bytes | null> {
  try {
    const context = contexts.partial(
      facts.tenantId,
      facts.requestId,
      keyId,
      approval.holderIndex,
      facts.requesterSub,
      keys.fingerprint
    );
    const sealed = parseSealed(approval.partials.get(keyId) ?? '', TAGS.partial);
    const plaintext = await openWithPrivateKey(sealed, keys.encPrivate, keys.encPub, context);
    return plaintext.length === PARTIAL_BYTES ? plaintext : null;
  } catch {
    return null;
  }
}

async function partialHolds(
  facts: Readonly<CombineFacts>,
  approval: Readonly<ServedApproval>,
  wrap: Readonly<RecoveryWrapRef>,
  holderShare: Bytes,
  plaintext: Bytes
): Promise<boolean> {
  const statement = { holderShare, ephemeral: wrap.ephemeral, partial: plaintext.slice(0, 65) };
  const proof = {
    c: bytesToBigInt(plaintext.slice(65, 97)),
    s: bytesToBigInt(plaintext.slice(97)),
  };
  const scope = [facts.tenantId, facts.requestId, wrap.keyId, approval.holderIndex] as const;
  return verifyDleq(scope, statement, proof).catch(() => false);
}

/** The custodian at this index, never the requester; null for anyone else (spec §9.5). */
function approverKey(
  trust: Readonly<CertifiedTrust>,
  holderIndex: number,
  requesterSub: string
): Bytes | null {
  const holder = trust.participants.find((p) => p.holderIndex === holderIndex);
  if (holder?.kind !== 'custodian' || holder.holderRef === requesterSub) return null;
  return holder.sigPub;
}

/** Each partial opened and its proof checked against the certified X_i. */
async function checkPartials(
  facts: Readonly<CombineFacts>,
  wraps: readonly RecoveryWrapRef[],
  trust: Readonly<CertifiedTrust>,
  keys: Readonly<UnlockedKeys>,
  approval: Readonly<ServedApproval>
): Promise<Checked> {
  const holderShare = trust.holderShares.get(approval.holderIndex) ?? new Uint8Array(0);
  const rejected = (fault: RejectionFault): Checked => ({
    rejection: { holderIndex: approval.holderIndex, attempt: approval.attempt, fault },
  });
  const points = new Map<string, Bytes>();
  for (const wrap of wraps) {
    const plaintext = await openPartial(facts, keys, approval, wrap.keyId);
    if (plaintext === null) return rejected('partial_unreadable');
    if (!(await partialHolds(facts, approval, wrap, holderShare, plaintext)))
      return rejected('proof_invalid');
    points.set(wrap.keyId, plaintext.slice(0, 65));
  }
  return { valid: { holderIndex: approval.holderIndex, points } };
}

/** One approval: ignored unless a custodian's, blamed on nobody unless signed as served. */
async function checkApproval(
  facts: Readonly<CombineFacts>,
  wraps: readonly RecoveryWrapRef[],
  trust: Readonly<CertifiedTrust>,
  keys: Readonly<UnlockedKeys>,
  approval: Readonly<ServedApproval>
): Promise<Checked> {
  const sigPub = approverKey(trust, approval.holderIndex, facts.requesterSub);
  if (sigPub === null) return null;
  const integrity = await signedAsServed(approval, facts, sigPub);
  if (integrity !== null) return { integrity };
  return checkPartials(facts, wraps, trust, keys, approval);
}

async function rewrap(
  facts: Readonly<CombineFacts>,
  trust: Readonly<CertifiedTrust>,
  keys: Readonly<UnlockedKeys>,
  wrap: Readonly<ServedRecoveryWrap>,
  chosen: readonly ValidPartials[]
): Promise<NewRecoveredWrap | null> {
  const sealed = parseSealed(wrap.blob, TAGS.ckWrap);
  const z = combinePartials(
    chosen.map((v) => ({
      index: v.holderIndex,
      partial: v.points.get(wrap.keyId) ?? new Uint8Array(0),
    }))
  );
  const recovery = contexts.ckWrap(
    facts.tenantId,
    wrap.conversationId,
    wrap.keyId,
    'recovery',
    trust.recoveryKeyId
  );
  let ck: Bytes;
  try {
    ck = await openWithSharedX(sealed, z, trust.recoveryPublicKey, recovery);
  } catch {
    return null; // valid proofs, but the unsigned ciphertext is damaged
  }
  try {
    const own = contexts.ckWrap(
      facts.tenantId,
      wrap.conversationId,
      wrap.keyId,
      'user',
      facts.requesterSub
    );
    const mine = await seal(TAGS.ckWrap, keys.encPub, ck, own);
    const signed = wrapFields({
      tenantId: facts.tenantId,
      conversationId: wrap.conversationId,
      keyId: wrap.keyId,
      ephemeral: mine.ephemeral,
      recipientKind: 'user',
      recipientRef: facts.requesterSub,
      recipientFingerprint: keys.fingerprint,
    });
    const signature = await signFields(keys.sigPrivate, TAGS.wrapSig, signed);
    return {
      conversationId: wrap.conversationId,
      keyId: wrap.keyId,
      blob: sealedToJson(mine),
      signature,
    };
  } finally {
    ck.fill(0);
  }
}

/** One partial set per custodian, lowest indices first, so a retry combines the same set. */
function uniqueHolders(valid: readonly ValidPartials[]): ValidPartials[] {
  const byHolder = new Map<number, ValidPartials>();
  for (const item of valid)
    if (!byHolder.has(item.holderIndex)) byHolder.set(item.holderIndex, item);
  return [...byHolder.values()].sort((left, right) => left.holderIndex - right.holderIndex);
}

async function servedWrapsSigned(
  facts: Readonly<CombineFacts>,
  trust: Readonly<CertifiedTrust>
): Promise<RecoveryWrapRef[] | null> {
  const refs = facts.wraps.map(servedRef);
  if (refs.some((ref) => ref === null)) return null;
  const valid = refs.filter((ref): ref is RecoveryWrapRef => ref !== null);
  const signed = await Promise.all(
    valid.map((ref) => recoveryWrapSigned(trust, facts.tenantId, ref))
  );
  return signed.includes(false) ? null : valid;
}

export function createWebRecoveryCrypto(): RecoveryCrypto {
  return {
    fingerprintOf: (tenantId, sub, keys) => fingerprint(tenantId, sub, keys.encPub, keys.sigPub),

    async signRequest(request, signingKey) {
      const reasonHash = await sha256(utf8(request.reason));
      return signFields(
        signingKey,
        TAGS.requestSig,
        requestFields({ ...request, kind: 'access', reasonHash })
      );
    },

    async approve(facts, trust, keys, callerSub) {
      if (callerSub === facts.requesterSub) fail('self_approval');
      checkListed(trust, facts, keys, callerSub);
      await checkRequest(facts);
      const signedWraps = await Promise.all(
        facts.keys.map((key) => recoveryWrapSigned(trust, facts.tenantId, key))
      );
      if (signedWraps.includes(false)) fail('wrap_signature');
      // Computed here from the served keys, never taken from the server: what the phone check confirms.
      const requesterFingerprint = await fingerprint(
        facts.tenantId,
        facts.requesterSub,
        facts.requesterKeys.encPub,
        facts.requesterKeys.sigPub
      );
      // Keys served after the tick are not the keys the phone call confirmed.
      if (!equalBytes(requesterFingerprint, facts.confirmedFingerprint))
        fail('fingerprint_changed');
      const share = await openShare(facts, trust, keys, callerSub);
      const partials = new Map<string, string>();
      for (const key of facts.keys)
        partials.set(key.keyId, await sealPartial(facts, requesterFingerprint, share, key));
      const hashes = await Promise.all(
        [...partials].map(async ([keyId, blob]) => ({ keyId, hash: await sha256(utf8(blob)) }))
      );
      const signed = approvalFields({
        tenantId: facts.tenantId,
        requestId: facts.requestId,
        holderIndex: facts.holderIndex,
        attempt: facts.attempt,
        partials: hashes,
      });
      return { partials, signature: await signFields(keys.sigPrivate, TAGS.approvalSig, signed) };
    },

    async combine(facts, trust, keys) {
      const wraps = await servedWrapsSigned(facts, trust);
      if (wraps === null) return { wraps: null, rejections: [], integrity: ['wrap_signature'] };
      const checked = await Promise.all(
        facts.approvals.map((a) => checkApproval(facts, wraps, trust, keys, a))
      );
      const valid = checked.flatMap((c) => (c !== null && 'valid' in c ? [c.valid] : []));
      const rejections = checked.flatMap((c) =>
        c !== null && 'rejection' in c ? [c.rejection] : []
      );
      const integrity = checked.flatMap((c) =>
        c !== null && 'integrity' in c ? [c.integrity] : []
      );
      const chosen = uniqueHolders(valid).slice(0, trust.k);
      if (chosen.length < trust.k) return { wraps: null, rejections, integrity };
      const rewrapped = await Promise.all(
        facts.wraps.map((w) => rewrap(facts, trust, keys, w, chosen))
      );
      const ready = rewrapped.filter((w): w is NewRecoveredWrap => w !== null);
      if (ready.length < rewrapped.length)
        return { wraps: null, rejections, integrity: [...integrity, 'wrap_damaged'] };
      return { wraps: ready, rejections, integrity };
    },
  };
}
