/** Type tags (spec A.2). Each is also the HKDF `info` of its payload. */
export const TAGS = {
  object: 'ssf-rec/object/v1',
  ckWrap: 'ssf-rec/ck-wrap/v1',
  privateKey: 'ssf-rec/private-key/v1',
  share: 'ssf-rec/share/v1',
  subshare: 'ssf-rec/subshare/v1',
  partial: 'ssf-rec/partial/v1',
  wrapSig: 'ssf-rec/wrap-sig/v1',
  chainSig: 'ssf-rec/chain-sig/v1',
  verificationSig: 'ssf-rec/verification-sig/v1',
  transcript: 'ssf-rec/transcript/v1',
  dleq: 'ssf-rec/dleq/v1',
  pok: 'ssf-rec/pok/v1',
  fingerprint: 'ssf-rec/fpr/v1',
} as const;

export type SealedType =
  | typeof TAGS.ckWrap
  | typeof TAGS.share
  | typeof TAGS.subshare
  | typeof TAGS.partial;

const SEALED_TYPES: readonly string[] = [TAGS.ckWrap, TAGS.share, TAGS.subshare, TAGS.partial];

export function isSealedType(value: string): value is SealedType {
  return SEALED_TYPES.includes(value);
}
