import { useMemo } from 'react';
import type { ReactNode } from 'react';
import type { AppConfig } from '@/app/config/env';
import { I18nProvider } from './I18nProvider';
import { LocaleProvider } from './LocaleProvider';
import { useLocale } from './locale';
import { QueryProvider } from './QueryProvider';
import { ThemeProvider } from './ThemeProvider';
import { BrandProvider } from './BrandProvider';
import { FeedbackProvider } from './FeedbackProvider';
import { PlaybackProvider } from './PlaybackProvider';
import { ServicesProvider } from './ServicesProvider';
import { createServices } from './services';

interface Props {
  children: ReactNode;
  config: AppConfig;
}

export function AppProvidersInner({ children, config }: Readonly<Props>) {
  return (
    <LocaleProvider>
      <LocalisedProviders config={config}>{children}</LocalisedProviders>
    </LocaleProvider>
  );
}

/**
 * Split out so the locale the screens set is readable by everything below it:
 * i18next needs it to pick a catalogue, and the http client sends it as the
 * request locale.
 */
function LocalisedProviders({ children, config }: Readonly<Props>) {
  const { locale, getLocale } = useLocale();

  // `getLocale` is stable, so a language change does not rebuild the graph. The
  // services own the socket factory and the repositories: a new set tears down
  // the live conversation socket and refetches its history the moment the
  // session's language lands, which is every load of the conversation screen.
  const services = useMemo(() => createServices(config, getLocale), [config, getLocale]);

  return (
    <I18nProvider locale={locale}>
      <ServicesProvider services={services}>
        <QueryProvider>
          <ThemeProvider>
            <BrandProvider source={services.brand}>
              <FeedbackProvider>
                <PlaybackProvider>{children}</PlaybackProvider>
              </FeedbackProvider>
            </BrandProvider>
          </ThemeProvider>
        </QueryProvider>
      </ServicesProvider>
    </I18nProvider>
  );
}
