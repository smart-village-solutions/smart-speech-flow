import { utf8 } from '@/core/crypto/bytes';
import type { ArchivedEntry, OpenedConversation } from '@/domain/archive/archive.types';
import { parseRecord } from '@/features/archive/records';
import type { Loaded } from '@/features/archive/timeline';

/** One recorded conversation, as the gateway would serve it; signatures are not checked here. */
export const IDS = {
  conversation: '6f1c1d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f',
  window: '2c3d4e5f-6a7b-4c8d-9e0f-1a2b3c4d5e6f',
  key: '9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d',
  unwrappedKey: '0b1c2d3e-4f5a-4b6c-8d7e-9f0a1b2c3d4e',
  consent: '10000000-0000-4000-8000-000000000001',
  message: '10000000-0000-4000-8000-000000000002',
  failed: '10000000-0000-4000-8000-000000000003',
  playback: '10000000-0000-4000-8000-000000000004',
  amendment: '10000000-0000-4000-8000-000000000005',
  correction: '10000000-0000-4000-8000-000000000006',
  unstored: '10000000-0000-4000-8000-000000000007',
  otherKey: '10000000-0000-4000-8000-000000000008',
  stray: '10000000-0000-4000-8000-000000000009',
};

export function messageJson(extra: Record<string, unknown> = {}) {
  return {
    v: 1,
    message_id: 'm1',
    sender: 'customer',
    input: 'audio',
    source_lang: 'ar',
    target_lang: 'de',
    accepted_at: '2026-10-29T10:01:00.000000+00:00',
    completed_at: '2026-10-29T10:01:03.000000+00:00',
    source_text: 'مرحبا',
    raw_translation: 'Hallo',
    final_text: 'Hallo!',
    steps: [{ name: 'refinement', status: 'success', changed: true, output: 'Hallo!' }],
    hashes: {
      original_audio_sha256: 'a'.repeat(64),
      asr_input_sha256: null,
      translated_audio_sha256: 'b'.repeat(64),
    },
    ...extra,
  };
}

export function consentJson(answer: 'yes' | 'no' = 'yes') {
  return {
    v: 1,
    request_id: 'r1',
    kind: 'first',
    requested_by: 'alice',
    requested_at: '2026-10-29T10:00:00.000000+00:00',
    answered_at: '2026-10-29T10:00:30.000000+00:00',
    answer,
    window_id: IDS.window,
    legal_basis: 'consent',
    guest: { name: 'Amira Haddad', entered_by: 'employee' },
    id_check: { policy: 'optional', checked: true, at: '2026-10-29T09:59:00+00:00' },
    text: {
      language: 'ar',
      kind: 'first',
      source: 'bundled',
      version: 'bundled-1',
      sha256: 'c'.repeat(64),
      html: '<p>Text</p>',
    },
  };
}

export function playbackJson(messageEntryId: string) {
  return {
    v: 1,
    message_id: 'm1',
    message_entry_id: messageEntryId,
    event: 'completed',
    reported_by: 'admin',
    at: '2026-10-29T10:01:09.000000+00:00',
  };
}

export function amendmentJson(references: string[], text = 'Name korrigiert', author = 'alice') {
  return { v: 1, references, text, author_sub: author, written_at: '2026-10-30T09:00:00.000Z' };
}

function entry(
  seq: number,
  entryId: string,
  kind: string,
  objects: string[],
  extra: Partial<ArchivedEntry> = {}
): ArchivedEntry {
  const listed = objects.map((type) => ({
    key: `${IDS.conversation}/${entryId}/${type}`,
    sha256: '0'.repeat(64),
    size: 10,
    type,
  }));
  return {
    seq,
    entryId,
    kind,
    windowId: kind === 'amendment' ? null : IDS.window,
    keyId: IDS.key,
    objects: JSON.stringify(listed),
    prevHash: new Uint8Array(32),
    hash: new Uint8Array(32).fill(seq),
    signerKeyId: 'gk-1',
    signature: new Uint8Array(64),
    createdAt: `2026-10-29T10:0${seq}:00+00:00`,
    storedTypes: objects,
    ...extra,
  };
}

export function openedConversation(): OpenedConversation {
  return {
    conversation: {
      conversationId: IDS.conversation,
      employeeSub: 'alice',
      legalBasis: 'consent',
      startedAt: '2026-10-29T10:00:00+00:00',
      endedAt: '2026-10-29T10:20:00+00:00',
      retentionUntil: '2027-10-29T10:00:00+00:00',
      legalHold: false,
      incomplete: true,
      verification: 'not_verified',
    },
    windows: [
      {
        windowId: IDS.window,
        openedAt: '2026-10-29T10:00:30+00:00',
        closedAt: '2026-10-29T10:19:00+00:00',
        closeReason: 'stopped_by_employee',
        pauses: [
          {
            at: '2026-10-29T10:02:30+00:00',
            reason: 'liveness',
            resumedAt: '2026-10-29T10:02:50+00:00',
          },
        ],
      },
    ],
    entries: [
      entry(1, IDS.consent, 'consent', ['consent.json']),
      entry(2, IDS.message, 'message', ['original.wav', 'record.json', 'translated.wav']),
      entry(3, IDS.failed, 'failed', ['original.wav', 'record.json']),
      entry(4, IDS.playback, 'playback', ['playback.json']),
      entry(5, IDS.unstored, 'message', ['record.json'], { storedTypes: [] }),
      entry(6, IDS.otherKey, 'message', ['record.json'], { keyId: IDS.unwrappedKey }),
      entry(7, IDS.amendment, 'amendment', ['amendment.json']),
      entry(8, IDS.correction, 'amendment', ['amendment.json']),
      entry(9, IDS.stray, 'amendment', ['amendment.json']),
    ],
    stamps: [{ headSeq: 9, headHash: new Uint8Array(32).fill(9), token: null }],
    keys: [
      {
        keyId: IDS.key,
        epoch: 1,
        recoveryWrapped: true,
        wrap: { blob: '{}', creatorRef: 'gk-1', creatorSignature: new Uint8Array(64) },
      },
      { keyId: IDS.unwrappedKey, epoch: 2, recoveryWrapped: true, wrap: null },
    ],
  };
}

const parsed = (kind: string, value: unknown) => parseRecord(kind, utf8(JSON.stringify(value)));

/** What the viewer loads for the fixture: one entry unstored, one under a key without a wrap. */
export function loadedFixture(): Map<string, Loaded> {
  return new Map<string, Loaded>([
    [IDS.consent, parsed('consent', consentJson())],
    [IDS.message, parsed('message', messageJson())],
    [
      IDS.failed,
      parsed(
        'failed',
        messageJson({
          source_text: 'شكرا',
          raw_translation: null,
          final_text: null,
          error: { stage: 'translation', code: 'MT_DOWN', message: null },
        })
      ),
    ],
    [IDS.playback, parsed('playback', playbackJson(IDS.message))],
    [IDS.unstored, 'notStored'],
    [IDS.amendment, parsed('amendment', amendmentJson([IDS.message]))],
    [IDS.correction, parsed('amendment', amendmentJson([IDS.amendment], 'Korrektur', 'bob'))],
    [IDS.stray, parsed('amendment', amendmentJson(['20000000-0000-4000-8000-000000000000']))],
  ]);
}
