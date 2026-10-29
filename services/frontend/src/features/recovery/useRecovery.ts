import { useCallback, useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getAdminIdentity, hasFreshStepUp } from '@/app/auth/keycloak';
import { useServices } from '@/app/providers/services';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import type { Bytes } from '@/core/crypto/bytes';
import type { ApprovalDetail, RecoveryCandidate } from '@/domain/recovery/requests.types';
import {
  type CombineOutcome,
  type RecoveryDeps,
  approveOnce,
  combineOnce,
  faultOf,
  fileOnce,
} from './steps';

/** The staff views exceptional access opens as; a step-up redirect may return to either. */
export const RECOVERY_REQUESTS_VIEW = 'recoveryRequests';
export const RECOVERY_APPROVALS_VIEW = 'recoveryApprovals';
export const SUPERVISE = 'ssf.recording.supervise';
const RECOVERY_QUERY = ['recovery'] as const;

function useDeps(): RecoveryDeps {
  const { archive, ceremonyCrypto, recoveryCrypto, recoveryRequests } = useServices();
  return { archive, ceremonyCrypto, recoveryCrypto, recoveryRequests };
}

export function useRecoveryRequests() {
  const { recoveryRequests } = useServices();
  return useQuery({
    queryKey: [...RECOVERY_QUERY, 'requests'],
    queryFn: () => recoveryRequests.requests(),
  });
}

export function useRequestProgress(requestId: string) {
  const { recoveryRequests } = useServices();
  return useQuery({
    queryKey: [...RECOVERY_QUERY, 'request', requestId],
    queryFn: () => recoveryRequests.progress(requestId),
  });
}

export function useApprovalsList() {
  const { recoveryRequests } = useServices();
  return useQuery({
    queryKey: [...RECOVERY_QUERY, 'approvals'],
    queryFn: () => recoveryRequests.approvals(),
  });
}

export function useApprovalDetail(requestId: string) {
  const { recoveryRequests } = useServices();
  // Fetched once per review: keys swapped in by a later refetch must not meet an earlier tick.
  return useQuery({
    queryKey: [...RECOVERY_QUERY, 'approval', requestId],
    queryFn: () => recoveryRequests.approval(requestId),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

export function useEmployees() {
  const { recoveryRequests } = useServices();
  return useQuery({
    queryKey: [...RECOVERY_QUERY, 'employees'],
    queryFn: () => recoveryRequests.employees(),
  });
}

export function useCandidates(employee: string, from: string, to: string) {
  const { recoveryRequests } = useServices();
  return useQuery({
    queryKey: [...RECOVERY_QUERY, 'candidates', employee, from, to],
    queryFn: () => recoveryRequests.candidates(employee, from, to),
    enabled: employee !== '' && from !== '' && from < to,
  });
}

interface Progress {
  pending: boolean;
  fault: string | null;
}

/** Runs one recovery step with its pending state; the queries refetch after it. */
function useStep() {
  const queryClient = useQueryClient();
  const [state, setState] = useState<Progress>({ pending: false, fault: null });
  const run = useCallback(
    async (work: () => Promise<void>): Promise<boolean> => {
      setState({ pending: true, fault: null });
      try {
        await work();
        await queryClient.invalidateQueries({ queryKey: RECOVERY_QUERY });
        setState({ pending: false, fault: null });
        return true;
      } catch (error) {
        setState({ pending: false, fault: faultOf(error) });
        return false;
      }
    },
    [queryClient]
  );
  const reset = useCallback(() => setState({ pending: false, fault: null }), []);
  return { ...state, run, reset };
}

export function useFileRequest(keys: UnlockedKeys) {
  const deps = useDeps();
  const step = useStep();
  const [stale, setStale] = useState(false);
  const file = (input: Readonly<{ reason: string; candidates: readonly RecoveryCandidate[] }>) => {
    const identity = getAdminIdentity();
    // The form may have taken longer than the step-up lasts; filing would only answer 403.
    if (!hasFreshStepUp()) {
      setStale(true);
      return Promise.resolve(false);
    }
    return step.run(async () => {
      if (identity === null) throw new Error('not signed in');
      await fileOnce(deps, identity, keys, input);
    });
  };
  return { file, pending: step.pending, fault: stale ? 'step_up' : step.fault };
}

export function useCancel(requestId: string) {
  const { recoveryRequests } = useServices();
  const step = useStep();
  return {
    cancel: () => step.run(() => recoveryRequests.cancel(requestId)),
    pending: step.pending,
  };
}

export function useCombine(requestId: string, keys: UnlockedKeys | null) {
  const deps = useDeps();
  const queryClient = useQueryClient();
  const [state, setState] = useState<{ pending: boolean; outcome: CombineOutcome | null }>({
    pending: false,
    outcome: null,
  });
  const run = async () => {
    const identity = getAdminIdentity();
    if (identity === null || keys === null) return;
    setState({ pending: true, outcome: null });
    let outcome: CombineOutcome;
    try {
      outcome = await combineOnce(deps, identity, keys, requestId);
    } catch (error) {
      outcome = { kind: 'failed', code: faultOf(error) };
    }
    // The archive lists the conversations once their wraps are stored.
    await queryClient.invalidateQueries({ queryKey: RECOVERY_QUERY });
    await queryClient.invalidateQueries({ queryKey: ['archive'] });
    setState({ pending: false, outcome });
  };
  return { run, ...state };
}

/** The requester's fingerprint, computed here from the served keys (spec §9.5 step 3). */
function useRequesterFingerprint(detail: Readonly<ApprovalDetail>): Bytes | null {
  const { recoveryCrypto } = useServices();
  const tenantId = getAdminIdentity()?.tenantId ?? null;
  const [result, setResult] = useState<{ detail: Readonly<ApprovalDetail>; value: Bytes } | null>(
    null
  );
  useEffect(() => {
    let live = true;
    if (tenantId === null) return undefined;
    const keys = { encPub: detail.requesterEncPub, sigPub: detail.requesterSigPub };
    recoveryCrypto.fingerprintOf(tenantId, detail.requesterSub, keys).then(
      (value) => {
        if (live) setResult({ detail, value });
      },
      () => undefined
    );
    return () => {
      live = false;
    };
  }, [recoveryCrypto, tenantId, detail]);
  // A value computed for an earlier detail is never shown for this one.
  return result?.detail === detail ? result.value : null;
}

export function useApprove(detail: Readonly<ApprovalDetail>, keys: UnlockedKeys | null) {
  const deps = useDeps();
  const step = useStep();
  const fingerprint = useRequesterFingerprint(detail);
  const [stale, setStale] = useState(false);
  // A step-up older than 240 s would expire mid-approval; asking first wipes nothing (§9.5).
  const guarded = (work: () => Promise<void>) => {
    if (!hasFreshStepUp()) {
      setStale(true);
      return Promise.resolve(false);
    }
    return step.run(work);
  };
  const approve = (confirmed: Bytes) =>
    guarded(async () => {
      const identity = getAdminIdentity();
      if (identity === null || keys === null) throw new Error('not signed in or locked');
      await approveOnce(deps, identity, keys, detail, confirmed);
    });
  const decline = (reason: string) =>
    guarded(() => deps.recoveryRequests.decline(detail.requestId, reason));
  const retry = () => {
    setStale(false);
    step.reset();
  };
  return {
    approve,
    decline,
    retry,
    fingerprint,
    pending: step.pending,
    fault: stale ? 'step_up' : step.fault,
  };
}
