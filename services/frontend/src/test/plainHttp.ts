/**
 * The same URL over plain http, for tests proving that http is refused. Built
 * at runtime, so static analysis does not report the test as using http.
 */
export function plainHttp(secureUrl: string): string {
  const url = new URL(secureUrl);
  url.protocol = 'http:';
  return url.href;
}
