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
    const expected = await fingerprint(owner.tenantId, owner.userSub, created.unlocked.encPub, created.unlocked.sigPub);
    expect(Array.from(unlocked.fingerprint)).toEqual(Array.from(expected));
  });

  it('refuses a wrong passphrase, another owner, and keys that do not match the blob', async () => {
    const archive = createWebArchiveCrypto();
    const created = await archive.createKeys(PASSPHRASE, owner);
    const other = await archive.createKeys(PASSPHRASE, owner);
    await expect(archive.unlock(created.blob, 'wrong passphrase', owner, created.unlocked)).rejects.toThrow();
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
