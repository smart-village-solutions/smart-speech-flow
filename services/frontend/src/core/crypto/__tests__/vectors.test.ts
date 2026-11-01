import { readFileSync } from 'node:fs';
import path from 'node:path';
import { p256 } from '@noble/curves/nist.js';
import { describe, expect, it } from 'vitest';
import { aesKey, objectAad, openEnvelope, sealEnvelope } from '@/core/crypto/aead';
import { type Bytes, bytesToBigInt, fromBase64Url, toBase64Url, toHex, utf8 } from '@/core/crypto/bytes';
import { mod, publicPoint } from '@/core/crypto/curve';
import { type Field, enc } from '@/core/crypto/encoding';
import { openWithSharedX, parseSealed, seal, sealedToJson } from '@/core/crypto/ecies';
import { openPrivateKeys, sealPrivateKeys } from '@/core/crypto/private-key-blob';
import {
  combinePartials,
  commitmentsOf,
  contribution,
  dleqProve,
  evaluatePolynomial,
  holderPublicShare,
  lagrangeAtZero,
  recoveryPublicKey,
  schnorrProve,
  shareProofProve,
  verifyDleq,
  verifySchnorr,
  verifyShareProof,
  verifySubshare,
} from '@/core/crypto/proofs';
import {
  approvalFields,
  dealingFields,
  participantsDigest,
  requestFields,
  reshareDealingFields,
  sha256,
  signedDigest,
  verifyFields,
  wrapFields,
} from '@/core/crypto/signatures';
import { type SealedType, TAGS } from '@/core/crypto/tags';
import { displayFingerprint, fingerprint, paperDeviceFingerprint, transcriptHash } from '@/core/crypto/transcript';

// The gateway generates and checks the same file (tests/test_recording_crypto_vectors.py).
const vectors = JSON.parse(
  readFileSync(
    path.join(import.meta.dirname, '../../../../../../tests/fixtures/recording/crypto_vectors_v1.json'),
    'utf8'
  )
);

type Typed = { s: string } | { b: string } | { i: number };

const b = (text: string): Bytes => fromBase64Url(text);
const n = (hex: string): bigint => BigInt(`0x${hex}`);
const same = (left: ArrayLike<number>, right: ArrayLike<number>) => expect(Array.from(left)).toEqual(Array.from(right));

function fields(typed: Typed[]): Field[] {
  return typed.map((item) => {
    if ('s' in item) return item.s;
    if ('b' in item) return b(item.b);
    return item.i;
  });
}

describe('shared crypto vectors', () => {
  it.each(vectors.encoding)('encodes $hex', (testCase: { fields: Typed[]; hex: string }) => {
    expect(toHex(enc(...fields(testCase.fields)))).toBe(testCase.hex);
  });

  it('computes and displays fingerprints', async () => {
    const f = vectors.fingerprint;
    const raw = await fingerprint(f.tenant_id, f.user_sub, b(f.enc_pub), b(f.sig_pub));
    expect(toBase64Url(raw)).toBe(f.fingerprint);
    expect(displayFingerprint(raw)).toBe(f.display);
    const paper = await paperDeviceFingerprint(f.tenant_id, b(f.paper_device.device_pub));
    expect(toBase64Url(paper)).toBe(f.paper_device.fingerprint);
  });

  it('seals and opens archive objects', async () => {
    const o = vectors.object;
    const aad = objectAad({
      tenantId: o.tenant_id,
      conversationId: o.conversation_id,
      entryId: o.entry_id,
      objectType: o.object_type,
      keyId: o.key_id,
    });
    const key = await aesKey(b(o.key));
    expect(toBase64Url(await sealEnvelope(key, b(o.plaintext), aad, b(o.nonce)))).toBe(o.envelope);
    same(await openEnvelope(key, b(o.envelope), aad), b(o.plaintext));
  });

  it.each(vectors.sealed)('seals and opens $type', async (v: Record<string, never>) => {
    const sealed = await seal(v.type as SealedType, b(v.recipient), b(v.plaintext), fields(v.context), {
      ephemeralScalar: n(v.ephemeral_scalar),
      nonce: b(v.nonce),
    });
    expect(sealedToJson(sealed)).toBe(v.payload);
    const parsed = parseSealed(v.payload, v.type as SealedType);
    same(publicPoint(n(v.recipient_scalar)), b(v.recipient));
    const z = p256.getSharedSecret(hexToBytes(v.recipient_scalar), parsed.ephemeral).slice(1);
    same(await openWithSharedX(parsed, Uint8Array.from(z), b(v.recipient), fields(v.context)), b(v.plaintext));
  });

  it.each(vectors.signatures)('reproduces and verifies the $tag signature', async (v: Record<string, never>) => {
    const signed = fields(v.fields);
    const digest = await signedDigest(v.tag, signed);
    expect(toBase64Url(digest)).toBe(v.digest);
    // RFC 6979 on both sides, so the gateway's signature is reproduced byte for byte.
    const deterministic = p256.sign(digest, hexToBytes(v.signer_scalar), { prehash: true, lowS: false });
    expect(toBase64Url(deterministic)).toBe(v.signature);
    expect(await verifyFields(b(v.signer), b(v.signature), v.tag, signed)).toBe(true);
  });

  it('orders wrap-signature fields as the gateway does', () => {
    const wrap = vectors.signatures.find((v: { tag: string }) => v.tag === TAGS.wrapSig);
    const [tenantId, conversationId, keyId, ephemeral, recipientKind, recipientRef, recipientFingerprint] = fields(wrap.fields);
    const rebuilt = wrapFields({
      tenantId: tenantId as string,
      conversationId: conversationId as string,
      keyId: keyId as string,
      ephemeral: ephemeral as Bytes,
      recipientKind: recipientKind as string,
      recipientRef: recipientRef as string,
      recipientFingerprint: recipientFingerprint as Bytes,
    });
    expect(toHex(enc(...rebuilt))).toBe(toHex(enc(...fields(wrap.fields))));
  });

  it('orders request-signature fields as the gateway does', async () => {
    const v = vectors.signatures.find((item: { tag: string }) => item.tag === TAGS.requestSig);
    const f = fields(v.fields);
    const pairs: { conversationId: string; keyId: string }[] = [];
    for (let i = 7; i < f.length; i += 2) pairs.push({ conversationId: f[i] as string, keyId: f[i + 1] as string });
    const rebuilt = requestFields({
      tenantId: f[0] as string,
      requestId: f[1] as string,
      kind: 'access',
      recoveryKeyId: f[3] as string,
      requesterSub: f[4] as string,
      reasonHash: await sha256(utf8('Employee left; the authority needs the record.')),
      scope: [...pairs].reverse(),
    });
    expect(pairs).toHaveLength(2);
    expect(toHex(enc(...rebuilt))).toBe(toHex(enc(...f)));
  });

  it('orders approval-signature fields as the gateway does', () => {
    const v = vectors.signatures.find((item: { tag: string }) => item.tag === TAGS.approvalSig);
    const f = fields(v.fields);
    const rebuilt = approvalFields({
      tenantId: f[0] as string,
      requestId: f[1] as string,
      holderIndex: f[2] as number,
      attempt: f[3] as number,
      partials: [
        { keyId: f[7] as string, hash: f[8] as Bytes },
        { keyId: f[5] as string, hash: f[6] as Bytes },
      ],
    });
    expect(f[4]).toBe(2);
    expect(toHex(enc(...rebuilt))).toBe(toHex(enc(...f)));
  });

  it('hashes a partial blob over its exact text', async () => {
    const v = vectors.signatures.find((item: { tag: string }) => item.tag === TAGS.approvalSig);
    const f = fields(v.fields);
    const at = f.indexOf('9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d');
    same(await sha256(utf8('{"v":1}')), f[at + 1] as Bytes);
  });

  it('orders dealing-signature fields as the gateway does', () => {
    const dealing = vectors.signatures.find((v: { tag: string }) => v.tag === TAGS.dealingSig);
    const signed = fields(dealing.fields);
    const commitments = signed.slice(4, -2) as Bytes[];
    const rebuilt = dealingFields({
      tenantId: signed[0] as string,
      ceremonyId: signed[1] as string,
      dealerIndex: signed[2] as number,
      commitments,
      proof: { c: bytesToBigInt(signed.at(-2) as Bytes), s: bytesToBigInt(signed.at(-1) as Bytes) },
    });
    expect(toHex(enc(...rebuilt))).toBe(toHex(enc(...signed)));
  });

  it('checks a whole ceremony', async () => {
    const c = vectors.ceremony;
    for (const dealing of c.dealings) {
      const proof = await schnorrProve(
        c.tenant_id,
        c.ceremony_id,
        dealing.dealer_index,
        n(c.polynomials[dealing.dealer_index][0]),
        n(c.pok_nonces[dealing.dealer_index])
      );
      expect(proof).toEqual({ c: n(dealing.c), s: n(dealing.s) });
      expect(await verifySchnorr(c.tenant_id, c.ceremony_id, dealing.dealer_index, b(dealing.commitments[0]), proof)).toBe(true);
      const coefficients = c.polynomials[dealing.dealer_index].map(n);
      expect(commitmentsOf(coefficients).map(toBase64Url)).toEqual(dealing.commitments);
    }
    const byDealer = Object.fromEntries(c.dealings.map((d: { dealer_index: number; commitments: string[] }) => [d.dealer_index, d.commitments.map(b)]));
    for (const [route, value] of Object.entries(c.subshares) as [string, string][]) {
      const [dealer, holder] = route.split('->').map(Number);
      expect(evaluatePolynomial(c.polynomials[dealer].map(n), holder)).toBe(n(value));
      expect(verifySubshare(holder, n(value), byDealer[dealer])).toBe(true);
    }
    const commitmentLists = c.dealings.map((d: { commitments: string[] }) => d.commitments.map(b));
    expect(toBase64Url(recoveryPublicKey(commitmentLists))).toBe(c.recovery_public_key);
    c.holder_shares.forEach((share: string, offset: number) => {
      expect(toBase64Url(holderPublicShare(offset + 1, commitmentLists))).toBe(share);
    });
    const hash = await transcriptHash({
      tenantId: c.tenant_id,
      ceremonyId: c.ceremony_id,
      k: c.k,
      participants: c.participants.map((p: { holder_ref: string; index: number; fingerprint: string }) => ({
        holderRef: p.holder_ref,
        index: p.index,
        fingerprint: b(p.fingerprint),
      })),
      dealings: c.dealings.map((d: { dealer_index: number; commitments: string[]; c: string; s: string }) => ({
        dealerIndex: d.dealer_index,
        commitments: d.commitments.map(b),
        proof: { c: n(d.c), s: n(d.s) },
      })),
      recoveryPublicKey: b(c.recovery_public_key),
      holderShares: c.holder_shares.map(b),
      gatewayKeys: c.gateway_keys.map((g: { key_id: string; public_key: string }) => ({
        keyId: g.key_id,
        publicKey: b(g.public_key),
      })),
    });
    expect(toBase64Url(hash)).toBe(c.transcript_hash);
  });

  it('checks a resharing that keeps X (spec §9.7)', async () => {
    const r = vectors.resharing;
    const c = vectors.ceremony;
    const dealers: number[] = r.dealers;
    for (const dealer of dealers) {
      expect(lagrangeAtZero(dealer, dealers)).toBe(n(r.lagrange[dealer]));
      same(contribution(dealer, dealers, b(c.holder_shares[dealer - 1])), b(r.contributions[dealer]));
      expect(mod(n(c.shares[dealer]) * lagrangeAtZero(dealer, dealers))).toBe(n(r.polynomials[dealer][0]));
    }
    const lists = r.dealings.map((d: { commitments: string[] }) => d.commitments.map(b));
    expect(toBase64Url(recoveryPublicKey(lists))).toBe(c.recovery_public_key);
    for (const dealing of r.dealings) {
      const proof = await schnorrProve(
        c.tenant_id,
        r.ceremony_id,
        dealing.dealer_index,
        n(r.polynomials[dealing.dealer_index][0]),
        n(r.pok_nonces[dealing.dealer_index])
      );
      expect(proof).toEqual({ c: n(dealing.c), s: n(dealing.s) });
    }
    const participants = r.participants.map((p: { holder_ref: string; index: number; fingerprint: string }) => ({
      holderRef: p.holder_ref,
      index: p.index,
      fingerprint: b(p.fingerprint),
    }));
    const digest = await participantsDigest(participants);
    same(digest, b(r.participants_digest));
    const first = r.dealings[0];
    const signed = reshareDealingFields({
      tenantId: c.tenant_id,
      ceremonyId: r.ceremony_id,
      dealerIndex: first.dealer_index,
      commitments: first.commitments.map(b),
      proof: { c: n(first.c), s: n(first.s) },
      previousTranscript: b(r.previous_transcript_hash),
      participantsDigest: digest,
    });
    same(enc(...signed), enc(...fields(r.dealing_fields)));
    const hash = await transcriptHash({
      tenantId: c.tenant_id,
      ceremonyId: r.ceremony_id,
      k: r.k,
      participants,
      dealings: r.dealings.map((d: { dealer_index: number; commitments: string[]; c: string; s: string }) => ({
        dealerIndex: d.dealer_index,
        commitments: d.commitments.map(b),
        proof: { c: n(d.c), s: n(d.s) },
      })),
      recoveryPublicKey: b(c.recovery_public_key),
      holderShares: r.holder_shares.map(b),
      gatewayKeys: c.gateway_keys.map((g: { key_id: string; public_key: string }) => ({
        keyId: g.key_id,
        publicKey: b(g.public_key),
      })),
      previousTranscript: b(r.previous_transcript_hash),
    });
    expect(toBase64Url(hash)).toBe(r.transcript_hash);
    const share = n(r.shares[r.share_proof.holder_index]);
    const proof = await shareProofProve(c.tenant_id, r.ceremony_id, 1, share, n(r.share_proof.nonce));
    expect(proof).toEqual({ c: n(r.share_proof.c), s: n(r.share_proof.s) });
    expect(await verifyShareProof(c.tenant_id, r.ceremony_id, 1, b(r.holder_shares[0]), proof)).toBe(true);
    expect(await verifyShareProof(c.tenant_id, r.ceremony_id, 2, b(r.holder_shares[0]), proof)).toBe(false);
  });

  it('recovers a conversation key from k partials', async () => {
    const r = vectors.recovery;
    const c = vectors.ceremony;
    const wrap = parseSealed(r.wrap, TAGS.ckWrap);
    const partials = [];
    for (const p of r.partials) {
      const scope = [c.tenant_id, r.request_id, r.key_id, p.holder_index] as const;
      const proved = await dleqProve(scope, n(c.shares[p.holder_index]), wrap.ephemeral, n(p.nonce));
      expect(toBase64Url(proved.partial)).toBe(p.partial);
      expect(proved.proof).toEqual({ c: n(p.c), s: n(p.s) });
      const statement = { holderShare: b(p.holder_share), ephemeral: wrap.ephemeral, partial: b(p.partial) };
      expect(await verifyDleq(scope, statement, proved.proof)).toBe(true);
      partials.push({ index: p.holder_index, partial: b(p.partial) });
    }
    const sharedX = combinePartials(partials);
    expect(toBase64Url(sharedX)).toBe(r.shared_x);
    same(await openWithSharedX(wrap, sharedX, b(c.recovery_public_key), fields(r.context)), b(r.ck));
  });

  it('seals the private-key blob the gateway can open, and opens it', async () => {
    const v = vectors.private_key_blob;
    const identity = { tenantId: v.tenant_id, userSub: v.user_sub };
    const blob = await sealPrivateKeys(v.passphrase, identity, { enc: b(v.enc_pkcs8), sig: b(v.sig_pkcs8) }, v.params, {
      salt: b(v.salt),
      nonces: { enc: b(v.nonces.enc), sig: b(v.nonces.sig) },
    });
    expect(blob).toBe(v.blob);
    const opened = await openPrivateKeys(v.blob, v.passphrase, identity);
    same(opened.enc, b(v.enc_pkcs8));
    same(opened.sig, b(v.sig_pkcs8));
  });
});

function hexToBytes(hex: string): Uint8Array {
  return Uint8Array.from(hex.match(/.{2}/g) ?? [], (pair) => Number.parseInt(pair, 16));
}
