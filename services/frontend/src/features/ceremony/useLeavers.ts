import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import { AppError } from '@/core/http/AppError';
import { STEP_UP_REQUIRED } from '@/domain/recording/recording.repository';
import type { LeaverCandidate } from '@/domain/recovery/recovery.types';
import { CEREMONY_QUERY } from './useCeremony';

const LEAVERS_QUERY = ['recording', 'leavers'] as const;

const FAILED = 'admin.ceremony.leavers.errorFailed';
const ERRORS: Readonly<Record<string, string>> = {
  DIRECTORY_UNAVAILABLE: 'admin.ceremony.leavers.errorDirectory',
  STILL_IN_DIRECTORY: 'admin.ceremony.leavers.errorStillListed',
  ALREADY_LEFT: 'admin.ceremony.leavers.errorAlreadyLeft',
  KEY_NOT_ENROLLED: 'admin.ceremony.leavers.errorNoKey',
  KEY_CHANGED: 'admin.ceremony.leavers.errorKeyChanged',
  CEREMONY_IN_PROGRESS: 'admin.ceremony.leavers.errorCeremony',
};

function serverCode(error: unknown): string | undefined {
  return error instanceof AppError ? error.serverCode : undefined;
}

function errorKey(error: unknown): string {
  return ERRORS[serverCode(error) ?? ''] ?? FAILED;
}

/** The org admin's leaver list and marking (spec §9.8); a marking refreshes the key card too. */
export function useLeavers() {
  const { recoveryCeremony } = useServices();
  const client = useQueryClient();
  const list = useQuery({
    queryKey: LEAVERS_QUERY,
    queryFn: () => recoveryCeremony.leavers(),
    retry: false,
  });
  const mark = useMutation({
    mutationFn: (candidate: Readonly<LeaverCandidate>) =>
      recoveryCeremony.markLeaver(candidate.sub, candidate.keyVersion),
    onSettled: async () => {
      await client.invalidateQueries({ queryKey: LEAVERS_QUERY });
      await client.invalidateQueries({ queryKey: CEREMONY_QUERY });
    },
  });
  return {
    candidates: list.data ?? null,
    listError: list.isError ? errorKey(list.error) : null,
    mark: (candidate: Readonly<LeaverCandidate>, onDone: () => void) =>
      mark.mutate(candidate, { onSuccess: onDone }),
    // A refusal names one attempt; asking about a candidate again starts afresh.
    reset: mark.reset,
    pending: mark.isPending,
    stepUp: mark.isError && serverCode(mark.error) === STEP_UP_REQUIRED,
    markError: mark.isError ? errorKey(mark.error) : null,
  };
}
