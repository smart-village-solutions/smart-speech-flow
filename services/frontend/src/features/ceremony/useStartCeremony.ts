import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import type { Bytes } from '@/core/crypto/bytes';
import { AppError } from '@/core/http/AppError';
import { STEP_UP_REQUIRED } from '@/domain/recording/recording.repository';
import { CEREMONY_QUERY } from './useCeremony';

export type StartError = 'stepUp' | 'invalid' | 'failed';

interface StartChoice {
  k: number;
  custodians: string[];
  paper: boolean;
}

function startError(caught: unknown): StartError {
  if (!(caught instanceof AppError)) return 'failed';
  if (caught.serverCode === STEP_UP_REQUIRED) return 'stepUp';
  return caught.status === 422 ? 'invalid' : 'failed';
}

export function useCandidates() {
  const { recoveryCeremony } = useServices();
  return useQuery({ queryKey: [...CEREMONY_QUERY, 'candidates'], queryFn: () => recoveryCeremony.candidates() });
}

/** Runs a start that, with paper, first makes this browser the ceremony device. */
export function useDeviceStart<E>(tenantId: string, classify: (caught: unknown) => E) {
  const { ceremonyCrypto, paperDevice } = useServices();
  const queryClient = useQueryClient();
  const [error, setError] = useState<E | null>(null);
  const [pending, setPending] = useState(false);

  const run = async (paper: boolean, post: (devicePub: Bytes | null) => Promise<unknown>) => {
    setError(null);
    setPending(true);
    try {
      const device = paper ? await ceremonyCrypto.createPaperDevice(tenantId) : null;
      await post(device?.publicKey ?? null);
      if (device) paperDevice.hold(device);
      await queryClient.invalidateQueries({ queryKey: CEREMONY_QUERY });
    } catch (caught) {
      setError(classify(caught));
    } finally {
      setPending(false);
    }
  };

  return { run, error, pending };
}

/**
 * With paper shares, this browser becomes the ceremony device: its key is made
 * here and lives in memory until the sheets are printed (spec §9.2).
 */
export function useStartCeremony(tenantId: string) {
  const { recoveryCeremony } = useServices();
  const step = useDeviceStart(tenantId, startError);
  const start = (choice: Readonly<StartChoice>) =>
    step.run(choice.paper, (devicePub) => recoveryCeremony.start(choice.k, choice.custodians, devicePub));
  return { start, error: step.error, pending: step.pending };
}
