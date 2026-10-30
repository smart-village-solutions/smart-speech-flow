import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import type { KeyOwner } from '@/core/crypto/archive-crypto.port';
import { AppError } from '@/core/http/AppError';
import type { Reenrolled } from '@/domain/recording/recording.types';
import { type EnrolmentError, useNewKeySubmit } from './useEnrolment';
import { OWN_KEY_QUERY } from './useKeys';

export type ReenrolmentError = EnrolmentError | 'changed' | 'ceremony';

const CODES: Record<string, ReenrolmentError> = {
  STEP_UP_REQUIRED: 'stepUp',
  KEY_CHANGED: 'changed',
  CEREMONY_IN_PROGRESS: 'ceremony',
};

function reenrolmentError(caught: unknown): ReenrolmentError {
  const code = caught instanceof AppError ? caught.serverCode : undefined;
  return (code !== undefined && CODES[code]) || 'failed';
}

/** A new key pair for a lost passphrase, replacing the version the screen showed (spec §9.6). */
export function useReenrolment(owner: Readonly<KeyOwner>, replacesVersion: number) {
  const { archiveCrypto, recordingKeys, keyVault } = useServices();
  const queryClient = useQueryClient();
  const [result, setResult] = useState<Reenrolled | null>(null);
  const step = useNewKeySubmit(
    owner,
    async (passphrase) => {
      // An old key still unlocked would sign for a key the gateway has retired.
      keyVault.lock();
      const created = await archiveCrypto.createKeys(passphrase, owner);
      const done = await recordingKeys.reenrol(created.unlocked, created.blob, replacesVersion);
      if (done.status === 'active') keyVault.hold(created.unlocked);
      setResult(done);
      await queryClient.invalidateQueries({ queryKey: OWN_KEY_QUERY });
    },
    reenrolmentError
  );
  return { ...step, result };
}
