import { useState } from 'react';
import type { FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import type { UnlockedKeys } from '@/core/crypto/archive-crypto.port';
import { Button } from '@/ui/primitives/Button';
import { TextField } from '@/ui/primitives/TextField';
import type { useDealerActions } from './useDealerActions';

export type DealerActions = ReturnType<typeof useDealerActions>;

function EarlierKeyForm({
  fingerprint,
  failed,
  onUnlock,
}: Readonly<{ fingerprint: string; failed: boolean; onUnlock: (passphrase: string) => void }>) {
  const { t } = useTranslation();
  const [passphrase, setPassphrase] = useState('');
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    onUnlock(passphrase);
  };
  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3">
      <p className="text-note leading-chat text-fg-muted">
        {t('admin.ceremony.reshare.retiredKey')} <code>{fingerprint}</code>
      </p>
      <TextField
        type="password"
        autoComplete="off"
        label={t('admin.keys.passphrase')}
        value={passphrase}
        onChange={(event) => setPassphrase(event.target.value)}
        error={failed ? t('admin.ceremony.reshare.unlockFailed') : null}
      />
      <Button type="submit" variant="compact" className="self-start bg-accent text-accent-on">
        {t('admin.ceremony.reshare.unlockRetired')}
      </Button>
    </form>
  );
}

interface KeyGateProps {
  actions: DealerActions;
  keys: UnlockedKeys | null;
  onOpenKeys: () => void;
}

/** Until the listed key is open: why it cannot be served, the keys screen, or its passphrase. */
export function KeyGate({ actions, keys, onOpenKeys }: Readonly<KeyGateProps>) {
  const { t } = useTranslation();
  // Said rather than shown as an empty card: otherwise the resharing would wait out its 24 hours.
  if (actions.loadFailed !== null) {
    return (
      <p role="alert" className="text-meta text-fg-status-alert">
        {t(
          actions.loadFailed === 'unusable'
            ? 'admin.ceremony.reshare.errorUnusable'
            : 'admin.ceremony.stepFailed'
        )}
      </p>
    );
  }
  const served = actions.served;
  if (served === null) return null;
  // A locked vault is unlocked on the keys screen; a custodian who left has none (§9.8).
  if (keys === null && served.hasActiveKey) {
    return (
      <>
        <p className="text-note leading-chat text-fg-muted">{t('admin.ceremony.unlockFirst')}</p>
        <Button
          variant="compact"
          className="self-start bg-accent text-accent-on"
          onClick={onOpenKeys}
        >
          {t('admin.ceremony.openKeys')}
        </Button>
      </>
    );
  }
  if (!actions.needsEarlierKey) return null;
  return (
    <EarlierKeyForm
      fingerprint={served.fingerprintDisplay}
      failed={actions.unlockFailed}
      onUnlock={(passphrase) => void actions.unlockEarlier(passphrase)}
    />
  );
}
