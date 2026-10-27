import { z } from 'zod';
import { fromBase64Url } from '@/core/crypto/bytes';
import type { EnrolledKey, OwnKey } from './recording.types';

const base64Url = z.string().regex(/^[A-Za-z0-9_-]+$/).transform(fromBase64Url);
const point = base64Url.refine((value) => value.length === 65, 'expected a 65-byte point');
const fingerprint = {
  fingerprint: base64Url.refine((value) => value.length === 32, 'expected 32 bytes'),
  fingerprint_display: z.string().regex(/^[0-9a-f]{4}( [0-9a-f]{4}){9}$/),
};

const ownKey = z.object({
  enc_pub: point,
  sig_pub: point,
  blob: z.string().min(1),
  created_at: z.string(),
  ...fingerprint,
});

const enrolledKey = z.object(fingerprint);

/** Each throws on a body it cannot use; callers treat that like any failed request. */
export function toOwnKey(body: unknown): OwnKey {
  const parsed = ownKey.parse(body);
  return {
    encPub: parsed.enc_pub,
    sigPub: parsed.sig_pub,
    blob: parsed.blob,
    createdAt: parsed.created_at,
    fingerprint: parsed.fingerprint,
    fingerprintDisplay: parsed.fingerprint_display,
  };
}

export function toEnrolledKey(body: unknown): EnrolledKey {
  const parsed = enrolledKey.parse(body);
  return { fingerprint: parsed.fingerprint, fingerprintDisplay: parsed.fingerprint_display };
}
