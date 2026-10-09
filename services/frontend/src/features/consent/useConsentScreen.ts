import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useScreenLocale } from '@/app/providers/locale';
import { useServices } from '@/app/providers/services';
import { mergeActivatedSession } from '@/domain/session/session.mapper';
import type { Session } from '@/domain/session/session.types';
import { languageChoice } from '@/features/content/guestLanguage';
import { useGuestLanguages } from '@/features/content/useGuestLanguages';
import { useConsentContent } from './useConsentContent';

export function useConsentScreen() {
  const { sessionId, languageCode } = useParams<{ sessionId: string; languageCode: string }>();
  const navigate = useNavigate();
  const { session } = useServices();
  const queryClient = useQueryClient();
  const languages = useGuestLanguages(sessionId);
  const { ready, copy } = useConsentContent(sessionId, languageCode);
  const [agreed, setAgreed] = useState(false);

  useScreenLocale(languageCode ?? '');

  const entry = languages.data?.find((candidate) => candidate.code === languageCode);

  const start = useMutation({
    // The answer travels on the activation request itself. A separate call to
    // the same endpoint would activate the session twice, and the second,
    // consent-less one would resolve to declined. Without a live `ask` there
    // is no question, so the answer is no.
    mutationFn: async () =>
      session.activate(sessionId as string, languageCode as string, copy.asksStorage && agreed),
    // The route guard cached this session before activation, when the customer
    // had no language yet. Publishing the activated one keeps the conversation
    // screen from opening on the stale entry and sending its first message
    // under the wrong source language, which the gateway rejects.
    onSuccess: (activated) => {
      queryClient.setQueryData<Session>(['session', sessionId], (previous) =>
        mergeActivatedSession(activated, previous)
      );
      void navigate(`/s/${sessionId}/live`);
    },
  });

  return {
    sessionId,
    language: entry && languageChoice(entry),
    ready,
    copy,
    agreed,
    setAgreed,
    start,
    goBack: () => void navigate(`/s/${sessionId}/language`),
    goHome: () => void navigate('/'),
  };
}
