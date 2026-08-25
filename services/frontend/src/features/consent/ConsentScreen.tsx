import { useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useScreenLocale } from '@/app/providers/locale';
import { useFeedback } from '@/app/providers/feedback';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import { AppError } from '@/core/http/AppError';
import { mergeActivatedSession } from '@/domain/session/session.mapper';
import type { Session } from '@/domain/session/session.types';
import { AppHeader } from '@/ui/patterns/AppHeader';
import { FlagAvatar } from '@/ui/patterns/FlagAvatar';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { Button } from '@/ui/primitives/Button';
import { Checkbox } from '@/ui/primitives/Checkbox';
import { useLanguages } from '@/features/language-select/useLanguages';

export function ConsentScreen() {
  const { t } = useTranslation();
  const { openFeedback } = useFeedback();
  const { sessionId, languageCode } = useParams<{ sessionId: string; languageCode: string }>();
  const navigate = useNavigate();
  const { session, consent } = useServices();
  const languages = useLanguages();
  const queryClient = useQueryClient();

  useScreenLocale(languageCode ?? '');

  const [agreed, setAgreed] = useState(false);

  const language = (languages.data ?? []).find((candidate) => candidate.code === languageCode);

  const start = useMutation({
    mutationFn: async () => {
      await consent.record({
        sessionId: sessionId as string,
        dataRetentionConsent: agreed,
        recordedAt: new Date().toISOString(),
      });
      return session.activate(sessionId as string, languageCode as string);
    },
    // The route guard cached this session before activation, when the customer
    // had no language yet. Publishing the activated one keeps the conversation
    // screen from opening on the stale entry and sending its first message
    // under the wrong source language, which the gateway rejects.
    onSuccess: (activated) => {
      queryClient.setQueryData<Session>(['session', sessionId], (previous) =>
        mergeActivatedSession(activated, previous)
      );
      void navigate(`/s/${sessionId}/live`);
    },
  });

  return (
    <ScreenShell>
      <AppHeader
        onBack={() => void navigate(`/s/${sessionId}/language`)}
        onHome={() => void navigate('/')}
        onFeedback={openFeedback}
      />

      <div className="flex-1 overflow-y-auto px-5 pb-12 pt-24">
        <div className="mx-auto max-w-app">
          {language && (
            <div className="mb-8 mt-6 flex justify-center">
              <FlagAvatar language={language} size="lg" />
            </div>
          )}

          <div className="flex flex-col gap-5 text-body font-normal leading-prose tracking-prose text-fg-body">
            <p>{t('consent.intro')}</p>
            <p>{t('consent.howTo')}</p>
            <p>{t('consent.retention')}</p>
            <p className="opacity-65">{t('consent.optIn')}</p>
          </div>

          <Checkbox checked={agreed} onCheckedChange={setAgreed} className="mt-8 opacity-65">
            {t('consent.checkbox')}
          </Checkbox>

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
              {t(start.error instanceof AppError ? start.error.userMessageKey : 'errors.unknown')}
            </p>
          )}
        </div>
      </div>
    </ScreenShell>
  );
}
