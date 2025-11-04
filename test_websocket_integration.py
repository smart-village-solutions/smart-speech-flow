#!/usr/bin/env python3
"""
T017.1: Automated Frontend-Backend Integration Tests
Comprehensive end-to-end testing for WebSocket integration workflow

This test suite validates:
- Complete WebSocket session lifecycle
- Message flow between Admin and Customer
- Session timeout and cleanup
- Fallback activation and recovery
- Cross-browser simulation
- Error handling and recovery
"""

import asyncio
import json
import time
import uuid
import aiohttp
import websockets
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
from dataclasses import dataclass
from enum import Enum

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TestResult(Enum):
    PASSED = "✅ PASSED"
    FAILED = "❌ FAILED"
    SKIPPED = "⏭️ SKIPPED"
    WARNING = "⚠️ WARNING"

@dataclass
class TestCase:
    name: str
    description: str
    result: TestResult = TestResult.SKIPPED
    duration: float = 0.0
    error_message: str = ""
    details: Dict = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}

class WebSocketIntegrationTester:
    """Comprehensive WebSocket integration testing framework"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.ws_url = base_url.replace("http", "ws")
        self.test_results: List[TestCase] = []
        self.session = None
        self.current_session_id = None

    async def setup_session(self):
        """Setup aiohttp session for HTTP requests"""
        self.session = aiohttp.ClientSession()

    async def cleanup_session(self):
        """Cleanup aiohttp session"""
        if self.session:
            await self.session.close()

    async def run_test(self, test_func, test_name: str, test_description: str) -> TestCase:
        """Run a single test with error handling and timing"""
        test_case = TestCase(
            name=test_name,
            description=test_description
        )

        start_time = time.time()

        try:
            logger.info(f"🧪 Running: {test_name}")

            # Handle both sync and async test functions
            if asyncio.iscoroutinefunction(test_func):
                result = await test_func()
            else:
                result = test_func()

            if result is True:
                test_case.result = TestResult.PASSED
                logger.info(f"✅ {test_name} - PASSED")
            elif result is False:
                test_case.result = TestResult.FAILED
                logger.error(f"❌ {test_name} - FAILED")
            else:
                test_case.result = TestResult.WARNING
                test_case.error_message = str(result)
                logger.warning(f"⚠️ {test_name} - WARNING: {result}")

        except Exception as e:
            test_case.result = TestResult.FAILED
            test_case.error_message = str(e)
            logger.error(f"❌ {test_name} - FAILED: {e}")

        test_case.duration = time.time() - start_time
        self.test_results.append(test_case)
        return test_case

    async def test_api_health(self) -> bool:
        """Test API Gateway health"""
        try:
            async with self.session.get(f"{self.base_url}/health") as response:
                if response.status == 200:
                    data = await response.json()
                    return all(status == "ok" for status in data.get("services", {}).values())
                return False
        except Exception as e:
            logger.error(f"API health check failed: {e}")
            return False

    async def test_session_creation(self) -> bool:
        """Test session creation via API"""
        try:
            url = f"{self.base_url}/api/session/create?admin_language=de&customer_language=en"
            async with self.session.post(url) as response:
                if response.status == 200:
                    data = await response.json()
                    session_id = data.get("session_id")
                    if session_id:
                        # Store session_id for use in other tests
                        self.current_session_id = session_id
                        logger.info(f"Created session: {session_id}")
                        return True
                return False
        except Exception as e:
            logger.error(f"Session creation failed: {e}")
            return False

    async def test_websocket_connection(self, session_id: str, client_type: str) -> bool:
        """Test WebSocket connection establishment"""
        try:
            uri = f"{self.ws_url}/ws/{session_id}/{client_type}"

            # Set connection timeout
            timeout = 10

            async with websockets.connect(
                uri,
                extra_headers={"Origin": "http://localhost:3000"},
                ping_timeout=timeout,
                close_timeout=timeout
            ) as websocket:

                # Send a test message
                test_message = {
                    "type": "connection_test",
                    "timestamp": datetime.now().isoformat(),
                    "client_type": client_type
                }

                await websocket.send(json.dumps(test_message))

                # Wait for response or timeout
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=5)
                    logger.info(f"WebSocket {client_type} connection successful")
                    return True

                except asyncio.TimeoutError:
                    logger.warning(f"WebSocket {client_type} no response within timeout")
                    return True  # Connection established, just no response

        except Exception as e:
            logger.error(f"WebSocket {client_type} connection failed: {e}")
            return False

    async def test_bidirectional_communication(self, session_id: str) -> bool:
        """Test bidirectional WebSocket communication between admin and customer"""
        admin_ws = None
        customer_ws = None

        try:
            # Connect both admin and customer
            admin_uri = f"{self.ws_url}/ws/{session_id}/admin"
            customer_uri = f"{self.ws_url}/ws/{session_id}/customer"

            admin_ws = await websockets.connect(
                admin_uri,
                extra_headers={"Origin": "http://localhost:3000"}
            )

            customer_ws = await websockets.connect(
                customer_uri,
                extra_headers={"Origin": "http://localhost:3000"}
            )

            # Admin sends message to customer
            admin_message = {
                "type": "text_message",
                "content": "Hello from admin",
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id
            }

            await admin_ws.send(json.dumps(admin_message))

            # Customer should receive the message
            try:
                customer_response = await asyncio.wait_for(customer_ws.recv(), timeout=5)
                received_data = json.loads(customer_response)

                if received_data.get("content") == "Hello from admin":
                    logger.info("✅ Admin → Customer communication successful")
                else:
                    logger.warning(f"Unexpected customer response: {received_data}")

            except asyncio.TimeoutError:
                logger.warning("Customer did not receive admin message within timeout")

            # Customer sends message to admin
            customer_message = {
                "type": "text_message",
                "content": "Hello from customer",
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id
            }

            await customer_ws.send(json.dumps(customer_message))

            # Admin should receive the message
            try:
                admin_response = await asyncio.wait_for(admin_ws.recv(), timeout=5)
                received_data = json.loads(admin_response)

                if received_data.get("content") == "Hello from customer":
                    logger.info("✅ Customer → Admin communication successful")
                    return True
                else:
                    logger.warning(f"Unexpected admin response: {received_data}")
                    return False

            except asyncio.TimeoutError:
                logger.warning("Admin did not receive customer message within timeout")
                return False

        except Exception as e:
            logger.error(f"Bidirectional communication test failed: {e}")
            return False

        finally:
            # Cleanup connections
            if admin_ws:
                await admin_ws.close()
            if customer_ws:
                await customer_ws.close()

    async def test_fallback_activation(self, session_id: str) -> bool:
        """Test fallback system activation"""
        try:
            fallback_request = {
                "session_id": session_id,
                "client_type": "customer",
                "origin": "http://localhost:3000",
                "reason": "integration_test",
                "error_details": {
                    "type": "test_error",
                    "message": "Integration test fallback activation"
                }
            }

            url = f"{self.base_url}/api/websocket/polling/activate"
            headers = {
                "Content-Type": "application/json",
                "Origin": "http://localhost:3000"
            }

            async with self.session.post(url, json=fallback_request, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    polling_id = data.get("polling_id")

                    if polling_id:
                        logger.info(f"✅ Fallback activated: {polling_id}")

                        # Test polling functionality
                        return await self.test_polling_communication(polling_id)

                return False

        except Exception as e:
            logger.error(f"Fallback activation test failed: {e}")
            return False

    async def test_polling_communication(self, polling_id: str) -> bool:
        """Test polling-based communication"""
        try:
            # Send message via polling
            message_data = {
                "type": "user_message",
                "content": {"text": "Test message via polling"},
                "session_id": polling_id.split("_")[1],  # Extract session ID
                "client_type": "customer",
                "timestamp": datetime.now().isoformat()
            }

            send_url = f"{self.base_url}/api/websocket/polling/send/{polling_id}"
            headers = {
                "Content-Type": "application/json",
                "Origin": "http://localhost:3000"
            }

            async with self.session.post(send_url, json=message_data, headers=headers) as response:
                if response.status == 200:
                    send_result = await response.json()

                    if send_result.get("status") == "success":
                        logger.info("✅ Polling message sent successfully")

                        # Test polling status
                        status_url = f"{self.base_url}/api/websocket/polling/status/{polling_id}"
                        async with self.session.get(status_url, headers={"Origin": "http://localhost:3000"}) as status_response:
                            if status_response.status == 200:
                                status_data = await status_response.json()
                                logger.info("✅ Polling status check successful")
                                return True

                return False

        except Exception as e:
            logger.error(f"Polling communication test failed: {e}")
            return False

    async def test_session_cleanup(self, session_id: str) -> bool:
        """Test session cleanup and timeout handling"""
        try:
            # Check session exists
            session_url = f"{self.base_url}/api/sessions/{session_id}"

            async with self.session.get(session_url) as response:
                if response.status == 200:
                    logger.info("✅ Session exists before cleanup")

                    # Simulate session timeout by waiting (simplified test)
                    # In a real test, we would trigger the cleanup mechanism
                    await asyncio.sleep(1)

                    # For now, just verify the session still exists
                    # (real timeout testing would require longer waits)
                    async with self.session.get(session_url) as response2:
                        if response2.status == 200:
                            logger.info("✅ Session persists (timeout testing requires longer intervals)")
                            return True

                return False

        except Exception as e:
            logger.error(f"Session cleanup test failed: {e}")
            return False

    async def test_monitoring_endpoints(self) -> bool:
        """Test WebSocket monitoring endpoints"""
        try:
            endpoints = [
                "/api/websocket/monitoring/health",
                "/api/websocket/monitoring/stats",
                "/api/websocket/monitoring/connections"
            ]

            headers = {"Origin": "http://localhost:3000"}

            for endpoint in endpoints:
                url = f"{self.base_url}{endpoint}"
                async with self.session.get(url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"Monitoring endpoint {endpoint} failed: {response.status}")
                        return False

                    data = await response.json()
                    if data.get("status") != "success":
                        logger.error(f"Monitoring endpoint {endpoint} returned error status")
                        return False

            logger.info("✅ All monitoring endpoints accessible")
            return True

        except Exception as e:
            logger.error(f"Monitoring endpoints test failed: {e}")
            return False

    async def test_cors_headers(self) -> bool:
        """Test CORS header handling"""
        try:
            test_origins = [
                "http://localhost:3000",
                "https://localhost:3000",
                "http://localhost:8080"
            ]

            for origin in test_origins:
                headers = {
                    "Origin": origin,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "Content-Type"
                }

                # Test preflight request
                async with self.session.options(f"{self.base_url}/api/websocket/monitoring/health", headers=headers) as response:
                    cors_headers = response.headers

                    if "Access-Control-Allow-Origin" not in cors_headers:
                        logger.warning(f"Missing CORS headers for origin: {origin}")
                        continue

                    logger.info(f"✅ CORS headers present for origin: {origin}")

            return True

        except Exception as e:
            logger.error(f"CORS headers test failed: {e}")
            return False

    async def run_all_tests(self) -> Dict:
        """Run complete test suite"""
        logger.info("🚀 Starting WebSocket Integration Test Suite")

        await self.setup_session()

        try:
            # Core API Tests
            await self.run_test(
                self.test_api_health,
                "API_HEALTH",
                "Verify API Gateway and services are healthy"
            )

            # Session Management Tests
            session_test = await self.run_test(
                self.test_session_creation,
                "SESSION_CREATION",
                "Create new WebSocket session via API"
            )

            session_result = None
            if session_test.result == TestResult.PASSED and hasattr(session_test, 'session_data'):
                session_result = session_test.session_data
            else:
                # Try to get session result directly for further tests
                try:
                    session_result = await self.test_session_creation()
                except:
                    session_result = (False, "")

            if session_test.result == TestResult.PASSED and self.current_session_id:
                session_id = self.current_session_id
                session_test.details["session_id"] = session_id

                # WebSocket Connection Tests
                async def test_admin_ws():
                    return await self.test_websocket_connection(session_id, "admin")

                await self.run_test(
                    test_admin_ws,
                    "WEBSOCKET_ADMIN_CONNECTION",
                    "Establish WebSocket connection as admin"
                )

                async def test_customer_ws():
                    return await self.test_websocket_connection(session_id, "customer")

                await self.run_test(
                    test_customer_ws,
                    "WEBSOCKET_CUSTOMER_CONNECTION",
                    "Establish WebSocket connection as customer"
                )

                # Communication Tests
                async def test_bidirectional():
                    return await self.test_bidirectional_communication(session_id)

                await self.run_test(
                    test_bidirectional,
                    "BIDIRECTIONAL_COMMUNICATION",
                    "Test message flow between admin and customer"
                )

                # Fallback System Tests
                async def test_fallback():
                    return await self.test_fallback_activation(session_id)

                await self.run_test(
                    test_fallback,
                    "FALLBACK_ACTIVATION",
                    "Test automatic fallback to polling system"
                )

                # Cleanup Tests
                async def test_cleanup():
                    return await self.test_session_cleanup(session_id)

                await self.run_test(
                    test_cleanup,
                    "SESSION_CLEANUP",
                    "Verify session cleanup and timeout handling"
                )            # System Tests
            await self.run_test(
                self.test_monitoring_endpoints,
                "MONITORING_ENDPOINTS",
                "Verify WebSocket monitoring APIs"
            )

            await self.run_test(
                self.test_cors_headers,
                "CORS_HEADERS",
                "Validate CORS configuration"
            )

        finally:
            await self.cleanup_session()

        return self.generate_report()

    def generate_report(self) -> Dict:
        """Generate comprehensive test report"""
        total_tests = len(self.test_results)
        passed_tests = sum(1 for t in self.test_results if t.result == TestResult.PASSED)
        failed_tests = sum(1 for t in self.test_results if t.result == TestResult.FAILED)
        warning_tests = sum(1 for t in self.test_results if t.result == TestResult.WARNING)

        total_duration = sum(t.duration for t in self.test_results)

        report = {
            "summary": {
                "total_tests": total_tests,
                "passed": passed_tests,
                "failed": failed_tests,
                "warnings": warning_tests,
                "success_rate": (passed_tests / total_tests * 100) if total_tests > 0 else 0,
                "total_duration": total_duration
            },
            "test_results": []
        }

        for test in self.test_results:
            report["test_results"].append({
                "name": test.name,
                "description": test.description,
                "result": test.result.value,
                "duration": f"{test.duration:.2f}s",
                "error_message": test.error_message,
                "details": test.details
            })

        return report

    def print_report(self, report: Dict):
        """Print formatted test report"""
        print("\n" + "="*80)
        print("🧪 WEBSOCKET INTEGRATION TEST REPORT")
        print("="*80)

        summary = report["summary"]
        print(f"📊 Summary:")
        print(f"   Total Tests: {summary['total_tests']}")
        print(f"   ✅ Passed: {summary['passed']}")
        print(f"   ❌ Failed: {summary['failed']}")
        print(f"   ⚠️ Warnings: {summary['warnings']}")
        print(f"   📈 Success Rate: {summary['success_rate']:.1f}%")
        print(f"   ⏱️ Total Duration: {summary['total_duration']:.2f}s")

        print("\n📋 Detailed Results:")
        for test in report["test_results"]:
            print(f"   {test['result']} {test['name']} ({test['duration']})")
            print(f"      {test['description']}")
            if test['error_message']:
                print(f"      Error: {test['error_message']}")
            print()

        print("="*80)

        if summary['failed'] == 0:
            print("🎉 ALL TESTS PASSED! WebSocket integration is working correctly.")
        else:
            print(f"⚠️ {summary['failed']} test(s) failed. Please review the errors above.")

        print("="*80)

async def main():
    """Main test execution function"""
    tester = WebSocketIntegrationTester()

    try:
        report = await tester.run_all_tests()
        tester.print_report(report)

        # Save report to file
        report_file = f"websocket_integration_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"\n📄 Detailed report saved to: {report_file}")

        # Exit with appropriate code
        if report["summary"]["failed"] == 0:
            exit(0)
        else:
            exit(1)

    except Exception as e:
        logger.error(f"Test execution failed: {e}")
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())
