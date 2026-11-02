import { describe, expect, it, vi } from 'vitest';
import { aesKey } from '@/core/crypto/aead';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { fromBuffer, randomBytes, utf8 } from '@/core/crypto/bytes';
import * as ecies from '@/core/crypto/ecies';
import { signFields, wrapFields } from '@/core/crypto/signatures';
import { TAGS } from '@/core/crypto/tags';
import { fingerprint } from '@/core/crypto/transcript';
import type { NoteAddress } from '@/core/crypto/verification';
import { createWebArchiveCrypto } from '@/core/crypto/web-archive-crypto';

const TENANT = 'tenant-kassel';
const C = '6f1c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f';
const K = '9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d';

async function keysFor(sub: string): Promise<UnlockedKeys> {
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

/** A wrap of `ck` for `sub`, made and signed by `signerSub` (their own key for a recovery). */
async function wrapOf(
  ck: Uint8Array,
  sub: string,
  keys: UnlockedKeys,
  signer: UnlockedKeys,
  signerSub: string
) {
  const sealed = await ecies.seal(
    TAGS.ckWrap,
    keys.encPub,
    ck,
    ecies.contexts.ckWrap(TENANT, C, K, 'user', sub)
  );
  const signature = await signFields(
    signer.sigPrivate,
    TAGS.wrapSig,
    wrapFields({
      tenantId: TENANT,
      conversationId: C,
      keyId: K,
      ephemeral: sealed.ephemeral,
      recipientKind: 'user',
      recipientRef: sub,
      recipientFingerprint: keys.fingerprint,
    })
  );
  return {
    tenantId: TENANT,
    conversationId: C,
    keyId: K,
    recipientRef: sub,
    blob: ecies.sealedToJson(sealed),
    creatorRef: signerSub,
    creatorSignature: signature,
  };
}

describe('reviewer crypto (spec §10.7)', { timeout: 30_000 }, () => {
  it('re-wraps a key for a reviewer, who opens it with the assigner as signer', async () => {
    const archive = createWebArchiveCrypto();
    const [alice, rita] = await Promise.all([keysFor('alice'), keysFor('rita')]);
    const ck = randomBytes(32);
    const own = await wrapOf(ck, 'alice', alice, alice, 'alice');

    const made = await archive.rewrapFor(own, alice, new Map(), {
      sub: 'rita',
      encPub: rita.encPub,
      fingerprint: rita.fingerprint,
    });
    const forRita = {
      tenantId: TENANT,
      conversationId: C,
      keyId: made.keyId,
      recipientRef: 'rita',
      blob: made.blob,
      creatorRef: 'alice',
      creatorSignature: made.signature,
    };

    const opened = await archive.openWrap(forRita, rita, new Map([['alice', alice.sigPub]]));
    const probe = await archive.sealObject(opened, objectAddress(), utf8('hello'));
    const original = await aesKey(ck);
    expect(
      new TextDecoder().decode(await archive.openObject(original, objectAddress(), probe))
    ).toBe('hello');
    await expect(archive.openWrap(forRita, rita, new Map())).rejects.toThrow();
  });

  it('never re-wraps a wrap whose signature it cannot check, and zeroes the raw key', async () => {
    const archive = createWebArchiveCrypto();
    const [alice, rita, mallory] = await Promise.all([
      keysFor('alice'),
      keysFor('rita'),
      keysFor('mallory'),
    ]);
    const forged = await wrapOf(randomBytes(32), 'alice', alice, mallory, 'gk-unknown');
    const recipient = { sub: 'rita', encPub: rita.encPub, fingerprint: rita.fingerprint };
    await expect(archive.rewrapFor(forged, alice, new Map(), recipient)).rejects.toThrow();

    const ck = randomBytes(32);
    const spy = vi.spyOn(ecies, 'openWithPrivateKey');
    await archive.rewrapFor(
      await wrapOf(ck, 'alice', alice, alice, 'alice'),
      alice,
      new Map(),
      recipient
    );
    const raw = (await spy.mock.results[0]?.value) as Uint8Array;
    expect(raw.every((byte) => byte === 0)).toBe(true);
    spy.mockRestore();
  });

  it('seals notes only for their own address', async () => {
    const archive = createWebArchiveCrypto();
    const key = await aesKey(randomBytes(32));
    const address: NoteAddress = {
      tenantId: TENANT,
      conversationId: C,
      verificationId: 'v-1',
      part: 'note',
      entryId: 'e-1',
      keyId: K,
    };
    const sealed = await archive.sealNote(key, address, utf8('{"v":1}'));
    expect(new TextDecoder().decode(await archive.openNote(key, address, sealed))).toBe('{"v":1}');
    await expect(archive.openNote(key, { ...address, entryId: 'e-2' }, sealed)).rejects.toThrow();
    await expect(archive.openNote(key, { ...address, part: 'overall' }, sealed)).rejects.toThrow();
  });

  it('signs a decision its verifier accepts and refuses any change', async () => {
    const archive = createWebArchiveCrypto();
    const rita = await keysFor('rita');
    const fields = {
      tenantId: TENANT,
      verificationId: 'v-1',
      conversationId: C,
      reviewedHead: new Uint8Array(32).fill(5),
      outcome: 'approved',
      notesDigest: new Uint8Array(32).fill(6),
      snapshot: ['ssf.recording.review'],
    };
    const signature = await archive.signVerification(rita, fields);
    expect(await archive.verifyVerification(rita.sigPub, signature, fields)).toBe(true);
    expect(
      await archive.verifyVerification(rita.sigPub, signature, {
        ...fields,
        outcome: 'not_approved',
      })
    ).toBe(false);
    expect(
      await archive.verifyVerification(rita.sigPub, signature, {
        ...fields,
        snapshot: ['ssf.recording.review.sworn'],
      })
    ).toBe(false);
  });
});

function objectAddress() {
  return { tenantId: TENANT, conversationId: C, entryId: 'e', objectType: 'record.json', keyId: K };
}
