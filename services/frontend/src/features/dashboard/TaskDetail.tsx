import { UnlockSigningVersion } from './stepUpReturn';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { getAdminIdentity } from '@/app/auth/keycloak';
import { useServices } from '@/app/providers/services';
import { equalBytes } from '@/core/crypto/bytes';
import { durationMinutes } from '@/lib/sessionTimes';
import { KeysScreen } from '@/features/keys/KeysScreen';
import { useKeyInventory, useVaultRevision } from '@/features/keys/useKeyInventory';
import { ConversationViewer } from '@/features/archive/ConversationViewer';
import { StaffViewShell } from '@/features/archive/StaffViewShell';
import { ReviewScreen } from '@/features/review/ReviewScreen';
import type { TaskTarget } from './TaskLists';

export interface StaffNav {
  onBack: () => void;
  onSignOut: () => void;
  onOpenKeys: () => void;
  studioUrl?: string;
  accountUrl?: string;
}

export function MetadataDetail({ target, ...nav }: Readonly<{ target: TaskTarget } & StaffNav>) {
  const { dashboard } = useServices();
  const { t, i18n } = useTranslation();
  const result = useQuery({
    queryKey: ['reviews', 'result', target.id],
    enabled: target.kind === 'result',
    gcTime: 0,
    staleTime: 0,
    queryFn: ({ signal }) => dashboard.result(target.id, signal),
  });
  const details = useQuery({
    queryKey: ['dashboard', 'details', target.id],
    enabled: target.kind === 'details',
    gcTime: 0,
    staleTime: 0,
    queryFn: async ({ signal }) => {
      let cursor: string | null = null;
      const visited = new Set<string | null>();
      do {
        visited.add(cursor);
        const page = await dashboard.conversations(cursor, signal);
        const row = page.items.find((r) => r.id === target.id);
        if (row && row.actions.includes('open_details') && row.recording_status === 'none')
          return row;
        cursor = page.next_cursor;
      } while (cursor && !visited.has(cursor));
      throw new Error('Unavailable');
    },
  });
  const local = (time: string) => new Date(time).toLocaleString(i18n.language);
  const detail = details.data,
    decision = result.data;
  const query = target.kind === 'details' ? details : result;
  return (
    <StaffViewShell {...nav}>
      <h1 className="text-thanks font-semibold">
        {t(target.kind === 'result' ? 'admin.tasks.openResult' : 'admin.tasks.open_details')}
      </h1>
      {query.isError ? (
        <p role="alert">{t('admin.tasks.unavailable')}</p>
      ) : query.isPending ? (
        <p role="status">{t('admin.tasks.loading')}</p>
      ) : detail ? (
        <>
          <p>{t('admin.tasks.noRecording')}</p>
          <dl>
            <dt>{t('admin.tasks.time')}</dt>
            <dd>{local(detail.started_at)}</dd>
            {detail.ended_at && (
              <>
                <dt>{t('admin.tasks.ended')}</dt>
                <dd>{local(detail.ended_at)}</dd>
                <dt>{t('admin.tasks.duration')}</dt>
                <dd>
                  {t('admin.tasks.minutes', {
                    n: durationMinutes(detail.started_at, detail.ended_at),
                  })}
                </dd>
              </>
            )}
            <dt>{t('admin.tasks.language')}</dt>
            <dd>{detail.customer_language ?? t('admin.tasks.unknown')}</dd>
            <dt>{t('admin.tasks.status')}</dt>
            <dd>{t(`admin.tasks.states.${detail.conversation_status}`)}</dd>
          </dl>
        </>
      ) : (
        decision && (
          <dl>
            <dt>{t('admin.tasks.assignment')}</dt>
            <dd>{decision.verification_id}</dd>
            <dt>{t('admin.tasks.status')}</dt>
            <dd>{t(`admin.tasks.states.${decision.outcome}`)}</dd>
            <dt>{t('admin.tasks.requested')}</dt>
            <dd>{local(decision.requested_at)}</dd>
            <dt>{t('admin.tasks.decided')}</dt>
            <dd>{local(decision.decided_at)}</dd>
            {decision.requested_by_name && (
              <>
                <dt>{t('admin.tasks.requester')}</dt>
                <dd>{decision.requested_by_name}</dd>
              </>
            )}
          </dl>
        )
      )}
    </StaffViewShell>
  );
}

export function ProtectedDetail({
  target,
  onDone,
  ...nav
}: Readonly<{ target: TaskTarget; onDone: () => void } & StaffNav>) {
  const { archive, reviews, keyVault } = useServices();
  const { t } = useTranslation();
  const owner = getAdminIdentity();
  const inventory = useKeyInventory(owner);
  useVaultRevision();
  const [signingVersion, setSigningVersion] = useState<number>();
  const [check, setCheck] = useState(0);
  const access = useQuery({
    queryKey: ['dashboard', 'access', target.kind, target.id, check],
    gcTime: 0,
    staleTime: 0,
    queryFn: async () => {
      if (target.kind === 'review') {
        const { record, opened } = await reviews.open(target.id);
        if (
          record.verificationId !== target.id ||
          record.reviewerSub !== owner?.userSub ||
          (record.status !== 'awaiting' && record.status !== 'in_review')
        )
          throw new Error('Unavailable');
        return {
          versions: [record.reviewerKeyVersion],
          fingerprint: record.reviewerFingerprint,
          employeeSub: opened.conversation.employeeSub,
        };
      }
      const opened = await archive.open(target.id);
      if (opened.conversation.conversationId !== target.id || !opened.requiredKeyVersions?.length)
        throw new Error('Unavailable');
      return {
        versions: opened.requiredKeyVersions,
        employeeSub: opened.conversation.employeeSub,
        fingerprint: null,
      };
    },
  });
  const needs = access.data;
  if (!owner || inventory.isError || access.isError)
    return (
      <StaffViewShell {...nav}>
        <p role="alert">{t('admin.tasks.unavailable')}</p>
      </StaffViewShell>
    );
  if (!needs || !inventory.data)
    return (
      <StaffViewShell {...nav}>
        <p role="status">{t('admin.tasks.loading')}</p>
      </StaffViewShell>
    );
  const unavailable = needs.versions.some(
    (version) =>
      !inventory.data.versions.some(
        (k) =>
          k.version === version &&
          (k.state === 'active' || k.state === 'superseded') &&
          (!needs.fingerprint || equalBytes(k.fingerprint, needs.fingerprint))
      )
  );
  if (unavailable)
    return (
      <StaffViewShell {...nav}>
        <p role="alert">{t('admin.tasks.contact')}</p>
      </StaffViewShell>
    );
  const missing = signingVersion ?? needs.versions.find((v) => !keyVault.version(owner, v));
  if (missing)
    return (
      <KeysScreen
        {...nav}
        requestedVersion={missing}
        onUnlocked={() => {
          setSigningVersion(undefined);
          setCheck((c) => c + 1);
        }}
      />
    );
  const unlocked = keyVault.version(owner, needs.versions[0]);
  if (!unlocked) return null;
  return (
    <StaffViewShell {...nav}>
      {target.kind === 'review' ? (
        <ReviewScreen verificationId={target.id} unlocked={unlocked} onDone={onDone} />
      ) : (
        <UnlockSigningVersion.Provider value={setSigningVersion}>
          <ConversationViewer
            conversationId={target.id}
            employeeSub={needs.employeeSub}
            unlocked={unlocked}
          />
        </UnlockSigningVersion.Provider>
      )}
    </StaffViewShell>
  );
}
