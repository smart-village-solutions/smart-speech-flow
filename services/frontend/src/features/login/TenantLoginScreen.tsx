import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useFeedback } from '@/app/providers/feedback';
import { useScreenLocale } from '@/app/providers/locale';
import { useServices } from '@/app/providers/services';
import { AppHeader } from '@/ui/patterns/AppHeader';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { StartPageFooter } from '@/ui/patterns/StartPageFooter';
import { Button } from '@/ui/primitives/Button';

const collator = new Intl.Collator('de', { sensitivity: 'base' });

export function TenantLoginScreen() {
  const { t } = useTranslation();
  const { openFeedback } = useFeedback();
  const { loginTenant } = useServices();
  const navigate = useNavigate();

  useScreenLocale('de');

  const tenants = useQuery({
    queryKey: ['login-tenants'],
    queryFn: () => loginTenant.list(),
  });
  const ordered = [...(tenants.data ?? [])].sort(
    (left, right) =>
      collator.compare(left.displayName, right.displayName) || left.id.localeCompare(right.id)
  );

  return (
    <ScreenShell>
      <AppHeader
        onBack={() => void navigate('/')}
        onHome={() => void navigate('/')}
        onFeedback={openFeedback}
        showNavigation={false}
      />

      <main className="flex w-full flex-1 flex-col px-5 pb-10 pt-content-top">
        <div className="mx-auto w-full max-w-sm">
          <h1 className="mb-4 text-center text-title font-bold leading-tight tracking-title text-fg-strong">
            {t('admin.tenantLogin.title')}
          </h1>
          <p className="mb-10 text-center text-body leading-prose tracking-prose text-fg-body">
            {t('admin.tenantLogin.instruction')}
          </p>

          {tenants.isPending && (
            <div className="flex justify-center">
              <span
                role="status"
                aria-label={t('admin.tenantLogin.loading')}
                className="size-8 animate-spin rounded-full border-4 border-accent-15 border-t-accent"
              />
            </div>
          )}

          {tenants.isError && (
            <div className="flex flex-col items-center gap-4">
              <p role="alert" className="text-center text-note text-fg-muted">
                {t('admin.tenantLogin.unavailable')}
              </p>
              <Button
                variant="compact"
                className="bg-accent text-accent-on"
                onClick={() => void tenants.refetch()}
              >
                {t('admin.tenantLogin.retry')}
              </Button>
            </div>
          )}

          {tenants.isSuccess && ordered.length === 0 && (
            <p className="text-center text-note text-fg-muted">{t('admin.tenantLogin.empty')}</p>
          )}

          {tenants.isSuccess && ordered.length > 0 && (
            <ul className="flex flex-col gap-3">
              {ordered.map((tenant) => (
                <li key={tenant.id}>
                  <Link
                    to={`/login/${encodeURIComponent(tenant.id)}`}
                    className="flex w-full rounded-row border border-border-card bg-surface-card px-4 py-3 text-item font-medium leading-tight tracking-item text-fg-strong transition-colors duration-150 hover:bg-surface-row-hover active:bg-surface-row-active focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                  >
                    {tenant.displayName}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </main>

      <StartPageFooter />
    </ScreenShell>
  );
}
