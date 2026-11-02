import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { getAdminIdentity, hasFreshStepUp } from '@/app/auth/keycloak';
import { useServices } from '@/app/providers/services';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { equalBytes } from '@/core/crypto/bytes';
import { displayFingerprint, fingerprint } from '@/core/crypto/transcript';
import { AppError } from '@/core/http/AppError';
import type { ReviewerCandidate } from '@/domain/archive/archive.types';
import { useOwnKey } from '@/features/keys/useKeys';
import type { Opened } from './openConversation';

type Ready = Extract<Opened, { status: 'ready' }>;
type RequestStage = 'stepUp' | 'pick' | 'confirm';

const KNOWN = new Set([
  'NOT_A_REVIEWER',
  'REVIEWER_NOT_ELIGIBLE',
  'ASSIGNMENT_EXISTS',
  'KEY_CHANGED',
  'REVIEWER_KEY_CHANGED',
  'SIGNATURE_INVALID',
  'SCOPE_NOT_COVERED',
  'DIRECTORY_UNAVAILABLE',
]);

function errorKey(error: unknown): string {
  const code = error instanceof AppError ? (error.serverCode ?? '') : '';
  return KNOWN.has(code) ? code : 'FAILED';
}

function requestError(mismatch: boolean, stage: RequestStage, error: unknown): string | null {
  if (mismatch) return 'FINGERPRINT_MISMATCH';
  // The step-up prompt says it all; a FAILED line beside it would only confuse.
  if (stage === 'stepUp' || error === null) return null;
  return errorKey(error);
}

/** Reviewers covering every language of the conversation, unless the caller asks for all. */
export function covering(candidates: readonly ReviewerCandidate[], languages: readonly string[]) {
  return candidates.filter((candidate) =>
    languages.every((lang) => candidate.languages.includes(lang))
  );
}

/** Wraps every conversation key for the reviewer in the browser, then assigns (spec §10.7). */
export function useRequestVerification(
  state: Ready,
  unlocked: UnlockedKeys,
  onAssigned: () => void
) {
  const { archive, archiveCrypto } = useServices();
  const ownKey = useOwnKey();
  const conversationId = state.opened.conversation.conversationId;
  const [stage, setStage] = useState<RequestStage>(() => (hasFreshStepUp() ? 'pick' : 'stepUp'));
  const [picked, setPicked] = useState<ReviewerCandidate | null>(null);
  // Computed here from the keys the wraps are sealed to; what the server displays is not shown.
  const [checked, setChecked] = useState<string | null>(null);
  const [mismatch, setMismatch] = useState(false);
  const candidates = useQuery({
    queryKey: ['archive', 'reviewers', conversationId],
    queryFn: () => archive.reviewers(conversationId),
    enabled: stage !== 'stepUp',
    staleTime: 0,
  });

  const assign = useMutation({
    mutationFn: async (reviewer: ReviewerCandidate) => {
      const identity = getAdminIdentity();
      const keyVersion = ownKey.data?.keyVersion;
      if (identity === null || keyVersion === undefined) throw new Error('no key');
      const recipient = {
        sub: reviewer.sub,
        encPub: reviewer.encPub,
        fingerprint: reviewer.fingerprint,
      };
      const wraps = [];
      for (const key of state.opened.keys) {
        if (key.wrap === null) throw new Error('a key is not open to the caller');
        const wrap = {
          tenantId: identity.tenantId,
          conversationId,
          keyId: key.keyId,
          recipientRef: identity.userSub,
          ...key.wrap,
        };
        wraps.push(await archiveCrypto.rewrapFor(wrap, unlocked, state.signers, recipient));
      }
      return archive.assign(conversationId, {
        keyVersion,
        reviewerSub: reviewer.sub,
        reviewerKeyVersion: reviewer.keyVersion,
        wraps,
      });
    },
    onSuccess: onAssigned,
    onError: (error) => {
      if (error instanceof AppError && error.serverCode === 'STEP_UP_REQUIRED') setStage('stepUp');
    },
  });

  return {
    stage,
    candidates,
    picked,
    pick: setPicked,
    checked,
    next: async () => {
      const identity = getAdminIdentity();
      if (picked === null || identity === null) return;
      const computed = await fingerprint(
        identity.tenantId,
        picked.sub,
        picked.encPub,
        picked.sigPub
      );
      const matches = equalBytes(computed, picked.fingerprint);
      setMismatch(!matches);
      if (!matches) return;
      setChecked(displayFingerprint(computed));
      setStage('confirm');
    },
    back: () => setStage('pick'),
    submit: () => picked && assign.mutate(picked),
    pending: assign.isPending,
    error: requestError(mismatch, stage, assign.isError ? assign.error : null),
  };
}

export type RequestVerification = ReturnType<typeof useRequestVerification>;
