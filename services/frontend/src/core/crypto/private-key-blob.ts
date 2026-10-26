import { argon2id } from 'hash-wasm';
import { aesDecrypt, aesEncrypt, aesKey } from './aead';
import { type Bytes, bytes, fromBase64Url, randomBytes, toBase64Url } from './bytes';
import { enc } from './encoding';
import { TAGS } from './tags';

/** Argon2id cost: memory in KiB, iterations, lanes (spec §8.3). */
export interface KdfParams {
  m: number;
  t: number;
  p: number;
}

/** 64 MiB, t = 3, p = 1; raised after measuring on the target tablets. */
export const ENROLMENT_KDF: KdfParams = { m: 65536, t: 3, p: 1 };

type Purpose = 'enc' | 'sig';
const PURPOSES: readonly Purpose[] = ['enc', 'sig'];

export interface PrivateKeys {
  enc: Bytes;
  sig: Bytes;
}

interface Identity {
  tenantId: string;
  userSub: string;
}

/** Vector tests only: fixed salt and nonces. */
export interface BlobRandomness {
  salt: Bytes;
  nonces: Record<Purpose, Bytes>;
}

async function stretch(passphrase: string, salt: Bytes, params: Readonly<KdfParams>): Promise<CryptoKey> {
  const raw = await argon2id({
    password: passphrase,
    salt,
    parallelism: params.p,
    iterations: params.t,
    memorySize: params.m,
    hashLength: 32,
    outputType: 'binary',
  });
  return aesKey(bytes(raw));
}

function blobAad(identity: Readonly<Identity>, purpose: Purpose, salt: Bytes, params: Readonly<KdfParams>): Bytes {
  return enc(TAGS.privateKey, identity.tenantId, identity.userSub, purpose, salt, params.m, params.t, params.p);
}

/** The PKCS#8 keys sealed under the stretched passphrase (spec A.5). */
export async function sealPrivateKeys(
  passphrase: string,
  identity: Readonly<Identity>,
  keys: Readonly<PrivateKeys>,
  params: Readonly<KdfParams> = ENROLMENT_KDF,
  randomness?: Readonly<BlobRandomness>
): Promise<string> {
  const salt = randomness?.salt ?? randomBytes(16);
  const key = await stretch(passphrase, salt, params);
  const sealed: Record<string, { nonce: string; ct: string }> = {};
  for (const purpose of PURPOSES) {
    const nonce = randomness?.nonces[purpose] ?? randomBytes(12);
    const ct = await aesEncrypt(key, nonce, keys[purpose], blobAad(identity, purpose, salt, params));
    sealed[purpose] = { nonce: toBase64Url(nonce), ct: toBase64Url(ct) };
  }
  return JSON.stringify({
    v: 1,
    kdf: { alg: 'argon2id', m: params.m, t: params.t, p: params.p, salt: toBase64Url(salt) },
    enc: sealed.enc,
    sig: sealed.sig,
  });
}

interface BlobBody {
  kdf: KdfParams & { salt: string };
  enc: { nonce: string; ct: string };
  sig: { nonce: string; ct: string };
}

/** Rejects with an EnvelopeError on a wrong passphrase. */
export async function openPrivateKeys(
  blob: string,
  passphrase: string,
  identity: Readonly<Identity>
): Promise<PrivateKeys> {
  const body = JSON.parse(blob) as BlobBody;
  const params = { m: body.kdf.m, t: body.kdf.t, p: body.kdf.p };
  const salt = fromBase64Url(body.kdf.salt);
  const key = await stretch(passphrase, salt, params);
  const open = (purpose: Purpose) =>
    aesDecrypt(
      key,
      fromBase64Url(body[purpose].nonce),
      fromBase64Url(body[purpose].ct),
      blobAad(identity, purpose, salt, params)
    );
  return { enc: await open('enc'), sig: await open('sig') };
}
