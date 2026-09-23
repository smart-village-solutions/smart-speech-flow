import { AppHeader } from './AppHeader';
import { AdminUserMenu } from './AdminUserMenu';

interface AdminHeaderProps {
  onBack: () => void;
  onHome: () => void;
  onFeedback: () => void;
  onSignOut: () => void;
  accountUrl?: string;
  studioUrl?: string;
}

/** The customer header plus the account menu: same 72px bar, same 800px column. */
export function AdminHeader({
  onBack,
  onHome,
  onFeedback,
  onSignOut,
  accountUrl,
  studioUrl,
}: Readonly<AdminHeaderProps>) {
  return (
    <AppHeader
      onBack={onBack}
      onHome={onHome}
      onFeedback={onFeedback}
      trailing={
        <AdminUserMenu onSignOut={onSignOut} accountUrl={accountUrl} studioUrl={studioUrl} />
      }
    />
  );
}
