import { ArrowRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useFeedback } from '@/app/providers/feedback';
import { guestOrigin } from '@/domain/feedback/feedbackOrigin';
import { AppError } from '@/core/http/AppError';
import { AppHeader } from '@/ui/patterns/AppHeader';
import { FlagAvatar } from '@/ui/patterns/FlagAvatar';
import { RichText } from '@/ui/patterns/RichText';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { Button } from '@/ui/primitives/Button';
import { Checkbox } from '@/ui/primitives/Checkbox';
import { SiteLegalLinks } from '@/features/content/SiteLegalLinks';
import { ConsentProse } from './ConsentProse';
import { ConsentSkeleton } from './ConsentSkeleton';
import { useConsentScreen } from './useConsentScreen';

export function ConsentScreen() {
  const { t } = useTranslation();
  const { openFeedback } = useFeedback();
  const { sessionId, language, ready, copy, agreed, setAgreed, start, goBack, goHome } =
    useConsentScreen();

  return (
    <ScreenShell>
      <AppHeader
        onBack={goBack}
        onHome={goHome}
        onFeedback={() => openFeedback(guestOrigin(sessionId))}
      />

      <div className="flex-1 overflow-y-auto px-5 pb-12 pt-content-top">
        <div className="mx-auto max-w-app">
          {language && (
            <div className="mb-8 mt-6 flex justify-center">
              <FlagAvatar language={language} iconUrl={language.iconUrl} size="lg" />
            </div>
          )}

          {ready ? (
            <>
              <ConsentProse explanationHtml={copy.explanationHtml} showsOptIn={copy.asksStorage} />

              {copy.asksStorage && (
                <Checkbox checked={agreed} onCheckedChange={setAgreed} className="mt-8 opacity-65">
                  {copy.questionHtml === undefined ? (
                    t('consent.checkbox')
                  ) : (
                    <RichText html={copy.questionHtml} inline />
                  )}
                </Checkbox>
              )}

              <Button
                className="mt-10 bg-accent text-accent-on"
                disabled={start.isPending}
                onClick={() => start.mutate()}
              >
                {t('consent.getStarted')}
                <ArrowRight size={16} strokeWidth={2.5} />
              </Button>

              {start.isError && (
                <p role="alert" className="mt-4 text-center text-note text-fg-muted">
                  {t(
                    start.error instanceof AppError ? start.error.userMessageKey : 'errors.unknown'
                  )}
                </p>
              )}
            </>
          ) : (
            <ConsentSkeleton label={t('consent.loading')} />
          )}
        </div>
      </div>
      <SiteLegalLinks className="px-5 pt-4 pb-legal-end" />
    </ScreenShell>
  );
}
