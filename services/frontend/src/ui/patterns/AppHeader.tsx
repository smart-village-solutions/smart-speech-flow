import { ArrowLeft, Home, Lightbulb, Moon, Sun } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { IconButton } from '@/ui/primitives/IconButton';
import { useBrand } from '@/app/providers/brand';
import { useTheme } from '@/app/providers/theme';
import { BrandLogo } from './BrandLogo';

interface AppHeaderProps {
  onBack: () => void;
  onHome: () => void;
  onFeedback: () => void;
}

export function AppHeader({ onBack, onHome, onFeedback }: AppHeaderProps) {
  const { t } = useTranslation();
  const { theme, toggleTheme } = useTheme();
  const { brand, toggleBrand } = useBrand();

  return (
    <header className="fixed inset-x-0 top-0 z-10 border-b border-border-header bg-surface-page">
      <div className="mx-auto flex h-header max-w-app items-center px-5">
        <div className="flex shrink-0 items-center gap-6">
          <button
            type="button"
            onClick={onBack}
            aria-label={t('header.back')}
            className="flex items-center gap-1.5 text-fg-consent transition-colors duration-150 hover:text-fg-strong"
          >
            <ArrowLeft size={17} strokeWidth={2.5} className="rtl:-scale-x-100" />
            <span className="text-note font-medium tracking-back">{t('header.back')}</span>
          </button>

          <IconButton label={t('header.home')} onClick={onHome}>
            <Home size={17} strokeWidth={2} />
          </IconButton>
        </div>

        <div className="flex flex-1 justify-center">
          <button
            type="button"
            onClick={toggleBrand}
            aria-label={t('header.brand')}
            className="flex h-header items-center justify-center text-fg-strong transition-opacity hover:opacity-80 active:opacity-60"
          >
            <BrandLogo className={brand === 'ssf' ? 'scale-[0.55]' : undefined} />
          </button>
        </div>

        <div className="flex items-center gap-6">
          <IconButton label={t('header.feedback')} onClick={onFeedback}>
            <Lightbulb size={18} strokeWidth={2} />
          </IconButton>

          <IconButton label={t('header.theme')} onClick={toggleTheme}>
            {theme === 'dark' ? (
              <Sun size={18} strokeWidth={2} />
            ) : (
              <Moon size={18} strokeWidth={2} />
            )}
          </IconButton>
        </div>
      </div>
    </header>
  );
}
