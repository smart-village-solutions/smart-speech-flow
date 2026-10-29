import type { ObjectAddress } from './aead';
import type { Bytes } from './bytes';

/** Who a key belongs to; both values are part of its fingerprint and its blob's AAD. */
export interface KeyOwner {
  tenantId: string;
  userSub: string;
}

export interface PublicKeys {
  encPub: Bytes;
  sigPub: Bytes;
}

/** Personal keys after unlock: non-extractable, in memory only (spec §8.3). */
export interface UnlockedKeys extends PublicKeys {
  encPrivate: CryptoKey;
  sigPrivate: CryptoKey;
  fingerprint: Bytes;
}

export interface NewKeys {
  /** The passphrase-sealed private keys; the only private material that leaves the browser. */
  blob: string;
  unlocked: UnlockedKeys;
}

/** A conversation key's wrap for the caller, as the archive serves it (spec A.4, A.6). */
export interface WrapToOpen {
  tenantId: string;
  conversationId: string;
  keyId: string;
  recipientRef: string;
  blob: string;
  /** A gateway key ID, or the caller's own sub for a wrap they made (#617). */
  creatorRef: string;
  creatorSignature: Bytes;
}

/** The browser's side of the archive crypto. Features reach it through this port only. */
export interface ArchiveCrypto {
  createKeys(passphrase: string, owner: Readonly<KeyOwner>): Promise<NewKeys>;
  /**
   * Opens the blob and checks that the keys inside match `expected`, so a
   * blob swapped for someone else's cannot pass as this user's.
   * Rejects on a wrong passphrase or a mismatch.
   */
  unlock(
    blob: string,
    passphrase: string,
    owner: Readonly<KeyOwner>,
    expected: Readonly<PublicKeys>
  ): Promise<UnlockedKeys>;
  /**
   * The conversation key, as a non-extractable AES key. Rejects unless an
   * accepted signer, or the caller's own signing key, signed the wrap for the
   * caller's fingerprint (spec A.6).
   */
  openWrap(
    wrap: Readonly<WrapToOpen>,
    keys: Readonly<UnlockedKeys>,
    signers: ReadonlyMap<string, Bytes>
  ): Promise<CryptoKey>;
  /** Rejects on any envelope that fails A.3 for `address`. */
  openObject(key: CryptoKey, address: Readonly<ObjectAddress>, envelope: Bytes): Promise<Bytes>;
  /** A.3 under the conversation key. */
  sealObject(key: CryptoKey, address: Readonly<ObjectAddress>, plaintext: Bytes): Promise<Bytes>;
}

/** Holds the unlocked keys for the life of the tab; never persisted. */
export interface KeyVault {
  current(): UnlockedKeys | null;
  hold(keys: UnlockedKeys): void;
  lock(): void;
  subscribe(listener: () => void): () => void;
}

/** zxcvbn behind a port, so tests do not load its dictionaries. */
export interface PassphraseStrength {
  /** 0–4; enrolment requires 4 (spec §8.3). */
  score(passphrase: string, userInputs: readonly string[]): Promise<number>;
}
