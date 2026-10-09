/**
 * Where the sheet was opened, which decides the audience: the start and login
 * pages give installation feedback, guest screens carry their session, staff
 * screens carry theirs when they have one.
 */
export type FeedbackOrigin =
  | { kind: 'public' }
  | { kind: 'guest'; sessionId: string }
  | { kind: 'staff'; sessionId: string | null };

/** Who the feedback is about: the installation's start pages, a guest's session, or staff. */
export type FeedbackAudience = 'installation' | 'guest' | 'staff';

/** Whether the answered form was Studio's or the bundled fallback. */
export type FeedbackFormSource = 'studio' | 'bundled';

/** Answers by question id, with what the gateway needs to find the form they answer. */
export interface FeedbackSubmission {
  audience: FeedbackAudience;
  /** Null for installation feedback and for staff feedback outside a session. */
  sessionId: string | null;
  locale: string;
  formSource: FeedbackFormSource;
  /** The content revision of a Studio form; null for the bundled form. */
  revision: string | null;
  /** Answered questions only. */
  answers: Readonly<Record<string, number | string>>;
}
