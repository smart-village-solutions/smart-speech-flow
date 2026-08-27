import { useState } from 'react';
import { ArrowRight, Moon, Sun } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useScreenLocale } from '@/app/providers/locale';
import { useMutation } from '@tanstack/react-query';
import { useServices } from '@/app/providers/services';
import { useTheme } from '@/app/providers/theme';
import { isJoinable } from '@/domain/session/session.types';
import { AppError } from '@/core/http/AppError';
import { Button } from '@/ui/primitives/Button';
import { IconButton } from '@/ui/primitives/IconButton';
import { BrandLogo } from '@/ui/patterns/BrandLogo';
import { CODE_LENGTH, normalizeCode } from '@/lib/accessCode';
import { CodeInput } from '@/ui/patterns/CodeInput';
import { ScreenShell } from '@/ui/patterns/ScreenShell';

export function AccessCodeScreen() {
  const { t } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const { session } = useServices();
  const navigate = useNavigate();

  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: (candidate: string) => session.getSession(candidate),
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
    <ScreenShell className="items-center">
      <div className="absolute end-5 top-5">
        <IconButton label={t('header.theme')} onClick={toggleTheme}>
          {theme === 'dark' ? (
            <Sun size={18} strokeWidth={2} />
          ) : (
            <Moon size={18} strokeWidth={2} />
          )}
        </IconButton>
      </div>

      <div className="mt-36 flex justify-center text-fg-strong">
        <BrandLogo />
      </div>

      <div className="-mt-12 flex w-full flex-1 flex-col items-center justify-center px-5">
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

        {/* The admin UI is the real one now; the legacy page lives on at
            /legacy/admin for comparison. */}
        <Link
          to="/admin"
          className="mt-32 text-note font-normal tracking-link text-fg-link underline underline-offset-2 transition-colors duration-200 hover:text-fg-link-hover"
        >
          {t('accessCode.adminLogin')}
        </Link>
      </div>
    </ScreenShell>
  );
}
