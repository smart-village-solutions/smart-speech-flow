import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useFeedback } from '@/app/providers/feedback';
import { ConversationSurface } from '@/features/conversation/ConversationSurface';
import { useConversationScreen } from '@/features/conversation/useConversationScreen';
// The languages query is a hook over a domain repository, not UI. Duplicating
// it in this feature would be worse than importing it across the boundary.
import { useLanguages } from '@/features/language-select/useLanguages';
import { AdminHeader } from '@/ui/patterns/AdminHeader';
import { SessionStatusOverlay } from './SessionStatusOverlay';
import { TerminateLink } from './TerminateLink';

interface AdminSessionScreenProps {
  sessionId: string;
  onLeave: () => void;
  onSignOut: () => void;
}

/**
 * The customer conversation, conducted from the other end. Everything below the
 * header is the shared surface; the three admin-only pieces arrive as slots.
 *
 * No `useScreenLocale` here: `useSessionLanguages` already pins the admin screen
 * to German, which is also what keeps its copy in the two catalogues it has.
 */
export function AdminSessionScreen({
  sessionId,
  onLeave,
  onSignOut,
}: Readonly<AdminSessionScreenProps>) {
  const { t } = useTranslation();
  const { openFeedback } = useFeedback();
  const navigate = useNavigate();
  const screen = useConversationScreen(sessionId, 'admin');
  const { data: languages = [] } = useLanguages();

  const language = languages.find((entry) => entry.code === screen.customerLanguage) ?? null;

  const footer = screen.state.ended ? (
    <button
      type="button"
      onClick={onLeave}
      className="text-label text-fg-link underline underline-offset-2 transition-colors duration-150 hover:text-fg-link-hover"
    >
      {t('admin.session.backToDashboard')}
    </button>
  ) : (
    <TerminateLink sessionId={sessionId} onTerminated={onLeave} />
  );

  return (
    <ConversationSurface
      screen={screen}
      contentTop="var(--spacing-admin-content)"
      header={
        <AdminHeader
          onBack={onLeave}
          onHome={() => void navigate('/')}
          onFeedback={openFeedback}
          onSignOut={onSignOut}
        />
      }
      overlay={
        <SessionStatusOverlay
          sessionId={sessionId}
          connection={screen.state.connection}
          language={language}
        />
      }
      footer={footer}
    />
  );
}
