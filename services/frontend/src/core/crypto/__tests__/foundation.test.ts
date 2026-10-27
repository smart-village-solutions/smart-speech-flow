import { describe, expect, it } from 'vitest';
import { aesKey, objectAad, openEnvelope, sealEnvelope } from '@/core/crypto/aead';
import { bytes, fromBase64Url, utf8 } from '@/core/crypto/bytes';
import { GENERATOR, decodePoint, encodePoint } from '@/core/crypto/curve';
import { enc } from '@/core/crypto/encoding';

describe('archive crypto foundation', () => {
  it('refuses integers that have no canonical form', () => {
    expect(() => enc(-1)).toThrow();
    expect(() => enc(1.5)).toThrow();
    expect(() => enc(new Uint8Array(65536))).toThrow();
  });

  it('keeps field boundaries', () => {
    expect(Array.from(enc('ab', 'c'))).not.toEqual(Array.from(enc('a', 'bc')));
  });

  it.each(['AA==', 'AA+/', 'A', 'A A'])('rejects %s as base64url', (text) => {
    expect(() => fromBase64Url(text)).toThrow();
  });

  it('rejects off-curve, compressed, truncated and identity points', () => {
    const generator = encodePoint(GENERATOR);
    const offCurve = bytes(generator);
    offCurve[64] ^= 1;
    // Valid on the curve, but the spec allows the uncompressed form only.
    const compressed = bytes(GENERATOR.toBytes(true));
    for (const raw of [offCurve, compressed, bytes([0]), generator.slice(0, 33)]) {
      expect(() => decodePoint(raw)).toThrow();
    }
  });

  it('fails to open an object moved to another entry', async () => {
    const key = await aesKey(new Uint8Array(32));
    const address = { tenantId: 't', conversationId: 'c', entryId: 'e1', objectType: 'original.wav', keyId: 'k' };
    const sealed = await sealEnvelope(key, utf8('audio'), objectAad(address));
    await expect(openEnvelope(key, sealed, objectAad({ ...address, entryId: 'e2' }))).rejects.toThrow();
  });
});
