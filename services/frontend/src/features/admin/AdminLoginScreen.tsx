import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useScreenLocale } from '@/app/providers/locale';
import { TextField } from '@/ui/primitives/TextField';

interface AdminLoginScreenProps {
  /** Returns false when the password was refused. Becomes async under Keycloak. */
  onSignIn: (password: string) => boolean;
  onBack: () => void;
}

/** Deliberately permissive: the gateway, not this form, owns what an account is. */
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Imitates the Keycloak page that replaces it, so an admin recognises the screen
 * it stands in for. Painted from src/ui/styles/keycloak.css rather than the
 * design system, and deleted together with those tokens when the real login
 * lands.
 *
 * It gates on a build-time password shared with the legacy chooser — a speed
 * bump, not authentication. The email is validated for shape and compared to
 * nothing: identity belongs to Keycloak.
 *
 * `kc-page` pins the colour tokens the shared primitives read, so the screen is
 * one light page in both themes. A real identity provider is its own site and
 * would not follow the app's theme either.
 */
export function AdminLoginScreen({ onSignIn, onBack }: Readonly<AdminLoginScreenProps>) {
  const { t } = useTranslation();
  useScreenLocale('de');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<'email' | 'credentials' | null>(null);

  const edit = (set: (value: string) => void) => (value: string) => {
    set(value);
    setError(null);
  };

  const submit = () => {
    if (!EMAIL.test(email.trim())) {
      setError('email');
      return;
    }
    if (!onSignIn(password)) {
      setError('credentials');
    }
  };

  return (
    <div className="kc-page flex min-h-dvh w-full flex-col bg-kc-chrome">
      <div className="flex items-center gap-3 bg-kc-brand px-6 py-3">
        <span className="flex size-7 items-center justify-center rounded-row bg-kc-badge text-caption font-bold text-white">
          KC
        </span>
        <span className="text-label text-white/70">{t('admin.login.topBar')}</span>
      </div>

      <div className="flex flex-1 items-center justify-center px-5 py-12">
        <form
          className="w-full max-w-kc-card overflow-hidden rounded-xl bg-white shadow-lg"
          // The browser's own validation of `type="email"` would block submit
          // before `submit` runs, replacing a translated in-page message with an
          // untranslated bubble in the browser's chrome.
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <div className="bg-kc-brand px-6 py-5">
            <p className="mb-1 text-label text-white/70">{t('admin.login.tenant')}</p>
            <h1 className="text-dots font-semibold text-white">{t('admin.login.title')}</h1>
          </div>

          <div className="flex flex-col gap-4 px-6 py-6">
            {error === 'credentials' && (
              <p role="alert" className="text-label text-fg-status-alert">
                {t('admin.login.invalidCredentials')}
              </p>
            )}

            <TextField
              label={t('admin.login.email')}
              type="email"
              autoComplete="username"
              placeholder={t('admin.login.emailPlaceholder')}
              value={email}
              error={error === 'email' ? t('admin.login.invalidEmail') : null}
              onChange={(event) => edit(setEmail)(event.target.value)}
            />
            <TextField
              label={t('admin.login.password')}
              type="password"
              autoComplete="current-password"
              placeholder={t('admin.login.passwordPlaceholder')}
              value={password}
              onChange={(event) => edit(setPassword)(event.target.value)}
            />

            <button
              type="submit"
              disabled={email.trim() === '' || password === ''}
              className="w-full rounded-row bg-kc-brand py-2.5 text-note font-semibold text-white disabled:opacity-30"
            >
              {t('admin.login.submit')}
            </button>

            <button type="button" onClick={onBack} className="text-label text-fg-body">
              {`← ${t('admin.login.back')}`}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
