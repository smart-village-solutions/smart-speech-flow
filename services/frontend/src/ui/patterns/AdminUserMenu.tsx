import { useCallback, useState } from 'react';
import type { ReactNode } from 'react';
import { User } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { IconButton } from '@/ui/primitives/IconButton';
import { TextField } from '@/ui/primitives/TextField';
import { useDismissOnOutsideTap } from '@/ui/hooks/useDismissOnOutsideTap';
import { cn } from '@/lib/cn';

type Section = 'none' | 'password' | 'email';

/** Menu fields are labelled by their placeholder, as the export does. */
function MenuField({ label, type }: Readonly<{ label: string; type: string }>) {
  return <TextField label={label} labelHidden density="compact" type={type} placeholder={label} />;
}

interface MenuSectionProps {
  label: string;
  expanded: boolean;
  onToggle: () => void;
  first?: boolean;
  children: ReactNode;
}

/** A disclosure row plus its form body. Every section ends in the same inert
 *  save button, so it lives here rather than in each caller. */
function MenuSection({
  label,
  expanded,
  onToggle,
  first = false,
  children,
}: Readonly<MenuSectionProps>) {
  const { t } = useTranslation();

  return (
    <>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className={cn(
          'flex h-menu-row w-full items-center justify-between px-4 text-note text-fg-body hover:bg-surface-row-hover',
          !first && 'border-t border-border-divider'
        )}
      >
        <span>{label}</span>
        <span
          aria-hidden
          className={cn('text-item opacity-40 transition-transform', expanded && 'rotate-45')}
        >
          +
        </span>
      </button>

      {expanded && (
        <div className="flex flex-col gap-2 border-t border-border-divider px-4 pb-4 pt-3">
          {children}
          <button
            type="button"
            className="self-start rounded-row bg-accent px-3 py-1.5 text-meta font-semibold text-accent-on"
          >
            {t('admin.menu.save')}
          </button>
        </div>
      )}
    </>
  );
}

interface AdminUserMenuProps {
  onSignOut: () => void;
}

/** Both forms are UI only: issue #202 defers account management to Keycloak. */
export function AdminUserMenu({ onSignOut }: Readonly<AdminUserMenuProps>) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [section, setSection] = useState<Section>('none');

  const close = useCallback(() => {
    setOpen(false);
    setSection('none');
  }, []);

  useDismissOnOutsideTap(open, close);

  const toggle = (next: Section) => setSection((current) => (current === next ? 'none' : next));

  return (
    <div className="relative" data-dismiss-keep="">
      <IconButton
        label={t('admin.menu.open')}
        onClick={() => (open ? close() : setOpen(true))}
        className={open ? 'bg-surface-icon-hover text-fg-strong' : undefined}
      >
        <User size={16} strokeWidth={2} />
      </IconButton>

      {open && (
        <div className="absolute end-0 top-11 z-50 w-menu overflow-hidden rounded-2xl border border-border-card bg-surface-card shadow-xl">
          <MenuSection
            first
            label={t('admin.menu.changePassword')}
            expanded={section === 'password'}
            onToggle={() => toggle('password')}
          >
            <MenuField label={t('admin.menu.newPassword')} type="password" />
            <MenuField label={t('admin.menu.confirmPassword')} type="password" />
          </MenuSection>

          <MenuSection
            label={t('admin.menu.changeEmail')}
            expanded={section === 'email'}
            onToggle={() => toggle('email')}
          >
            <MenuField label={t('admin.menu.newEmail')} type="email" />
          </MenuSection>

          <button
            type="button"
            onClick={onSignOut}
            className="h-menu-row w-full border-t border-border-divider px-4 text-start text-note text-fg-danger hover:bg-surface-danger-hover"
          >
            {t('admin.menu.signOut')}
          </button>
        </div>
      )}
    </div>
  );
}
