/**
 * An opaque id for correlating a request with its log line.
 *
 * `crypto.randomUUID` exists only in a secure context, and this is called from
 * the request interceptor — an unguarded call there fails every request the app
 * makes, not just the one that needed an id. An on-site tablet reaching a
 * locally hosted gateway over http:// has no secure context.
 *
 * `crypto.getRandomValues` has no such restriction, so it covers that case
 * without falling back to a pseudorandom source.
 */
export function randomId(): string {
  if (typeof crypto === 'undefined') {
    return `${Date.now().toString(36)}-${Math.trunc(performance.now()).toString(36)}`;
  }

  if (typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
}
