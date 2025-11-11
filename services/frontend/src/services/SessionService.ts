import api from './api';

export interface SessionData {
  session_id: string;
  status: 'pending' | 'active' | 'terminated';
  admin_language?: string;
  customer_language?: string;
}

export interface CreateSessionResponse {
  session_id: string;
  status: string;
  message: string;
}

export interface TerminateSessionResponse {
  message: string;
  session_id: string;
}

class SessionService {
  /**
   * Create a new session (admin)
   * POST /api/admin/session/create
   */
  async createSession(): Promise<CreateSessionResponse> {
    const response = await api.post<CreateSessionResponse>('/api/admin/session/create');
    return response.data;
  }

  /**
   * Terminate an active session (admin)
   * DELETE /api/admin/session/{sessionId}
   */
  async terminateSession(sessionId: string): Promise<TerminateSessionResponse> {
    const response = await api.delete<TerminateSessionResponse>(`/api/admin/session/${sessionId}`);
    return response.data;
  }

  /**
   * Get session status
   * GET /api/session/{sessionId}
   */
  async getSessionStatus(sessionId: string): Promise<SessionData> {
    const response = await api.get<SessionData>(`/api/session/${sessionId}`);
    return response.data;
  }
}

export default new SessionService();
