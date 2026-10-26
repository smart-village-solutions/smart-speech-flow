import { type Bytes, concat, utf8 } from './bytes';

/** A field of the canonical encoding (spec A.1): text, raw bytes or an unsigned integer. */
export type Field = string | Uint8Array | number;

const MAX_FIELD_BYTES = 0xffff;

function fieldBytes(field: Field): Uint8Array {
  if (typeof field === 'string') return utf8(field);
  if (typeof field === 'number') {
    if (!Number.isSafeInteger(field) || field < 0) {
      throw new Error('integers are encoded unsigned and exact');
    }
    return utf8(field.toString(10));
  }
  return field;
}

/** Length-prefix each field with two big-endian bytes, so no field can shift into the next. */
export function enc(...fields: readonly Field[]): Bytes {
  return concat(
    ...fields.map((field) => {
      const raw = fieldBytes(field);
      if (raw.length > MAX_FIELD_BYTES) throw new Error('an encoded field is longer than 65535 bytes');
      return concat([raw.length >> 8, raw.length & 0xff], raw);
    })
  );
}
