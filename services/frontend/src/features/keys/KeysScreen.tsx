import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import { useTranslation } from 'react-i18next';
import type { KeyOwner, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import type { OwnKey } from '@/domain/recording/recording.types';
import { getAdminIdentity, hasFreshStepUp } from '@/app/auth/keycloak';
import { useFeedback } from '@/app/providers/feedback';
import { useScreenLocale } from '@/app/providers/locale';
import { AdminHeader } from '@/ui/patterns/AdminHeader';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { PassphraseBackup } from './PassphraseBackup';
import { EnrolForm } from './EnrolForm';
import { FingerprintCard } from './FingerprintCard';
import { ReenrolPanel } from './ReenrolPanel';
import { StepUpPrompt } from './StepUpPrompt';
import { UnlockForm } from './UnlockForm';
import { useKeyInventory, useVaultRevision } from './useKeyInventory';

function KeysPanel({
  requestedVersion,
  onUnlocked,
}: Readonly<{ requestedVersion?: number; onUnlocked?: () => void }>) {
  const owner = getAdminIdentity();
  const { recordingKeys } = useServices();
  const policy = useQuery({
    queryKey: ['recording', 'keyPolicy', owner?.tenantId, owner?.userSub],
    queryFn: () => recordingKeys.passphraseFileEnabled(),
    enabled: owner !== null,
    refetchOnWindowFocus: true,
  });
  const fileEnabled = policy.data === true && !policy.isError;
  if (policy.isPending && owner !== null) return null;
  // A policy or identity change discards transient passphrase input and backup offers.
  return (
    <KeysContent
      key={`${owner?.tenantId}:${owner?.userSub}:${fileEnabled}`}
      fileEnabled={fileEnabled}
      requestedVersion={requestedVersion}
      onUnlocked={onUnlocked}
    />
  );
}

function KeysContent({
  fileEnabled,
  requestedVersion,
  onUnlocked,
}: Readonly<{ fileEnabled: boolean; requestedVersion?: number; onUnlocked?: () => void }>) {
  const { t } = useTranslation();
  const owner = getAdminIdentity();
  const { keyVault, recordingKeys } = useServices();
  const [backup, setBackup] = useState<string | null>(null);
  const offerBackup = (passphrase: string) => {
    if (fileEnabled) setBackup(passphrase);
  };
  useEffect(() => keyVault.subscribe(() => setBackup(null)), [keyVault]);
  const inventory = useKeyInventory(owner);
  const [chosen, setChosen] = useState<number>();
  const selected = requestedVersion ?? chosen ?? inventory.data?.activeVersion;
  const binding = inventory.data?.versions.find(
    (k) => k.version === selected && (k.state === 'active' || k.state === 'superseded')
  );
  const ownKey = useQuery({
    queryKey: ['recording', 'versionBlob', owner?.tenantId, owner?.userSub, binding?.version],
    queryFn: () => recordingKeys.version(binding!.version),
    enabled: !!binding,
    gcTime: 0,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });
  useVaultRevision();
  const unlocked = owner && binding ? keyVault.version(owner, binding.version) : null;
  if (
    owner === null ||
    inventory.isError ||
    ownKey.isError ||
    (selected && !binding && !inventory.isPending)
  ) {
    return (
      <p role="alert" className="text-note text-fg-status-alert">
        {t('admin.keys.unavailable')}
      </p>
    );
  }
  if (inventory.isPending || (binding && ownKey.isPending)) return null;
  return (
    <>
      {inventory.data.versions.length > 0 && (
        <label>
          {t('admin.tasks.keyVersion')}{' '}
          <select
            aria-label={t('admin.tasks.keyVersion')}
            value={selected ?? ''}
            disabled={requestedVersion !== undefined}
            onChange={(event) => {
              setChosen(Number(event.target.value));
              setBackup(null);
            }}
          >
            {inventory.data.versions
              .filter((k) => k.state === 'active' || k.state === 'superseded')
              .map((k) => (
                <option key={k.version} value={k.version}>
                  {k.version} · {t(`admin.tasks.${k.state}`)}
                </option>
              ))}
          </select>
        </label>
      )}
      <KeyActions
        key={selected ?? 'new'}
        owner={owner}
        ownKey={ownKey.data ?? null}
        unlocked={unlocked}
        fileEnabled={fileEnabled}
        onPassphraseEntered={(value) => {
          offerBackup(value);
          onUnlocked?.();
        }}
        active={binding?.state === 'active'}
      />
      {fileEnabled && backup !== null && (
        <PassphraseBackup passphrase={backup} onClose={() => setBackup(null)} />
      )}
    </>
  );
}

interface KeyActionsProps {
  owner: KeyOwner;
  ownKey: OwnKey | null;
  unlocked: UnlockedKeys | null;
  fileEnabled: boolean;
  onPassphraseEntered: (passphrase: string) => void;
  active: boolean;
}

function KeyActions({
  owner,
  ownKey,
  unlocked,
  fileEnabled,
  onPassphraseEntered,
  active,
}: Readonly<KeyActionsProps>) {
  if (ownKey === null) {
    if (unlocked !== null) return <FingerprintCard keys={unlocked} />;
    return hasFreshStepUp() ? (
      <EnrolForm owner={owner} onPassphraseEntered={onPassphraseEntered} />
    ) : (
      <StepUpPrompt />
    );
  }
  return (
    <>
      {unlocked === null ? (
        <UnlockForm
          owner={owner}
          ownKey={ownKey}
          fileEnabled={fileEnabled}
          onPassphraseEntered={onPassphraseEntered}
        />
      ) : (
        <FingerprintCard keys={unlocked} />
      )}
      {active && (
        <ReenrolPanel owner={owner} ownKey={ownKey} onPassphraseEntered={onPassphraseEntered} />
      )}
    </>
  );
}

interface KeysScreenProps {
  onBack: () => void;
  onSignOut: () => void;
  requestedVersion?: number;
  onUnlocked?: () => void;
  accountUrl?: string;
  studioUrl?: string;
}

/** Personal access passphrase, historical key versions and external account settings. */
export function KeysScreen({
  onBack,
  onSignOut,
  requestedVersion,
  onUnlocked,
  accountUrl,
  studioUrl,
}: Readonly<KeysScreenProps>) {
  const { t } = useTranslation();
  const heading = useRef<HTMLHeadingElement>(null);
  const { openFeedback } = useFeedback();
  useScreenLocale('de');

  return (
    <ScreenShell>
      <AdminHeader
        onBack={onBack}
        onHome={onBack}
        onFeedback={() => openFeedback({ kind: 'staff', sessionId: null })}
        onOpenKeys={() => heading.current?.focus()}
        onSignOut={onSignOut}
        accountUrl={accountUrl}
        studioUrl={studioUrl}
      />
      <div className="flex flex-col gap-6 px-5 pb-16 pt-content-top">
        <div className="rounded-2xl border border-border-card bg-surface-card p-5">
          <h1
            ref={heading}
            tabIndex={-1}
            className="mb-1.5 text-thanks font-semibold text-fg-strong"
          >
            {t('admin.tasks.account')}
          </h1>
          <p className="text-note leading-chat text-fg-muted">{t('admin.tasks.keyIntro')}</p>
        </div>
        {accountUrl && (
          <a className="underline" href={accountUrl} target="_blank" rel="noreferrer">
            {t('admin.menu.accountSettings')}
          </a>
        )}
        <KeysPanel requestedVersion={requestedVersion} onUnlocked={onUnlocked} />
      </div>
    </ScreenShell>
  );
}
