import { useNavigate, useParams } from 'react-router-dom';
import { useFeedback } from '@/app/providers/feedback';
import { guestOrigin } from '@/domain/feedback/feedbackOrigin';
import { useGuestContent } from '@/features/content/useGuestContent';
import { GuestRecording } from '@/features/recording/GuestRecording';
import { useRecordingBand } from '@/features/recording/useRecordingBand';
import { AppHeader } from '@/ui/patterns/AppHeader';
import { ConversationSurface } from './ConversationSurface';
import { useConversationScreen } from './useConversationScreen';

export function ConversationScreen() {
  const { openFeedback } = useFeedback();
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const screen = useConversationScreen(sessionId as string, 'customer');
  const { recording, connection } = screen.state;
  const { content } = useGuestContent(sessionId, screen.customerLanguage ?? undefined);
  const band = useRecordingBand('customer', recording, connection, false, content?.recordingStatus);

  return (
    <ConversationSurface
      screen={screen}
      information={content?.legalInformation}
      contentTop="var(--spacing-content-top)"
      recording={
        <GuestRecording
          sessionId={sessionId as string}
          slice={recording}
          dispatch={screen.dispatch}
          band={band}
          language={screen.customerLanguage}
        />
      }
      recordingBand={band.view !== null}
      header={
        <AppHeader
          onBack={() => void navigate(`/s/${sessionId}/language`)}
          onHome={() => void navigate('/')}
          onFeedback={() => openFeedback(guestOrigin(sessionId))}
        />
      }
    />
  );
}
