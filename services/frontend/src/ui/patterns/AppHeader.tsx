import type { ReactNode } from 'react';
import { ArrowLeft, Home, Lightbulb, Moon, Sun } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { IconButton } from '@/ui/primitives/IconButton';
import { useTheme } from '@/app/providers/theme';

interface AppHeaderProps {
  onBack: () => void;
  onHome: () => void;
  onFeedback: () => void;
  /** The start page has no meaningful previous page or home destination. */
  showNavigation?: boolean;
  /** The admin header puts its user menu here, after the theme toggle. */
  trailing?: ReactNode;
}

export function AppHeader({
  onBack,
  onHome,
  onFeedback,
  showNavigation = true,
  trailing,
}: Readonly<AppHeaderProps>) {
  const { t } = useTranslation();
  const { theme, toggleTheme } = useTheme();

  return (
    // z-20, above the z-10 the status overlays use. `fixed` with a z-index makes
    // this a stacking context, so the user menu's own z-50 is scoped inside the
    // header and cannot lift it over a sibling: at an equal z-10 the overlay won
    // on document order alone, and painted straight over the open menu. The
    // header's z is therefore what decides it, not the menu's.
    <header className="fixed inset-x-0 top-0 z-20 border-b border-black/10 bg-white shadow-[0_2px_6px_rgba(0,0,0,0.08)]">
      <div className="mx-auto flex h-[180px] max-w-app flex-wrap content-start items-center px-5 md:flex-nowrap">
        <div className="order-2 flex flex-1 items-center gap-6 md:order-1 md:flex-none">
          {showNavigation && (
            <>
              <button
                type="button"
                onClick={onBack}
                aria-label={t('header.back')}
                className="flex items-center gap-1.5 text-black/60 transition-colors duration-150 hover:text-black"
              >
                <ArrowLeft size={17} strokeWidth={2.5} className="rtl:-scale-x-100" />
                <span className="text-note font-medium tracking-back">{t('header.back')}</span>
              </button>

              <IconButton
                label={t('header.home')}
                onClick={onHome}
                className="text-black/50 hover:bg-black/8 hover:text-black"
              >
                <Home size={17} strokeWidth={2} />
              </IconButton>
            </>
          )}
        </div>

        <div className="order-1 flex h-[108px] w-full flex-none justify-center md:order-2 md:h-full md:flex-1">
          <img
            src="/assets/Logo.png"
            alt="Smart Speech Flow"
            className="h-full w-full object-contain"
          />
        </div>

        <div className="order-3 flex flex-1 items-center justify-end gap-6 md:flex-none">
          <IconButton
            label={t('header.feedback')}
            onClick={onFeedback}
            className="text-black/50 hover:bg-black/8 hover:text-black"
          >
            <Lightbulb size={18} strokeWidth={2} />
          </IconButton>

          <IconButton
            label={t('header.theme')}
            onClick={toggleTheme}
            className="text-black/50 hover:bg-black/8 hover:text-black"
          >
            {theme === 'dark' ? (
              <Sun size={18} strokeWidth={2} />
            ) : (
              <Moon size={18} strokeWidth={2} />
            )}
          </IconButton>

          {trailing}
        </div>
      </div>
    </header>
  );
}
