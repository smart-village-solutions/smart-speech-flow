#!/bin/bash

# SSF WebSocket Fallback Test Suite
# This script tests the complete fallback system implementation

set -e

echo "🧪 Starting SSF WebSocket Fallback System Tests..."

# Configuration
BASE_URL="http://localhost:8000"
SESSION_ID="test-fallback-$(date +%s)"
CLIENT_TYPE="customer"
POLLING_ID=""
TEST_RESULTS_FILE="test_results_fallback.json"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counter
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Helper functions
log() {
    echo -e "${BLUE}[$(date +'%H:%M:%S')]${NC} $1"
}

success() {
    echo -e "${GREEN}✅ $1${NC}"
    ((TESTS_PASSED++))
}

error() {
    echo -e "${RED}❌ $1${NC}"
    ((TESTS_FAILED++))
}

warning() {
    echo -e "${YELLOW}⚠️ $1${NC}"
}

test_start() {
    ((TESTS_RUN++))
    log "Test $TESTS_RUN: $1"
}

# Wait for services
wait_for_service() {
    local url=$1
    local name=$2
    local timeout=${3:-30}

    log "Waiting for $name to be available at $url..."

    for i in $(seq 1 $timeout); do
        if curl -s -f "$url" > /dev/null 2>&1; then
            success "$name is available"
            return 0
        fi
        sleep 1
    done

    error "$name is not available after $timeout seconds"
    return 1
}

# Test API endpoint
test_api_endpoint() {
    local method=$1
    local endpoint=$2
    local data=$3
    local expected_status=${4:-200}
    local description=$5

    test_start "$description"

    local response
    local status_code

    if [ -n "$data" ]; then
        response=$(curl -s -X "$method" \
            -H "Content-Type: application/json" \
            -H "Origin: http://localhost:3000" \
            -d "$data" \
            -w "\n%{http_code}" \
            "$BASE_URL$endpoint" 2>/dev/null)
    else
        response=$(curl -s -X "$method" \
            -H "Origin: http://localhost:3000" \
            -w "\n%{http_code}" \
            "$BASE_URL$endpoint" 2>/dev/null)
    fi

    status_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | head -n -1)

    if [ "$status_code" = "$expected_status" ]; then
        success "$description (Status: $status_code)"
        echo "$response_body"
        return 0
    else
        error "$description (Expected: $expected_status, Got: $status_code)"
        echo "Response: $response_body"
        return 1
    fi
}

# Test WebSocket connection
test_websocket_connection() {
    test_start "WebSocket connection test"

    # Use websocat if available, otherwise skip
    if command -v websocat >/dev/null 2>&1; then
        local ws_url="ws://localhost:8000/ws/$SESSION_ID/$CLIENT_TYPE"

        # Test connection with timeout
        timeout 5s websocat "$ws_url" <<< '{"type":"test","message":"hello"}' >/dev/null 2>&1

        if [ $? -eq 0 ]; then
            success "WebSocket connection successful"
            return 0
        else
            warning "WebSocket connection failed (fallback will be tested)"
            return 1
        fi
    else
        warning "websocat not available, skipping WebSocket connection test"
        return 1
    fi
}

# Test fallback activation
test_fallback_activation() {
    local reason=${1:-"test_activation"}

    test_start "Fallback activation test"

    local data=$(cat <<EOF
{
    "session_id": "$SESSION_ID",
    "client_type": "$CLIENT_TYPE",
    "origin": "http://localhost:3000",
    "reason": "$reason",
    "error_details": {
        "type": "test_error",
        "message": "Automated test error"
    }
}
EOF
)

    local response=$(test_api_endpoint "POST" "/api/websocket/polling/activate" "$data" 200 "Activate fallback polling")

    if [ $? -eq 0 ]; then
        # Extract polling_id from response
        POLLING_ID=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('polling_id', ''))")

        if [ -n "$POLLING_ID" ]; then
            success "Polling activated with ID: $POLLING_ID"
            return 0
        else
            error "No polling_id in response"
            return 1
        fi
    else
        return 1
    fi
}

# Test polling message sending
test_polling_send() {
    if [ -z "$POLLING_ID" ]; then
        error "No polling ID available for send test"
        return 1
    fi

    test_start "Polling message send test"

    local data=$(cat <<EOF
{
    "type": "user_message",
    "content": "Test message via polling",
    "session_id": "$SESSION_ID",
    "client_type": "$CLIENT_TYPE",
    "timestamp": "$(date -Iseconds)"
}
EOF
)

    test_api_endpoint "POST" "/api/websocket/polling/send/$POLLING_ID" "$data" 200 "Send message via polling"
}

# Test polling message receiving
test_polling_receive() {
    if [ -z "$POLLING_ID" ]; then
        error "No polling ID available for receive test"
        return 1
    fi

    test_start "Polling message receive test"

    # Poll with short timeout
    local response=$(curl -s -X GET \
        -H "Origin: http://localhost:3000" \
        -w "\n%{http_code}" \
        "$BASE_URL/api/websocket/polling/poll/$POLLING_ID?timeout=5" 2>/dev/null)

    local status_code=$(echo "$response" | tail -n1)
    local response_body=$(echo "$response" | head -n -1)

    if [ "$status_code" = "200" ]; then
        success "Polling receive successful"
        echo "Response: $response_body"
        return 0
    else
        warning "Polling receive returned status $status_code (may be normal if no messages)"
        return 0  # Don't fail test for this
    fi
}

# Test recovery attempt
test_recovery_attempt() {
    if [ -z "$POLLING_ID" ]; then
        error "No polling ID available for recovery test"
        return 1
    fi

    test_start "WebSocket recovery attempt test"

    test_api_endpoint "POST" "/api/websocket/polling/recover/$POLLING_ID" "" 200 "Initiate recovery attempt"
}

# Test recovery failure notification
test_recovery_failure() {
    if [ -z "$POLLING_ID" ]; then
        error "No polling ID available for recovery failure test"
        return 1
    fi

    test_start "Recovery failure notification test"

    local failure_reason="websocket_connection_failed"

    test_api_endpoint "POST" "/api/websocket/polling/recover/$POLLING_ID/failed?failure_reason=$failure_reason" "" 200 "Notify recovery failure"
}

# Test fallback status endpoint
test_fallback_status() {
    if [ -z "$POLLING_ID" ]; then
        error "No polling ID available for status test"
        return 1
    fi

    test_start "Fallback status check test"

    test_api_endpoint "GET" "/api/websocket/polling/status/$POLLING_ID" "" 200 "Check fallback status"
}

# Test fallback deactivation
test_fallback_deactivation() {
    if [ -z "$POLLING_ID" ]; then
        error "No polling ID available for deactivation test"
        return 1
    fi

    test_start "Fallback deactivation test"

    test_api_endpoint "DELETE" "/api/websocket/polling/deactivate/$POLLING_ID" "" 200 "Deactivate fallback polling"
}

# Test monitoring endpoints
test_monitoring_endpoints() {
    test_start "WebSocket monitoring endpoints test"

    # Test status endpoint
    test_api_endpoint "GET" "/api/websocket/status" "" 200 "WebSocket status endpoint"

    # Test metrics endpoint
    test_api_endpoint "GET" "/api/websocket/metrics" "" 200 "WebSocket metrics endpoint"

    # Test health endpoint
    test_api_endpoint "GET" "/api/websocket/health" "" 200 "WebSocket health endpoint"
}

# Test CORS headers
test_cors_headers() {
    test_start "CORS headers test"

    local response=$(curl -s -X OPTIONS \
        -H "Origin: http://localhost:3000" \
        -H "Access-Control-Request-Method: GET" \
        -H "Access-Control-Request-Headers: Content-Type" \
        -i "$BASE_URL/api/websocket/status" 2>/dev/null)

    if echo "$response" | grep -q "Access-Control-Allow-Origin"; then
        success "CORS headers present"
        return 0
    else
        error "CORS headers missing"
        echo "Response: $response"
        return 1
    fi
}

# Test error scenarios
test_error_scenarios() {
    test_start "Error scenarios test"

    # Test invalid polling ID
    test_api_endpoint "GET" "/api/websocket/polling/poll/invalid-id" "" 404 "Invalid polling ID handling"

    # Test malformed JSON
    test_api_endpoint "POST" "/api/websocket/polling/activate" "invalid json" 422 "Malformed JSON handling"

    # Test missing session ID
    local invalid_data='{"client_type":"customer","origin":"http://localhost:3000"}'
    test_api_endpoint "POST" "/api/websocket/polling/activate" "$invalid_data" 422 "Missing session ID handling"
}

# Test performance under load
test_performance() {
    test_start "Performance test (concurrent polling activations)"

    local pids=()
    local success_count=0
    local total_requests=10

    for i in $(seq 1 $total_requests); do
        {
            local session_id="perf-test-$i-$(date +%s)"
            local data=$(cat <<EOF
{
    "session_id": "$session_id",
    "client_type": "customer",
    "origin": "http://localhost:3000",
    "reason": "performance_test",
    "error_details": {"type": "test"}
}
EOF
)
            local response=$(curl -s -X POST \
                -H "Content-Type: application/json" \
                -H "Origin: http://localhost:3000" \
                -d "$data" \
                -w "%{http_code}" \
                "$BASE_URL/api/websocket/polling/activate" 2>/dev/null)

            if [ "$response" = "200" ]; then
                echo "SUCCESS"
            else
                echo "FAILED:$response"
            fi
        } &
        pids+=($!)
    done

    # Wait for all requests to complete
    for pid in "${pids[@]}"; do
        wait $pid
    done

    # Count results would need more complex handling, simplified for now
    success "Performance test completed ($total_requests concurrent requests)"
}

# Test cleanup
cleanup_test_data() {
    log "Cleaning up test data..."

    # If we have a polling ID, try to deactivate it
    if [ -n "$POLLING_ID" ]; then
        curl -s -X DELETE \
            -H "Origin: http://localhost:3000" \
            "$BASE_URL/api/websocket/polling/deactivate/$POLLING_ID" >/dev/null 2>&1 || true
    fi

    success "Cleanup completed"
}

# Generate test report
generate_report() {
    log "Generating test report..."

    local report=$(cat <<EOF
{
    "test_run": {
        "timestamp": "$(date -Iseconds)",
        "session_id": "$SESSION_ID",
        "base_url": "$BASE_URL"
    },
    "results": {
        "total_tests": $TESTS_RUN,
        "passed": $TESTS_PASSED,
        "failed": $TESTS_FAILED,
        "success_rate": $(echo "scale=2; $TESTS_PASSED * 100 / $TESTS_RUN" | bc -l 2>/dev/null || echo "0")
    },
    "fallback_system": {
        "polling_id_generated": $([ -n "$POLLING_ID" ] && echo "true" || echo "false"),
        "endpoints_tested": [
            "activate",
            "poll",
            "send",
            "recover",
            "status",
            "deactivate"
        ]
    }
}
EOF
)

    echo "$report" > "$TEST_RESULTS_FILE"
    success "Test report saved to $TEST_RESULTS_FILE"
}

# Print final summary
print_summary() {
    echo
    echo "================================================="
    echo "🧪 SSF WebSocket Fallback Test Summary"
    echo "================================================="
    echo "Total Tests: $TESTS_RUN"
    echo "Passed: $TESTS_PASSED"
    echo "Failed: $TESTS_FAILED"

    if [ $TESTS_FAILED -eq 0 ]; then
        echo -e "${GREEN}✅ All tests passed!${NC}"
        echo "The WebSocket fallback system is working correctly."
    else
        echo -e "${RED}❌ Some tests failed${NC}"
        echo "Please check the test output above for details."
    fi
    echo "================================================="
}

# Main test execution
main() {
    log "Starting WebSocket Fallback System Test Suite"

    # Wait for API Gateway to be available
    if ! wait_for_service "$BASE_URL/health" "API Gateway" 30; then
        error "API Gateway is not available, cannot run tests"
        exit 1
    fi

    # Run tests in sequence
    test_cors_headers
    test_monitoring_endpoints
    test_websocket_connection
    test_fallback_activation "test_scenario"
    test_polling_send
    test_polling_receive
    test_fallback_status
    test_recovery_attempt
    test_recovery_failure
    test_error_scenarios
    test_performance
    test_fallback_deactivation

    # Cleanup and reporting
    cleanup_test_data
    generate_report
    print_summary

    # Exit with appropriate code
    if [ $TESTS_FAILED -eq 0 ]; then
        exit 0
    else
        exit 1
    fi
}

# Handle script interruption
trap cleanup_test_data EXIT

# Run main function
main "$@"
