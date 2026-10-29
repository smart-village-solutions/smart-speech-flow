import { useState } from 'react';
import { getAdminIdentity } from '@/app/auth/keycloak';
import { useServices } from '@/app/providers/services';
import { AppError } from '@/core/http/AppError';
import { type AmendmentPost, AmendmentNotStoredError } from '@/domain/archive/archive.repository';
import type { OpenedConversation } from '@/domain/archive/archive.types';
import { newAmendment } from './records';

export const AMENDMENT_MAX = 4000;

/** The newest key the caller can open and recovery can too, so recovery always reads it (§10.6). */
function pickAmendmentKey(
  opened: OpenedConversation,
  keys: ReadonlyMap<string, CryptoKey>
): string | null {
  const usable = opened.keys.filter((key) => key.recoveryWrapped && keys.has(key.keyId));
  usable.sort((left, right) => right.epoch - left.epoch);
  return usable[0]?.keyId ?? null;
}

type AmendFailure = 'notStored' | 'failed' | 'noKey';

export interface Amend {
  submit: (references: readonly string[], text: string) => Promise<void>;
  /** Posts the unconfirmed amendment again: the same entry and bytes, which the gateway accepts. */
  retry: () => Promise<void>;
  /** An amendment was sealed and posted, but its storing was never confirmed. */
  unconfirmed: boolean;
  failure: AmendFailure | null;
  pending: boolean;
}

/**
 * Lives with the viewer, not the dialog: an amendment the gateway may already
 * hold in its chain must keep its bytes until it is confirmed (§10.6).
 */
export function useAmend(
  opened: OpenedConversation,
  keys: ReadonlyMap<string, CryptoKey>,
  onAdded: () => void
): Amend {
  const { archive, archiveCrypto } = useServices();
  const [unconfirmed, setUnconfirmed] = useState<AmendmentPost | null>(null);
  const [failure, setFailure] = useState<AmendFailure | null>(null);
  const [pending, setPending] = useState(false);

  const seal = async (
    references: readonly string[],
    text: string
  ): Promise<AmendmentPost | null> => {
    const identity = getAdminIdentity();
    const keyId = pickAmendmentKey(opened, keys);
    const key = keyId === null ? undefined : keys.get(keyId);
    if (identity === null || keyId === null || key === undefined) return null;
    const entryId = crypto.randomUUID();
    const address = {
      tenantId: identity.tenantId,
      conversationId: opened.conversation.conversationId,
      entryId,
      objectType: 'amendment.json',
      keyId,
    };
    const plaintext = newAmendment(references, text, identity.userSub, new Date());
    return { entryId, keyId, ciphertext: await archiveCrypto.sealObject(key, address, plaintext) };
  };

  const post = async (amendment: AmendmentPost) => {
    try {
      await archive.amend(opened.conversation.conversationId, amendment);
      setUnconfirmed(null);
      onAdded();
    } catch (error) {
      // A definite refusal stored nothing; only a failure that may have kept it in the chain
      // (a failed store write, a lost answer, a server error) keeps the bytes for a retry.
      const notStored = error instanceof AmendmentNotStoredError;
      const maybeKept = notStored || (error instanceof AppError && error.retryable);
      setUnconfirmed(maybeKept ? amendment : null);
      setFailure(notStored ? 'notStored' : 'failed');
    }
  };

  const run = async (work: () => Promise<void>) => {
    setPending(true);
    setFailure(null);
    try {
      await work();
    } finally {
      setPending(false);
    }
  };

  const submit = (references: readonly string[], text: string) =>
    run(async () => {
      const sealed = await seal(references, text);
      if (sealed === null) setFailure('noKey');
      else await post(sealed);
    });

  const retry = () =>
    run(async () => {
      if (unconfirmed !== null) await post(unconfirmed);
    });

  return { submit, retry, unconfirmed: unconfirmed !== null, failure, pending };
}
