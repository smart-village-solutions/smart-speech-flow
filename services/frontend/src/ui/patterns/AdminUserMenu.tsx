import { useCallback, useState } from 'react';
import type { ReactNode } from 'react';
import { ExternalLink, LogOut, User } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { IconButton } from '@/ui/primitives/IconButton';
import { useDismissOnOutsideTap } from '@/ui/hooks/useDismissOnOutsideTap';

const ROW =
  'flex h-menu-row w-full items-center justify-between px-4 text-note transition-colors duration-150';

interface MenuRowProps {
  label: string;
  onClick: () => void;
  className: string;
  children: ReactNode;
}

function MenuRow({ label, onClick, className, children }: Readonly<MenuRowProps>) {
  return (
    <button type="button" onClick={onClick} className={`${ROW} text-start ${className}`}>
      <span>{label}</span>
      {children}
    </button>
  );
}

interface MenuLinkProps {
  label: string;
  href: string;
  onClick: () => void;
}

/** Leaves SSF in a new tab so a live conversation behind the menu keeps running. */
function MenuLink({ label, href, onClick }: Readonly<MenuLinkProps>) {
  const { t } = useTranslation();

  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      onClick={onClick}
      className={`${ROW} text-fg-body hover:bg-surface-row-hover`}
    >
      <span>
        {label} <span className="sr-only">{t('admin.menu.opensInNewTab')}</span>
      </span>
      <ExternalLink aria-hidden size={16} strokeWidth={2} />
    </a>
  );
}

interface AdminUserMenuProps {
  onSignOut: () => void;
  accountUrl?: string;
  studioUrl?: string;
}

/** Credentials are Keycloak's concern (#396): SSF only links to its account console. */
export function AdminUserMenu({ onSignOut, accountUrl, studioUrl }: Readonly<AdminUserMenuProps>) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  const close = useCallback(() => setOpen(false), []);

  useDismissOnOutsideTap(open, close);

  return (
    <div className="relative" data-dismiss-keep="">
      <IconButton
        label={t('admin.menu.open')}
        onClick={() => (open ? close() : setOpen(true))}
        className={
          open ? 'bg-black/8 !text-black' : 'text-black/50 hover:bg-black/8 hover:text-black'
        }
      >
        <User size={16} strokeWidth={2} />
      </IconButton>

      {open && (
        <div className="absolute end-0 top-11 z-50 w-menu divide-y divide-border-divider overflow-hidden rounded-2xl border border-border-card bg-surface-card shadow-xl">
          {accountUrl && (
            <MenuLink label={t('admin.menu.accountSettings')} href={accountUrl} onClick={close} />
          )}

          {studioUrl && (
            <MenuLink label={t('admin.menu.openStudio')} href={studioUrl} onClick={close} />
          )}

          <MenuRow
            label={t('admin.menu.signOut')}
            onClick={onSignOut}
            className="text-fg-danger hover:bg-surface-danger-hover"
          >
            <LogOut aria-hidden size={16} strokeWidth={2} />
          </MenuRow>
        </div>
      )}
    </div>
  );
}
