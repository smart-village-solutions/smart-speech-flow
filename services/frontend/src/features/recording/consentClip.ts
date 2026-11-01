const PREFIX = 'consent-';

/** The playback id of a question's read-aloud clip; never a message's id. */
export function consentClipId(requestId: string): string {
  return `${PREFIX}${requestId}`;
}

export function isConsentClip(id: string): boolean {
  return id.startsWith(PREFIX);
}
