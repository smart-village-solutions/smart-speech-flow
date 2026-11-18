import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  downloadPassphrase,
  parsePassphraseFile,
  passphraseFileText,
  readPassphraseFile,
} from '../passphrase-file';

const date = new Date('2026-11-18T09:00:00.000Z');

describe('local passphrase backup', () => {
  afterEach(() => vi.restoreAllMocks());

  it('round trips exact Unicode, whitespace and line breaks', () => {
    const passphrase = '  Wörter 🔑\n"quoted"\t ';
    const text = passphraseFileText(passphrase, date);
    expect(text).toContain('SSF recording passphrase backup v1');
    expect(text).toContain(date.toISOString());
    expect(parsePassphraseFile(text)).toBe(passphrase);
  });

  it.each(['plain password', '', 'SSF recording passphrase backup v2\n', 'x'.repeat(16385)])(
    'rejects unsupported or oversized files',
    (text) => {
      expect(() => parsePassphraseFile(text)).toThrow();
    }
  );

  it('rejects a malformed body and invalid metadata', () => {
    expect(() =>
      parsePassphraseFile(passphraseFileText('secret', date).replace('"secret"', '123'))
    ).toThrow();
    expect(() =>
      parsePassphraseFile(
        passphraseFileText('secret', date).replace(date.toISOString(), 'yesterday')
      )
    ).toThrow();
  });

  it('reads a local file and rejects an oversized file before reading it', async () => {
    await expect(
      readPassphraseFile(new File([passphraseFileText('local secret', date)], 'backup.txt'))
    ).resolves.toBe('local secret');
    await expect(readPassphraseFile(new File(['x'.repeat(16385)], 'large.txt'))).rejects.toThrow();
  });

  it('downloads only on request and revokes its temporary URL', () => {
    vi.useFakeTimers();
    const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:backup');
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    try {
      expect(click).not.toHaveBeenCalled();
      downloadPassphrase('secret', date);
      expect(create).toHaveBeenCalledWith(expect.any(Blob));
      expect(click).toHaveBeenCalledOnce();
      vi.runAllTimers();
      expect(revoke).toHaveBeenCalledWith('blob:backup');
      expect(document.querySelector('a[download]')).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
