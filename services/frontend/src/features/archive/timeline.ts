import type {
  ArchivedEntry,
  OpenedConversation,
  WindowFacts,
} from '@/domain/archive/archive.types';
import type { AmendmentRecord, ConsentRecord, ParsedRecord, PlaybackRecord } from './records';

export type GapKind = 'pause' | 'failed' | 'notStored' | 'noKey' | 'damaged';

export interface Gap {
  at: string;
  kind: GapKind;
  reason?: string;
  resumedAt?: string | null;
}

export type EntryState = 'ok' | 'noKey' | 'notStored' | 'damaged';

export interface AmendmentView {
  entryId: string;
  createdAt: string;
  record: AmendmentRecord;
  /** A later amendment references this one. */
  superseded: boolean;
  /** Written by someone other than the conversation's employee. */
  foreignAuthor: boolean;
}

export interface EntryView {
  entry: ArchivedEntry;
  state: EntryState;
  record?: ParsedRecord;
  amendments: AmendmentView[];
  playbacks: PlaybackRecord[];
  opens?: WindowFacts;
  closes?: WindowFacts;
}

export interface HeaderView {
  guestName: string | null;
  enteredBy: string | null;
  languages: string[];
}

export interface Timeline {
  entries: EntryView[];
  gaps: Gap[];
  unattached: AmendmentView[];
  header: HeaderView;
}

/** A decrypted record, or why there is none. */
export type Loaded = ParsedRecord | 'damaged' | 'notStored';

const byTime = (left: Gap, right: Gap) => left.at.localeCompare(right.at);

function stateOf(
  entry: ArchivedEntry,
  keys: ReadonlyMap<string, CryptoKey>,
  loaded: Loaded | undefined
): EntryState {
  if (!keys.has(entry.keyId)) return 'noKey';
  if (loaded === 'notStored') return 'notStored';
  if (loaded === undefined || loaded === 'damaged') return 'damaged';
  return 'ok';
}

function amendmentRecord(view: EntryView): AmendmentRecord | null {
  return view.record?.kind === 'amendment' ? view.record.record : null;
}

function amendmentsOf(views: readonly EntryView[], employeeSub: string): AmendmentView[] {
  const records = views.flatMap((view) => {
    const record = amendmentRecord(view);
    return record === null ? [] : [{ view, record }];
  });
  const referenced = new Set(records.flatMap(({ record }) => record.references));
  return records.map(({ view, record }) => ({
    entryId: view.entry.entryId,
    createdAt: view.entry.createdAt,
    record,
    superseded: referenced.has(view.entry.entryId),
    foreignAuthor: record.author_sub !== employeeSub,
  }));
}

/** Playbacks and amendments are drawn beside other entries, never as cards of their own. */
function isShown(view: EntryView): boolean {
  return view.entry.kind !== 'playback' && view.entry.kind !== 'amendment';
}

/**
 * An amendment of an amendment belongs beside what the first one named (§10.6,
 * "versioned"); one that names nothing shown, or an amendment it cannot read, is unattached.
 */
function targetsOf(
  references: readonly string[],
  byId: ReadonlyMap<string, EntryView>,
  seen: Set<string> = new Set()
): EntryView[] {
  return references.flatMap((id) => {
    const target = byId.get(id);
    if (target === undefined || seen.has(id)) return [];
    seen.add(id);
    const nested = amendmentRecord(target);
    if (nested !== null) return targetsOf(nested.references, byId, seen);
    return isShown(target) ? [target] : [];
  });
}

function attach(
  views: readonly EntryView[],
  amendments: readonly AmendmentView[]
): AmendmentView[] {
  const byId = new Map(views.map((view) => [view.entry.entryId, view]));
  const unattached: AmendmentView[] = [];
  for (const amendment of amendments) {
    const targets = targetsOf(amendment.record.references, byId);
    if (targets.length === 0) unattached.push(amendment);
    for (const target of new Set(targets)) target.amendments.push(amendment);
  }
  for (const view of views) {
    if (view.record?.kind === 'playback')
      byId.get(view.record.record.message_entry_id)?.playbacks.push(view.record.record);
  }
  return unattached;
}

function firstYes(views: readonly EntryView[]): ConsentRecord | undefined {
  return views
    .map((view) => (view.record?.kind === 'consent' ? view.record.record : null))
    .find((record): record is ConsentRecord => record?.answer === 'yes');
}

function languages(views: readonly EntryView[]): string[] {
  const found = new Set<string>();
  for (const view of views) {
    const record = view.record;
    if (record?.kind !== 'message' && record?.kind !== 'failed') continue;
    found.add(record.record.source_lang);
    found.add(record.record.target_lang);
  }
  return [...found].sort((left, right) => left.localeCompare(right));
}

function header(views: readonly EntryView[]): HeaderView {
  const guest = firstYes(views)?.guest;
  return {
    guestName: guest?.name ?? null,
    enteredBy: guest?.entered_by ?? null,
    languages: languages(views),
  };
}

function gaps(opened: Readonly<OpenedConversation>, views: readonly EntryView[]): Gap[] {
  const list: Gap[] = opened.windows.flatMap((window) =>
    window.pauses.map((pause) => ({
      at: pause.at,
      kind: 'pause' as const,
      reason: pause.reason,
      resumedAt: pause.resumedAt,
    }))
  );
  for (const view of views) {
    if (view.entry.kind === 'failed') list.push({ at: view.entry.createdAt, kind: 'failed' });
    if (view.state !== 'ok') list.push({ at: view.entry.createdAt, kind: view.state });
  }
  return list.sort(byTime);
}

function markWindows(shown: readonly EntryView[], windows: readonly WindowFacts[]): void {
  for (const window of windows) {
    const inside = shown.filter((view) => view.entry.windowId === window.windowId);
    if (inside.length === 0) continue;
    inside[0].opens = window;
    if (window.closedAt !== null) (inside.at(-1) as EntryView).closes = window;
  }
}

/** The viewer's model: entries in seq order, amendments and playbacks beside what they name (§10.6). */
export function buildTimeline(
  opened: Readonly<OpenedConversation>,
  loaded: ReadonlyMap<string, Loaded>,
  keys: ReadonlyMap<string, CryptoKey>
): Timeline {
  const views: EntryView[] = opened.entries.map((entry) => {
    const record = loaded.get(entry.entryId);
    const state = stateOf(entry, keys, record);
    return {
      entry,
      state,
      record: state === 'ok' ? (record as ParsedRecord) : undefined,
      amendments: [],
      playbacks: [],
    };
  });
  const unattached = attach(views, amendmentsOf(views, opened.conversation.employeeSub));
  const shown = views.filter(
    (view) => view.entry.kind !== 'playback' && view.entry.kind !== 'amendment'
  );
  markWindows(shown, opened.windows);
  return { entries: shown, gaps: gaps(opened, views), unattached, header: header(views) };
}
