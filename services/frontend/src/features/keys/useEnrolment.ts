import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import type { KeyOwner, PassphraseStrength } from '@/core/crypto/archive-crypto.port';
import { fromServerCode } from '@/core/http/AppError';
import { STEP_UP_REQUIRED } from '@/domain/recording/recording.repository';
import { OWN_KEY_QUERY } from './useKeys';

export type EnrolmentError = 'mismatch' | 'weak' | 'stepUp' | 'email' | 'failed';

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

export const ENROLMENT_CODES: Readonly<Record<string, EnrolmentError>> = {
  [STEP_UP_REQUIRED]: 'stepUp',
  EMAIL_NOT_VERIFIED: 'email',
};

function enrolmentError(caught: unknown): EnrolmentError {
  return fromServerCode(caught, ENROLMENT_CODES, 'failed');
}

/** The passphrase checks, the pending state and the error every new key shares (§8.3, §9.6). */
export function useNewKeySubmit<E extends string>(
  owner: Readonly<KeyOwner>,
  work: (passphrase: string, generation: number) => Promise<boolean | void>,
  toError: (caught: unknown) => E
) {
  const { passphraseStrength, keyVault } = useServices();
  const [error, setError] = useState<EnrolmentError | E | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async (passphrase: string, confirmation: string): Promise<boolean> => {
    const generation = keyVault.generation();
    setError(null);
    setPending(true);
    try {
      const problem = await problemWith(passphrase, confirmation, owner, passphraseStrength);
      if (problem !== null) {
        setError(problem);
        return false;
      }
      if (generation !== keyVault.generation()) return false;
      const succeeded = await work(passphrase, generation);
      return succeeded !== false && generation === keyVault.generation();
    } catch (caught) {
      setError(toError(caught));
      return false;
    } finally {
      setPending(false);
    }
  };

  return { submit, error, pending };
}

export function useEnrolment(owner: Readonly<KeyOwner>) {
  const { archiveCrypto, recordingKeys, keyVault } = useServices();
  const queryClient = useQueryClient();
  return useNewKeySubmit(
    owner,
    async (passphrase, generation) => {
      const created = await archiveCrypto.createKeys(passphrase, owner);
      if (generation !== keyVault.generation()) return false;
      await recordingKeys.enrol(created.unlocked, created.blob);
      // A read begun before enrolment must not deliver its old key after the new hold.
      await queryClient.cancelQueries({ queryKey: OWN_KEY_QUERY });
      if (!keyVault.holdIfCurrent(created.unlocked, generation)) return false;
      await queryClient.invalidateQueries({ queryKey: OWN_KEY_QUERY });
      return true;
    },
    enrolmentError
  );
}
