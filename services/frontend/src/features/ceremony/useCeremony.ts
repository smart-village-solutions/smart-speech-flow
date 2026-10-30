import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import { type Bytes, equalBytes } from '@/core/crypto/bytes';
import {
  CeremonyCheckError,
  type CeremonyFacts,
  type CeremonyFault,
  type CertifiedTrust,
} from '@/core/crypto/ceremony-crypto.port';
import { AppError } from '@/core/http/AppError';
import { STEP_UP_REQUIRED } from '@/domain/recording/recording.repository';
import { trustChain } from '@/domain/recovery/chain.mapper';
import type { Ceremony, CeremonyParticipant, ServedChain } from '@/domain/recovery/recovery.types';

export const CEREMONY_QUERY = ['recording', 'ceremony'] as const;
/** The staff view the step-up redirect returns to. */
export const CEREMONY_VIEW = 'ceremony';
export const TENANT_MANAGE = 'ssf.configuration.tenant.manage';
export const CUSTODIAN = 'ssf.recording.recovery.custodian';
/** Other custodians deal and sign on their own devices; this view follows them. */
const POLL_MS = 5000;

export function useCeremonyState() {
  const { recoveryCeremony } = useServices();
  return useQuery({
    queryKey: CEREMONY_QUERY,
    queryFn: () => recoveryCeremony.state(),
    refetchInterval: (query) => (query.state.data?.ceremony ? POLL_MS : false),
  });
}

/** A resharing's facts carry the generation it replaces, once this browser certified it (§9.7). */
export function ceremonyFacts(
  tenantId: string,
  ceremony: Readonly<Ceremony>,
  previous: CertifiedTrust | null = null
): CeremonyFacts {
  const facts: CeremonyFacts = {
    tenantId,
    ceremonyId: ceremony.ceremonyId,
    k: ceremony.k,
    participants: ceremony.participants,
    dealings: ceremony.dealings,
    gatewayKeys: ceremony.gatewayKeys,
  };
  if (ceremony.kind !== 'resharing' || ceremony.recoveryKeyId === null || ceremony.previousTranscript === null) {
    return facts;
  }
  return {
    ...facts,
    resharing: {
      recoveryKeyId: ceremony.recoveryKeyId,
      previousTranscript: ceremony.previousTranscript,
      dealers: ceremony.dealers.map((dealer) => dealer.dealerIndex),
      previous,
    },
  };
}

/**
 * The current holders, certified here before anyone deals to or receives from a
 * resharing. A chain that fails leaves `previous` null, so every step aborts with chain_invalid.
 */
export function useCertifiedChain(tenantId: string, chain: Readonly<ServedChain> | null) {
  const { ceremonyCrypto } = useServices();
  const last = chain?.generations.at(-1)?.ceremonyId ?? null;
  const query = useQuery({
    // Outside the ceremony's query key: a step refetches that, and the chain does not change.
    queryKey: ['recording', 'certified-chain', last],
    queryFn: () => ceremonyCrypto.certifyChain(trustChain(tenantId, chain as ServedChain)),
    enabled: chain !== null,
    retry: false,
    staleTime: Infinity,
  });
  return { previous: query.data ?? null, pending: chain !== null && query.isPending };
}

export type StepError = 'stepUp' | 'failed' | CeremonyFault;

/**
 * Runs one ceremony step. A failed check aborts the ceremony with its reason,
 * because the ceremony is abort-on-failure (spec §9.2); a missing step-up asks
 * for a fresh login; anything else may simply be retried.
 */
export function useCeremonyStep(ceremonyId: string) {
  const { recoveryCeremony } = useServices();
  const queryClient = useQueryClient();
  const [error, setError] = useState<StepError | null>(null);
  const [pending, setPending] = useState(false);

  const run = async (step: () => Promise<void>) => {
    setError(null);
    setPending(true);
    try {
      await step();
    } catch (caught) {
      setError(await classify(caught, () => recoveryCeremony.abort(ceremonyId, faultOf(caught))));
    } finally {
      setPending(false);
      await queryClient.invalidateQueries({ queryKey: CEREMONY_QUERY });
    }
  };

  return { run, error, pending };
}

function faultOf(caught: unknown): CeremonyFault {
  return caught instanceof CeremonyCheckError ? caught.fault : 'transcript_mismatch';
}

async function classify(caught: unknown, abort: () => Promise<void>): Promise<StepError> {
  if (caught instanceof AppError && caught.serverCode === STEP_UP_REQUIRED) return 'stepUp';
  if (!(caught instanceof CeremonyCheckError)) return 'failed';
  await abort().catch(() => undefined);
  return caught.fault;
}

/** Every new holder ticked as compared, with exactly the fingerprint listed now (spec §9.7). */
export function allTicked(
  participants: readonly CeremonyParticipant[],
  ticked: ReadonlyMap<number, Bytes>
): boolean {
  return participants.every((p) => {
    const seen = ticked.get(p.holderIndex);
    return seen !== undefined && equalBytes(seen, p.fingerprint);
  });
}
