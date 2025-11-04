/**
 * Smart Speech Flow WebSocket Client
 *
 * A comprehensive JavaScript client for integrating with the Smart Speech Flow WebSocket API.
 * Supports automatic reconnection, fallback to polling, and cross-origin WebSocket connections.
 *
 * Usage:
 * const client = new SSFWebSocketClient('session-id', 'customer', options);
 * client.connect();
 *
 * @version 1.0.0
 * @author Smart Village Solutions
 */

class SSFWebSocketClient {
    /**
     * Create a new SSF WebSocket client
     * @param {string} sessionId - The session ID to connect to
     * @param {string} clientType - Either 'admin' or 'customer'
     * @param {Object} options - Configuration options
     */
    constructor(sessionId, clientType, options = {}) {
        // Validate required parameters
        if (!sessionId || !clientType) {
            throw new Error('sessionId and clientType are required parameters');
        }

        if (!['admin', 'customer'].includes(clientType)) {
            throw new Error('clientType must be either "admin" or "customer"');
        }

        this.sessionId = sessionId;
        this.clientType = clientType;

        // Configuration with defaults
        this.options = {
            // Connection settings
            protocol: typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss:' : 'ws:',
            host: options.host || 'ssf.smart-village.solutions',

            // Reconnection settings
            reconnectAttempts: options.reconnectAttempts || 5,
            reconnectInterval: options.reconnectInterval || 1000,
            maxReconnectInterval: options.maxReconnectInterval || 30000,

            // Fallback settings
            fallbackToPolling: options.fallbackToPolling !== false,
            pollingInterval: options.pollingInterval || 2000,

            // Heartbeat settings
            heartbeatInterval: options.heartbeatInterval || 30000,
            heartbeatTimeout: options.heartbeatTimeout || 60000,

            // Debug settings
            debug: options.debug || false,

            ...options
        };

        // Internal state
        this.ws = null;
        this.reconnectCount = 0;
        this.isConnected = false;
        this.messageQueue = [];
        this.pollingId = null;
        this.pollingInterval = null;
        this.heartbeatInterval = null;
        this.lastHeartbeat = null;

        // Event handlers - can be overridden or passed in options
        this.onOpen = options.onOpen || (() => {});
        this.onMessage = options.onMessage || (() => {});
        this.onError = options.onError || (() => {});
        this.onClose = options.onClose || (() => {});
        this.onReconnect = options.onReconnect || (() => {});

        // Bind methods to preserve context
        this.connect = this.connect.bind(this);
        this.disconnect = this.disconnect.bind(this);
        this.sendMessage = this.sendMessage.bind(this);
        this.handleMessage = this.handleMessage.bind(this);
    }

    /**
     * Test WebSocket connection compatibility before connecting
     * @returns {Promise<Object>} Compatibility test result
     */
    static async testCompatibility(host = 'ssf.smart-village.solutions') {
        try {
            const protocol = typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'https:' : 'http:';
            const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost';

            const response = await fetch(`${protocol}//${host}/api/websocket/debug/connection-test`, {
                method: 'GET',
                headers: {
                    'Origin': origin,
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();

            return {
                compatible: result.origin_allowed,
                details: result,
                suggestions: result.suggestions || []
            };

        } catch (error) {
            return {
                compatible: false,
                error: error.message,
                suggestions: [
                    'Check network connectivity',
                    'Verify the host URL is correct',
                    'Ensure CORS is properly configured'
                ]
            };
        }
    }

    /**
     * Connect to the WebSocket server
     * @returns {Promise<void>}
     */
    async connect() {
        // Don't connect if already connected
        if (this.isConnected) {
            this.log('Already connected, skipping connection attempt');
            return;
        }

        const wsUrl = `${this.options.protocol}//${this.options.host}/ws/${this.sessionId}/${this.clientType}`;

        try {
            this.log(`Attempting to connect to: ${wsUrl}`);

            // Create WebSocket connection
            this.ws = new WebSocket(wsUrl);

            // Set up event handlers
            this.ws.onopen = this.handleOpen.bind(this);
            this.ws.onmessage = this.handleRawMessage.bind(this);
            this.ws.onerror = this.handleError.bind(this);
            this.ws.onclose = this.handleClose.bind(this);

        } catch (error) {
            this.log(`Connection failed: ${error.message}`);
            this.handleError(error);

            if (this.options.fallbackToPolling) {
                await this.enablePollingFallback();
            }
        }
    }

    /**
     * Handle WebSocket open event
     * @param {Event} event
     */
    handleOpen(event) {
        this.log('WebSocket connection established');

        this.isConnected = true;
        this.reconnectCount = 0;

        // Start heartbeat if configured
        if (this.options.heartbeatInterval > 0) {
            this.startHeartbeat();
        }

        // Send queued messages
        this.flushMessageQueue();

        // Notify listeners
        this.onOpen(event);
    }

    /**
     * Handle raw WebSocket message (before JSON parsing)
     * @param {MessageEvent} event
     */
    handleRawMessage(event) {
        try {
            const data = JSON.parse(event.data);
            this.handleMessage(data);
        } catch (error) {
            this.log(`Failed to parse message: ${error.message}`, 'error');
            this.log(`Raw message: ${event.data}`, 'error');
        }
    }

    /**
     * Handle parsed WebSocket message
     * @param {Object} data - Parsed message data
     */
    handleMessage(data) {
        this.log(`Received message: ${data.type}`, 'debug');

        switch (data.type) {
            case 'connection_ack':
                this.log('Connection acknowledged by server');
                break;

            case 'heartbeat_ping':
                this.log('Received heartbeat ping, sending pong');
                this.sendMessage({ type: 'heartbeat_pong' });
                break;

            case 'heartbeat_pong':
                this.log('Received heartbeat pong');
                this.lastHeartbeat = Date.now();
                break;

            case 'session_terminated':
                this.log(`Session terminated: ${data.reason}`);
                this.disconnect();
                break;

            case 'message':
                this.log(`Received chat message from ${data.from || 'unknown'}`);
                this.onMessage(data);
                break;

            case 'typing_indicator':
                this.log(`${data.from} is ${data.is_typing ? 'typing' : 'not typing'}`);
                this.onMessage(data);
                break;

            case 'client_joined':
                this.log(`Client joined: ${data.client_type}`);
                this.onMessage(data);
                break;

            case 'error':
                this.log(`Server error: ${data.error}`, 'error');
                this.onError(new Error(data.error));
                break;

            default:
                this.log(`Unknown message type: ${data.type}`);
                this.onMessage(data);
        }
    }

    /**
     * Handle WebSocket error
     * @param {Event|Error} error
     */
    handleError(error) {
        this.log(`WebSocket error: ${error.message || 'Unknown error'}`, 'error');

        this.onError(error);

        // Attempt fallback to polling if we've exhausted reconnection attempts
        if (this.options.fallbackToPolling && this.reconnectCount >= this.options.reconnectAttempts) {
            this.enablePollingFallback();
        }
    }

    /**
     * Handle WebSocket close event
     * @param {CloseEvent} event
     */
    handleClose(event) {
        this.log(`WebSocket closed: ${event.code} - ${event.reason}`);

        this.isConnected = false;

        // Stop heartbeat
        this.stopHeartbeat();

        this.onClose(event);

        // Attempt reconnection for non-normal closures
        if (event.code !== 1000 && this.reconnectCount < this.options.reconnectAttempts) {
            this.scheduleReconnect();
        } else if (event.code !== 1000 && this.options.fallbackToPolling) {
            this.enablePollingFallback();
        }
    }

    /**
     * Send a message to the server
     * @param {Object} message - Message to send
     */
    sendMessage(message) {
        // Add timestamp if not present
        if (!message.timestamp) {
            message.timestamp = new Date().toISOString();
        }

        const messageString = JSON.stringify(message);

        if (this.isConnected && this.ws && this.ws.readyState === WebSocket.OPEN) {
            try {
                this.ws.send(messageString);
                this.log(`Sent message: ${message.type}`, 'debug');
            } catch (error) {
                this.log(`Failed to send message: ${error.message}`, 'error');
                this.messageQueue.push(message);
            }
        } else {
            // Queue message for later delivery
            this.messageQueue.push(message);
            this.log(`Message queued (not connected): ${message.type}`);
        }
    }

    /**
     * Schedule a reconnection attempt
     */
    scheduleReconnect() {
        this.reconnectCount++;

        // Calculate delay with exponential backoff
        const delay = Math.min(
            this.options.reconnectInterval * Math.pow(2, this.reconnectCount - 1),
            this.options.maxReconnectInterval
        );

        this.log(`Scheduling reconnection in ${delay}ms (attempt ${this.reconnectCount}/${this.options.reconnectAttempts})`);

        setTimeout(() => {
            this.log(`Reconnection attempt ${this.reconnectCount}`);
            this.onReconnect({ attempt: this.reconnectCount, maxAttempts: this.options.reconnectAttempts });
            this.connect();
        }, delay);
    }

    /**
     * Enable polling fallback when WebSocket fails
     */
    async enablePollingFallback() {
        this.log('Enabling polling fallback...');

        try {
            const protocol = this.options.protocol === 'wss:' ? 'https:' : 'http:';
            const response = await fetch(`${protocol}//${this.options.host}/api/websocket/sessions/${this.sessionId}/polling/enable`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    client_type: this.clientType
                })
            });

            if (!response.ok) {
                throw new Error(`Failed to enable polling: HTTP ${response.status}`);
            }

            const result = await response.json();
            this.pollingId = result.polling_id;

            this.startPolling();

            // Simulate connection for API compatibility
            this.isConnected = true;
            this.onOpen({ type: 'polling_fallback' });

        } catch (error) {
            this.log(`Failed to enable polling fallback: ${error.message}`, 'error');
            this.onError(error);
        }
    }

    /**
     * Start polling for messages
     */
    startPolling() {
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
        }

        this.log(`Starting polling with ID: ${this.pollingId}`);

        this.pollingInterval = setInterval(async () => {
            try {
                const protocol = this.options.protocol === 'wss:' ? 'https:' : 'http:';
                const response = await fetch(`${protocol}//${this.options.host}/api/websocket/polling/${this.pollingId}/messages`);

                if (response.ok) {
                    const messages = await response.json();
                    messages.forEach(message => this.handleMessage(message));
                } else {
                    this.log(`Polling request failed: HTTP ${response.status}`, 'error');
                }

            } catch (error) {
                this.log(`Polling error: ${error.message}`, 'error');
            }
        }, this.options.pollingInterval);
    }

    /**
     * Start heartbeat monitoring
     */
    startHeartbeat() {
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
        }

        this.lastHeartbeat = Date.now();

        this.heartbeatInterval = setInterval(() => {
            const now = Date.now();
            const timeSinceLastHeartbeat = now - this.lastHeartbeat;

            if (timeSinceLastHeartbeat > this.options.heartbeatTimeout) {
                this.log('Heartbeat timeout, disconnecting', 'error');
                this.disconnect();
                return;
            }

            // Send ping
            this.sendMessage({ type: 'heartbeat_ping' });
        }, this.options.heartbeatInterval);
    }

    /**
     * Stop heartbeat monitoring
     */
    stopHeartbeat() {
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = null;
        }
    }

    /**
     * Flush queued messages
     */
    flushMessageQueue() {
        this.log(`Flushing ${this.messageQueue.length} queued messages`);

        while (this.messageQueue.length > 0) {
            const message = this.messageQueue.shift();
            this.sendMessage(message);
        }
    }

    /**
     * Disconnect from the server
     */
    disconnect() {
        this.log('Disconnecting...');

        // Close WebSocket connection
        if (this.ws) {
            this.ws.close(1000, 'Client disconnect');
            this.ws = null;
        }

        // Stop polling
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = null;
        }

        // Stop heartbeat
        this.stopHeartbeat();

        this.isConnected = false;
        this.reconnectCount = 0;
        this.messageQueue = [];

        this.log('Disconnected');
    }

    /**
     * Get connection statistics
     * @returns {Object} Connection statistics
     */
    getStats() {
        return {
            isConnected: this.isConnected,
            reconnectCount: this.reconnectCount,
            queuedMessages: this.messageQueue.length,
            usingPolling: !!this.pollingId,
            lastHeartbeat: this.lastHeartbeat,
            sessionId: this.sessionId,
            clientType: this.clientType
        };
    }

    /**
     * Log messages with optional level
     * @param {string} message - Log message
     * @param {string} level - Log level (log, error, debug)
     */
    log(message, level = 'log') {
        if (!this.options.debug && level === 'debug') {
            return;
        }

        const prefix = `[SSF-WebSocket:${this.sessionId}:${this.clientType}]`;
        const timestamp = new Date().toISOString();

        switch (level) {
            case 'error':
                console.error(`${prefix} ${timestamp} ${message}`);
                break;
            case 'debug':
                console.debug(`${prefix} ${timestamp} ${message}`);
                break;
            default:
                console.log(`${prefix} ${timestamp} ${message}`);
        }
    }
}

// Export for both CommonJS and ES modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SSFWebSocketClient;
} else if (typeof window !== 'undefined') {
    window.SSFWebSocketClient = SSFWebSocketClient;
}

// Also support ES6 modules
if (typeof exports !== 'undefined') {
    exports.default = SSFWebSocketClient;
    exports.SSFWebSocketClient = SSFWebSocketClient;
}