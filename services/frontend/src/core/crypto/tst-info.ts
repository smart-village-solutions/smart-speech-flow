import { type Bytes, toHex } from './bytes';

class TimestampFormatError extends Error {
  constructor() {
    super('not a SHA-256 RFC 3161 token');
    this.name = 'TimestampFormatError';
  }
}

interface Element {
  tag: number;
  value: Bytes;
}

const SIGNED_DATA = '2a864886f70d010702';
const TST_INFO = '2a864886f70d0109100104';
const SHA256 = '608648016503040201';
const SEQUENCE = 0x30;
const OID = 0x06;
const OCTET_STRING = 0x04;
const CONTEXT_0 = 0xa0;
const GENERALIZED_TIME = 0x18;

function fail(): never {
  throw new TimestampFormatError();
}

function byteAt(data: Bytes, index: number): number {
  const value = data[index];
  return value ?? fail();
}

/** The DER length at `at`: its value and where the content starts. */
function lengthAt(data: Bytes, at: number): { length: number; start: number } {
  const first = byteAt(data, at);
  if ((first & 0x80) === 0) return { length: first, start: at + 1 };
  const count = first & 0x7f;
  if (count === 0 || count > 3) fail();
  let length = 0;
  for (let i = 1; i <= count; i += 1) length = length * 256 + byteAt(data, at + i);
  return { length, start: at + 1 + count };
}

/** DER TLVs inside `data`, in order; any overrun fails. */
function children(data: Bytes): Element[] {
  const items: Element[] = [];
  let at = 0;
  while (at < data.length) {
    const tag = byteAt(data, at);
    const { length, start } = lengthAt(data, at + 1);
    if (start + length > data.length) fail();
    items.push({ tag, value: data.slice(start, start + length) });
    at = start + length;
  }
  return items;
}

function only(data: Bytes, tag: number): Bytes {
  const items = children(data);
  if (items.length !== 1 || items[0].tag !== tag) fail();
  return items[0].value;
}

function at(list: readonly Element[], index: number, tag: number): Bytes {
  const item = list[index];
  if (item?.tag !== tag) fail();
  return item.value;
}

/** `YYYYMMDDHHMMSS[.f]Z` -> ISO 8601 with milliseconds. */
function isoTime(raw: Bytes): string {
  const text = new TextDecoder().decode(raw);
  const match = /^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?:\.(\d{1,9}))?Z$/.exec(text);
  if (match === null) fail();
  const [, year, month, day, hour, minute, second, fraction = ''] = match;
  return `${year}-${month}-${day}T${hour}:${minute}:${second}.${(fraction + '000').slice(0, 3)}Z`;
}

/**
 * The imprint and genTime of a TimeStampToken (spec §11.2). The authority's
 * CMS signature is not checked here; #619 does (spec §10.6).
 */
export function readTimestamp(token: Bytes): { imprint: Bytes; genTime: string } {
  const contentInfo = children(only(token, SEQUENCE));
  if (toHex(at(contentInfo, 0, OID)) !== SIGNED_DATA) fail();
  const signedData = children(only(at(contentInfo, 1, CONTEXT_0), SEQUENCE));
  const encapsulated = children(at(signedData, 2, SEQUENCE));
  if (toHex(at(encapsulated, 0, OID)) !== TST_INFO) fail();
  const info = children(only(only(at(encapsulated, 1, CONTEXT_0), OCTET_STRING), SEQUENCE));
  const imprint = children(at(info, 2, SEQUENCE));
  const algorithm = children(at(imprint, 0, SEQUENCE));
  if (toHex(at(algorithm, 0, OID)) !== SHA256) fail();
  const digest = at(imprint, 1, OCTET_STRING);
  if (digest.length !== 32) fail();
  return { imprint: digest, genTime: isoTime(at(info, 4, GENERALIZED_TIME)) };
}
