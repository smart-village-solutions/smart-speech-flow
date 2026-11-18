import { useEffect, useState, useSyncExternalStore } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';
import {
  getAccountConsoleUrl,
  getAdminIdentity,
  hasPermission,
  subscribeToKeycloakAuthorization,
} from '@/app/auth/keycloak';
import { useServices } from '@/app/providers/services';
import { AdminDashboardScreen } from '@/features/admin/AdminDashboardScreen';
import { AdminSessionScreen } from '@/features/admin/AdminSessionScreen';
import { KeysScreen } from '@/features/keys/KeysScreen';
import { INBOX_QUERY, REVIEW_PERMISSION } from '@/features/review/useReviews';
import { initialFilters, OVERVIEW } from './filterRows';
import { actionStyle } from './TaskTable';
import { ConversationTable, ReviewTable, type TaskTarget } from './TaskLists';
import { MetadataDetail, ProtectedDetail } from './TaskDetail';

const filters = z.object({
  language: z.string().max(64),
  status: z.string().max(64),
  order: z.enum(['newest', 'oldest']),
});
const remembered = z.object({
  owner: z.string(),
  tab: z.enum(['conversations', 'reviews']),
  account: z.boolean(),
  target: z
    .object({
      kind: z.enum(['review', 'recording', 'session', 'result', 'details']),
      id: z.string().min(1).max(256),
    })
    .refine(({ kind, id }) => {
      if (kind === 'session') return /^[A-Z0-9]{8}$/.test(id);
      if (kind === 'details') return /^[a-zA-Z0-9_-]+$/.test(id);
      return z.uuid().safeParse(id).success;
    })
    .nullable(),
  conversations: filters,
  reviews: filters,
});
function restore(raw: string | null, owner: string) {
  try {
    const state = remembered.safeParse(JSON.parse(raw ?? 'null'));
    if (state.success && state.data.owner === owner) return state.data;
  } catch {
    /* Unrecognised or obsolete redirect reference. */
  }
  return {
    owner,
    tab: 'conversations' as const,
    account: raw === 'keys',
    target: null,
    conversations: initialFilters,
    reviews: initialFilters,
  };
}

export function TaskWorkspace({
  onSignOut,
  studioUrl,
  onLocationChange,
}: Readonly<{
  onSignOut: () => void;
  studioUrl?: string;
  onLocationChange?: (location: string) => void;
}>) {
  const { resume } = useServices();
  const { t } = useTranslation();
  const client = useQueryClient();
  const owner = JSON.stringify(getAdminIdentity());
  const [start] = useState(() => restore(owner === 'null' ? null : resume.take(), owner));
  const [target, setTarget] = useState<TaskTarget | null>(start.target);
  const [account, setAccount] = useState(start.account);
  const [tab, setTab] = useState<'reviews' | 'conversations'>(start.tab);
  const [conversations, setConversations] = useState(start.conversations);
  const [reviews, setReviews] = useState(start.reviews);
  const canReview = useSyncExternalStore(subscribeToKeycloakAuthorization, () =>
    hasPermission(REVIEW_PERMISSION)
  );
  const reviewTarget = target?.kind === 'review' || target?.kind === 'result';
  const [previousPermission, setPreviousPermission] = useState<boolean | null>(null);
  if (previousPermission !== canReview) {
    setPreviousPermission(canReview);
    if (!canReview) {
      setTab('conversations');
      setReviews(initialFilters);
      if (reviewTarget) setTarget(null);
    }
  }
  useEffect(() => {
    if (canReview) return;
    client.removeQueries({ queryKey: ['reviews'] });
    client.removeQueries({ queryKey: ['dashboard', 'access', 'review'] });
  }, [canReview, client]);
  const showReviews = canReview && tab === 'reviews';
  const allowed = reviewTarget && !canReview ? null : target;
  const back = () => {
    setTarget(null);
    setAccount(false);
  };
  const done = () => {
    void client.invalidateQueries({ queryKey: INBOX_QUERY });
    void client.invalidateQueries({ queryKey: OVERVIEW });
    back();
  };
  const nav = {
    onBack: back,
    onOpenKeys: () => setAccount(true),
    onSignOut,
    studioUrl,
    accountUrl: getAccountConsoleUrl() ?? undefined,
  };
  const view = () => {
    const accountScreen = account ? <KeysScreen {...nav} onBack={() => setAccount(false)} /> : null;
    if (allowed?.kind === 'session') {
      // The mounted session owns the socket, microphone and unsent draft.
      return (
        <>
          <div hidden={account} inert={account}>
            <AdminSessionScreen key={allowed.id} {...nav} sessionId={allowed.id} onLeave={done} />
          </div>
          {accountScreen}
        </>
      );
    }
    if (accountScreen) return accountScreen;
    if (allowed) {
      switch (allowed.kind) {
        case 'recording':
        case 'review':
          return <ProtectedDetail key={allowed.id} target={allowed} {...nav} onDone={done} />;
        default:
          return <MetadataDetail key={allowed.id} target={allowed} {...nav} />;
      }
    }
    return (
      <AdminDashboardScreen
        {...nav}
        onEnterSession={(id) => setTarget({ kind: 'session', id })}
        conversationView={!showReviews}
        navigation={
          canReview && (
            <nav aria-label={t('admin.tasks.views')} className="flex flex-wrap gap-2">
              {(['conversations', 'reviews'] as const).map((key) => (
                <button
                  key={key}
                  className={actionStyle}
                  aria-pressed={tab === key}
                  onClick={() => setTab(key)}
                >
                  {t(`admin.tasks.${key}`)}
                </button>
              ))}
            </nav>
          )
        }
      >
        {showReviews ? (
          <ReviewTable filters={reviews} onChange={setReviews} open={setTarget} />
        ) : (
          <ConversationTable filters={conversations} onChange={setConversations} open={setTarget} />
        )}
      </AdminDashboardScreen>
    );
  };
  useEffect(() => {
    if (owner !== 'null') {
      onLocationChange?.(
        JSON.stringify({ owner, tab, account, target: allowed, conversations, reviews })
      );
    }
  }, [onLocationChange, owner, tab, account, allowed, conversations, reviews]);
  return view();
}
