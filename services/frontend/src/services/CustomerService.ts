import api from './api';

export interface Language {
  code: string;
  name: string;
  native_name?: string;
}

export interface ActivateSessionRequest {
  session_id: string;
  customer_language: string;
}

export interface ActivateSessionResponse {
  session_id: string;
  status: string;
  customer_language: string;
  message: string;
}

class CustomerService {
  /**
   * Get list of supported languages
   * GET /api/languages/supported
   */
  async getLanguages(): Promise<Language[]> {
    const response = await api.get<{ languages: Record<string, { name: string; native: string }> }>('/api/languages/supported');

    // Transform object to array
    const languagesObj = response.data.languages;
    return Object.entries(languagesObj).map(([code, info]) => ({
      code,
      name: info.name,
      native_name: info.native,
    }));
  }

  /**
   * Activate a session with customer language
   * POST /api/customer/session/activate
   */
  async activateSession(sessionId: string, customerLanguage: string): Promise<ActivateSessionResponse> {
    const response = await api.post<ActivateSessionResponse>('/api/customer/session/activate', {
      session_id: sessionId,
      customer_language: customerLanguage,
    });
    return response.data;
  }

  /**
   * Verify if a session exists and is joinable
   * GET /api/session/{sessionId}
   */
  async verifySession(sessionId: string): Promise<boolean> {
    try {
      const response = await api.get(`/api/session/${sessionId}`);
      return response.data.status === 'pending' || response.data.status === 'active';
    } catch (error) {
      return false;
    }
  }
}

export default new CustomerService();
