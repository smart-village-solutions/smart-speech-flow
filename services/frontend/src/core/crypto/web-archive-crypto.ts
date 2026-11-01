import { aesKey, objectAad, openEnvelope, sealEnvelope } from './aead';
import type { ArchiveCrypto, KeyOwner, NewKeys, PublicKeys, UnlockedKeys, WrapToOpen } from './archive-crypto.port';
import { type Bytes, concat, equalBytes, fromBase64Url, fromBuffer } from './bytes';
import { contexts, openWithPrivateKey, parseSealed } from './ecies';
import { ENROLMENT_KDF, openPrivateKeys, sealPrivateKeys } from './private-key-blob';
import { verifyFields, wrapFields } from './signatures';
import { TAGS } from './tags';
import { fingerprint } from './transcript';

const ECDH = { name: 'ECDH', namedCurve: 'P-256' } as const;
const ECDSA = { name: 'ECDSA', namedCurve: 'P-256' } as const;

async function exportPublic(key: CryptoKey): Promise<Bytes> {
  return fromBuffer(await crypto.subtle.exportKey('raw', key));
}

async function exportPkcs8(key: CryptoKey): Promise<Bytes> {
  return fromBuffer(await crypto.subtle.exportKey('pkcs8', key));
}

/** The public point inside a PKCS#8 key, read through a short-lived extractable import. */
async function publicOf(pkcs8: Bytes, algorithm: typeof ECDH | typeof ECDSA, usage: KeyUsage): Promise<Bytes> {
  const key = await crypto.subtle.importKey('pkcs8', pkcs8, algorithm, true, [usage]);
  const jwk = await crypto.subtle.exportKey('jwk', key);
  return concat([0x04], fromBase64Url(jwk.x ?? ''), fromBase64Url(jwk.y ?? ''));
}

function importPrivate(pkcs8: Bytes, algorithm: typeof ECDH | typeof ECDSA, usage: KeyUsage): Promise<CryptoKey> {
  return crypto.subtle.importKey('pkcs8', pkcs8, algorithm, false, [usage]);
}

async function unlocked(owner: Readonly<KeyOwner>, keys: { enc: Bytes; sig: Bytes }, pub: PublicKeys): Promise<UnlockedKeys> {
  return {
    ...pub,
    encPrivate: await importPrivate(keys.enc, ECDH, 'deriveBits'),
    sigPrivate: await importPrivate(keys.sig, ECDSA, 'sign'),
    fingerprint: await fingerprint(owner.tenantId, owner.userSub, pub.encPub, pub.sigPub),
  };
}

class WrapRefusedError extends Error {
  constructor() {
    super('wrap refused');
    this.name = 'WrapRefusedError';
  }
}

/** A gateway key the ceremony certified, or the caller's own key for a wrap they made. */
function wrapSigned(
  wrap: Readonly<WrapToOpen>,
  keys: Readonly<UnlockedKeys>,
  ephemeral: Bytes,
  signers: ReadonlyMap<string, Bytes>
): Promise<boolean> {
  const signer = wrap.creatorRef === wrap.recipientRef ? keys.sigPub : signers.get(wrap.creatorRef);
  if (signer === undefined) return Promise.resolve(false);
  const signed = wrapFields({
    tenantId: wrap.tenantId,
    conversationId: wrap.conversationId,
    keyId: wrap.keyId,
    ephemeral,
    recipientKind: 'user',
    recipientRef: wrap.recipientRef,
    recipientFingerprint: keys.fingerprint,
  });
  return verifyFields(signer, wrap.creatorSignature, TAGS.wrapSig, signed);
}

export function createWebArchiveCrypto(): ArchiveCrypto {
  return {
    async createKeys(passphrase, owner): Promise<NewKeys> {
      const enc = await crypto.subtle.generateKey(ECDH, true, ['deriveBits']);
      const sig = await crypto.subtle.generateKey(ECDSA, true, ['sign', 'verify']);
      const keys = { enc: await exportPkcs8(enc.privateKey), sig: await exportPkcs8(sig.privateKey) };
      const pub = { encPub: await exportPublic(enc.publicKey), sigPub: await exportPublic(sig.publicKey) };
      const blob = await sealPrivateKeys(passphrase, owner, keys, ENROLMENT_KDF);
      return { blob, unlocked: await unlocked(owner, keys, pub) };
    },

    async unlock(blob, passphrase, owner, expected): Promise<UnlockedKeys> {
      const keys = await openPrivateKeys(blob, passphrase, owner);
      const matches =
        equalBytes(await publicOf(keys.enc, ECDH, 'deriveBits'), expected.encPub) &&
        equalBytes(await publicOf(keys.sig, ECDSA, 'sign'), expected.sigPub);
      if (!matches) throw new Error('the sealed keys do not match the enrolled public keys');
      return unlocked(owner, keys, expected);
    },

    async openWrap(wrap, keys, signers) {
      const sealed = parseSealed(wrap.blob, TAGS.ckWrap);
      if (!(await wrapSigned(wrap, keys, sealed.ephemeral, signers))) throw new WrapRefusedError();
      const context = contexts.ckWrap(
        wrap.tenantId,
        wrap.conversationId,
        wrap.keyId,
        'user',
        wrap.recipientRef
      );
      const raw = await openWithPrivateKey(sealed, keys.encPrivate, keys.encPub, context);
      try {
        return await aesKey(raw);
      } finally {
        raw.fill(0);
      }
    },

    openObject: (key, address, envelope) => openEnvelope(key, envelope, objectAad(address)),

    sealObject: (key, address, plaintext) => sealEnvelope(key, plaintext, objectAad(address)),
  };
}
