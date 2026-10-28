import { utf8 } from './bytes';

/** Hex SHA-256 of a string's UTF-8 bytes: how the gateway hashes a consent text it serves. */
export async function sha256Hex(text: string): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', utf8(text)));
  return Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('');
}
