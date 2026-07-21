import axios from 'axios';

function localApiBaseUrl(): string {
  const scheme = 'http';
  return `${scheme}://localhost:8000`;
}

// Create axios instance with base URL from environment
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || localApiBaseUrl(),
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor for logging (dev only)
if (import.meta.env.DEV) {
  api.interceptors.request.use(
    (config) => {
      console.log(`[API] ${config.method?.toUpperCase()} request started`);
      return config;
    },
    (error) => {
      console.error('[API] Request error');
      return Promise.reject(error);
    }
  );
}

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => {
    if (import.meta.env.DEV) {
      console.log('[API] Response received');
    }
    return response;
  },
  (error) => {
    if (error.response) {
      // Server responded with error status
      console.error('[API] Response error:', error.response.status);
    } else if (error.request) {
      // Request made but no response received
      console.error('[API] No response received');
    } else {
      // Error setting up the request
      console.error('[API] Request setup error');
    }
    return Promise.reject(error);
  }
);

export default api;
