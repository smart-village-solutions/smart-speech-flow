import { expect, it } from 'vitest';
import { filterRows } from '../filterRows';

const rows = [
  { id: 'a', time: '2026-01-01', language: null, status: 'ended' },
  { id: 'b', time: '2026-01-03', language: 'de', status: 'active' },
  { id: 'c', time: '2026-01-02', language: 'de', status: 'ended' },
];

it('excludes unknown languages from specific matches, exposes them explicitly, and orders only loaded matches', () => {
  expect(
    filterRows(rows, { language: 'de', status: '', order: 'oldest' }).map((r) => r.id)
  ).toEqual(['c', 'b']);
  expect(filterRows(rows, { language: '?', status: '', order: 'newest' })).toEqual([rows[0]]);
  expect(filterRows(rows, { language: 'de', status: 'ended', order: 'newest' })).toEqual([rows[2]]);
});
