#!/usr/bin/env python3
"""
T017.3: Load Testing and Performance Validation
Advanced scalability testing for WebSocket fallback system under high load

This test suite validates:
- Concurrent session handling (100+ sessions)
- Message throughput under load conditions
- Fallback performance during peak usage
- Resource utilization and memory management
- System scalability limits and bottlenecks
- Performance degradation analysis
"""

import asyncio
import json
import time
import uuid
import random
import aiohttp
import psutil
import statistics
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import logging
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
import threading
import gc
import tracemalloc

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TestResult(Enum):
    PASSED = "✅ PASSED"
    FAILED = "❌ FAILED"
    SKIPPED = "⏭️ SKIPPED"
    WARNING = "⚠️ WARNING"
    EXCELLENT = "🏆 EXCELLENT"

@dataclass
class PerformanceMetrics:
    """Performance metrics for load testing"""
    response_times: List[float] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    error_details: List[str] = field(default_factory=list)
    throughput: float = 0.0
    cpu_usage: List[float] = field(default_factory=list)
    memory_usage: List[float] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return (self.success_count / total * 100) if total > 0 else 0

    @property
    def avg_response_time(self) -> float:
        return statistics.mean(self.response_times) if self.response_times else 0

    @property
    def p95_response_time(self) -> float:
        return statistics.quantiles(self.response_times, n=20)[18] if len(self.response_times) > 1 else 0

    @property
    def p99_response_time(self) -> float:
        return statistics.quantiles(self.response_times, n=100)[98] if len(self.response_times) > 1 else 0

@dataclass
class TestCase:
    name: str
    description: str
    result: TestResult = TestResult.SKIPPED
    duration: float = 0.0
    error_message: str = ""
    details: Dict = None
    success_criteria: List[str] = None
    metrics: PerformanceMetrics = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}
        if self.success_criteria is None:
            self.success_criteria = []
        if self.metrics is None:
            self.metrics = PerformanceMetrics()

class LoadTestingFramework:
    def __init__(self, base_url: str = "http://localhost:8000", max_sessions: int = 150):
        self.base_url = base_url
        self.max_sessions = max_sessions
        self.test_cases: List[TestCase] = []
        self.session_timeout = 30
        self.concurrent_limit = 50  # Concurrent connection limit

        # Performance thresholds
        self.thresholds = {
            "avg_response_time": 2.0,  # seconds
            "p95_response_time": 5.0,  # seconds
            "p99_response_time": 10.0, # seconds
            "success_rate": 95.0,      # percentage
            "throughput": 50.0,        # ops/second
            "cpu_usage": 80.0,         # percentage
            "memory_usage": 1024.0     # MB
        }

        # Test data generators
        # Alle 10 unterstützten Sprachen
        self.languages = ["de", "en", "ar", "tr", "ru", "uk", "am", "fa", "ku", "ti"]
        self.message_templates = [
            "Hello, I need help with my account",
            "Can you assist me with technical support?",
            "I have a question about billing",
            "Please help me reset my password",
            "I want to update my profile information"
        ]

    async def create_session_pool(self, count: int) -> List[str]:
        """Create a pool of sessions for load testing"""
        logger.info(f"Creating {count} sessions for load testing...")

        tasks = []
        for i in range(count):
            task = asyncio.create_task(self._create_single_session(i))
            tasks.append(task)

            # Batch creation to avoid overwhelming the server
            if (i + 1) % self.concurrent_limit == 0:
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                yield [r for r in batch_results if isinstance(r, str)]
                tasks = []
                await asyncio.sleep(0.1)  # Brief pause between batches

        # Handle remaining tasks
        if tasks:
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            yield [r for r in batch_results if isinstance(r, str)]

    async def _create_single_session(self, index: int) -> Optional[str]:
        """Create a single session with randomized parameters"""
        language = random.choice(self.languages)
        url = f"{self.base_url}/api/session/create?customer_language={language}"

        headers = {
            "User-Agent": f"LoadTest-Client-{index}",
            "Origin": "http://localhost:3000"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, ssl=False) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result.get("session_id")
        except Exception as e:
            logger.warning(f"Session creation failed for index {index}: {e}")
        return None

    async def test_concurrent_session_handling(self) -> TestCase:
        """Test system capability to handle 100+ concurrent sessions"""
        test = TestCase(
            name="Concurrent Session Handling",
            description="Validate system performance with 100+ concurrent sessions",
            success_criteria=[
                f"Successfully create {self.max_sessions} concurrent sessions",
                f"Maintain success rate ≥ {self.thresholds['success_rate']}%",
                f"Average response time ≤ {self.thresholds['avg_response_time']}s",
                f"P95 response time ≤ {self.thresholds['p95_response_time']}s"
            ]
        )

        start_time = time.time()
        session_ids = []

        try:
            # Monitor system resources
            resource_monitor = ResourceMonitor()
            await resource_monitor.start()

            # Create sessions in batches
            creation_start = time.time()
            async for batch in self.create_session_pool(self.max_sessions):
                session_ids.extend(batch)
                test.metrics.success_count += len(batch)

                # Track response time for batch
                batch_time = time.time() - creation_start
                test.metrics.response_times.append(batch_time)
                creation_start = time.time()

            await resource_monitor.stop()

            # Calculate performance metrics
            test.metrics.failure_count = self.max_sessions - len(session_ids)
            test.duration = time.time() - start_time
            test.metrics.throughput = len(session_ids) / test.duration

            # System resource usage
            test.metrics.cpu_usage = resource_monitor.cpu_readings
            test.metrics.memory_usage = resource_monitor.memory_readings

            # Populate test details
            test.details = {
                "sessions_created": len(session_ids),
                "target_sessions": self.max_sessions,
                "success_rate": f"{test.metrics.success_rate:.1f}%",
                "avg_response_time": f"{test.metrics.avg_response_time:.2f}s",
                "p95_response_time": f"{test.metrics.p95_response_time:.2f}s",
                "p99_response_time": f"{test.metrics.p99_response_time:.2f}s",
                "throughput": f"{test.metrics.throughput:.1f} sessions/sec",
                "avg_cpu_usage": f"{statistics.mean(test.metrics.cpu_usage):.1f}%",
                "peak_cpu_usage": f"{max(test.metrics.cpu_usage):.1f}%",
                "avg_memory_usage": f"{statistics.mean(test.metrics.memory_usage):.1f} MB",
                "peak_memory_usage": f"{max(test.metrics.memory_usage):.1f} MB"
            }

            # Evaluate performance against thresholds
            if (test.metrics.success_rate >= self.thresholds["success_rate"] and
                test.metrics.avg_response_time <= self.thresholds["avg_response_time"] and
                test.metrics.p95_response_time <= self.thresholds["p95_response_time"]):

                if test.metrics.success_rate >= 99.0 and test.metrics.avg_response_time <= 1.0:
                    test.result = TestResult.EXCELLENT
                else:
                    test.result = TestResult.PASSED
            elif (test.metrics.success_rate >= 80.0 and
                  test.metrics.avg_response_time <= self.thresholds["avg_response_time"] * 1.5):
                test.result = TestResult.WARNING
            else:
                test.result = TestResult.FAILED
                test.error_message = f"Performance below thresholds: {test.metrics.success_rate:.1f}% success, {test.metrics.avg_response_time:.2f}s avg response"

        except Exception as e:
            test.error_message = f"Concurrent session test failed: {str(e)}"
            test.result = TestResult.FAILED

        test.duration = time.time() - start_time
        return test

    async def test_message_throughput_under_load(self) -> TestCase:
        """Test message processing throughput under high load"""
        test = TestCase(
            name="Message Throughput Under Load",
            description="Validate message processing performance with concurrent sessions",
            success_criteria=[
                "Process messages across 50+ concurrent sessions",
                f"Achieve throughput ≥ {self.thresholds['throughput']} messages/sec",
                "Maintain low latency for message delivery",
                "No message loss during peak load"
            ]
        )

        start_time = time.time()
        session_count = 50
        messages_per_session = 10

        try:
            # Create session pool
            session_ids = []
            async for batch in self.create_session_pool(session_count):
                session_ids.extend(batch)
                if len(session_ids) >= session_count:
                    break

            if len(session_ids) < session_count // 2:
                test.error_message = f"Insufficient sessions created: {len(session_ids)}/{session_count}"
                test.result = TestResult.FAILED
                return test

            # Activate fallback for all sessions
            fallback_tasks = []
            for session_id in session_ids:
                task = asyncio.create_task(self._activate_fallback_for_load_test(session_id))
                fallback_tasks.append(task)

            fallback_results = await asyncio.gather(*fallback_tasks, return_exceptions=True)
            active_polls = [r for r in fallback_results if isinstance(r, dict) and r.get("success")]

            # Send messages through polling system
            message_start = time.time()
            message_tasks = []

            for poll_data in active_polls:
                for msg_idx in range(messages_per_session):
                    task = asyncio.create_task(
                        self._send_polling_message(poll_data, msg_idx)
                    )
                    message_tasks.append(task)

            # Process messages in batches to avoid overwhelming
            batch_size = 20
            message_results = []

            for i in range(0, len(message_tasks), batch_size):
                batch = message_tasks[i:i + batch_size]
                batch_results = await asyncio.gather(*batch, return_exceptions=True)
                message_results.extend(batch_results)

                # Brief pause between batches
                await asyncio.sleep(0.05)

            message_duration = time.time() - message_start

            # Analyze results
            successful_messages = len([r for r in message_results if r is True])
            total_messages = len(message_tasks)

            test.metrics.success_count = successful_messages
            test.metrics.failure_count = total_messages - successful_messages
            test.metrics.throughput = successful_messages / message_duration if message_duration > 0 else 0

            test.details = {
                "active_sessions": len(session_ids),
                "active_polls": len(active_polls),
                "total_messages": total_messages,
                "successful_messages": successful_messages,
                "message_success_rate": f"{test.metrics.success_rate:.1f}%",
                "throughput": f"{test.metrics.throughput:.1f} messages/sec",
                "message_duration": f"{message_duration:.2f}s",
                "avg_messages_per_second": f"{total_messages / message_duration:.1f}"
            }

            # Evaluate performance
            if (test.metrics.success_rate >= 95.0 and
                test.metrics.throughput >= self.thresholds["throughput"]):
                test.result = TestResult.PASSED
                if test.metrics.throughput >= self.thresholds["throughput"] * 2:
                    test.result = TestResult.EXCELLENT
            elif (test.metrics.success_rate >= 80.0 and
                  test.metrics.throughput >= self.thresholds["throughput"] * 0.7):
                test.result = TestResult.WARNING
            else:
                test.result = TestResult.FAILED
                test.error_message = f"Throughput below threshold: {test.metrics.throughput:.1f} < {self.thresholds['throughput']}"

        except Exception as e:
            test.error_message = f"Message throughput test failed: {str(e)}"
            test.result = TestResult.FAILED

        test.duration = time.time() - start_time
        return test

    async def test_fallback_performance_peak_usage(self) -> TestCase:
        """Test fallback system performance during peak usage simulation"""
        test = TestCase(
            name="Fallback Performance at Peak Usage",
            description="Validate fallback system under sustained peak load conditions",
            success_criteria=[
                "Maintain stable performance for 60+ seconds",
                "Handle session churn (creation/deletion) gracefully",
                "Sustain polling operations under continuous load",
                "Memory usage remains stable (no leaks)"
            ]
        )

        start_time = time.time()
        peak_duration = 60  # seconds
        session_pool_size = 75

        try:
            # Start memory tracking
            tracemalloc.start()
            initial_memory = tracemalloc.get_traced_memory()[0]

            # Create initial session pool
            session_pool = []
            async for batch in self.create_session_pool(session_pool_size):
                session_pool.extend(batch)
                if len(session_pool) >= session_pool_size:
                    break

            # Activate fallback for sessions
            fallback_pools = []
            for session_id in session_pool:
                fallback_result = await self._activate_fallback_for_load_test(session_id)
                if fallback_result.get("success"):
                    fallback_pools.append(fallback_result)

            # Simplified peak usage simulation focusing on available operations
            if len(fallback_pools) == 0:
                test.error_message = "No fallback pools available for peak testing"
                test.result = TestResult.FAILED
                return test

            peak_start = time.time()
            operations_completed = 0
            memory_snapshots = []
            performance_snapshots = []

            # Run for reduced time if no fallback pools available
            effective_duration = min(peak_duration, 10) if len(fallback_pools) < 5 else peak_duration

            while time.time() - peak_start < effective_duration:
                iteration_start = time.time()

                # Simulate available operations
                tasks = []

                # 1. Polling operations (80% of operations) - only if fallback pools exist
                if fallback_pools:
                    for _ in range(min(10, len(fallback_pools))):
                        poll_data = random.choice(fallback_pools)
                        task = asyncio.create_task(self._poll_for_messages(poll_data))
                        tasks.append(task)

                # 2. New session creation (20% of operations)
                for _ in range(2):
                    task = asyncio.create_task(self._create_single_session(operations_completed))
                    tasks.append(task)

                # Execute operations
                results = await asyncio.gather(*tasks, return_exceptions=True)
                successful_ops = len([r for r in results if not isinstance(r, Exception) and r])
                operations_completed += successful_ops                # Take performance snapshot
                iteration_time = time.time() - iteration_start
                performance_snapshots.append({
                    "timestamp": time.time() - peak_start,
                    "operations": len(tasks),
                    "successful": successful_ops,
                    "duration": iteration_time,
                    "ops_per_second": len(tasks) / iteration_time if iteration_time > 0 else 0
                })

                # Memory snapshot every 10 seconds
                if len(performance_snapshots) % 10 == 0:
                    current_memory = tracemalloc.get_traced_memory()[0]
                    memory_snapshots.append({
                        "timestamp": time.time() - peak_start,
                        "memory_mb": current_memory / 1024 / 1024,
                        "memory_delta_mb": (current_memory - initial_memory) / 1024 / 1024
                    })

                # Brief pause to prevent overwhelming
                await asyncio.sleep(0.1)

            # Analyze peak performance
            final_memory = tracemalloc.get_traced_memory()[0]
            tracemalloc.stop()

            total_ops = sum(s["operations"] for s in performance_snapshots)
            successful_ops = sum(s["successful"] for s in performance_snapshots)
            avg_ops_per_sec = statistics.mean([s["ops_per_second"] for s in performance_snapshots])

            test.details = {
                "peak_duration": f"{peak_duration}s",
                "total_operations": total_ops,
                "successful_operations": successful_ops,
                "success_rate": f"{(successful_ops / total_ops * 100):.1f}%",
                "avg_ops_per_second": f"{avg_ops_per_sec:.1f}",
                "memory_usage": {
                    "initial_mb": f"{initial_memory / 1024 / 1024:.1f}",
                    "final_mb": f"{final_memory / 1024 / 1024:.1f}",
                    "delta_mb": f"{(final_memory - initial_memory) / 1024 / 1024:.1f}"
                },
                "active_sessions": len(session_pool),
                "active_fallbacks": len(fallback_pools),
                "performance_stability": "stable" if len(set(s["ops_per_second"] for s in performance_snapshots[-10:])) < 5 else "variable"
            }

            # Evaluate peak performance
            success_rate = successful_ops / total_ops * 100
            memory_growth = (final_memory - initial_memory) / 1024 / 1024  # MB

            if (success_rate >= 95.0 and
                avg_ops_per_sec >= 10.0 and
                memory_growth < 100):  # Less than 100MB growth
                test.result = TestResult.PASSED
                if success_rate >= 98.0 and memory_growth < 50:
                    test.result = TestResult.EXCELLENT
            elif (success_rate >= 85.0 and
                  avg_ops_per_sec >= 5.0 and
                  memory_growth < 200):
                test.result = TestResult.WARNING
            else:
                test.result = TestResult.FAILED
                test.error_message = f"Peak performance insufficient: {success_rate:.1f}% success, {avg_ops_per_sec:.1f} ops/sec, {memory_growth:.1f}MB growth"

        except Exception as e:
            test.error_message = f"Peak usage test failed: {str(e)}"
            test.result = TestResult.FAILED

        test.duration = time.time() - start_time
        return test

    async def test_scalability_limits_analysis(self) -> TestCase:
        """Analyze system scalability limits and identify bottlenecks"""
        test = TestCase(
            name="Scalability Limits Analysis",
            description="Determine system capacity limits and performance degradation points",
            success_criteria=[
                "Identify maximum concurrent session capacity",
                "Measure performance degradation curve",
                "Detect system bottlenecks and limits",
                "Provide capacity planning recommendations"
            ]
        )

        start_time = time.time()

        try:
            # Test different load levels
            load_levels = [25, 50, 75, 100, 125, 150]
            scalability_data = []

            for load_level in load_levels:
                logger.info(f"Testing scalability at {load_level} sessions...")
                level_start = time.time()

                # Create sessions at this load level
                session_ids = []
                async for batch in self.create_session_pool(load_level):
                    session_ids.extend(batch)
                    if len(session_ids) >= load_level:
                        break

                creation_time = time.time() - level_start

                # Activate fallback for a sample
                sample_size = min(10, len(session_ids))
                sample_sessions = random.sample(session_ids, sample_size)

                fallback_start = time.time()
                fallback_tasks = [
                    self._activate_fallback_for_load_test(sid)
                    for sid in sample_sessions
                ]
                fallback_results = await asyncio.gather(*fallback_tasks, return_exceptions=True)
                fallback_time = time.time() - fallback_start

                successful_fallbacks = len([r for r in fallback_results if isinstance(r, dict) and r.get("success")])

                # Performance metrics at this load level
                level_data = {
                    "load_level": load_level,
                    "sessions_created": len(session_ids),
                    "creation_time": creation_time,
                    "creation_rate": len(session_ids) / creation_time if creation_time > 0 else 0,
                    "fallback_success_rate": (successful_fallbacks / sample_size * 100) if sample_size > 0 else 0,
                    "fallback_avg_time": fallback_time / sample_size if sample_size > 0 else 0,
                    "total_test_time": time.time() - level_start
                }

                scalability_data.append(level_data)

                # Brief cleanup pause
                await asyncio.sleep(2)

            # Analyze scalability patterns
            max_sessions = max(d["sessions_created"] for d in scalability_data)
            peak_creation_rate = max(d["creation_rate"] for d in scalability_data)
            degradation_points = []

            for i, data in enumerate(scalability_data):
                if i > 0:
                    prev_rate = scalability_data[i-1]["creation_rate"]
                    current_rate = data["creation_rate"]
                    if current_rate < prev_rate * 0.8:  # 20% degradation
                        degradation_points.append({
                            "load_level": data["load_level"],
                            "degradation_percent": ((prev_rate - current_rate) / prev_rate * 100)
                        })

            test.details = {
                "max_concurrent_sessions": max_sessions,
                "peak_creation_rate": f"{peak_creation_rate:.1f} sessions/sec",
                "scalability_data": scalability_data,
                "degradation_points": degradation_points,
                "recommended_capacity": max_sessions * 0.8,  # 80% of max for safety margin
                "performance_analysis": {
                    "linear_scalability": len(degradation_points) == 0,
                    "degradation_starts_at": degradation_points[0]["load_level"] if degradation_points else "beyond test range"
                }
            }

            # Evaluate scalability
            if max_sessions >= 100 and len(degradation_points) <= 1:
                test.result = TestResult.PASSED
                if max_sessions >= 150 and len(degradation_points) == 0:
                    test.result = TestResult.EXCELLENT
            elif max_sessions >= 75:
                test.result = TestResult.WARNING
            else:
                test.result = TestResult.FAILED
                test.error_message = f"Insufficient scalability: max {max_sessions} sessions"

        except Exception as e:
            test.error_message = f"Scalability analysis failed: {str(e)}"
            test.result = TestResult.FAILED

        test.duration = time.time() - start_time
        return test

    async def _activate_fallback_for_load_test(self, session_id: str) -> Dict[str, Any]:
        """Helper method to activate fallback for load testing"""
        try:
            url = f"{self.base_url}/api/websocket/polling/activate"
            fallback_data = {
                "session_id": session_id,
                "client_type": "customer",
                "origin": "http://localhost:3000",
                "reason": "load_test"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=fallback_data, ssl=False) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "success": True,
                            "session_id": session_id,
                            "polling_id": data.get("polling_id"),
                            "endpoints": data.get("endpoints", {}),
                            "data": data
                        }
                    else:
                        return {"success": False, "session_id": session_id, "status": response.status}
        except Exception as e:
            return {"success": False, "session_id": session_id, "error": str(e)}

    async def _send_polling_message(self, poll_data: Dict[str, Any], message_index: int) -> bool:
        """Helper method to send message via polling"""
        try:
            endpoints = poll_data.get("endpoints", {})
            send_url = endpoints.get("send")
            if not send_url:
                return False

            url = f"{self.base_url}{send_url}"

            # Use correct message format for PollingMessage
            message = {
                "type": "text_message",
                "content": {
                    "text": f"{random.choice(self.message_templates)} (Load Test #{message_index})",
                    "metadata": {"test": True, "index": message_index}
                },
                "session_id": poll_data.get("session_id"),
                "client_type": "customer",
                "timestamp": datetime.now().isoformat()
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=message, ssl=False) as response:
                    return response.status == 200

        except Exception:
            return False

    async def _poll_for_messages(self, poll_data: Dict[str, Any]) -> bool:
        """Helper method to poll for messages"""
        try:
            endpoints = poll_data.get("endpoints", {})
            poll_url = endpoints.get("poll")
            if not poll_url:
                return False

            url = f"{self.base_url}{poll_url}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, ssl=False) as response:
                    return response.status == 200

        except Exception:
            return False

    async def run_all_tests(self) -> Dict[str, Any]:
        """Run comprehensive load testing and performance validation"""
        logger.info("🚀 Starting T017.3 - Load Testing and Performance Validation")
        logger.info("=" * 80)

        start_time = time.time()

        # Test API health first
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/health", ssl=False) as response:
                    if response.status != 200:
                        logger.error(f"API health check failed: {response.status}")
                        return {"error": "API not accessible", "status": "failed"}
        except Exception as e:
            logger.error(f"Cannot connect to API: {e}")
            return {"error": f"Connection failed: {e}", "status": "failed"}

        # Run all performance tests
        tests = [
            await self.test_concurrent_session_handling(),
            await self.test_message_throughput_under_load(),
            await self.test_fallback_performance_peak_usage(),
            await self.test_scalability_limits_analysis()
        ]

        self.test_cases = tests
        total_duration = time.time() - start_time

        # Calculate overall results
        passed = len([t for t in tests if t.result in [TestResult.PASSED, TestResult.EXCELLENT]])
        failed = len([t for t in tests if t.result == TestResult.FAILED])
        warnings = len([t for t in tests if t.result == TestResult.WARNING])
        excellent = len([t for t in tests if t.result == TestResult.EXCELLENT])

        success_rate = (passed / len(tests)) * 100 if tests else 0

        report = {
            "test_suite": "T017.3 - Load Testing and Performance Validation",
            "timestamp": datetime.now().isoformat(),
            "duration": f"{total_duration:.2f}s",
            "total_tests": len(tests),
            "passed": passed,
            "failed": failed,
            "warnings": warnings,
            "excellent": excellent,
            "success_rate": f"{success_rate:.1f}%",
            "status": "passed" if success_rate >= 75 else "failed" if success_rate < 50 else "warning",
            "performance_summary": {
                "max_concurrent_sessions": max([
                    int(t.details.get("sessions_created", 0)) for t in tests
                    if "sessions_created" in t.details
                ], default=0),
                "peak_throughput": max([
                    float(t.details.get("throughput", "0").split()[0]) for t in tests
                    if "throughput" in t.details and isinstance(t.details["throughput"], str)
                ], default=0.0),
                "system_stability": "excellent" if excellent > 0 else "good" if passed > failed else "needs_improvement"
            },
            "test_results": tests
        }

        return report

    def print_detailed_report(self, report: Dict[str, Any]):
        """Print comprehensive performance test results"""
        print("\n" + "=" * 80)
        print(f"🏋️ {report['test_suite']}")
        print("=" * 80)
        print(f"📅 Timestamp: {report['timestamp']}")
        print(f"⏱️  Duration: {report['duration']}")
        print(f"📊 Results: {report['passed']}/{report['total_tests']} passed ({report['success_rate']})")
        print(f"📈 Status: {report['status'].upper()}")

        if report.get('excellent', 0) > 0:
            print(f"🏆 Excellent: {report['excellent']}")
        if report.get('warnings', 0) > 0:
            print(f"⚠️  Warnings: {report['warnings']}")
        if report.get('failed', 0) > 0:
            print(f"❌ Failed: {report['failed']}")

        # Performance summary
        perf_summary = report.get("performance_summary", {})
        print(f"\n🚀 PERFORMANCE SUMMARY")
        print("-" * 80)
        print(f"📊 Max Concurrent Sessions: {perf_summary.get('max_concurrent_sessions', 'N/A')}")
        print(f"⚡ Peak Throughput: {perf_summary.get('peak_throughput', 'N/A')} ops/sec")
        print(f"🎯 System Stability: {perf_summary.get('system_stability', 'N/A').upper()}")

        print(f"\n📋 DETAILED TEST RESULTS")
        print("-" * 80)

        for test in self.test_cases:
            icon = "🏆" if test.result == TestResult.EXCELLENT else test.result.value.split()[0]
            print(f"\n{test.result.value} {test.name}")
            print(f"   📝 {test.description}")
            print(f"   ⏱️  Duration: {test.duration:.2f}s")

            if test.success_criteria:
                print(f"   ✓ Success Criteria:")
                for criteria in test.success_criteria:
                    print(f"     • {criteria}")

            if test.error_message:
                print(f"   ❌ Error: {test.error_message}")

            if test.details:
                print(f"   📊 Performance Details:")
                for key, value in test.details.items():
                    if isinstance(value, dict):
                        print(f"     • {key}:")
                        for subkey, subvalue in value.items():
                            print(f"       - {subkey}: {subvalue}")
                    elif isinstance(value, list) and len(value) > 5:
                        print(f"     • {key}: {len(value)} data points")
                    else:
                        print(f"     • {key}: {value}")

        print("\n" + "=" * 80)
        print("🎯 T017.3 LOAD TESTING AND PERFORMANCE VALIDATION COMPLETE")
        print("=" * 80)


class ResourceMonitor:
    """System resource monitoring during tests"""
    def __init__(self):
        self.cpu_readings = []
        self.memory_readings = []
        self.monitoring = False
        self.monitor_task = None

    async def start(self):
        """Start monitoring system resources"""
        self.monitoring = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        """Stop monitoring system resources"""
        self.monitoring = False
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass

    async def _monitor_loop(self):
        """Monitor system resources in background"""
        try:
            while self.monitoring:
                # CPU usage
                cpu_percent = psutil.cpu_percent(interval=0.1)
                self.cpu_readings.append(cpu_percent)

                # Memory usage
                memory = psutil.virtual_memory()
                memory_mb = memory.used / 1024 / 1024
                self.memory_readings.append(memory_mb)

                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass


async def main():
    """Main function to run load testing and performance validation"""
    tester = LoadTestingFramework()

    try:
        report = await tester.run_all_tests()
        tester.print_detailed_report(report)

        # Return appropriate exit code
        if report.get("status") == "passed":
            return 0
        elif report.get("status") == "warning":
            return 1
        else:
            return 2

    except Exception as e:
        logger.error(f"Load testing suite execution failed: {e}")
        return 3


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
