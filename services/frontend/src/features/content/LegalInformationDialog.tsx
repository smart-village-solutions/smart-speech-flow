import * as Dialog from '@radix-ui/react-dialog';
import { useTranslation } from 'react-i18next';
import type { LegalInformation } from '@/domain/content/content.types';
import { cn } from '@/lib/cn';
import type { LegalLinksTone } from '@/ui/patterns/LegalLinks';
import { LegalInformationSections } from './DocumentationInformation';
import { Button } from '@/ui/primitives/Button';

/** Reading source wording never submits a consent or recording decision. */
export function LegalInformationDialog({
  information,
  tone = 'themed',
}: Readonly<{
  information: LegalInformation;
  tone?: LegalLinksTone;
}>) {
  const { t } = useTranslation();
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button
          type="button"
          className={cn(
            'pointer-events-auto text-label leading-snug tracking-link underline underline-offset-2 transition-colors duration-200',
            tone === 'light'
              ? 'text-black/60 hover:text-black'
              : 'text-fg-consent hover:text-fg-consent-hover'
          )}
        >
          {t('legal.informationTitle')}
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="pointer-events-auto fixed inset-0 z-50 bg-surface-scrim" />
        <Dialog.Content className="pointer-events-auto fixed inset-x-5 top-1/2 z-50 mx-auto flex max-h-[85dvh] max-w-dialog -translate-y-1/2 flex-col rounded-2xl border border-border-card bg-surface-card p-5">
          <Dialog.Title className="text-thanks font-semibold text-fg-strong">
            {t('legal.informationTitle')}
          </Dialog.Title>
          <Dialog.Description className="mt-2 text-note leading-chat text-fg-muted">
            {t('legal.informationNotice')}
          </Dialog.Description>
          <p className="mt-3 text-label text-fg-muted">
            {t('legal.informationSource', {
              locale: information.locale,
              version: information.version,
            })}
          </p>
          <div
            role="region"
            aria-label={t('legal.informationTitle')}
            tabIndex={0}
            lang={information.locale}
            dir="auto"
            className="mt-4 min-h-0 space-y-5 overflow-y-auto text-note leading-chat text-fg-body"
          >
            <LegalInformationSections information={information} />
          </div>
          <Dialog.Close asChild>
            <Button
              variant="sheet"
              className="mt-5 shrink-0 border border-border-card text-fg-body"
            >
              {t('legal.informationClose')}
            </Button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
