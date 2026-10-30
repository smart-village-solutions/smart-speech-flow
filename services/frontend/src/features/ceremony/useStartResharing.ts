import { useServices } from '@/app/providers/services';
import { AppError } from '@/core/http/AppError';
import { STEP_UP_REQUIRED } from '@/domain/recording/recording.repository';
import { useDeviceStart } from './useStartCeremony';

export type ResharingError = 'stepUp' | 'dealers' | 'unusable' | 'changed' | 'invalid' | 'failed';

export interface ResharingChoice {
  k: number;
  custodians: string[];
  dealers: number[];
  paper: boolean;
  holdersCeremonyId: string;
}

const BY_CODE: Record<string, ResharingError> = {
  [STEP_UP_REQUIRED]: 'stepUp',
  INVALID_DEALERS: 'dealers',
  HOLDERS_CHANGED: 'changed',
  DEALER_UNUSABLE: 'unusable',
};

function resharingError(caught: unknown): ResharingError {
  if (!(caught instanceof AppError)) return 'failed';
  const known = caught.serverCode === undefined ? undefined : BY_CODE[caught.serverCode];
  if (known !== undefined) return known;
  return caught.status === 422 ? 'invalid' : 'failed';
}

/** With a new paper backup, this browser becomes the ceremony device, as at the first ceremony. */
export function useStartResharing(tenantId: string) {
  const { recoveryCeremony } = useServices();
  const step = useDeviceStart(tenantId, resharingError);
  const start = (choice: Readonly<ResharingChoice>) =>
    step.run(choice.paper, (paperDevicePub) =>
      recoveryCeremony.startResharing({
        k: choice.k,
        custodians: choice.custodians,
        dealers: choice.dealers,
        paperDevicePub,
        holdersCeremonyId: choice.holdersCeremonyId,
      })
    );
  return { start, error: step.error, pending: step.pending };
}
