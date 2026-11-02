import { AppHeader } from './AppHeader';
import { AdminUserMenu, type AdminUserMenuProps } from './AdminUserMenu';

interface AdminHeaderProps extends AdminUserMenuProps {
  onBack: () => void;
  onHome: () => void;
  onFeedback: () => void;
}

/** The customer header plus the account menu: same 72px bar, same 800px column. */
export function AdminHeader({ onBack, onHome, onFeedback, ...menu }: Readonly<AdminHeaderProps>) {
  return (
    <AppHeader
      onBack={onBack}
      onHome={onHome}
      onFeedback={onFeedback}
      trailing={<AdminUserMenu {...menu} />}
    />
  );
}
