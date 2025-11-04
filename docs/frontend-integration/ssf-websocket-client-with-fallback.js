/**
 * Enhanced SSF WebSocket Client with Automatic Fallback
 *
 * This is an enhanced version of the SSF WebSocket client that includes
 * automatic fallback to polling when WebSocket connections fail.
 *
 * Features:
 * - Automatic WebSocket connection with fallback to polling
 * - Intelligent error detection and classification
 * - Seamless user experience during fallbacks
 * - Automatic recovery attempts
 * - CORS-aware error handling
 *
 * @version 2.0.0
 */

class SSFWebSocketClientWithFallback {
    constructor(sessionId, clientType, options = {}) {
        this.sessionId = sessionId;
        this.clientType = clientType; // 'admin' or 'customer'
        this.options = {
            baseUrl: options.baseUrl || window.location.origin,
            enableFallback: options.enableFallback !== false,
            enableAutoRecovery: options.enableAutoRecovery !== false,
            maxRetries: options.maxRetries || 3,
            retryDelay: options.retryDelay || 1000,
            pollingInterval: options.pollingInterval || 5000,
            recoveryCheckInterval: options.recoveryCheckInterval || 300000, // 5 minutes
            debug: options.debug || false,
            userNotifications: options.userNotifications !== false,
            ...options
        };

        // Connection state
        this.connectionState = 'disconnected'; // 'connecting', 'connected', 'polling', 'disconnected'
        this.websocket = null;
        this.pollingId = null;
        this.isPolling = false;
        this.retryCount = 0;
        this.lastError = null;

        // Event handlers
        this.eventHandlers = {
            open: [],
            message: [],
            close: [],
            error: [],
            fallback: [],
            recovery: [],
            notification: []
        };

        // Timers
        this.reconnectTimer = null;
        this.pollingTimer = null;
        this.recoveryTimer = null;
        this.heartbeatTimer = null;

        // Message queue for reliability
        this.messageQueue = [];
        this.isProcessingQueue = false;

        this.log('SSF WebSocket Client with Fallback initialized');
    }

    /**
     * Connect to the WebSocket server with automatic fallback
     */
    async connect() {
        if (this.connectionState === 'connecting') {
            this.log('Connection already in progress');
            return;
        }

        this.connectionState = 'connecting';
        this.retryCount = 0;

        try {
            await this._attemptWebSocketConnection();
        } catch (error) {
            this.log('WebSocket connection failed, evaluating fallback', error);
            await this._handleConnectionFailure(error);
        }
    }

    /**
     * Attempt WebSocket connection
     */
    async _attemptWebSocketConnection() {
        return new Promise((resolve, reject) => {
            try {
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const wsUrl = `${protocol}//${this.options.baseUrl.replace(/^https?:\/\//, '')}/ws/${this.sessionId}/${this.clientType}`;

                this.log(`Attempting WebSocket connection to: ${wsUrl}`);

                this.websocket = new WebSocket(wsUrl);

                // Connection timeout
                const connectionTimeout = setTimeout(() => {
                    if (this.websocket && this.websocket.readyState === WebSocket.CONNECTING) {
                        this.websocket.close();
                        reject(new Error('WebSocket connection timeout'));
                    }
                }, 10000);

                this.websocket.onopen = (event) => {
                    clearTimeout(connectionTimeout);
                    this.log('WebSocket connected successfully');

                    this.connectionState = 'connected';
                    this.retryCount = 0;
                    this.lastError = null;

                    // Start heartbeat
                    this._startHeartbeat();

                    // Process queued messages
                    this._processMessageQueue();

                    // Notify handlers
                    this._notifyHandlers('open', event);

                    resolve();
                };

                this.websocket.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        this._handleWebSocketMessage(data);
                    } catch (error) {
                        this.log('Error parsing WebSocket message:', error);
                        this._notifyHandlers('error', { type: 'parse_error', error, rawData: event.data });
                    }
                };

                this.websocket.onclose = (event) => {
                    clearTimeout(connectionTimeout);
                    this._stopHeartbeat();

                    this.log(`WebSocket closed: ${event.code} - ${event.reason}`);

                    const shouldReconnect = event.code !== 1000 && this.connectionState !== 'disconnected';

                    if (shouldReconnect) {
                        const error = {
                            type: 'websocket_close',
                            code: event.code,
                            reason: event.reason,
                            wasClean: event.wasClean
                        };

                        reject(error);
                    } else {
                        this.connectionState = 'disconnected';
                        this._notifyHandlers('close', event);
                    }
                };

                this.websocket.onerror = (event) => {
                    clearTimeout(connectionTimeout);
                    this.log('WebSocket error:', event);

                    const error = {
                        type: 'websocket_error',
                        event: event,
                        message: 'WebSocket connection error'
                    };

                    reject(error);
                };

            } catch (error) {
                reject(error);
            }
        });
    }

    /**
     * Handle WebSocket connection failure and potentially activate fallback
     */
    async _handleConnectionFailure(error) {
        this.lastError = error;
        this.retryCount++;

        this.log(`Connection failure #${this.retryCount}:`, error);

        // Classify the error
        const errorClassification = this._classifyError(error);

        // Determine if fallback should be activated
        const shouldActivateFallback = this._shouldActivateFallback(errorClassification, this.retryCount);

        if (shouldActivateFallback && this.options.enableFallback) {
            this.log('Activating polling fallback');
            await this._activatePollingFallback(errorClassification.reason);
        } else if (this.retryCount < this.options.maxRetries) {
            this.log(`Scheduling retry attempt #${this.retryCount + 1}`);
            this._scheduleReconnect();
        } else {
            this.log('Max retries exceeded, connection failed');
            this.connectionState = 'disconnected';
            this._notifyHandlers('error', {
                type: 'connection_failed',
                error: error,
                retryCount: this.retryCount
            });
        }
    }

    /**
     * Classify connection error for appropriate handling
     */
    _classifyError(error) {
        const errorMessage = (error.message || error.reason || '').toLowerCase();
        const errorCode = error.code;

        // CORS related errors
        if (errorMessage.includes('cors') || errorMessage.includes('origin')) {
            return {
                type: 'cors',
                reason: 'cors_origin_blocked',
                shouldFallback: true,
                userMessage: 'Connection switched to compatibility mode due to security restrictions.'
            };
        }

        // WebSocket handshake failures
        if (errorCode === 403 || errorMessage.includes('handshake') || errorCode === 1002 || errorCode === 1003) {
            return {
                type: 'handshake',
                reason: 'websocket_handshake_failed',
                shouldFallback: true,
                userMessage: 'Connection using compatibility mode for optimal performance.'
            };
        }

        // Network errors
        if (errorMessage.includes('network') || errorMessage.includes('timeout') || errorCode === 0) {
            return {
                type: 'network',
                reason: 'network_error',
                shouldFallback: this.retryCount >= 2,
                userMessage: 'Connection adapted to network conditions.'
            };
        }

        // Generic connection failures
        return {
            type: 'connection',
            reason: 'websocket_connection_failed',
            shouldFallback: this.retryCount >= 2,
            userMessage: 'Connection using alternative mode for reliability.'
        };
    }

    /**
     * Determine if fallback should be activated
     */
    _shouldActivateFallback(classification, retryCount) {
        // Immediate fallback for CORS issues
        if (classification.type === 'cors') {
            return true;
        }

        // Immediate fallback for handshake failures
        if (classification.type === 'handshake') {
            return true;
        }

        // Fallback after multiple network failures
        if (classification.type === 'network' && retryCount >= 2) {
            return true;
        }

        // Fallback after multiple generic failures
        if (retryCount >= 3) {
            return true;
        }

        return false;
    }

    /**
     * Activate polling fallback
     */
    async _activatePollingFallback(reason) {
        try {
            const response = await fetch(`${this.options.baseUrl}/api/websocket/polling/activate`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Origin': window.location.origin
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    client_type: this.clientType,
                    origin: window.location.origin,
                    reason: reason,
                    error_details: this.lastError
                })
            });

            if (!response.ok) {
                throw new Error(`Failed to activate fallback: ${response.status} ${response.statusText}`);
            }

            const result = await response.json();

            this.pollingId = result.polling_id;
            this.connectionState = 'polling';

            this.log(`Polling fallback activated: ${this.pollingId}`);

            // Start polling
            this._startPolling();

            // Schedule recovery attempts
            if (this.options.enableAutoRecovery) {
                this._scheduleRecoveryAttempt();
            }

            // Notify user if enabled
            if (this.options.userNotifications) {
                const notification = {
                    type: 'fallback_activated',
                    reason: reason,
                    message: this._classifyError(this.lastError).userMessage,
                    mode: 'polling'
                };
                this._notifyHandlers('notification', notification);
            }

            // Notify fallback handlers
            this._notifyHandlers('fallback', {
                type: 'activated',
                polling_id: this.pollingId,
                reason: reason,
                endpoints: result.endpoints
            });

            // Process queued messages
            this._processMessageQueue();

        } catch (error) {
            this.log('Failed to activate polling fallback:', error);

            // Still try to reconnect via WebSocket
            this._scheduleReconnect();
        }
    }

    /**
     * Start polling for messages
     */
    _startPolling() {
        if (this.isPolling || !this.pollingId) {
            return;
        }

        this.isPolling = true;
        this._pollMessages();
    }

    /**
     * Poll for messages
     */
    async _pollMessages() {
        if (!this.isPolling || !this.pollingId) {
            return;
        }

        try {
            const response = await fetch(
                `${this.options.baseUrl}/api/websocket/polling/poll/${this.pollingId}?timeout=30`,
                {
                    method: 'GET',
                    headers: {
                        'Origin': window.location.origin
                    }
                }
            );

            if (!response.ok) {
                if (response.status === 404) {
                    // Polling session expired
                    this.log('Polling session expired');
                    this._stopPolling();
                    this._scheduleReconnect();
                    return;
                }
                throw new Error(`Polling failed: ${response.status} ${response.statusText}`);
            }

            const result = await response.json();

            // Process messages
            if (result.messages && result.messages.length > 0) {
                for (const message of result.messages) {
                    this._handlePollingMessage(message);
                }
            }

            // Schedule next poll
            if (this.isPolling) {
                const pollInterval = result.next_poll_interval || this.options.pollingInterval;
                this.pollingTimer = setTimeout(() => this._pollMessages(), pollInterval);
            }

        } catch (error) {
            this.log('Polling error:', error);

            // Retry polling after delay
            if (this.isPolling) {
                this.pollingTimer = setTimeout(() => this._pollMessages(), this.options.pollingInterval);
            }
        }
    }

    /**
     * Stop polling
     */
    _stopPolling() {
        this.isPolling = false;

        if (this.pollingTimer) {
            clearTimeout(this.pollingTimer);
            this.pollingTimer = null;
        }
    }

    /**
     * Handle message received via polling
     */
    _handlePollingMessage(message) {
        // Check for system messages
        if (message.type === 'websocket_retry_suggestion') {
            this.log('Received WebSocket retry suggestion');
            this._attemptWebSocketRecovery();
            return;
        }

        if (message.type === 'fallback_notification') {
            this._notifyHandlers('notification', message);
            return;
        }

        // Regular message
        this._notifyHandlers('message', { data: JSON.stringify(message) });
    }

    /**
     * Handle WebSocket message
     */
    _handleWebSocketMessage(data) {
        // Check for system messages
        if (data.type === 'fallback_activated') {
            this.log('Received fallback activation message from server');
            // Server is telling us to switch to polling
            this._handleServerRequestedFallback(data);
            return;
        }

        if (data.type === 'connection_ack') {
            this.log('Received connection acknowledgment');
            return;
        }

        if (data.type === 'heartbeat_pong') {
            this.log('Received heartbeat pong');
            return;
        }

        // Regular message
        this._notifyHandlers('message', { data: JSON.stringify(data) });
    }

    /**
     * Handle server-requested fallback
     */
    async _handleServerRequestedFallback(data) {
        this.log('Server requested fallback activation');

        // Close WebSocket
        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }

        // Activate polling with provided info
        this.pollingId = data.polling_id;
        this.connectionState = 'polling';

        this._startPolling();

        if (this.options.enableAutoRecovery) {
            this._scheduleRecoveryAttempt();
        }

        // Notify handlers
        this._notifyHandlers('fallback', {
            type: 'server_requested',
            polling_id: this.pollingId,
            reason: data.fallback_reason,
            message: data.message
        });
    }

    /**
     * Schedule WebSocket recovery attempt
     */
    _scheduleRecoveryAttempt() {
        if (this.recoveryTimer) {
            clearTimeout(this.recoveryTimer);
        }

        this.recoveryTimer = setTimeout(async () => {
            await this._attemptWebSocketRecovery();
        }, this.options.recoveryCheckInterval);
    }

    /**
     * Attempt WebSocket recovery
     */
    async _attemptWebSocketRecovery() {
        if (!this.pollingId || this.connectionState !== 'polling') {
            return;
        }

        this.log('Attempting WebSocket recovery');

        try {
            // Notify server of recovery attempt
            const response = await fetch(
                `${this.options.baseUrl}/api/websocket/polling/recover/${this.pollingId}`,
                {
                    method: 'POST',
                    headers: {
                        'Origin': window.location.origin
                    }
                }
            );

            if (!response.ok) {
                throw new Error(`Recovery request failed: ${response.status}`);
            }

            const result = await response.json();

            // Attempt WebSocket connection
            try {
                await this._attemptWebSocketConnection();

                // Success - notify server and cleanup polling
                await this._notifyRecoverySuccess();

                this.log('WebSocket recovery successful');

            } catch (error) {
                // Recovery failed
                await this._notifyRecoveryFailure(error);

                this.log('WebSocket recovery failed, continuing with polling');

                // Schedule next recovery attempt
                this._scheduleRecoveryAttempt();
            }

        } catch (error) {
            this.log('Recovery attempt failed:', error);

            // Schedule next recovery attempt
            this._scheduleRecoveryAttempt();
        }
    }

    /**
     * Notify server of successful recovery
     */
    async _notifyRecoverySuccess() {
        try {
            await fetch(
                `${this.options.baseUrl}/api/websocket/polling/recover/${this.pollingId}/success`,
                {
                    method: 'POST',
                    headers: {
                        'Origin': window.location.origin
                    }
                }
            );

            // Cleanup polling
            this._stopPolling();
            this.pollingId = null;

            // Clear recovery timer
            if (this.recoveryTimer) {
                clearTimeout(this.recoveryTimer);
                this.recoveryTimer = null;
            }

            this._notifyHandlers('recovery', {
                type: 'success',
                message: 'WebSocket connection restored'
            });

        } catch (error) {
            this.log('Failed to notify recovery success:', error);
        }
    }

    /**
     * Notify server of failed recovery
     */
    async _notifyRecoveryFailure(error) {
        try {
            const errorClassification = this._classifyError(error);

            await fetch(
                `${this.options.baseUrl}/api/websocket/polling/recover/${this.pollingId}/failed?failure_reason=${errorClassification.reason}`,
                {
                    method: 'POST',
                    headers: {
                        'Origin': window.location.origin
                    }
                }
            );

        } catch (notifyError) {
            this.log('Failed to notify recovery failure:', notifyError);
        }
    }

    /**
     * Send message
     */
    async send(data) {
        const message = typeof data === 'string' ? data : JSON.stringify(data);

        if (this.connectionState === 'connected' && this.websocket && this.websocket.readyState === WebSocket.OPEN) {
            // Send via WebSocket
            this.websocket.send(message);

        } else if (this.connectionState === 'polling' && this.pollingId) {
            // Send via polling
            try {
                const messageData = typeof data === 'string' ? JSON.parse(data) : data;

                const response = await fetch(
                    `${this.options.baseUrl}/api/websocket/polling/send/${this.pollingId}`,
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Origin': window.location.origin
                        },
                        body: JSON.stringify({
                            type: messageData.type || 'message',
                            content: messageData,
                            session_id: this.sessionId,
                            client_type: this.clientType,
                            timestamp: new Date().toISOString()
                        })
                    }
                );

                if (!response.ok) {
                    throw new Error(`Failed to send via polling: ${response.status}`);
                }

            } catch (error) {
                this.log('Failed to send message via polling:', error);

                // Queue message for later
                this.messageQueue.push(message);
            }

        } else {
            // Queue message for when connection is established
            this.messageQueue.push(message);
            this.log('Message queued (not connected)');
        }
    }

    /**
     * Process queued messages
     */
    async _processMessageQueue() {
        if (this.isProcessingQueue || this.messageQueue.length === 0) {
            return;
        }

        this.isProcessingQueue = true;

        while (this.messageQueue.length > 0) {
            const message = this.messageQueue.shift();

            try {
                await this.send(message);

                // Small delay to avoid overwhelming
                await new Promise(resolve => setTimeout(resolve, 10));

            } catch (error) {
                // Put message back in queue
                this.messageQueue.unshift(message);
                break;
            }
        }

        this.isProcessingQueue = false;
    }

    /**
     * Schedule reconnect attempt
     */
    _scheduleReconnect() {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
        }

        const delay = this.options.retryDelay * Math.pow(2, Math.min(this.retryCount - 1, 5)); // Exponential backoff, max 32x

        this.log(`Scheduling reconnect in ${delay}ms`);

        this.reconnectTimer = setTimeout(() => {
            this.connect();
        }, delay);
    }

    /**
     * Start heartbeat
     */
    _startHeartbeat() {
        this._stopHeartbeat();

        this.heartbeatTimer = setInterval(() => {
            if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
                this.websocket.send(JSON.stringify({
                    type: 'heartbeat_ping',
                    timestamp: Date.now()
                }));
            }
        }, 30000); // 30 seconds
    }

    /**
     * Stop heartbeat
     */
    _stopHeartbeat() {
        if (this.heartbeatTimer) {
            clearInterval(this.heartbeatTimer);
            this.heartbeatTimer = null;
        }
    }

    /**
     * Close connection
     */
    close() {
        this.connectionState = 'disconnected';

        // Clear timers
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }

        if (this.recoveryTimer) {
            clearTimeout(this.recoveryTimer);
            this.recoveryTimer = null;
        }

        this._stopPolling();
        this._stopHeartbeat();

        // Close WebSocket
        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }

        // Deactivate polling if active
        if (this.pollingId) {
            fetch(`${this.options.baseUrl}/api/websocket/polling/deactivate/${this.pollingId}`, {
                method: 'DELETE',
                headers: { 'Origin': window.location.origin }
            }).catch(error => this.log('Failed to deactivate polling:', error));

            this.pollingId = null;
        }
    }

    /**
     * Add event listener
     */
    addEventListener(event, handler) {
        if (this.eventHandlers[event]) {
            this.eventHandlers[event].push(handler);
        }
    }

    /**
     * Remove event listener
     */
    removeEventListener(event, handler) {
        if (this.eventHandlers[event]) {
            const index = this.eventHandlers[event].indexOf(handler);
            if (index > -1) {
                this.eventHandlers[event].splice(index, 1);
            }
        }
    }

    /**
     * Notify event handlers
     */
    _notifyHandlers(event, data) {
        if (this.eventHandlers[event]) {
            this.eventHandlers[event].forEach(handler => {
                try {
                    handler(data);
                } catch (error) {
                    this.log(`Error in ${event} handler:`, error);
                }
            });
        }
    }

    /**
     * Get connection status
     */
    getStatus() {
        return {
            connectionState: this.connectionState,
            isWebSocketConnected: this.websocket && this.websocket.readyState === WebSocket.OPEN,
            isPolling: this.isPolling,
            pollingId: this.pollingId,
            retryCount: this.retryCount,
            lastError: this.lastError,
            queuedMessages: this.messageQueue.length
        };
    }

    /**
     * Force switch to polling mode (for testing)
     */
    async forceFallback(reason = 'manual_fallback') {
        if (this.connectionState === 'polling') {
            this.log('Already in polling mode');
            return;
        }

        // Close WebSocket if connected
        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }

        await this._activatePollingFallback(reason);
    }

    /**
     * Debug logging
     */
    log(message, ...args) {
        if (this.options.debug) {
            console.log(`[SSF WebSocket Fallback] ${message}`, ...args);
        }
    }

    /**
     * Static method to test compatibility
     */
    static async testCompatibility(baseUrl = window.location.origin) {
        const tests = {
            websocket_support: typeof WebSocket !== 'undefined',
            fetch_support: typeof fetch !== 'undefined',
            json_support: typeof JSON !== 'undefined',
            promise_support: typeof Promise !== 'undefined',
            origin_header: !!window.location.origin
        };

        // Test CORS preflight
        try {
            const response = await fetch(`${baseUrl}/api/websocket/debug/connection-test`, {
                method: 'GET',
                headers: {
                    'Origin': window.location.origin
                }
            });
            tests.cors_preflight = response.ok;
        } catch (error) {
            tests.cors_preflight = false;
        }

        const compatible = Object.values(tests).every(test => test === true);

        return {
            compatible,
            tests,
            recommendations: compatible ? [] : [
                !tests.websocket_support && 'WebSocket not supported - will use polling fallback',
                !tests.fetch_support && 'Fetch API not supported - consider polyfill',
                !tests.cors_preflight && 'CORS preflight failed - check server configuration'
            ].filter(Boolean)
        };
    }
}

// Export for different module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SSFWebSocketClientWithFallback;
} else if (typeof window !== 'undefined') {
    window.SSFWebSocketClientWithFallback = SSFWebSocketClientWithFallback;
}