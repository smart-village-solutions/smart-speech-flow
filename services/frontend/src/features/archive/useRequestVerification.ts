import { UnlockSigningVersion } from '@/features/dashboard/unlockSigningVersion';
import { useContext, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { getAdminIdentity } from '@/app/auth/keycloak';
import { useServices } from '@/app/providers/services';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { equalBytes } from '@/core/crypto/bytes';
import { displayFingerprint, fingerprint } from '@/core/crypto/transcript';
import { knownServerCode } from '@/core/http/AppError';
import type { ReviewerCandidate } from '@/domain/archive/archive.types';
import { useKeyInventory } from '@/features/keys/useKeyInventory';
import type { Opened } from './openConversation';

type Ready = Extract<Opened, { status: 'ready' }>;
type RequestStage = 'pick' | 'confirm';

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

function requestError(mismatch: boolean, error: unknown): string | null {
  if (mismatch) return 'FINGERPRINT_MISMATCH';
  if (error === null) return null;
  return knownServerCode(error, KNOWN, 'FAILED');
}

/** Reviewers covering every language of the conversation, unless the caller asks for all. */
export function covering(candidates: readonly ReviewerCandidate[], languages: readonly string[]) {
  return candidates.filter((candidate) => {
    const spoken = new Set(candidate.languages.map(primaryLanguage));
    return languages.every((lang) => spoken.has(primaryLanguage(lang)));
  });
}

/** Studio sends BCP 47 tags such as `en-US`; a conversation names the bare language. */
function primaryLanguage(tag: string): string {
  const end = tag.indexOf('-');
  return (end === -1 ? tag : tag.slice(0, end)).toLowerCase();
}

/** Wraps every conversation key for the reviewer in the browser, then assigns (spec §10.7). */
export function useRequestVerification(
  state: Ready,
  unlocked: UnlockedKeys,
  onAssigned: () => void
) {
  const { keyVault, archive, archiveCrypto } = useServices();
  const inventory = useKeyInventory(getAdminIdentity());
  const unlockSigner = useContext(UnlockSigningVersion);
  const conversationId = state.opened.conversation.conversationId;
  const [stage, setStage] = useState<RequestStage>('pick');
  const [picked, setPicked] = useState<ReviewerCandidate | null>(null);
  // Computed here from the keys the wraps are sealed to; what the server displays is not shown.
  const [checked, setChecked] = useState<string | null>(null);
  const [mismatch, setMismatch] = useState(false);
  const candidates = useQuery({
    queryKey: ['archive', 'reviewers', conversationId],
    queryFn: () => archive.reviewers(conversationId),
    staleTime: 0,
  });

  const assign = useMutation({
    mutationFn: async (reviewer: ReviewerCandidate) => {
      const identity = getAdminIdentity();
      const keyVersion = inventory.data?.activeVersion;
      if (identity === null || keyVersion == null) throw new Error('no key');
      const generation = keyVault.generation();
      const versioned = state.opened.requiredKeyVersions !== undefined;
      const signer = versioned ? keyVault.version(identity, keyVersion) : unlocked;
      if (!signer) {
        unlockSigner?.(keyVersion);
        throw new Error('Active signing key is locked');
      }
      const recipient = {
        version: reviewer.keyVersion,
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
        const source =
          wrap.recipientVersion === undefined
            ? unlocked
            : keyVault.version(identity, wrap.recipientVersion);
        if (!source || generation !== keyVault.generation())
          throw new Error('Source key unavailable');
        wraps.push(
          versioned
            ? await archiveCrypto.rewrapFor(
                wrap,
                source,
                state.signers,
                recipient,
                signer.sigPrivate
              )
            : await archiveCrypto.rewrapFor(wrap, source, state.signers, recipient)
        );
      }
      if (
        generation !== keyVault.generation() ||
        (versioned && keyVault.version(identity, keyVersion) !== signer)
      )
        throw new Error('Signing key changed');
      return archive.assign(conversationId, {
        keyVersion,
        reviewerSub: reviewer.sub,
        reviewerKeyVersion: reviewer.keyVersion,
        wraps,
      });
    },
    onSuccess: onAssigned,
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
    error: requestError(mismatch, assign.isError ? assign.error : null),
  };
}

export type RequestVerification = ReturnType<typeof useRequestVerification>;
