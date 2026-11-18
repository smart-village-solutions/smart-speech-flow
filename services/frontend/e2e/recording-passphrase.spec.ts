import { readFile } from 'node:fs/promises';
import { expect, test } from '@playwright/test';

const moduleUrl = '/src/features/keys/passphrase-file.ts';
const passphrase = '  Wörter 🔑\n"quoted"\t ';

test('downloads an explicit local TXT backup and imports it without changing the passphrase', async ({
  page,
}) => {
  await page.goto('/design-system.html');
  const downloadEvent = page.waitForEvent('download');
  await page.evaluate(
    async ({ url, secret }) => {
      const { downloadPassphrase } = await import(url);
      downloadPassphrase(secret, new Date('2026-11-18T09:00:00Z'));
    },
    { url: moduleUrl, secret: passphrase }
  );
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe('ssf-passphrase-2026-11-18.txt');
  const path = await download.path();
  expect(path).not.toBeNull();
  const text = await readFile(path!, 'utf8');
  const restored = await page.evaluate(
    async ({ url, text }) => {
      const { readPassphraseFile } = await import(url);
      return readPassphraseFile(new File([text], 'backup.txt', { type: 'text/plain' }));
    },
    { url: moduleUrl, text }
  );
  expect(restored).toBe(passphrase);
});

test('rejects malformed and oversized local files in the browser', async ({ page }) => {
  await page.goto('/design-system.html');
  const accepted = await page.evaluate(async (url) => {
    const { readPassphraseFile } = await import(url);
    return Promise.all(
      ['wrong format', 'x'.repeat(16385)].map(async (text) => {
        try {
          await readPassphraseFile(new File([text], 'backup.txt'));
          return true;
        } catch {
          return false;
        }
      })
    );
  }, moduleUrl);
  expect(accepted).toEqual([false, false]);
});
