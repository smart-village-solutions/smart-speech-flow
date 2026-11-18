import { z } from 'zod';
import { sized } from '@/domain/recovery/recovery.mapper';
import { displayFingerprint } from '@/core/crypto/transcript';
import type { OwnKey } from './recording.types';

const version = z.number().int().positive();
const metadata = z.object({
  version,
  state: z.enum(['active', 'superseded', 'revoked', 'left']),
  fingerprint: sized(32),
  encPub: sized(65),
  sigPub: sized(65),
  createdAt: z.string(),
});
export const inventory = z
  .object({ activeVersion: version.nullable(), versions: z.array(metadata) })
  .refine(
    ({ activeVersion, versions }) =>
      new Set(versions.map((k) => k.version)).size === versions.length &&
      versions.filter((k) => k.state === 'active').length === (activeVersion === null ? 0 : 1) &&
      (activeVersion === null ||
        versions.some((k) => k.version === activeVersion && k.state === 'active'))
  );
export type KeyInventory = z.infer<typeof inventory>;
export function readVersion(value: unknown, requested: number): OwnKey {
  const key = metadata.extend({ blob: z.string().min(1) }).parse(value);
  if (key.version !== requested || (key.state !== 'active' && key.state !== 'superseded'))
    throw new Error('Key unavailable');
  return {
    ...key,
    keyVersion: key.version,
    fingerprintDisplay: displayFingerprint(key.fingerprint),
  };
}
