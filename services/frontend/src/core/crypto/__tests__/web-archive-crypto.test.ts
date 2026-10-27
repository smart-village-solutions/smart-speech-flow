import { describe, expect, it } from 'vitest';
import { fingerprint } from '@/core/crypto/transcript';
import { createWebArchiveCrypto } from '@/core/crypto/web-archive-crypto';

const owner = { tenantId: 'tenant-kassel', userSub: 'alice' };
const PASSPHRASE = 'Kanne Wolke Ferne Tisch 42';

// Real Argon2id at the enrolment cost: slow by design.
describe('web archive crypto', { timeout: 30_000 }, () => {
  it('creates keys that unlock again, non-extractable, with the right fingerprint', async () => {
    const archive = createWebArchiveCrypto();
    const created = await archive.createKeys(PASSPHRASE, owner);
    expect(created.unlocked.encPrivate.extractable).toBe(false);
    expect(created.unlocked.sigPrivate.extractable).toBe(false);

    const unlocked = await archive.unlock(created.blob, PASSPHRASE, owner, created.unlocked);
    expect(unlocked.encPrivate.extractable).toBe(false);
    const expected = await fingerprint(owner.tenantId, owner.userSub, created.unlocked.encPub, created.unlocked.sigPub);
    expect(Array.from(unlocked.fingerprint)).toEqual(Array.from(expected));
  });

  it('refuses a wrong passphrase, another owner, and keys that do not match the blob', async () => {
    const archive = createWebArchiveCrypto();
    const created = await archive.createKeys(PASSPHRASE, owner);
    const other = await archive.createKeys(PASSPHRASE, owner);
    await expect(archive.unlock(created.blob, 'wrong passphrase', owner, created.unlocked)).rejects.toThrow();
    await expect(
      archive.unlock(created.blob, PASSPHRASE, { ...owner, userSub: 'bob' }, created.unlocked)
    ).rejects.toThrow();
    await expect(archive.unlock(created.blob, PASSPHRASE, owner, other.unlocked)).rejects.toThrow();
  });
});
