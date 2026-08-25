import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useScreenLocale } from '@/app/providers/locale';
import { useFeedback } from '@/app/providers/feedback';
import { AppHeader } from '@/ui/patterns/AppHeader';
import { FlagAvatar } from '@/ui/patterns/FlagAvatar';
import { ScreenShell } from '@/ui/patterns/ScreenShell';
import { Button } from '@/ui/primitives/Button';
import { LanguageSkeleton } from './LanguageSkeleton';
import { useLanguages } from './useLanguages';

export function LanguageSelectScreen() {
  const { t } = useTranslation();
  const { openFeedback } = useFeedback();

  // Nobody has said which language they read yet, so the picker is English.
  useScreenLocale('en');

  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const languages = useLanguages();

  return (
    <ScreenShell>
      <AppHeader
        onBack={() => void navigate('/')}
        onHome={() => void navigate('/')}
        onFeedback={openFeedback}
      />

      <div className="flex-1 overflow-y-auto px-5 pb-8 pt-24">
        <div className="mx-auto max-w-app">
          <h1 className="mb-10 text-center text-title font-bold leading-tight tracking-title text-fg-strong">
            {t('language.title')}
          </h1>

          {languages.isPending && <LanguageSkeleton label={t('language.title')} />}

          {languages.isError && (
            <div className="mx-auto flex max-w-sm flex-col items-center gap-4">
              <p role="alert" className="text-center text-note text-fg-muted">
                {t('language.loadFailed')}
              </p>
              <Button
                variant="compact"
                onClick={() => void languages.refetch()}
                className="bg-accent text-accent-on"
              >
                {t('language.retry')}
              </Button>
            </div>
          )}

          {languages.isSuccess && (
            <ul className="mx-auto flex max-w-sm flex-col gap-4">
              {languages.data.map((language) => (
                <li key={language.code}>
                  <button
                    type="button"
                    onClick={() => void navigate(`/s/${sessionId}/info/${language.code}`)}
                    className="flex w-full items-center gap-6 rounded-row px-4 py-2 transition-colors duration-150 hover:bg-surface-row-hover active:bg-surface-row-active"
                  >
                    <FlagAvatar language={language} />
                    <span className="flex-1 text-start">
                      <span className="block text-item font-normal leading-tight tracking-item text-fg-strong">
                        {language.native}
                      </span>
                      {language.native !== language.english && (
                        <span className="block text-meta font-normal leading-tight tracking-meta text-fg-subtle">
                          {language.english}
                        </span>
                      )}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </ScreenShell>
  );
}
