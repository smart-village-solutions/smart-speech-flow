import { useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useScreenLocale } from '@/app/providers/locale';
import { useMutation } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import { useFeedback } from '@/app/providers/feedback';
import { isJoinable } from '@/domain/session/session.types';
import { AppError } from '@/core/http/AppError';
import { Button } from '@/ui/primitives/Button';
import { AppHeader } from '@/ui/patterns/AppHeader';
import { CODE_LENGTH, normalizeCode } from '@/lib/accessCode';
import { CodeInput } from '@/ui/patterns/CodeInput';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { StartPageFooter } from '@/ui/patterns/StartPageFooter';

export function AccessCodeScreen() {
  const { t } = useTranslation();
  const { openFeedback } = useFeedback();
  const { session } = useServices();
  const navigate = useNavigate();

  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: (candidate: string) => session.getSession(candidate, 'customer'),
    onSuccess: (found) => {
      if (!isJoinable(found)) {
        setError(t('accessCode.notFound'));
        return;
      }
      void navigate(`/s/${found.id}/language`);
    },
    onError: (failure: unknown) => {
      if (failure instanceof AppError) {
        setError(t(failure.kind === 'notFound' ? 'accessCode.notFound' : failure.userMessageKey));
        return;
      }
      setError(t('errors.unknown'));
    },
  });

  // The customer has not chosen a language yet; the counterpart's is German.
  useScreenLocale('de');

  const normalized = normalizeCode(code);
  const isComplete = normalized.length === CODE_LENGTH;

  return (
    <ScreenShell>
      <AppHeader
        onBack={() => void navigate('/')}
        onHome={() => void navigate('/')}
        onFeedback={openFeedback}
        showNavigation={false}
      />

      <div className="flex w-full flex-1 flex-col items-center justify-center px-5 pt-content-top">
        <h1 className="mb-10 text-center text-title font-bold leading-tight tracking-title text-fg-strong">
          {t('accessCode.title')}
        </h1>

        <CodeInput
          value={code}
          onChange={(next) => {
            setCode(next);
            setError(null);
          }}
        />

        <Button
          disabled={!isComplete || submit.isPending}
          onClick={() => submit.mutate(normalized)}
          className="bg-accent text-accent-on"
        >
          {t('accessCode.continue')}
          <ArrowRight size={16} strokeWidth={2.5} />
        </Button>

        {error !== null && (
          <p role="alert" className="mt-4 text-center text-note text-fg-muted">
            {error}
          </p>
        )}

        <div className="mt-16 flex flex-col items-center gap-3">
          <Link
            to="/login"
            className="text-note font-normal tracking-link text-fg-link underline underline-offset-2 transition-colors duration-200 hover:text-fg-link-hover"
          >
            {t('admin.tenantLogin.title')}
          </Link>
        </div>
      </div>

      <StartPageFooter />
    </ScreenShell>
  );
}
