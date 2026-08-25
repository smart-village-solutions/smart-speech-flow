import type { ReactElement, ReactNode } from 'react';
import { render, type RenderResult } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { I18nProvider } from '@/app/providers/I18nProvider';
import { LocaleProvider } from '@/app/providers/LocaleProvider';
import { useLocale } from '@/app/providers/locale';
import { ThemeProvider } from '@/app/providers/ThemeProvider';
import { type Theme } from '@/app/providers/theme';
import { BrandProvider } from '@/app/providers/BrandProvider';
import { FeedbackProvider } from '@/app/providers/FeedbackProvider';
import { PlaybackProvider } from '@/app/providers/PlaybackProvider';
import { ServicesProvider } from '@/app/providers/ServicesProvider';
import { createServices, type Services } from '@/app/providers/services';
import { createStaticBrandSource } from '@/domain/brand/StaticBrandSource';
import { readConfig } from '@/app/config/env';
import type { BrandId } from '@/app/config/env';
import type { AudioPlayerPort } from '@/core/audio/player.port';
import type { ClipLoader } from '@/core/audio/clips';
import { createFakeAudioPlayer } from './fakeAudioPlayer';
import { createFakeClipLoader } from './fakeClipLoader';

interface Options {
  route?: string;
  theme?: Theme;
  brand?: BrandId;
  locale?: string;
  /** Override individual services with fakes; the rest are the real ones. */
  services?: Partial<Services>;
  /** Drives playback assertions; jsdom implements no media element at all. */
  player?: AudioPlayerPort;
  /** Supplies waveform shapes; jsdom implements no Web Audio at all. */
  clips?: ClipLoader;
}

export function renderWithProviders(ui: ReactElement, options: Options = {}): RenderResult {
  const { route = '/', theme = 'dark', brand = 'ssf', locale = 'en' } = options;
  const player = options.player ?? createFakeAudioPlayer().port;
  const clips = options.clips ?? createFakeClipLoader();

  const services: Services = {
    ...createServices(readConfig({}), () => locale),
    ...options.services,
  };

  // A fresh client per render stops query caches leaking between tests.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  function Localised({ children }: { children: ReactNode }) {
    const { locale: active } = useLocale();
    return <I18nProvider locale={active}>{children}</I18nProvider>;
  }

  return render(
    <MemoryRouter initialEntries={[route]}>
      <LocaleProvider initialLocale={locale}>
        <Localised>
          <ServicesProvider services={services}>
            <QueryClientProvider client={queryClient}>
              <ThemeProvider initialTheme={theme}>
                <BrandProvider source={createStaticBrandSource(brand)}>
                  <FeedbackProvider>
                    <PlaybackProvider player={player} clips={clips}>
                      {ui}
                    </PlaybackProvider>
                  </FeedbackProvider>
                </BrandProvider>
              </ThemeProvider>
            </QueryClientProvider>
          </ServicesProvider>
        </Localised>
      </LocaleProvider>
    </MemoryRouter>
  );
}
