"""
OpenAPI Specification Validation Tests
========================================

Tests that validate the OpenAPI specification against the actual implementation.

This ensures:
1. All documented endpoints actually exist
2. Response schemas match the OpenAPI spec
3. Required fields are present in responses
4. Field types match the specification
5. Status codes match documentation

These tests run against the LIVE PRODUCTION API at https://ssf.smart-village.solutions
"""

import pytest
import yaml
import requests
from pathlib import Path


# Production API base URL
PRODUCTION_API_URL = "https://ssf.smart-village.solutions"


@pytest.fixture(scope="module")
def openapi_spec():
    """Load the OpenAPI specification"""
    # Prefer canonical spec in docs/ to avoid duplicate root file
    spec_path = Path(__file__).parent.parent / "docs" / "openapi.yaml"
    with open(spec_path, 'r') as f:
        return yaml.safe_load(f)


@pytest.fixture
def client():
    """Returns the production API URL for testing"""
    return PRODUCTION_API_URL



@pytest.fixture
def active_session(client):
    """Create and activate a test session"""
    response = requests.post(f"{client}/api/admin/session/create")
    assert response.status_code == 201
    session_id = response.json()["session_id"]

    requests.post(f"{client}/api/customer/session/activate", json={
        "session_id": session_id,
        "customer_language": "en"
    })

    return session_id


class TestOpenAPIEndpoints:
    """Test that all OpenAPI endpoints exist and return correct status codes"""

    def test_admin_session_create_endpoint_exists(self, client, openapi_spec):
        """Test POST /api/admin/session/create matches OpenAPI spec"""
        # Get expected response from OpenAPI spec
        endpoint_spec = openapi_spec['paths']['/api/admin/session/create']['post']

        # Call endpoint
        response = requests.post(f"{client}/api/admin/session/create")

        # Validate status code
        assert response.status_code == 201, "Should return 201 Created"
        assert '201' in endpoint_spec['responses'], "OpenAPI should document 201 response"

        # Validate response structure
        data = response.json()
        schema = endpoint_spec['responses']['201']['content']['application/json']['schema']
        required_fields = schema.get('required', [])

        for field in required_fields:
            assert field in data, f"Required field '{field}' missing from response"

    def test_customer_session_activate_endpoint_exists(self, client, openapi_spec):
        """Test POST /api/customer/session/activate matches OpenAPI spec"""
        endpoint_spec = openapi_spec['paths']['/api/customer/session/activate']['post']

        # Create session first
        resp = requests.post(f"{client}/api/admin/session/create")
        session_id = resp.json()["session_id"]

        # Activate session
        response = requests.post(f"{client}/api/customer/session/activate", json={
            "session_id": session_id,
            "customer_language": "en"
        })

        assert response.status_code == 200, "Should return 200 OK"
        assert '200' in endpoint_spec['responses'], "OpenAPI should document 200 response"

    def test_session_status_endpoint_exists(self, client, active_session, openapi_spec):
        """Test GET /api/session/{sessionId} matches OpenAPI spec"""
        endpoint_spec = openapi_spec['paths']['/api/session/{sessionId}']['get']

        response = requests.get(f"{client}/api/session/{active_session}")

        assert response.status_code == 200, "Should return 200 OK"
        assert '200' in endpoint_spec['responses'], "OpenAPI should document 200 response"

        # Validate response has expected fields
        data = response.json()
        expected_fields = ['status', 'customer_language', 'admin_language', 'message_count']
        for field in expected_fields:
            assert field in data, f"Expected field '{field}' in session status response"

    def test_unified_message_endpoint_exists(self, client, active_session, openapi_spec):
        """Test POST /api/session/{sessionId}/message matches OpenAPI spec"""
        endpoint_spec = openapi_spec['paths']['/api/session/{sessionId}/message']['post']

        # Test with text message
        response = requests.post(
            f"{client}/api/session/{active_session}/message",
            json={
                "text": "Hello",
                "source_lang": "en",
                "target_lang": "de",
                "client_type": "admin"
            }
        )

        assert response.status_code == 200, "Should return 200 OK"
        assert '200' in endpoint_spec['responses'], "OpenAPI should document 200 response"

    def test_message_history_endpoint_exists(self, client, active_session, openapi_spec):
        """Test GET /api/session/{sessionId}/messages matches OpenAPI spec"""
        endpoint_spec = openapi_spec['paths']['/api/session/{sessionId}/messages']['get']

        response = requests.get(f"{client}/api/session/{active_session}/messages")

        assert response.status_code == 200, "Should return 200 OK"
        assert '200' in endpoint_spec['responses'], "OpenAPI should document 200 response"

        data = response.json()
        assert 'messages' in data, "Response should contain 'messages' array"

    def test_supported_languages_endpoint_exists(self, client, openapi_spec):
        """Test GET /api/languages/supported matches OpenAPI spec"""
        endpoint_spec = openapi_spec['paths']['/api/languages/supported']['get']

        response = requests.get(f"{client}/api/languages/supported")

        assert response.status_code == 200, "Should return 200 OK"
        assert '200' in endpoint_spec['responses'], "OpenAPI should document 200 response"

        data = response.json()
        assert 'languages' in data, "Response should contain 'languages' object"


class TestMessageResponseSchema:
    """Test that MessageResponse matches OpenAPI schema"""

    def test_message_response_has_all_required_fields(self, client, active_session, openapi_spec):
        """Test that message response contains all required fields from OpenAPI spec"""
        # Get MessageResponse schema from OpenAPI
        message_response_schema = openapi_spec['components']['schemas']['MessageResponse']
        required_fields = message_response_schema.get('required', [])

        # Send a message
        response = requests.post(
            f"{client}/api/session/{active_session}/message",
            json={
                "text": "Test message",
                "source_lang": "en",
                "target_lang": "de",
                "client_type": "customer"
            }
        )

        assert response.status_code == 200
        data = response.json()

        # Check all required fields are present
        missing_fields = [field for field in required_fields if field not in data]
        assert not missing_fields, f"Missing required fields: {missing_fields}"

    def test_message_response_field_types(self, client, active_session, openapi_spec):
        """Test that MessageResponse field types match OpenAPI spec"""
        message_response_schema = openapi_spec['components']['schemas']['MessageResponse']
        properties = message_response_schema['properties']

        # Send a message
        response = requests.post(
            f"{client}/api/session/{active_session}/message",
            json={
                "text": "Test",
                "source_lang": "en",
                "target_lang": "de",
                "client_type": "admin"
            }
        )

        data = response.json()

        # Validate field types
        type_mapping = {
            'string': str,
            'integer': int,
            'boolean': bool,
            'object': dict,
            'array': list
        }

        for field_name, field_spec in properties.items():
            if field_name in data and data[field_name] is not None:
                expected_type_name = field_spec.get('type')
                if expected_type_name in type_mapping:
                    expected_type = type_mapping[expected_type_name]
                    actual_value = data[field_name]
                    assert isinstance(actual_value, expected_type), \
                        f"Field '{field_name}' should be {expected_type_name}, got {type(actual_value).__name__}"

    def test_message_response_status_enum(self, client, active_session, openapi_spec):
        """Test that status field matches enum values from OpenAPI spec"""
        message_response_schema = openapi_spec['components']['schemas']['MessageResponse']
        status_enum = message_response_schema['properties']['status'].get('enum', [])

        response = requests.post(
            f"{client}/api/session/{active_session}/message",
            json={
                "text": "Test",
                "source_lang": "en",
                "target_lang": "de",
                "client_type": "admin"
            }
        )

        data = response.json()
        assert data['status'] in status_enum, \
            f"Status '{data['status']}' not in allowed values: {status_enum}"

    def test_message_response_pipeline_type_enum(self, client, active_session, openapi_spec):
        """Test that pipeline_type field matches enum values from OpenAPI spec"""
        message_response_schema = openapi_spec['components']['schemas']['MessageResponse']
        pipeline_type_enum = message_response_schema['properties']['pipeline_type'].get('enum', [])

        response = requests.post(
            f"{client}/api/session/{active_session}/message",
            json={
                "text": "Test",
                "source_lang": "en",
                "target_lang": "de",
                "client_type": "admin"
            }
        )

        data = response.json()
        assert data['pipeline_type'] in pipeline_type_enum, \
            f"Pipeline type '{data['pipeline_type']}' not in allowed values: {pipeline_type_enum}"
class TestOpenAPICompleteness:
    """Test that OpenAPI spec is complete and up-to-date"""

    def test_openapi_version_is_current(self, openapi_spec):
        """Test that OpenAPI spec version is 1.3.0 or higher"""
        version = openapi_spec['info']['version']
        major, minor, patch = map(int, version.split('.'))

        assert major >= 1, "Major version should be at least 1"
        assert minor >= 3, "Minor version should be at least 3 (current: 1.3.0 with WebSocket docs)"

    def test_all_message_endpoints_documented(self, openapi_spec):
        """Test that all known message endpoints are documented"""
        paths = openapi_spec['paths']

        # Check critical endpoints exist
        assert '/api/admin/session/create' in paths, "Admin session creation should be documented"
        assert '/api/customer/session/activate' in paths, "Customer activation should be documented"
        assert '/api/session/{sessionId}' in paths, "Session status should be documented"
        assert '/api/session/{sessionId}/message' in paths, "Unified message endpoint should be documented"
        assert '/api/session/{sessionId}/messages' in paths, "Message history should be documented"
        assert '/api/languages/supported' in paths, "Supported languages should be documented"

    def test_websocket_endpoints_documented(self, openapi_spec):
        """Test that WebSocket endpoints are documented"""
        paths = openapi_spec['paths']

        # WebSocket endpoints
        assert '/ws/{sessionId}/{clientType}' in paths, "WebSocket connection endpoint should be documented"
        assert '/api/websocket/debug/connection-test' in paths, "WebSocket diagnostics should be documented"
        assert '/api/websocket/poll/{polling_id}' in paths, "WebSocket polling fallback should be documented"

        # Audio endpoints (including original)
        assert '/api/audio/{message_id}.wav' in paths, "Translated audio endpoint should be documented"
        assert '/api/audio/input_{message_id}.wav' in paths, "Original audio input endpoint should be documented"

    def test_websocket_message_schema_complete(self, openapi_spec):
        """Test that WebSocketMessage schema includes all required fields"""
        ws_schema = openapi_spec['components']['schemas']['WebSocketMessage']
        required_fields = ws_schema.get('required', [])

        # Critical fields that MUST be in WebSocket messages
        critical_fields = [
            'type', 'role', 'message_id', 'session_id', 'text',
            'sender', 'timestamp', 'source_lang', 'target_lang',
            'audio_available', 'pipeline_metadata'
        ]

        for field in critical_fields:
            assert field in required_fields, f"WebSocketMessage should require '{field}'"

        # Check role enum values
        role_enum = ws_schema['properties']['role'].get('enum', [])
        assert 'sender_confirmation' in role_enum, "Role should include 'sender_confirmation'"
        assert 'receiver_message' in role_enum, "Role should include 'receiver_message'"

    def test_deprecated_endpoints_not_documented(self, openapi_spec):
        """Test that old/deprecated endpoints are not in the spec"""
        paths = openapi_spec['paths']

        # These endpoints should NOT exist (old API design)
        deprecated = [
            '/api/session',  # Old session creation
            '/api/session/{session_id}/audio',  # Separate audio endpoint
            '/api/session/{session_id}/text',  # Separate text endpoint
        ]

        for endpoint in deprecated:
            assert endpoint not in paths, f"Deprecated endpoint '{endpoint}' should not be documented"


class TestWebSocketEndpoints:
    """Test WebSocket endpoint documentation completeness"""

    def test_websocket_connection_endpoint_documented(self, openapi_spec):
        """Test that WebSocket connection endpoint is properly documented"""
        ws_endpoint = openapi_spec['paths']['/ws/{sessionId}/{clientType}']

        # Check parameters
        params = {p['name']: p for p in ws_endpoint['get']['parameters']}
        assert 'sessionId' in params, "sessionId parameter should be documented"
        assert 'clientType' in params, "clientType parameter should be documented"

        # Check clientType enum
        client_type_enum = params['clientType']['schema'].get('enum', [])
        assert 'admin' in client_type_enum, "clientType should allow 'admin'"
        assert 'customer' in client_type_enum, "clientType should allow 'customer'"

        # Check responses
        responses = ws_endpoint['get']['responses']
        assert '101' in responses, "WebSocket upgrade (101) should be documented"
        assert '404' in responses, "Session not found (404) should be documented"

    def test_websocket_fallback_documented(self, openapi_spec):
        """Test that WebSocket polling fallback is documented"""
        polling_endpoint = openapi_spec['paths']['/api/websocket/poll/{polling_id}']

        # Check it returns WebSocketMessage array
        response_schema = polling_endpoint['get']['responses']['200']['content']['application/json']['schema']
        assert 'messages' in response_schema['properties'], "Polling should return messages array"

        messages_schema = response_schema['properties']['messages']
        assert '$ref' in messages_schema['items'], "Messages should reference WebSocketMessage schema"
        assert 'WebSocketMessage' in messages_schema['items']['$ref'], "Should use WebSocketMessage schema"

    def test_websocket_diagnostics_documented(self, openapi_spec):
        """Test that WebSocket diagnostics endpoint is documented"""
        diag_endpoint = openapi_spec['paths']['/api/websocket/debug/connection-test']

        response_schema = diag_endpoint['get']['responses']['200']['content']['application/json']['schema']
        properties = response_schema['properties']

        assert 'origin_allowed' in properties, "Should check if origin is allowed"
        assert 'websocket_supported' in properties, "Should check WebSocket support"
        assert 'suggestions' in properties, "Should provide troubleshooting suggestions"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
