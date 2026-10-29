import { useCallback, useEffect, useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { getAdminIdentity } from '@/app/auth/keycloak';
import { useServices } from '@/app/providers/services';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import type { ArchiveCursor } from '@/domain/archive/archive.repository';
import type { OpenedConversation } from '@/domain/archive/archive.types';
import { type Opened, openConversation, openObject } from './openConversation';

export type { Opened } from './openConversation';

/** The staff view the archive opens as; a step-up redirect may return to it. */
export const ARCHIVE_VIEW = 'archive';
const ARCHIVE_LIST_QUERY = ['archive', 'list'] as const;
/** Any of these opens the archive; the gateway enforces the same list (`RECORDING_PERMISSIONS`). */
export const ARCHIVE_PERMISSIONS = [
  'ssf.recording.request',
  'ssf.recording.review',
  'ssf.recording.review.sworn',
  'ssf.recording.supervise',
  'ssf.recording.recovery.custodian',
] as const;
const PAGE = 50;

export function useArchiveList() {
  const { archive } = useServices();
  return useInfiniteQuery({
    queryKey: ARCHIVE_LIST_QUERY,
    queryFn: ({ pageParam }: { pageParam: ArchiveCursor | undefined }) => archive.list(pageParam),
    initialPageParam: undefined as ArchiveCursor | undefined,
    getNextPageParam: (page) => {
      const last = page.at(-1);
      return page.length === PAGE && last
        ? { startedBefore: last.startedAt, beforeId: last.conversationId }
        : undefined;
    },
  });
}

/** Keys and plaintext live in this state only, and go when the viewer closes. */
export function useOpenedConversation(
  conversationId: string,
  unlocked: UnlockedKeys,
  version: number
): Opened {
  const { archive, archiveCrypto, ceremonyCrypto } = useServices();
  // `version` re-opens the conversation after an amendment; a result for an older request reads as checking.
  const request = `${conversationId}:${version}`;
  const [result, setResult] = useState<{ request: string; opened: Opened } | null>(null);

  useEffect(() => {
    let live = true;
    const identity = getAdminIdentity();
    const opening: Promise<Opened> =
      identity === null
        ? Promise.resolve({ status: 'unavailable' })
        : openConversation(
            { archive, archiveCrypto, ceremonyCrypto, identity },
            conversationId,
            unlocked
          );
    const settle = (opened: Opened) => {
      if (live) setResult({ request, opened });
    };
    opening.then(settle, () => settle({ status: 'unavailable' }));
    return () => {
      live = false;
    };
  }, [archive, archiveCrypto, ceremonyCrypto, conversationId, unlocked, request]);

  return result?.request === request ? result.opened : { status: 'checking' };
}

export function useObjectOpener() {
  const { archive, archiveCrypto, ceremonyCrypto } = useServices();
  return useCallback(
    (
      opened: OpenedConversation,
      keys: ReadonlyMap<string, CryptoKey>,
      entryId: string,
      objectType: string
    ) => {
      const identity = getAdminIdentity();
      if (identity === null) return Promise.reject(new Error('signed out'));
      return openObject(
        { archive, archiveCrypto, ceremonyCrypto, identity },
        opened,
        keys,
        entryId,
        objectType
      );
    },
    [archive, archiveCrypto, ceremonyCrypto]
  );
}
