import { useNavigate, useParams } from 'react-router-dom';
import { useFeedback } from '@/app/providers/feedback';
import { AppHeader } from '@/ui/patterns/AppHeader';
import { ConversationSurface } from './ConversationSurface';
import { useConversationScreen } from './useConversationScreen';

export function ConversationScreen() {
  const { openFeedback } = useFeedback();
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const screen = useConversationScreen(sessionId as string, 'customer');

  return (
    <ConversationSurface
      screen={screen}
      contentTop="var(--spacing-header)"
      header={
        <AppHeader
          onBack={() => void navigate(`/s/${sessionId}/language`)}
          onHome={() => void navigate('/')}
          onFeedback={openFeedback}
        />
      }
    />
  );
}
