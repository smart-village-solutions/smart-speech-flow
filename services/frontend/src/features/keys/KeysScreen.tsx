import { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, ChevronDown } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import { useTranslation } from 'react-i18next';
import type { KeyOwner, UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import type { KeyInventory } from '@/domain/recording/keyVersions';
import type { OwnKey } from '@/domain/recording/recording.types';
import { getAdminIdentity } from '@/app/auth/keycloak';
import { useFeedback } from '@/app/providers/feedback';
import { useScreenLocale } from '@/app/providers/locale';
import { AdminHeader } from '@/ui/patterns/AdminHeader';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { PassphraseBackup } from './PassphraseBackup';
import { EnrolForm } from './EnrolForm';
import { FingerprintCard } from './FingerprintCard';
import { ReenrolPanel } from './ReenrolPanel';
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
        <KeyVersionSelect
          versions={inventory.data.versions}
          selected={selected ?? ''}
          disabled={requestedVersion !== undefined}
          onChange={(version) => {
            setChosen(version);
            setBackup(null);
          }}
        />
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

function KeyVersionSelect({
  versions,
  selected,
  disabled,
  onChange,
}: Readonly<{
  versions: KeyInventory['versions'];
  selected: number | '';
  disabled: boolean;
  onChange: (version: number) => void;
}>) {
  const { t } = useTranslation();
  return (
    <label className="flex w-fit max-w-full flex-col gap-1.5 text-label font-medium text-fg-muted">
      {t('admin.tasks.keyVersion')}
      <span className="relative">
        <select
          className="focus-ring min-h-11 w-full appearance-none rounded-lg border border-border-field bg-surface-field py-2 ps-3 pe-9 text-note text-fg-strong"
          aria-label={t('admin.tasks.keyVersion')}
          value={selected}
          disabled={disabled}
          onChange={(event) => onChange(Number(event.target.value))}
        >
          {versions
            .filter((k) => k.state === 'active' || k.state === 'superseded')
            .map((k) => (
              <option key={k.version} value={k.version}>
                {k.version} · {t(`admin.tasks.${k.state}`)}
              </option>
            ))}
        </select>
        <ChevronDown
          aria-hidden
          className="pointer-events-none absolute end-3 top-1/2 size-4 -translate-y-1/2"
        />
      </span>
    </label>
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
    if (unlocked !== null)
      return (
        <div className="rounded-2xl border border-border-card bg-surface-card p-5">
          <FingerprintCard keys={unlocked} />
        </div>
      );
    return <EnrolForm owner={owner} onPassphraseEntered={onPassphraseEntered} />;
  }
  return (
    <div className="rounded-2xl border border-border-card bg-surface-card p-5">
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
        <div className="mt-3 border-t border-border-divider pt-3">
          <ReenrolPanel owner={owner} ownKey={ownKey} onPassphraseEntered={onPassphraseEntered} />
        </div>
      )}
    </div>
  );
}

interface KeysScreenProps {
  children?: React.ReactNode;
  onBack: () => void;
  onSignOut: () => void;
  requestedVersion?: number;
  onUnlocked?: () => void;
  accountUrl?: string;
  studioUrl?: string;
}

/** Personal access passphrase, historical key versions and external account settings. */
export function KeysScreen({
  children,
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
      <div className="flex flex-col gap-4 px-5 pb-16 pt-content-top">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
          <div className="min-w-0">
            <h1
              ref={heading}
              tabIndex={-1}
              className="mb-1.5 text-title font-semibold text-fg-strong"
            >
              {t('admin.tasks.account')}
            </h1>
            <p className="max-w-lg text-note leading-chat text-fg-muted">
              {t('admin.tasks.keyIntro')}
            </p>
          </div>
          {accountUrl && (
            <a
              className="focus-ring inline-flex min-h-11 shrink-0 items-center gap-2 self-start rounded-pill border border-border-card bg-surface-card px-4 text-label font-medium text-fg-strong hover:bg-surface-row-hover"
              href={accountUrl}
              target="_blank"
              rel="noreferrer"
            >
              {t('admin.menu.accountSettings')}
              <ArrowUpRight aria-hidden className="size-4" />
            </a>
          )}
        </div>
        {children}
        <KeysPanel requestedVersion={requestedVersion} onUnlocked={onUnlocked} />
      </div>
    </ScreenShell>
  );
}
