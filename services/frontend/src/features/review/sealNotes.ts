import type { ArchiveCrypto } from '@/core/crypto/archive-crypto.port';
import { noteAddress } from '@/core/crypto/verification';
import type { SealedNoteFacts } from '@/domain/archive/archive.types';
import { type Finding, noteJson, overallJson } from '@/domain/review/findings';
import type { ReviewDraft, ReviewOpened } from '@/domain/review/review.types';
import { headEntry } from './openReview';

interface SealInput {
  crypto: ArchiveCrypto;
  tenantId: string;
  review: ReviewOpened;
  keys: ReadonlyMap<string, CryptoKey>;
  findings: ReadonlyMap<string, readonly Finding[]>;
  overall: string;
}

/** Each entry's note under its own key, the overall note under the reviewed head's (A.3a). */
export async function sealNotes(input: Readonly<SealInput>): Promise<ReviewDraft> {
  const { crypto, tenantId, review, keys } = input;
  const { record, opened } = review;
  const scope = {
    tenantId,
    conversationId: opened.conversation.conversationId,
    verificationId: record.verificationId,
  };
  const notes: SealedNoteFacts[] = [];
  for (const [entryId, all] of input.findings) {
    // The reader requires text (A.3a); an empty row left in the editor must not break the record.
    const findings = all.filter((finding) => finding.text.trim() !== '');
    if (findings.length === 0) continue;
    const entry = opened.entries.find((item) => item.entryId === entryId);
    const key = entry ? keys.get(entry.keyId) : undefined;
    if (entry === undefined || key === undefined) continue;
    const at = noteAddress(scope, 'note', entryId, entry.keyId);
    notes.push({
      entryId,
      keyId: entry.keyId,
      ciphertext: await crypto.sealNote(
        key,
        at,
        noteJson(record.verificationId, entryId, findings)
      ),
    });
  }
  const head = headEntry(opened, record);
  const headKey = head ? keys.get(head.keyId) : undefined;
  let overall = null;
  if (input.overall.trim() !== '' && head && headKey) {
    const at = noteAddress(scope, 'overall', head.entryId, head.keyId);
    overall = await crypto.sealNote(headKey, at, overallJson(record.verificationId, input.overall));
  }
  return { overall, notes };
}
