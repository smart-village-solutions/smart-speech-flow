import { describe, expect, it } from 'vitest';
import { buildTimeline } from '@/features/archive/timeline';
import { IDS, loadedFixture, openedConversation } from './archiveFixture';

const keys = () => new Map([[IDS.key, {} as CryptoKey]]);

describe('buildTimeline', () => {
  it('shows messages, failures and consent in order, without playbacks or amendments of their own', () => {
    const view = buildTimeline(openedConversation(), loadedFixture(), keys());
    expect(view.entries.map((e) => [e.entry.entryId, e.state])).toEqual([
      [IDS.consent, 'ok'],
      [IDS.message, 'ok'],
      [IDS.failed, 'ok'],
      [IDS.unstored, 'notStored'],
      [IDS.otherKey, 'noKey'],
    ]);
  });

  it('lists every gap with its time, in order', () => {
    const { gaps } = buildTimeline(openedConversation(), loadedFixture(), keys());
    expect(gaps.map((g) => [g.kind, g.at])).toEqual([
      ['pause', '2026-10-29T10:02:30+00:00'],
      ['failed', '2026-10-29T10:03:00+00:00'],
      ['notStored', '2026-10-29T10:05:00+00:00'],
      ['noKey', '2026-10-29T10:06:00+00:00'],
    ]);
    expect(gaps[0]).toMatchObject({ reason: 'liveness', resumedAt: '2026-10-29T10:02:50+00:00' });
  });

  it('puts playbacks and amendments beside the message they name, a correction beside its amendment’s target', () => {
    const { entries, unattached } = buildTimeline(openedConversation(), loadedFixture(), keys());
    const message = entries[1];
    expect(message.playbacks.map((p) => p.event)).toEqual(['completed']);
    expect(message.amendments.map((a) => [a.entryId, a.superseded, a.foreignAuthor])).toEqual([
      [IDS.amendment, true, false],
      [IDS.correction, false, true],
    ]);
    expect(unattached.map((a) => a.entryId)).toEqual([IDS.stray]);
  });

  it('marks a damaged entry as a gap, and never attaches its content', () => {
    const loaded = loadedFixture();
    loaded.set(IDS.message, 'damaged');
    const { entries, gaps } = buildTimeline(openedConversation(), loaded, keys());
    expect(entries[1]).toMatchObject({ state: 'damaged', record: undefined });
    expect(gaps.map((g) => g.kind)).toContain('damaged');
  });

  it('shows a correction whose amendment cannot be read as unattached, never hides it', () => {
    const loaded = loadedFixture();
    loaded.set(IDS.amendment, 'damaged');
    const { entries, unattached } = buildTimeline(openedConversation(), loaded, keys());
    expect(entries[1].amendments).toEqual([]);
    expect(unattached.map((a) => a.entryId)).toEqual([IDS.correction, IDS.stray]);
  });

  it('reads the guest’s name from the first yes and the languages from the messages', () => {
    const { header } = buildTimeline(openedConversation(), loadedFixture(), keys());
    expect(header).toEqual({
      guestName: 'Amira Haddad',
      enteredBy: 'employee',
      languages: ['ar', 'de'],
    });
  });

  it('opens a window at its first entry and closes it after its last', () => {
    const { entries } = buildTimeline(openedConversation(), loadedFixture(), keys());
    expect(entries[0].opens?.windowId).toBe(IDS.window);
    expect(entries.at(-1)?.closes?.closeReason).toBe('stopped_by_employee');
    expect(entries.slice(1, -1).every((e) => e.opens === undefined && e.closes === undefined)).toBe(
      true
    );
  });
});
