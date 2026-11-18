/** A local plaintext backup, never an upload or a backup of the private keys. */
const HEADER = 'SSF recording passphrase backup v1\n';
const MAX_FILE_BYTES = 16 * 1024;

function invalidFile(): Error {
  return new Error('Invalid passphrase backup');
}

export function passphraseFileText(passphrase: string, createdAt = new Date()): string {
  const text =
    HEADER + JSON.stringify({ createdAt: createdAt.toISOString(), passphrase }, null, 2) + '\n';
  if (!passphrase || new TextEncoder().encode(text).length > MAX_FILE_BYTES) throw invalidFile();
  return text;
}

export function parsePassphraseFile(text: string): string {
  if (new TextEncoder().encode(text).length > MAX_FILE_BYTES || !text.startsWith(HEADER))
    throw invalidFile();
  let body: unknown;
  try {
    body = JSON.parse(text.slice(HEADER.length));
  } catch {
    throw invalidFile();
  }
  if (typeof body !== 'object' || body === null) throw invalidFile();
  const { createdAt, passphrase } = body as Record<string, unknown>;
  if (
    typeof createdAt !== 'string' ||
    !Number.isFinite(Date.parse(createdAt)) ||
    typeof passphrase !== 'string' ||
    !passphrase
  ) {
    throw invalidFile();
  }
  return passphrase;
}

export async function readPassphraseFile(file: File): Promise<string> {
  if (file.size > MAX_FILE_BYTES) throw invalidFile();
  const text = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () =>
      typeof reader.result === 'string' ? resolve(reader.result) : reject(invalidFile());
    reader.onerror = () => reject(invalidFile());
    reader.onabort = () => reject(invalidFile());
    reader.readAsText(file, 'UTF-8');
  });
  return parsePassphraseFile(text);
}

export function downloadPassphrase(passphrase: string, createdAt = new Date()): void {
  const blob = new Blob([passphraseFileText(passphrase, createdAt)], {
    type: 'text/plain;charset=utf-8',
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  try {
    link.href = url;
    link.download = `ssf-passphrase-${createdAt.toISOString().slice(0, 10)}.txt`;
    document.body.append(link);
    link.click();
  } finally {
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}
