import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import type { KeyOwner, PassphraseStrength } from '@/core/crypto/archive-crypto.port';
import { AppError } from '@/core/http/AppError';
import { STEP_UP_REQUIRED } from '@/domain/recording/recording.repository';
import { OWN_KEY_QUERY } from './useKeys';

export type EnrolmentError = 'mismatch' | 'weak' | 'stepUp' | 'failed';

/** Spec §8.3: at least 12 characters and the top zxcvbn score. */
const MIN_LENGTH = 12;
const REQUIRED_SCORE = 4;

async function problemWith(
  passphrase: string,
  confirmation: string,
  owner: Readonly<KeyOwner>,
  strength: PassphraseStrength
): Promise<EnrolmentError | null> {
  if (passphrase !== confirmation) return 'mismatch';
  if (passphrase.length < MIN_LENGTH) return 'weak';
  const score = await strength.score(passphrase, [owner.userSub, owner.tenantId]);
  return score >= REQUIRED_SCORE ? null : 'weak';
}

function enrolmentError(caught: unknown): EnrolmentError {
  return caught instanceof AppError && caught.serverCode === STEP_UP_REQUIRED ? 'stepUp' : 'failed';
}

export function useEnrolment(owner: Readonly<KeyOwner>) {
  const { archiveCrypto, recordingKeys, keyVault, passphraseStrength } = useServices();
  const queryClient = useQueryClient();
  const [error, setError] = useState<EnrolmentError | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async (passphrase: string, confirmation: string) => {
    setError(null);
    setPending(true);
    try {
      const problem = await problemWith(passphrase, confirmation, owner, passphraseStrength);
      if (problem !== null) {
        setError(problem);
        return;
      }
      const created = await archiveCrypto.createKeys(passphrase, owner);
      await recordingKeys.enrol(created.unlocked, created.blob);
      keyVault.hold(created.unlocked);
      await queryClient.invalidateQueries({ queryKey: OWN_KEY_QUERY });
    } catch (caught) {
      setError(enrolmentError(caught));
    } finally {
      setPending(false);
    }
  };

  return { submit, error, pending };
}
