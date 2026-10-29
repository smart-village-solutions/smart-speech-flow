import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { fromBase64Url, toBase64Url } from '@/core/crypto/bytes';
import { readTimestamp } from '@/core/crypto/tst-info';

const vectors = JSON.parse(
  readFileSync(
    path.join(
      import.meta.dirname,
      '../../../../../../tests/fixtures/recording/crypto_vectors_v1.json'
    ),
    'utf8'
  )
);

describe('readTimestamp', () => {
  it('reads the imprint and the authority’s time from a token', () => {
    const read = readTimestamp(fromBase64Url(vectors.timestamp.der));
    expect(toBase64Url(read.imprint)).toBe(vectors.timestamp.imprint);
    expect(read.genTime).toBe(vectors.timestamp.gen_time);
  });

  it('refuses a truncated token and another content type', () => {
    const token = fromBase64Url(vectors.timestamp.der);
    expect(() => readTimestamp(token.slice(0, -3))).toThrow();
    const other = token.slice();
    other[6] ^= 0x01; // a byte of the signedData OID
    expect(() => readTimestamp(other)).toThrow();
  });

  it('refuses an imprint made with another hash', () => {
    const token = fromBase64Url(vectors.timestamp.der);
    const sha256 = [0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01];
    const at = token.findIndex((_, i) => sha256.every((byte, j) => token[i + j] === byte));
    const other = token.slice();
    other[at + sha256.length - 1] = 0x03; // SHA-512
    expect(() => readTimestamp(other)).toThrow();
  });
});
