import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useFeedback } from '@/app/providers/feedback';
import { ConversationSurface } from '@/features/conversation/ConversationSurface';
import { useConversationScreen } from '@/features/conversation/useConversationScreen';
import { useStaffContent } from '@/features/content/useStaffContent';
import { RecordingIndicator } from '@/features/recording/RecordingIndicator';
import { RecordingRequestDialog } from '@/features/recording/RecordingRequestDialog';
import { useAdminRecording } from '@/features/recording/useAdminRecording';
import { usePlaybackReports } from '@/features/recording/usePlaybackReports';
import { useRecordingBand } from '@/features/recording/useRecordingBand';
import { AdminHeader } from '@/ui/patterns/AdminHeader';
import { SessionStatusOverlay } from './SessionStatusOverlay';
import { TerminateLink } from './TerminateLink';
import { useStaffLocalisation } from './useStaffLocalisation';

interface AdminSessionScreenProps {
  sessionId: string;
  onLeave: () => void;
  onSignOut: () => void;
  accountUrl?: string;
  studioUrl?: string;
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
  accountUrl,
  studioUrl,
}: Readonly<AdminSessionScreenProps>) {
  const { t } = useTranslation();
  const { openFeedback } = useFeedback();
  const navigate = useNavigate();
  const screen = useConversationScreen(sessionId, 'admin');
  const { languageOf } = useStaffLocalisation();
  const { recording, connection } = screen.state;
  const admin = useAdminRecording(sessionId, recording, screen.dispatch);
  const { content } = useStaffContent();
  const band = useRecordingBand(
    'admin',
    recording,
    connection,
    admin.canRequest,
    content?.recordingStatus
  );
  usePlaybackReports(sessionId, 'admin', band.view?.variant === 'live');

  // A code SSF does not list would read as "Sprache offen", i.e. not yet chosen.
  const chosen = languageOf(screen.customerLanguage);
  const language = chosen.bundled === null ? null : chosen;

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
      information={content?.legalInformation}
      contentTop="var(--spacing-content-top)"
      recording={
        <>
          <RecordingIndicator band={band} onAction={admin.onAction} />
          {admin.firstRequest.open && (
            <RecordingRequestDialog
              kind={admin.firstRequest.kind}
              staffRelease={admin.firstRequest.staffRelease}
              idCheck={admin.firstRequest.idCheck}
              error={admin.firstRequest.error}
              sending={admin.firstRequest.sending}
              onSubmit={(ask) => void admin.firstRequest.submit(ask)}
              onCancel={admin.firstRequest.hide}
            />
          )}
        </>
      }
      recordingBand={band.view !== null}
      header={
        <AdminHeader
          onBack={onLeave}
          onHome={() => void navigate('/')}
          onFeedback={() => openFeedback({ kind: 'staff', sessionId })}
          onSignOut={onSignOut}
          accountUrl={accountUrl}
          studioUrl={studioUrl}
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
