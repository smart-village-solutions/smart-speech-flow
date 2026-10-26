import { useTranslation } from 'react-i18next';
import { getAdminIdentity, hasPermission } from '@/app/auth/keycloak';
import { useFeedback } from '@/app/providers/feedback';
import { useScreenLocale } from '@/app/providers/locale';
import { AdminHeader } from '@/ui/patterns/AdminHeader';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { OpenCeremony } from './OpenCeremony';
import { RecoveryKeyCard } from './RecoveryKeyCard';
import { StartForm } from './StartForm';
import { TENANT_MANAGE, useCeremonyState } from './useCeremony';

function CeremonyPanel({ onOpenKeys }: Readonly<{ onOpenKeys: () => void }>) {
  const { t } = useTranslation();
  const owner = getAdminIdentity();
  const state = useCeremonyState();

  if (owner === null || state.isError) {
    return (
      <p role="alert" className="text-note text-fg-status-alert">
        {t('admin.ceremony.unavailable')}
      </p>
    );
  }
  if (state.isPending) return null;
  const { recoveryKey, ceremony } = state.data;
  if (recoveryKey !== null) return <RecoveryKeyCard recoveryKey={recoveryKey} />;
  if (ceremony !== null) return <OpenCeremony ceremony={ceremony} owner={owner} onOpenKeys={onOpenKeys} />;
  if (hasPermission(TENANT_MANAGE)) return <StartForm tenantId={owner.tenantId} />;
  return <p className="text-note text-fg-muted">{t('admin.ceremony.noCeremony')}</p>;
}

interface CeremonyScreenProps {
  onBack: () => void;
  onOpenKeys: () => void;
  onSignOut: () => void;
  accountUrl?: string;
  studioUrl?: string;
}

/** The tenant's recovery key and the ceremony that creates it (spec §9.2). */
export function CeremonyScreen({ onBack, onOpenKeys, onSignOut, accountUrl, studioUrl }: Readonly<CeremonyScreenProps>) {
  const { t } = useTranslation();
  const { openFeedback } = useFeedback();
  useScreenLocale('de');

  return (
    <ScreenShell>
      <div className="print:hidden">
        <AdminHeader
          onBack={onBack}
          onHome={onBack}
          onFeedback={() => openFeedback({ kind: 'staff', sessionId: null })}
          onSignOut={onSignOut}
          accountUrl={accountUrl}
          studioUrl={studioUrl}
        />
      </div>
      <div className="flex flex-col gap-6 px-5 pb-16 pt-content-top print:p-0">
        <div className="rounded-2xl border border-border-card bg-surface-card p-5 print:hidden">
          <h1 className="mb-1.5 text-thanks font-semibold text-fg-strong">{t('admin.ceremony.title')}</h1>
          <p className="text-note leading-chat text-fg-muted">{t('admin.ceremony.intro')}</p>
        </div>
        <CeremonyPanel onOpenKeys={onOpenKeys} />
      </div>
    </ScreenShell>
  );
}
