import { describe, expect, it } from 'vitest';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { fromBuffer, randomBytes, utf8 } from '@/core/crypto/bytes';
import { contexts, seal, sealedToJson } from '@/core/crypto/ecies';
import { signFields, wrapFields } from '@/core/crypto/signatures';
import { TAGS } from '@/core/crypto/tags';
import { fingerprint } from '@/core/crypto/transcript';
import { createWebArchiveCrypto } from '@/core/crypto/web-archive-crypto';

const owner = { tenantId: 'tenant-kassel', userSub: 'alice' };
const PASSPHRASE = 'Kanne Wolke Ferne Tisch 42';

// Real Argon2id at the enrolment cost: slow by design.
describe('web archive crypto', { timeout: 30_000 }, () => {
  it('creates keys that unlock again, non-extractable, with the right fingerprint', async () => {
    const archive = createWebArchiveCrypto();
    const created = await archive.createKeys(PASSPHRASE, owner);
    expect(created.unlocked.encPrivate.extractable).toBe(false);
    expect(created.unlocked.sigPrivate.extractable).toBe(false);

    const unlocked = await archive.unlock(created.blob, PASSPHRASE, owner, created.unlocked);
    expect(unlocked.encPrivate.extractable).toBe(false);
    const expected = await fingerprint(
      owner.tenantId,
      owner.userSub,
      created.unlocked.encPub,
      created.unlocked.sigPub
    );
    expect(Array.from(unlocked.fingerprint)).toEqual(Array.from(expected));
  });

  it('refuses a wrong passphrase, another owner, and keys that do not match the blob', async () => {
    const archive = createWebArchiveCrypto();
    const created = await archive.createKeys(PASSPHRASE, owner);
    const other = await archive.createKeys(PASSPHRASE, owner);
    await expect(
      archive.unlock(created.blob, 'wrong passphrase', owner, created.unlocked)
    ).rejects.toThrow();
    await expect(
      archive.unlock(created.blob, PASSPHRASE, { ...owner, userSub: 'bob' }, created.unlocked)
    ).rejects.toThrow();
    await expect(archive.unlock(created.blob, PASSPHRASE, owner, other.unlocked)).rejects.toThrow();
  });
});

const C = '6f1c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f';
const K = '9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d';
const E = '1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5';

/** A conversation key wrapped for `keys` and signed by `signer`, as the gateway stores it. */
async function wrapFor(keys: UnlockedKeys, signer: CryptoKey, creatorRef: string) {
  const sealed = await seal(
    TAGS.ckWrap,
    keys.encPub,
    randomBytes(32),
    contexts.ckWrap(owner.tenantId, C, K, 'user', 'alice')
  );
  const signature = await signFields(
    signer,
    TAGS.wrapSig,
    wrapFields({
      tenantId: owner.tenantId,
      conversationId: C,
      keyId: K,
      ephemeral: sealed.ephemeral,
      recipientKind: 'user',
      recipientRef: 'alice',
      recipientFingerprint: keys.fingerprint,
    })
  );
  return {
    tenantId: owner.tenantId,
    conversationId: C,
    keyId: K,
    recipientRef: 'alice',
    blob: sealedToJson(sealed),
    creatorRef,
    creatorSignature: signature,
  };
}

describe('wraps and objects', { timeout: 30_000 }, () => {
  it('opens a wrap a certified gateway key signed, and the objects under it', async () => {
    const archive = createWebArchiveCrypto();
    const { unlocked } = await archive.createKeys(PASSPHRASE, owner);
    const gateway = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, [
      'sign',
      'verify',
    ]);
    const gatewayPub = fromBuffer(await crypto.subtle.exportKey('raw', gateway.publicKey));
    const wrap = await wrapFor(unlocked, gateway.privateKey, 'gk-1');

    const key = await archive.openWrap(wrap, unlocked, new Map([['gk-1', gatewayPub]]));
    expect(key.extractable).toBe(false);
    const address = {
      tenantId: owner.tenantId,
      conversationId: C,
      entryId: E,
      objectType: 'amendment.json',
      keyId: K,
    };
    const envelope = await archive.sealObject(key, address, utf8('{"v":1}'));
    expect(new TextDecoder().decode(await archive.openObject(key, address, envelope))).toBe(
      '{"v":1}'
    );
    await expect(archive.openObject(key, { ...address, entryId: C }, envelope)).rejects.toThrow();

    await expect(
      archive.openWrap(wrap, unlocked, new Map([['gk-2', gatewayPub]]))
    ).rejects.toThrow();
    await expect(
      archive.openWrap({ ...wrap, keyId: E }, unlocked, new Map([['gk-1', gatewayPub]]))
    ).rejects.toThrow();
  });

  it('accepts the caller’s own signing key as creator, and nobody else’s', async () => {
    const archive = createWebArchiveCrypto();
    const { unlocked } = await archive.createKeys(PASSPHRASE, owner);
    const own = await wrapFor(unlocked, unlocked.sigPrivate, 'alice');
    await expect(archive.openWrap(own, unlocked, new Map())).resolves.toBeDefined();
    const stranger = await crypto.subtle.generateKey(
      { name: 'ECDSA', namedCurve: 'P-256' },
      false,
      ['sign', 'verify']
    );
    const forged = await wrapFor(unlocked, stranger.privateKey, 'alice');
    await expect(archive.openWrap(forged, unlocked, new Map())).rejects.toThrow();
  });
});

it('opens a V2 wrap and rejects recipient-version substitution or a missing version', async () => {
  const archive = createWebArchiveCrypto();
  const { unlocked } = await archive.createKeys(PASSPHRASE, owner);
  const { enc } = await import('@/core/crypto/encoding');
  const fields = [owner.tenantId, C, K, 'user', owner.userSub, 3, unlocked.fingerprint];
  const sealed = await seal('SSF-CK-WRAP-V2', unlocked.encPub, randomBytes(32), fields);
  const signature = await signFields(unlocked.sigPrivate, 'SSF-CK-WRAP-SIG-V2', [
    enc(...fields),
    enc(1, sealed.type, sealed.ephemeral, sealed.nonce, sealed.ciphertext),
  ]);
  const wrap = {
    tenantId: owner.tenantId,
    conversationId: C,
    keyId: K,
    recipientRef: owner.userSub,
    recipientVersion: 3,
    blob: sealedToJson(sealed),
    creatorRef: 'gateway',
    creatorSignature: signature,
  };
  const signers = new Map([['gateway', unlocked.sigPub]]);
  expect((await archive.openWrap(wrap, unlocked, signers)).extractable).toBe(false);
  await expect(
    archive.openWrap({ ...wrap, recipientVersion: 2 }, unlocked, signers)
  ).rejects.toThrow();
  await expect(
    archive.openWrap({ ...wrap, recipientVersion: undefined }, unlocked, signers)
  ).rejects.toThrow();
});

it('verifies and opens the shared Gateway transfer vector with the recipient private key', async () => {
  const { readFileSync } = await import('node:fs');
  const { join } = await import('node:path');
  const { fromBase64Url } = await import('@/core/crypto/bytes');
  const vector = JSON.parse(
    readFileSync(
      join(import.meta.dirname, '../../../../../../tests/fixtures/recording/lifecycle_v2.json'),
      'utf8'
    )
  );
  const keys = {
    encPrivate: await crypto.subtle.importKey(
      'pkcs8',
      fromBase64Url(vector.targetPrivateKeyPkcs8),
      { name: 'ECDH', namedCurve: 'P-256' },
      false,
      ['deriveBits']
    ),
    encPub: fromBase64Url(vector.targetEncPub),
    fingerprint: fromBase64Url(vector.targetFingerprint),
  } as UnlockedKeys;
  const archive = createWebArchiveCrypto();
  const opened = await archive.openWrap(
    {
      tenantId: vector.tenantId,
      conversationId: vector.conversationId,
      keyId: vector.keyId,
      recipientVersion: vector.targetVersion,
      recipientRef: vector.targetUserSub,
      creatorRef: 'gateway',
      creatorSignature: fromBase64Url(vector.targetSignature),
      blob: JSON.stringify(vector.targetEnvelope),
    },
    keys,
    new Map([['gateway', fromBase64Url(vector.gatewayPublicKey)]])
  );
  const iv = new Uint8Array(12);
  const plaintext = utf8('Known-answer test');
  const expected = await crypto.subtle.importKey(
    'raw',
    fromBase64Url(vector.contentKey),
    'AES-GCM',
    false,
    ['encrypt']
  );
  expect(
    new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, opened, plaintext))
  ).toEqual(
    new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, expected, plaintext))
  );
});
