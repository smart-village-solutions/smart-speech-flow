import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { type Bytes, fromBase64Url, fromBuffer } from '@/core/crypto/bytes';
import { type SignedEntry, listedObjects, verifyChain } from '@/core/crypto/chain';
import { signFields, signedDigest } from '@/core/crypto/signatures';
import { TAGS } from '@/core/crypto/tags';

// The gateway signs this chain (tests/recording_crypto_vectors.py).
const vectors = JSON.parse(
  readFileSync(
    path.join(
      import.meta.dirname,
      '../../../../../../tests/fixtures/recording/crypto_vectors_v1.json'
    ),
    'utf8'
  )
);
const v = vectors.chain;
const signers = new Map([[v.signer_key_id as string, fromBase64Url(v.signer)]]);

function entries(): SignedEntry[] {
  return v.entries.map((e: Record<string, never>) => ({
    seq: e.seq,
    entryId: e.entry_id,
    kind: e.kind,
    windowId: e.window_id,
    keyId: e.key_id,
    objects: e.objects,
    prevHash: fromBase64Url(e.prev_hash),
    hash: fromBase64Url(e.hash),
    signerKeyId: e.signer_key_id,
    signature: fromBase64Url(e.signature),
  }));
}

const check = (list: SignedEntry[], keys: ReadonlyMap<string, Uint8Array<ArrayBuffer>> = signers) =>
  verifyChain(v.tenant_id, v.conversation_id, list, keys);

describe('verifyChain', () => {
  it('accepts the gateway-signed vector chain', async () => {
    expect(await check(entries())).toBe(true);
  });

  it('refuses a removed, reordered or altered entry', async () => {
    const list = entries();
    expect(await check([list[0], list[2]])).toBe(false);
    expect(await check([list[1], list[0], list[2]])).toBe(false);
    expect(await check([list[0], { ...list[1], kind: 'failed' }, list[2]])).toBe(false);
  });

  it('refuses a signer the trust check did not accept', async () => {
    expect(await check(entries(), new Map())).toBe(false);
  });

  it('refuses an entry ID its signed object keys do not name', async () => {
    const list = entries();
    list[1] = { ...list[1], entryId: list[0].entryId };
    expect(await check(list)).toBe(false);
  });

  it('refuses another conversation', async () => {
    expect(
      await verifyChain(v.tenant_id, '00000000-0000-4000-8000-000000000000', entries(), signers)
    ).toBe(false);
  });

  it('refuses an entry naming a signer the trust check did not list, though a listed key would verify it', async () => {
    const renamed = new Map([['gk-other', fromBase64Url(v.signer)]]);
    expect(await check(entries(), renamed)).toBe(false);
  });

  it('refuses a validly signed entry spliced in from another fork', async () => {
    const key = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, [
      'sign',
      'verify',
    ]);
    const pub = fromBuffer(await crypto.subtle.exportKey('raw', key.publicKey));
    const keys = new Map([['gk-test', pub]]);
    const sign = async (seq: number, entryId: string, prevHash: Bytes): Promise<SignedEntry> => {
      const objects = JSON.stringify([
        {
          key: `${v.conversation_id}/${entryId}/record.json`,
          sha256: '0'.repeat(64),
          size: 1,
          type: 'record.json',
        },
      ]);
      const fields = [v.tenant_id, v.conversation_id, seq, 'message', '', 'k', objects, prevHash];
      return {
        seq,
        entryId,
        kind: 'message',
        windowId: null,
        keyId: 'k',
        objects,
        prevHash,
        hash: await signedDigest(TAGS.chainSig, fields),
        signerKeyId: 'gk-test',
        signature: await signFields(key.privateKey, TAGS.chainSig, fields),
      };
    };
    const genesis = new Uint8Array(32);
    const first = await sign(1, '10000000-0000-4000-8000-000000000001', genesis);
    const forkFirst = await sign(1, '10000000-0000-4000-8000-000000000002', genesis);
    const forkSecond = await sign(2, '10000000-0000-4000-8000-000000000003', forkFirst.hash);
    expect(await check([forkFirst, forkSecond], keys)).toBe(true);
    expect(await check([first, forkSecond], keys)).toBe(false);
  });

  it('lists an entry’s objects from the signed text', () => {
    expect(listedObjects(entries()[2]).map((o) => o.type)).toEqual(['amendment.json']);
  });
});
