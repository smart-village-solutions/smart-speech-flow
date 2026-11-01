import { describe, expect, it } from 'vitest';
import { utf8 } from '@/core/crypto/bytes';
import { newAmendment, parseRecord } from '@/features/archive/records';
import { amendmentJson, consentJson, messageJson, playbackJson } from './archiveFixture';

const REF = '1c2d3e4f-5a6b-4c7d-8e9f-a0b1c2d3e4f5';
const bytes = (value: unknown) => utf8(JSON.stringify(value));

describe('archived records', () => {
  it('reads every kind the gateway writes', () => {
    expect(parseRecord('message', bytes(messageJson())).kind).toBe('message');
    expect(
      parseRecord(
        'failed',
        bytes(messageJson({ error: { stage: 'asr', code: 'X', message: null } }))
      ).kind
    ).toBe('failed');
    expect(parseRecord('consent', bytes(consentJson())).kind).toBe('consent');
    expect(parseRecord('playback', bytes(playbackJson(REF))).kind).toBe('playback');
    expect(parseRecord('amendment', bytes(amendmentJson([REF]))).kind).toBe('amendment');
  });

  it('refuses another version, kind or shape, and bytes that are not UTF-8', () => {
    expect(() => parseRecord('message', bytes({ ...messageJson(), v: 2 }))).toThrow();
    expect(() => parseRecord('window', bytes(messageJson()))).toThrow();
    expect(() => parseRecord('playback', bytes({ v: 1 }))).toThrow();
    expect(() => parseRecord('message', new Uint8Array([0xff, 0xfe]))).toThrow();
  });

  it('bounds an amendment’s references and text', () => {
    expect(() => parseRecord('amendment', bytes(amendmentJson([])))).toThrow();
    expect(() =>
      parseRecord('amendment', bytes(amendmentJson(Array.from({ length: 21 }, () => REF))))
    ).toThrow();
    expect(() => parseRecord('amendment', bytes(amendmentJson([REF], 'x'.repeat(4001))))).toThrow();
  });

  it('writes an amendment the viewer reads back', () => {
    const written = newAmendment(
      [REF],
      'Name korrigiert',
      'alice',
      new Date('2026-10-29T12:00:00Z')
    );
    expect(parseRecord('amendment', written)).toEqual({
      kind: 'amendment',
      record: {
        v: 1,
        references: [REF],
        text: 'Name korrigiert',
        author_sub: 'alice',
        written_at: '2026-10-29T12:00:00.000Z',
      },
    });
    expect(() => newAmendment([REF], '', 'alice', new Date())).toThrow();
  });
});
