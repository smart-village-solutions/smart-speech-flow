export type ClientType = 'admin' | 'customer';
export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export interface WebSocketMessage {
  role: 'sender_confirmation' | 'receiver_message' | 'session_terminated' | 'session_activated' | 'client_joined' | 'error';
  session_id: string;
  message_id?: string;
  text?: string;  // Backend sendet "text" statt "content"
  audio_url?: string;
  source_lang?: string;
  target_lang?: string;
  sender?: string;
  customer_language?: string;
  client_type?: string;  // For client_joined events
  connection_id?: string;  // For client_joined events
  pipeline_metadata?: {
    input?: {
      type: 'audio' | 'text';
      source_lang: string;
      audio_url?: string;
    };
    steps?: Array<{
      name: string;
      input?: unknown;
      output?: unknown;
      started_at?: string;
      completed_at?: string;
      duration_ms: number;
    }>;
    total_duration_ms?: number;
    pipeline_started_at?: string;
    pipeline_completed_at?: string;
  };
  error?: string;
}

type MessageHandler = (message: WebSocketMessage) => void;
type StatusHandler = (status: ConnectionStatus) => void;

class WebSocketService {
  private ws: WebSocket | null = null;
  private sessionId: string | null = null;
  private clientType: ClientType | null = null;
  private readonly messageHandlers: Set<MessageHandler> = new Set();
  private readonly statusHandlers: Set<StatusHandler> = new Set();
  private reconnectAttempts = 0;
  private readonly maxReconnectAttempts = 5;
  private readonly reconnectDelay = 1000;
  private status: ConnectionStatus = 'disconnected';
  private heartbeatInterval: number | null = null;
  private readonly HEARTBEAT_INTERVAL_MS = 30000; // 30 Sekunden

  /**
   * Connect to WebSocket server
   */
  connect(sessionId: string, clientType: ClientType): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      console.log('[WebSocket] Already connected');
      return;
    }

    this.sessionId = sessionId;
    this.clientType = clientType;
    this.setStatus('connecting');

    const wsBaseUrl = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000';
    const wsUrl = `${wsBaseUrl}/ws/${sessionId}/${clientType}`;

    console.log(`[WebSocket] Connecting to ${wsUrl}`);

    try {
      this.ws = new WebSocket(wsUrl);
      this.setupEventHandlers();
    } catch (error) {
      console.error('[WebSocket] Connection error:', error);
      this.setStatus('error');
      this.scheduleReconnect();
    }
  }

  /**
   * Disconnect from WebSocket
   */
  disconnect(): void {
    console.log('[WebSocket] Disconnecting');
    this.reconnectAttempts = this.maxReconnectAttempts; // Prevent auto-reconnect
    this.stopHeartbeat();
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.setStatus('disconnected');
  }

  /**
   * Register message handler
   */
  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler);
    return () => this.messageHandlers.delete(handler);
  }

  /**
   * Register status handler
   */
  onStatusChange(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    // Call immediately with current status
    handler(this.status);
    return () => this.statusHandlers.delete(handler);
  }

  /**
   * Get current connection status
   */
  getStatus(): ConnectionStatus {
    return this.status;
  }

  /**
   * Check if connected
   */
  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  private setupEventHandlers(): void {
    if (!this.ws) return;

    this.ws.onopen = () => {
      console.log('[WebSocket] Connected');
      this.reconnectAttempts = 0;
      this.setStatus('connected');
      this.startHeartbeat();
    };

    this.ws.onmessage = (event) => {
      try {
        const rawMessage = JSON.parse(event.data);
        console.log('[WebSocket] Message received:', rawMessage);

        // Map backend message types to frontend role format
        // Prioritize 'role' over 'type' to preserve differentiated message types
        const message: WebSocketMessage = {
          ...rawMessage,
          role: rawMessage.role || rawMessage.type, // Use 'role' if present, fallback to 'type'
        };

        this.notifyMessageHandlers(message);
      } catch (error) {
        console.error('[WebSocket] Failed to parse message:', error);
      }
    };

    this.ws.onerror = (error) => {
      console.error('[WebSocket] Error:', error);
      this.setStatus('error');
    };

    this.ws.onclose = (event) => {
      console.log('[WebSocket] Closed:', event.code, event.reason);
      this.setStatus('disconnected');
      this.stopHeartbeat();
      this.ws = null;

      // Auto-reconnect if not intentionally closed
      if (this.reconnectAttempts < this.maxReconnectAttempts) {
        this.scheduleReconnect();
      }
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.log('[WebSocket] Max reconnect attempts reached');
      return;
    }

    this.reconnectAttempts++;
    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);

    console.log(`[WebSocket] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);

    setTimeout(() => {
      if (this.sessionId && this.clientType) {
        this.connect(this.sessionId, this.clientType);
      }
    }, delay);
  }

  private setStatus(status: ConnectionStatus): void {
    if (this.status === status) return;
    this.status = status;
    this.statusHandlers.forEach((handler) => handler(status));
  }

  private notifyMessageHandlers(message: WebSocketMessage): void {
    this.messageHandlers.forEach((handler) => handler(message));
  }

  /**
   * Start sending heartbeat messages
   */
  private startHeartbeat(): void {
    this.stopHeartbeat(); // Clear any existing interval

    this.heartbeatInterval = globalThis.setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        try {
          this.ws.send(JSON.stringify({ type: 'heartbeat_pong' }));
          console.log('[WebSocket] Heartbeat sent');
        } catch (error) {
          console.error('[WebSocket] Failed to send heartbeat:', error);
        }
      }
    }, this.HEARTBEAT_INTERVAL_MS);
  }

  /**
   * Stop sending heartbeat messages
   */
  private stopHeartbeat(): void {
    if (this.heartbeatInterval !== null) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }
}

// Singleton instance
export default new WebSocketService();
