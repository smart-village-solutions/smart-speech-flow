/**
 * `crypto.randomUUID` exists only in a secure context. An on-site tablet
 * reaching a locally hosted gateway over http:// has none, and this is called
 * from the request interceptor — an unguarded call there fails every request
 * the app makes, not just the one that needed an id.
 */
export function randomId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  const random = Math.floor(Math.random() * 1e12).toString(36);
  return `${Date.now().toString(36)}-${random}`;
}
