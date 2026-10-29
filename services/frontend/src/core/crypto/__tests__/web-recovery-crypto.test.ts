import { describe, expect, it } from 'vitest';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import {
  concat,
  equalBytes,
  fromBuffer,
  randomBytes,
  scalarToBytes,
  utf8,
} from '@/core/crypto/bytes';
import type { CeremonyParticipant, CertifiedTrust } from '@/core/crypto/ceremony-crypto.port';
import { mod, publicPoint, randomScalar } from '@/core/crypto/curve';
import { contexts, openWithPrivateKey, parseSealed, seal, sealedToJson } from '@/core/crypto/ecies';
import { dleqProve, evaluatePolynomial } from '@/core/crypto/proofs';
import type {
  ApprovalFacts,
  ApprovalResult,
  CombineFacts,
  ServedApproval,
} from '@/core/crypto/recovery-crypto.port';
import {
  approvalFields,
  sha256,
  signFields,
  verifyFields,
  wrapFields,
} from '@/core/crypto/signatures';
import { TAGS } from '@/core/crypto/tags';
import { fingerprint } from '@/core/crypto/transcript';
import { createWebRecoveryCrypto } from '@/core/crypto/web-recovery-crypto';

const TENANT = 'tenant-kassel';
const C = '6f1c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f';
const K = '9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d';
const recovery = createWebRecoveryCrypto();

async function unlockedKeys(sub: string): Promise<UnlockedKeys> {
  const enc = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, false, [
    'deriveBits',
  ]);
  const sig = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, false, [
    'sign',
    'verify',
  ]);
  const encPub = fromBuffer(await crypto.subtle.exportKey('raw', enc.publicKey));
  const sigPub = fromBuffer(await crypto.subtle.exportKey('raw', sig.publicKey));
  return {
    encPub,
    sigPub,
    encPrivate: enc.privateKey,
    sigPrivate: sig.privateKey,
    fingerprint: await fingerprint(TENANT, sub, encPub, sigPub),
  };
}

/** A recovery key split k-of-n among `custodians`, a CK wrapped to X, and a signed request. */
async function world(k = 2, custodians = ['carol', 'dave', 'erin'], requester = 'sam') {
  const coefficients = Array.from({ length: k }, () => randomScalar());
  const shares = new Map(
    custodians.map((_, i) => [i + 1, evaluatePolynomial(coefficients, i + 1)])
  );
  const recoveryKeyId = crypto.randomUUID();
  const transcriptHash = randomBytes(32);
  const keys = new Map<string, UnlockedKeys>();
  for (const sub of [...custodians, requester]) keys.set(sub, await unlockedKeys(sub));
  const participants: CeremonyParticipant[] = custodians.map((sub, i) => {
    const own = keys.get(sub) as UnlockedKeys;
    return { holderIndex: i + 1, holderRef: sub, kind: 'custodian', displayName: null, ...own };
  });
  const gateway = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, false, [
    'sign',
    'verify',
  ]);
  const gatewayPub = fromBuffer(await crypto.subtle.exportKey('raw', gateway.publicKey));
  const trust: CertifiedTrust = {
    recoveryKeyId,
    k,
    transcriptHash,
    recoveryPublicKey: publicPoint(coefficients[0]),
    participants,
    holderShares: new Map([...shares].map(([index, share]) => [index, publicPoint(share)])),
    gatewayKeys: new Map([['gw-1', gatewayPub]]),
  };
  const ck = randomBytes(32);
  const wrap = await seal(
    TAGS.ckWrap,
    trust.recoveryPublicKey,
    ck,
    contexts.ckWrap(TENANT, C, K, 'recovery', recoveryKeyId)
  );
  const wrapSignature = await signFields(
    gateway.privateKey,
    TAGS.wrapSig,
    wrapFields({
      tenantId: TENANT,
      conversationId: C,
      keyId: K,
      ephemeral: wrap.ephemeral,
      recipientKind: 'recovery',
      recipientRef: recoveryKeyId,
      recipientFingerprint: transcriptHash,
    })
  );
  const requesterKeys = keys.get(requester) as UnlockedKeys;
  const requestId = crypto.randomUUID();
  const reason = 'Employee left; the authority needs the record.';
  const signedScope = [{ conversationId: C, keyId: K }];
  const requestSignature = await recovery.signRequest(
    {
      tenantId: TENANT,
      requestId,
      recoveryKeyId,
      requesterSub: requester,
      reason,
      scope: signedScope,
    },
    requesterKeys.sigPrivate
  );

  async function approvalFacts(
    sub: string,
    share = shares.get(custodians.indexOf(sub) + 1) ?? 0n
  ): Promise<ApprovalFacts> {
    const index = custodians.indexOf(sub) + 1;
    const own = keys.get(sub) as UnlockedKeys;
    const encryptedShare = sealedToJson(
      await seal(
        TAGS.share,
        own.encPub,
        scalarToBytes(share),
        contexts.share(TENANT, recoveryKeyId, index, sub)
      )
    );
    return {
      tenantId: TENANT,
      requestId,
      recoveryKeyId,
      requesterSub: requester,
      requesterKeys: { encPub: requesterKeys.encPub, sigPub: requesterKeys.sigPub },
      reason,
      requestSignature,
      signedScope,
      keys: [
        {
          conversationId: C,
          keyId: K,
          ephemeral: wrap.ephemeral,
          signerKeyId: 'gw-1',
          signature: wrapSignature,
        },
      ],
      holderIndex: index,
      attempt: 1,
      encryptedShare,
      confirmedFingerprint: requesterKeys.fingerprint,
    };
  }

  async function served(
    results: readonly { holderIndex: number; result: ApprovalResult }[]
  ): Promise<CombineFacts> {
    const approvals: ServedApproval[] = [];
    for (const { holderIndex, result } of results) {
      const signedPartials = await Promise.all(
        [...result.partials].map(async ([keyId, blob]) => ({
          keyId,
          hash: await sha256(utf8(blob)),
        }))
      );
      approvals.push({
        holderIndex,
        attempt: 1,
        signedPartials,
        signature: result.signature,
        partials: result.partials,
      });
    }
    return {
      tenantId: TENANT,
      requestId,
      requesterSub: requester,
      wraps: [
        {
          conversationId: C,
          keyId: K,
          blob: sealedToJson(wrap),
          signerKeyId: 'gw-1',
          signature: wrapSignature,
        },
      ],
      approvals,
    };
  }

  /** What a custodian's browser would send for `share`, honest or not, signed with their key. */
  async function craftedApproval(
    sub: string,
    index: number,
    share: bigint
  ): Promise<ApprovalResult> {
    const own = keys.get(sub) as UnlockedKeys;
    const { partial, proof } = await dleqProve(
      [TENANT, requestId, K, index],
      share,
      wrap.ephemeral,
      randomScalar()
    );
    const context = contexts.partial(
      TENANT,
      requestId,
      K,
      index,
      requester,
      requesterKeys.fingerprint
    );
    const blob = sealedToJson(
      await seal(
        TAGS.partial,
        requesterKeys.encPub,
        concat(partial, scalarToBytes(proof.c), scalarToBytes(proof.s)),
        context
      )
    );
    const signature = await signFields(
      own.sigPrivate,
      TAGS.approvalSig,
      approvalFields({
        tenantId: TENANT,
        requestId,
        holderIndex: index,
        attempt: 1,
        partials: [{ keyId: K, hash: await sha256(utf8(blob)) }],
      })
    );
    return { partials: new Map([[K, blob]]), signature };
  }

  const approveAs = async (sub: string) =>
    recovery.approve(await approvalFacts(sub), trust, keys.get(sub) as UnlockedKeys, sub);

  return {
    trust,
    keys,
    shares,
    ck,
    requester,
    requesterKeys,
    approvalFacts,
    served,
    craftedApproval,
    approveAs,
  };
}

describe('web recovery crypto', () => {
  it('k approvals reopen the conversation key, re-wrapped and signed for the requester', async () => {
    const w = await world();
    const facts = await w.served([
      { holderIndex: 1, result: await w.approveAs('carol') },
      { holderIndex: 2, result: await w.approveAs('dave') },
    ]);

    const result = await recovery.combine(facts, w.trust, w.requesterKeys);

    expect(result.rejections).toEqual([]);
    expect(result.integrity).toEqual([]);
    const [mine] = result.wraps ?? [];
    const sealed = parseSealed(mine.blob, TAGS.ckWrap);
    const opened = await openWithPrivateKey(
      sealed,
      w.requesterKeys.encPrivate,
      w.requesterKeys.encPub,
      contexts.ckWrap(TENANT, C, K, 'user', 'sam')
    );
    expect(equalBytes(opened, w.ck)).toBe(true);
    const signed = wrapFields({
      tenantId: TENANT,
      conversationId: C,
      keyId: K,
      ephemeral: sealed.ephemeral,
      recipientKind: 'user',
      recipientRef: 'sam',
      recipientFingerprint: w.requesterKeys.fingerprint,
    });
    expect(await verifyFields(w.requesterKeys.sigPub, mine.signature, TAGS.wrapSig, signed)).toBe(
      true
    );
  });

  it('k − 1 approvals open nothing', async () => {
    const w = await world();
    const facts = await w.served([{ holderIndex: 1, result: await w.approveAs('carol') }]);
    expect(await recovery.combine(facts, w.trust, w.requesterKeys)).toEqual({
      wraps: null,
      rejections: [],
      integrity: [],
    });
  });

  it('a custodian whose share does not match the transcript refuses to approve', async () => {
    const w = await world();
    const wrong = mod((w.shares.get(2) ?? 0n) + 1n);
    const facts = await w.approvalFacts('dave', wrong);
    await expect(
      recovery.approve(facts, w.trust, w.keys.get('dave') as UnlockedKeys, 'dave')
    ).rejects.toMatchObject({
      fault: 'share_mismatch',
    });
  });

  it('a forged partial is rejected and names its custodian; a third approval still combines', async () => {
    const w = await world();
    const forged = await w.craftedApproval('dave', 2, mod((w.shares.get(2) ?? 0n) + 1n));
    const facts = await w.served([
      { holderIndex: 1, result: await w.approveAs('carol') },
      { holderIndex: 2, result: forged },
      { holderIndex: 3, result: await w.approveAs('erin') },
    ]);

    const result = await recovery.combine(facts, w.trust, w.requesterKeys);

    expect(result.rejections).toEqual([{ holderIndex: 2, attempt: 1, fault: 'proof_invalid' }]);
    expect(result.wraps).toHaveLength(1);
  });

  it('a partial swapped after signing blames nobody', async () => {
    const w = await world();
    const carol = await w.approveAs('carol');
    const dave = await w.approveAs('dave');
    const facts = await w.served([
      { holderIndex: 1, result: carol },
      { holderIndex: 2, result: dave },
    ]);
    facts.approvals[0].partials = new Map(dave.partials);

    const result = await recovery.combine(facts, w.trust, w.requesterKeys);

    expect(result).toEqual({ wraps: null, rejections: [], integrity: ['partial_hash'] });
  });

  it("an approval whose signature is not its custodian's blames nobody and does not count", async () => {
    const w = await world();
    const carol = await w.approveAs('carol');
    const dave = await w.approveAs('dave');
    const facts = await w.served([
      { holderIndex: 1, result: { ...carol, signature: dave.signature } },
      { holderIndex: 2, result: dave },
    ]);

    const result = await recovery.combine(facts, w.trust, w.requesterKeys);

    expect(result).toEqual({ wraps: null, rejections: [], integrity: ['approval_signature'] });
  });

  it('a partial sealed to substituted keys cannot be opened by the real requester', async () => {
    const w = await world();
    const mallory = await unlockedKeys('sam');
    const requesterKeys = { encPub: mallory.encPub, sigPub: w.requesterKeys.sigPub };
    const shown = await recovery.fingerprintOf(TENANT, 'sam', requesterKeys);
    expect(equalBytes(shown, w.requesterKeys.fingerprint)).toBe(false);
    // The custodian confirmed what the screen showed: the substituted keys' fingerprint.
    const facts = {
      ...(await w.approvalFacts('carol')),
      requesterKeys,
      confirmedFingerprint: shown,
    };
    const substituted = await recovery.approve(
      facts,
      w.trust,
      w.keys.get('carol') as UnlockedKeys,
      'carol'
    );
    const served = await w.served([
      { holderIndex: 1, result: substituted },
      { holderIndex: 2, result: await w.approveAs('dave') },
    ]);

    const result = await recovery.combine(served, w.trust, w.requesterKeys);

    expect(result.wraps).toBeNull();
    expect(result.rejections).toEqual([
      { holderIndex: 1, attempt: 1, fault: 'partial_unreadable' },
    ]);
  });

  it("refuses to approve as the requester, or for someone else's transcript slot", async () => {
    const w = await world();
    const facts = await w.approvalFacts('carol');
    const carol = w.keys.get('carol') as UnlockedKeys;
    await expect(recovery.approve(facts, w.trust, carol, 'sam')).rejects.toMatchObject({
      fault: 'self_approval',
    });
    await expect(
      recovery.approve({ ...facts, holderIndex: 2 }, w.trust, carol, 'carol')
    ).rejects.toMatchObject({
      fault: 'not_listed',
    });
  });

  it('refuses a scope key the requester did not sign, a forged request and an uncertified wrap signer', async () => {
    const w = await world();
    const carol = w.keys.get('carol') as UnlockedKeys;
    const facts = await w.approvalFacts('carol');
    const extra = { ...facts.keys[0], conversationId: crypto.randomUUID() };
    await expect(
      recovery.approve({ ...facts, keys: [...facts.keys, extra] }, w.trust, carol, 'carol')
    ).rejects.toMatchObject({ fault: 'out_of_scope' });
    await expect(
      recovery.approve({ ...facts, reason: 'Another reason.' }, w.trust, carol, 'carol')
    ).rejects.toMatchObject({
      fault: 'request_signature',
    });
    const unknown = { ...facts, keys: [{ ...facts.keys[0], signerKeyId: 'gw-2' }] };
    await expect(recovery.approve(unknown, w.trust, carol, 'carol')).rejects.toMatchObject({
      fault: 'wrap_signature',
    });
  });

  it("ignores an approval from the requester's own holder index", async () => {
    const w = await world(2, ['carol', 'dave', 'sam']);
    const own = await w.craftedApproval('sam', 3, w.shares.get(3) ?? 0n);
    const facts = await w.served([
      { holderIndex: 1, result: await w.approveAs('carol') },
      { holderIndex: 3, result: own },
    ]);
    expect((await recovery.combine(facts, w.trust, w.requesterKeys)).wraps).toBeNull();
  });

  it('a served recovery wrap that no certified key signed stops everything', async () => {
    const w = await world();
    const facts = await w.served([
      { holderIndex: 1, result: await w.approveAs('carol') },
      { holderIndex: 2, result: await w.approveAs('dave') },
    ]);
    const tampered = { ...facts, wraps: [{ ...facts.wraps[0], signature: new Uint8Array(64) }] };
    expect(await recovery.combine(tampered, w.trust, w.requesterKeys)).toEqual({
      wraps: null,
      rejections: [],
      integrity: ['wrap_signature'],
    });
  });

  it('a damaged recovery ciphertext under valid proofs is reported, not opened', async () => {
    const w = await world();
    const facts = await w.served([
      { holderIndex: 1, result: await w.approveAs('carol') },
      { holderIndex: 2, result: await w.approveAs('dave') },
    ]);
    const body = JSON.parse(facts.wraps[0].blob) as Record<string, string>;
    const damaged = JSON.stringify({
      ...body,
      ct: body.ct.slice(0, -2) + (body.ct.endsWith('A') ? 'BA' : 'AA'),
    });
    const result = await recovery.combine(
      { ...facts, wraps: [{ ...facts.wraps[0], blob: damaged }] },
      w.trust,
      w.requesterKeys
    );
    expect(result).toEqual({ wraps: null, rejections: [], integrity: ['wrap_damaged'] });
  });

  it('refuses keys that changed after the fingerprint was confirmed', async () => {
    const w = await world();
    const mallory = await unlockedKeys('sam');
    const facts = {
      ...(await w.approvalFacts('carol')),
      requesterKeys: { encPub: mallory.encPub, sigPub: w.requesterKeys.sigPub },
    };
    await expect(
      recovery.approve(facts, w.trust, w.keys.get('carol') as UnlockedKeys, 'carol')
    ).rejects.toMatchObject({ fault: 'fingerprint_changed' });
  });

  it('refuses a transcript slot listing other keys under the caller, or another recovery key', async () => {
    const w = await world();
    const carol = w.keys.get('carol') as UnlockedKeys;
    const facts = await w.approvalFacts('carol');
    const impostor = { ...carol, fingerprint: (w.keys.get('dave') as UnlockedKeys).fingerprint };
    await expect(recovery.approve(facts, w.trust, impostor, 'carol')).rejects.toMatchObject({
      fault: 'not_listed',
    });
    await expect(
      recovery.approve({ ...facts, recoveryKeyId: crypto.randomUUID() }, w.trust, carol, 'carol')
    ).rejects.toMatchObject({ fault: 'not_listed' });
  });
});
