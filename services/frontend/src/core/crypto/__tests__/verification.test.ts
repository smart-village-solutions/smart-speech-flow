import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { aesKey, openEnvelope, sealEnvelope } from '@/core/crypto/aead';
import { type Bytes, fromBase64Url } from '@/core/crypto/bytes';
import { signedDigest, verifyFields } from '@/core/crypto/signatures';
import { TAGS } from '@/core/crypto/tags';
import {
  decisionImprint,
  noteAad,
  notesDigest,
  verificationFields,
} from '@/core/crypto/verification';

// The gateway generates the same vector (tests/recording_crypto_vectors.py, A.3a).
const vector = JSON.parse(
  readFileSync(
    path.join(
      import.meta.dirname,
      '../../../../../../tests/fixtures/recording/crypto_vectors_v1.json'
    ),
    'utf8'
  )
).verification;

const b = (text: string): Bytes => fromBase64Url(text);
const same = (left: ArrayLike<number>, right: ArrayLike<number>) =>
  expect(Array.from(left)).toEqual(Array.from(right));

interface NoteVector {
  entry_id: string;
  key_id: string;
  plaintext: string;
  nonce: string;
  aad: string;
  envelope: string;
}

const address = (part: 'note' | 'overall', note: NoteVector) => ({
  tenantId: vector.tenant_id,
  conversationId: vector.conversation_id,
  verificationId: vector.verification_id,
  part,
  entryId: note.entry_id,
  keyId: note.key_id,
});

const notes = () =>
  (vector.notes as NoteVector[]).map((note) => ({
    entryId: note.entry_id,
    keyId: note.key_id,
    ciphertext: b(note.envelope),
  }));

const fieldsFor = (digest: Bytes, outcome: string) =>
  verificationFields({
    tenantId: vector.tenant_id,
    verificationId: vector.verification_id,
    conversationId: vector.conversation_id,
    reviewedHead: b(vector.reviewed_head),
    outcome,
    notesDigest: digest,
    snapshot: vector.snapshot,
  });

describe('verification records (A.3a)', () => {
  it('builds the note AAD the gateway builds, and seals and opens notes under it', async () => {
    const key = await aesKey(b(vector.key));
    for (const note of vector.notes as NoteVector[]) {
      const aad = noteAad(address('note', note));
      same(aad, b(note.aad));
      same(await sealEnvelope(key, b(note.plaintext), aad, b(note.nonce)), b(note.envelope));
      same(await openEnvelope(key, b(note.envelope), aad), b(note.plaintext));
    }
    same(noteAad(address('overall', vector.overall)), b(vector.overall.aad));
  });

  it('refuses a note opened under another part', async () => {
    const key = await aesKey(b(vector.key));
    const note = vector.notes[0] as NoteVector;
    await expect(
      openEnvelope(key, b(note.envelope), noteAad(address('overall', note)))
    ).rejects.toThrow();
  });

  it('digests the notes in entry order whatever order they come in', async () => {
    const overall = b(vector.overall.envelope);
    same(await notesDigest(overall, notes()), b(vector.digest));
    same(await notesDigest(overall, [...notes()].reverse()), b(vector.digest));
    same(await notesDigest(null, []), b(vector.empty_digest));
  });

  it('signs the fields the gateway verifies, and a changed outcome fails', async () => {
    const digest = b(vector.digest);
    const fields = fieldsFor(digest, vector.outcome);
    same(await signedDigest(TAGS.verificationSig, fields), b(vector.signed_digest));
    expect(
      await verifyFields(b(vector.signer), b(vector.signature), TAGS.verificationSig, fields)
    ).toBe(true);
    const tampered = fieldsFor(digest, 'approved');
    expect(
      await verifyFields(b(vector.signer), b(vector.signature), TAGS.verificationSig, tampered)
    ).toBe(false);
  });

  it('refuses an unknown outcome and orders the snapshot by code point', () => {
    expect(() => fieldsFor(b(vector.digest), 'maybe')).toThrow();
    const fields = fieldsFor(b(vector.digest), vector.outcome);
    expect(fields.slice(-3)).toEqual([2, 'ssf.recording.review', 'ssf.recording.review.sworn']);
  });

  it('stamps the signed digest and the signature together', async () => {
    same(await decisionImprint(b(vector.signed_digest), b(vector.signature)), b(vector.imprint));
  });
});
