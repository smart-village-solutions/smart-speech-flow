export function conversationRow(id: string, active = true) {
  return {
    id: 'dashboard-' + id,
    session_id: id,
    recording_id: null,
    origin: 'own' as const,
    started_at: '2026-08-26T11:20:00Z',
    ended_at: active ? null : '2026-08-26T11:29:00Z',
    conversation_status: active ? ('active' as const) : ('ended' as const),
    recording_status: 'none' as const,
    recording_access: 'none' as const,
    customer_language: active ? 'ar' : 'tr',
    language_visibility: 'clear' as const,
    verification: null,
    actions: active ? ['resume' as const, 'open_details' as const] : ['open_details' as const],
  };
}
