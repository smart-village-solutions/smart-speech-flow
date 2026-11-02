import { useState } from 'react';
import { useServices } from '@/app/providers/services';
import type { KeyOwner } from '@/core/crypto/archive-crypto.port';
import { fromServerCode } from '@/core/http/AppError';
import type { Reenrolled } from '@/domain/recording/recording.types';
import { ENROLMENT_CODES, type EnrolmentError, useNewKeySubmit } from './useEnrolment';

export type ReenrolmentError = EnrolmentError | 'changed' | 'ceremony' | 'mail';

const CODES: Readonly<Record<string, ReenrolmentError>> = {
  ...ENROLMENT_CODES,
  KEY_CHANGED: 'changed',
  CEREMONY_IN_PROGRESS: 'ceremony',
  MAIL_UNAVAILABLE: 'mail',
};

function reenrolmentError(caught: unknown): ReenrolmentError {
  return fromServerCode(caught, CODES, 'failed');
}

/** A new key pair for a lost passphrase, replacing the version the screen showed (spec §9.6). */
export function useReenrolment(owner: Readonly<KeyOwner>, replacesVersion: number) {
  const { archiveCrypto, recordingKeys } = useServices();
  const [result, setResult] = useState<Reenrolled | null>(null);
  const step = useNewKeySubmit(
    owner,
    async (passphrase) => {
      const created = await archiveCrypto.createKeys(passphrase, owner);
      // The old key stays unlocked and in use until the mailed link is confirmed (§9.9).
      setResult(await recordingKeys.reenrol(created.unlocked, created.blob, replacesVersion));
    },
    reenrolmentError
  );
  return { ...step, result };
}
