import { Fragment, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { ChevronRight, Lightbulb, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useServices } from '@/app/providers/services';
import { cn } from '@/lib/cn';
import { Button } from '@/ui/primitives/Button';
import { IconButton } from '@/ui/primitives/IconButton';
import { NpsScale } from '@/ui/patterns/NpsScale';
import { StarRating } from '@/ui/patterns/StarRating';

interface FeedbackSheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sessionId?: string | null;
}

const EMPTY = { quality: 0, performance: 0, usability: 0, nps: -1, improvements: '' };

const RATING_SECTIONS = [
  { key: 'quality', field: 'quality' },
  { key: 'performance', field: 'performance' },
  { key: 'usability', field: 'usability' },
] as const;

/**
 * Radix owns presence here rather than forceMount: a force-mounted panel keeps
 * the modal scroll lock and aria-hidden applied to the rest of the page even
 * while closed. Radix holds the node until the exit animation finishes, so the
 * design's 300ms slide survives.
 */
export function FeedbackSheet({ open, onOpenChange, sessionId = null }: Readonly<FeedbackSheetProps>) {
  const { t } = useTranslation();
  const { feedback } = useServices();
  const [form, setForm] = useState(EMPTY);
  const [submitted, setSubmitted] = useState(false);

  const canSubmit = form.quality > 0 && form.performance > 0 && form.usability > 0 && form.nps >= 0;

  const close = () => {
    onOpenChange(false);
    window.setTimeout(() => {
      setForm(EMPTY);
      setSubmitted(false);
    }, 300);
  };

  const submit = async () => {
    await feedback.submit({
      translationQuality: form.quality,
      performance: form.performance,
      usability: form.usability,
      netPromoterScore: form.nps,
      improvements: form.improvements,
      sessionId,
    });
    setSubmitted(true);
  };

  return (
    <Dialog.Root open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-surface-scrim data-[state=closed]:animate-scrim-out data-[state=open]:animate-scrim-in" />
        <Dialog.Content
          aria-describedby={undefined}
          className={cn(
            'fixed inset-x-0 bottom-0 z-50 max-h-[90dvh] overflow-y-auto',
            'rounded-t-sheet border-x border-t border-border-header bg-surface-panel',
            'data-[state=closed]:animate-sheet-out data-[state=open]:animate-sheet-in'
          )}
        >
          <div className="flex justify-center pb-1 pt-3">
            <div className="h-1 w-10 rounded-full bg-surface-handle" />
          </div>

          <div className="flex items-center justify-between px-5 py-4">
            <div className="flex items-center gap-2">
              <Lightbulb size={18} strokeWidth={2} className="text-accent" />
              <Dialog.Title className="text-item font-semibold text-fg-strong">
                {t('feedback.title')}
              </Dialog.Title>
            </div>
            <IconButton label={t('feedback.close')} tone="close" onClick={close}>
              <X size={16} strokeWidth={2} />
            </IconButton>
          </div>

          <div className="mx-5 border-t border-border-divider" />

          {submitted ? (
            <div className="flex flex-col items-center justify-center gap-3 px-5 py-14">
              <div className="flex size-14 items-center justify-center rounded-full bg-accent-15">
                <Lightbulb size={26} strokeWidth={1.5} className="text-accent" />
              </div>
              <p className="text-center text-thanks font-semibold text-fg-strong">
                {t('feedback.thanksTitle')}
              </p>
              <p className="text-center text-note leading-chat text-fg-muted">
                {t('feedback.thanksBody')}
              </p>
              <Button variant="compact" onClick={close} className="mt-4 bg-accent text-accent-on">
                {t('feedback.close')}
              </Button>
            </div>
          ) : (
            <div className="flex flex-col gap-6 px-5 pb-8 pt-5">
              {RATING_SECTIONS.map((section, index) => (
                <Fragment key={section.key}>
                  {index > 0 && <div className="border-t border-border-divider" />}
                  <div className="flex flex-col gap-2">
                    <p className="text-label font-medium uppercase tracking-wider text-fg-muted">
                      {t(`feedback.${section.key}.label`)}
                    </p>
                    <p className="text-body text-fg-strong">
                      {t(`feedback.${section.key}.question`)}
                    </p>
                    <StarRating
                      label={t(`feedback.${section.key}.label`)}
                      value={form[section.field]}
                      onChange={(value) =>
                        setForm((current) => ({ ...current, [section.field]: value }))
                      }
                    />
                  </div>
                </Fragment>
              ))}

              <div className="border-t border-border-divider" />

              <div className="flex flex-col gap-3">
                <p className="text-label font-medium uppercase tracking-wider text-fg-muted">
                  {t('feedback.nps.label')}
                </p>
                <p className="text-body text-fg-strong">{t('feedback.nps.question')}</p>
                <NpsScale
                  value={form.nps}
                  onChange={(nps) => setForm((current) => ({ ...current, nps }))}
                />
                <div className="flex justify-between text-caption text-fg-muted">
                  <span>{t('feedback.nps.low')}</span>
                  <span>{t('feedback.nps.high')}</span>
                </div>
              </div>

              <div className="border-t border-border-divider" />

              <div className="flex flex-col gap-2">
                <p className="text-label font-medium uppercase tracking-wider text-fg-muted">
                  {t('feedback.improvements.label')}
                </p>
                <p className="text-body text-fg-strong">{t('feedback.improvements.question')}</p>
                <textarea
                  rows={3}
                  value={form.improvements}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, improvements: event.target.value }))
                  }
                  placeholder={t('feedback.improvements.placeholder')}
                  className="w-full resize-none rounded-xl border border-border-header bg-surface-field px-4 py-3 text-note leading-chat text-fg-body outline-none transition-colors duration-150 placeholder:text-fg-placeholder focus:border-accent-60"
                />
              </div>

              <Button
                variant="sheet"
                disabled={!canSubmit}
                onClick={() => void submit()}
                className={cn(
                  canSubmit ? 'bg-accent text-accent-on' : 'bg-surface-disabled text-fg-disabled'
                )}
              >
                {t('feedback.submit')}
                {canSubmit && <ChevronRight size={16} strokeWidth={2.5} />}
              </Button>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
