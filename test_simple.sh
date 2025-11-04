#!/bin/bash

# =============================================================================
# SSF Backend Test Script - Session & Text Chat Simulation
# =============================================================================

set -e

# Konfiguration
API_BASE="https://ssf.smart-village.solutions"
FRONTEND_BASE="https://translate.smart-village.solutions"
CUSTOMER_LANGUAGE="de"
ADMIN_LANGUAGE="de"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Simple API call function
simple_api_call() {
    local method=$1
    local url=$2
    local data=$3

    if [ -n "$data" ]; then
        curl -s -X "$method" -H "Content-Type: application/json" -d "$data" "$url"
    else
        curl -s -X "$method" "$url"
    fi
}

main() {
    echo "=================================================="
    echo "🚀 SSF Backend Test Script"
    echo "🕒 $(date)"
    echo "=================================================="

    # Step 1: Create Session
    log_info "🔧 Schritt 1: Admin-Session erstellen"
    session_response=$(simple_api_call "POST" "$API_BASE/api/admin/session/create?customer_language=$CUSTOMER_LANGUAGE" "")

    echo "Raw response: $session_response"

    SESSION_ID=$(echo "$session_response" | grep -o '"session_id":"[^"]*"' | cut -d'"' -f4)

    if [ -z "$SESSION_ID" ]; then
        log_error "Konnte Session-ID nicht extrahieren"
        exit 1
    fi

    log_success "✅ Session erstellt: $SESSION_ID"

    # Step 2: Check Session
    log_info "🔍 Schritt 2: Session-Status prüfen"
    session_status=$(simple_api_call "GET" "$API_BASE/api/session/$SESSION_ID" "")
    echo "Session Status: $session_status"

    # Step 3: Activate Session
    log_info "🎯 Schritt 3: Session aktivieren"
    activation_data="{\"session_id\":\"$SESSION_ID\",\"customer_language\":\"$CUSTOMER_LANGUAGE\"}"
    activation_response=$(simple_api_call "POST" "$API_BASE/api/customer/session/activate" "$activation_data")
    echo "Activation Response: $activation_response"

    # Step 4: Test WebSocket
    log_info "🔌 Schritt 4: WebSocket testen"
    echo "Testing WebSocket connection..."
    timeout 3 curl --http1.1 -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" "https://ssf.smart-village.solutions/ws/$SESSION_ID/admin" || log_info "WebSocket test completed"

    # Step 5: Send Test Message
    log_info "💬 Schritt 5: Test-Nachricht senden"
    message_data="{\"text\":\"Hallo Test aus dem Backend!\",\"source_lang\":\"$CUSTOMER_LANGUAGE\",\"target_lang\":\"en\",\"client_type\":\"customer\"}"
    message_response=$(simple_api_call "POST" "$API_BASE/api/session/$SESSION_ID/message" "$message_data")
    echo "Message Response: $message_response"

    # Step 6: Get Messages
    log_info "📥 Schritt 6: Nachrichten abrufen"
    messages=$(simple_api_call "GET" "$API_BASE/api/session/$SESSION_ID/messages" "")
    echo "Messages: $messages"

    # Step 7: Health Check
    log_info "🏥 Schritt 7: Health Check"
    health=$(simple_api_call "GET" "$API_BASE/api/health/summary" "")
    echo "Health: $health"

    log_success "🎉 Test abgeschlossen!"
    log_success "Session ID: $SESSION_ID"
    log_success "Frontend URL: $FRONTEND_BASE/join/$SESSION_ID"
}

# Run the test
main "$@"
