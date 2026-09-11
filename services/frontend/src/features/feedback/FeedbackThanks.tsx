import { Lightbulb } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/ui/primitives/Button';

export function FeedbackThanks({ onClose }: Readonly<{ onClose: () => void }>) {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col items-center justify-center gap-3 px-5 py-14">
      <div className="flex size-14 items-center justify-center rounded-full bg-accent-15">
        <Lightbulb size={26} strokeWidth={1.5} className="text-accent" />
      </div>
      <p className="text-center text-thanks font-semibold text-fg-strong">
        {t('feedback.thanksTitle')}
      </p>
      <p className="text-center text-note leading-chat text-fg-muted">{t('feedback.thanksBody')}</p>
      <Button variant="compact" onClick={onClose} className="mt-4 bg-accent text-accent-on">
        {t('feedback.close')}
      </Button>
    </div>
  );
}
