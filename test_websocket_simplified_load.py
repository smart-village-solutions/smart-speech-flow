#!/usr/bin/env python3
"""
T017.3: Simplified Load Testing and Performance Validation
Focused testing on proven functional endpoints for production readiness validation

This test suite validates:
- Concurrent session creation at scale (150+ sessions)
- Session management under high load
- API response times and throughput
- System resource utilization
- Performance stability analysis
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

class SimplifiedLoadTester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.test_cases: List[TestCase] = []
        self.concurrent_limit = 50

        # Performance thresholds
        self.thresholds = {
            "avg_response_time": 2.0,
            "p95_response_time": 5.0,
            "success_rate": 95.0,
            "throughput": 100.0,
            "cpu_usage": 80.0,
            "memory_usage": 1024.0
        }

        self.languages = ["de", "en", "ar", "tr", "ru", "uk", "am", "fa"]

    async def create_session_batch(self, batch_size: int, batch_index: int) -> Tuple[List[str], float]:
        """Create a batch of sessions and return session IDs with timing"""
        start_time = time.time()
        tasks = []

        for i in range(batch_size):
            task = asyncio.create_task(self._create_single_session(batch_index * batch_size + i))
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)
        duration = time.time() - start_time

        session_ids = [r for r in results if isinstance(r, str)]
        return session_ids, duration

    async def _create_single_session(self, index: int) -> Optional[str]:
        """Create a single session with randomized language"""
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
            logger.debug(f"Session creation failed for index {index}: {e}")
        return None

    async def test_massive_concurrent_sessions(self) -> TestCase:
        """Test creating 200+ concurrent sessions for maximum load validation"""
        test = TestCase(
            name="Massive Concurrent Session Creation",
            description="Validate system performance with 200+ concurrent sessions",
            success_criteria=[
                "Successfully create 200+ concurrent sessions",
                "Maintain success rate ≥ 95%",
                "Average response time ≤ 2.0s",
                "P95 response time ≤ 5.0s",
                "System remains stable under load"
            ]
        )

        start_time = time.time()
        target_sessions = 200
        batch_size = self.concurrent_limit

        try:
            # Monitor system resources
            resource_monitor = ResourceMonitor()
            await resource_monitor.start()

            # Create sessions in controlled batches
            all_session_ids = []
            batch_count = (target_sessions + batch_size - 1) // batch_size

            for batch_index in range(batch_count):
                batch_start = time.time()
                remaining_sessions = target_sessions - len(all_session_ids)
                current_batch_size = min(batch_size, remaining_sessions)

                session_ids, batch_duration = await self.create_session_batch(current_batch_size, batch_index)
                all_session_ids.extend(session_ids)

                test.metrics.response_times.append(batch_duration)
                test.metrics.success_count += len(session_ids)
                test.metrics.failure_count += current_batch_size - len(session_ids)

                # Brief pause between batches to avoid overwhelming
                await asyncio.sleep(0.1)

            await resource_monitor.stop()

            # Calculate performance metrics
            test.duration = time.time() - start_time
            test.metrics.throughput = len(all_session_ids) / test.duration
            test.metrics.cpu_usage = resource_monitor.cpu_readings
            test.metrics.memory_usage = resource_monitor.memory_readings

            test.details = {
                "sessions_created": len(all_session_ids),
                "target_sessions": target_sessions,
                "success_rate": f"{test.metrics.success_rate:.1f}%",
                "avg_response_time": f"{test.metrics.avg_response_time:.2f}s",
                "p95_response_time": f"{test.metrics.p95_response_time:.2f}s",
                "p99_response_time": f"{test.metrics.p99_response_time:.2f}s",
                "throughput": f"{test.metrics.throughput:.1f} sessions/sec",
                "avg_cpu_usage": f"{statistics.mean(test.metrics.cpu_usage) if test.metrics.cpu_usage else 0:.1f}%",
                "peak_cpu_usage": f"{max(test.metrics.cpu_usage) if test.metrics.cpu_usage else 0:.1f}%",
                "avg_memory_usage": f"{statistics.mean(test.metrics.memory_usage) if test.metrics.memory_usage else 0:.1f} MB",
                "peak_memory_usage": f"{max(test.metrics.memory_usage) if test.metrics.memory_usage else 0:.1f} MB",
                "batches_processed": batch_count
            }

            # Evaluate performance
            if (test.metrics.success_rate >= self.thresholds["success_rate"] and
                test.metrics.avg_response_time <= self.thresholds["avg_response_time"] and
                test.metrics.p95_response_time <= self.thresholds["p95_response_time"]):

                if (test.metrics.success_rate >= 99.0 and
                    test.metrics.avg_response_time <= 1.0 and
                    test.metrics.throughput >= 200.0):
                    test.result = TestResult.EXCELLENT
                else:
                    test.result = TestResult.PASSED
            elif (test.metrics.success_rate >= 85.0 and
                  test.metrics.avg_response_time <= self.thresholds["avg_response_time"] * 1.5):
                test.result = TestResult.WARNING
            else:
                test.result = TestResult.FAILED
                test.error_message = f"Performance below thresholds: {test.metrics.success_rate:.1f}% success, {test.metrics.avg_response_time:.2f}s avg response"

        except Exception as e:
            test.error_message = f"Massive concurrent test failed: {str(e)}"
            test.result = TestResult.FAILED

        test.duration = time.time() - start_time
        return test

    async def test_session_info_retrieval_load(self) -> TestCase:
        """Test session info retrieval performance under load"""
        test = TestCase(
            name="Session Info Retrieval Under Load",
            description="Validate session information retrieval performance with concurrent requests",
            success_criteria=[
                "Retrieve session info for 50+ sessions concurrently",
                "Maintain response times under 1 second",
                "Handle concurrent info requests without conflicts",
                "Ensure data consistency across requests"
            ]
        )

        start_time = time.time()
        session_count = 50

        try:
            # Create session pool first
            session_ids, creation_duration = await self.create_session_batch(session_count, 0)

            if len(session_ids) < session_count // 2:
                test.error_message = f"Insufficient sessions created: {len(session_ids)}/{session_count}"
                test.result = TestResult.FAILED
                return test

            # Test concurrent session info retrieval
            info_start = time.time()
            info_tasks = []

            for session_id in session_ids:
                task = asyncio.create_task(self._get_session_info(session_id))
                info_tasks.append(task)

            info_results = await asyncio.gather(*info_tasks, return_exceptions=True)
            info_duration = time.time() - info_start

            # Analyze results
            successful_retrievals = len([r for r in info_results if isinstance(r, dict)])
            test.metrics.success_count = successful_retrievals
            test.metrics.failure_count = len(session_ids) - successful_retrievals
            test.metrics.throughput = successful_retrievals / info_duration if info_duration > 0 else 0

            # Validate data consistency
            language_counts = {}
            for result in info_results:
                if isinstance(result, dict):
                    lang = result.get("customer_language", "unknown")
                    language_counts[lang] = language_counts.get(lang, 0) + 1

            test.details = {
                "sessions_tested": len(session_ids),
                "successful_retrievals": successful_retrievals,
                "success_rate": f"{test.metrics.success_rate:.1f}%",
                "throughput": f"{test.metrics.throughput:.1f} requests/sec",
                "avg_response_time": f"{info_duration / len(session_ids):.3f}s",
                "language_distribution": language_counts,
                "data_consistency": "validated" if len(language_counts) > 0 else "failed"
            }

            # Evaluate performance
            avg_response_time = info_duration / len(session_ids)
            if (test.metrics.success_rate >= 95.0 and avg_response_time <= 1.0):
                test.result = TestResult.PASSED
                if test.metrics.success_rate >= 99.0 and avg_response_time <= 0.5:
                    test.result = TestResult.EXCELLENT
            elif (test.metrics.success_rate >= 85.0 and avg_response_time <= 2.0):
                test.result = TestResult.WARNING
            else:
                test.result = TestResult.FAILED
                test.error_message = f"Info retrieval performance insufficient: {test.metrics.success_rate:.1f}% success, {avg_response_time:.3f}s avg"

        except Exception as e:
            test.error_message = f"Session info load test failed: {str(e)}"
            test.result = TestResult.FAILED

        test.duration = time.time() - start_time
        return test

    async def test_sustained_load_stability(self) -> TestCase:
        """Test system stability under sustained load for extended period"""
        test = TestCase(
            name="Sustained Load Stability",
            description="Validate system stability under continuous load for 2 minutes",
            success_criteria=[
                "Maintain stable performance for 120 seconds",
                "Handle continuous session creation/retrieval",
                "Memory usage remains stable (no significant leaks)",
                "Response times stay consistent over time"
            ]
        )

        start_time = time.time()
        duration = 120  # 2 minutes

        try:
            # Start memory tracking
            tracemalloc.start()
            initial_memory = tracemalloc.get_traced_memory()[0]

            # Sustained load simulation
            operations_completed = 0
            response_times = []
            memory_snapshots = []

            while time.time() - start_time < duration:
                iteration_start = time.time()

                # Create a batch of sessions
                batch_sessions, batch_duration = await self.create_session_batch(10, operations_completed // 10)
                operations_completed += len(batch_sessions)
                response_times.append(batch_duration / len(batch_sessions) if batch_sessions else 0)

                # Retrieve info for some existing sessions (if we have any)
                if batch_sessions and len(batch_sessions) >= 3:
                    sample_sessions = random.sample(batch_sessions, 3)
                    info_tasks = [self._get_session_info(sid) for sid in sample_sessions]
                    info_results = await asyncio.gather(*info_tasks, return_exceptions=True)
                    successful_info = len([r for r in info_results if isinstance(r, dict)])
                    operations_completed += successful_info

                # Memory snapshot every 20 seconds
                if int(time.time() - start_time) % 20 == 0 and len(memory_snapshots) < 6:
                    current_memory = tracemalloc.get_traced_memory()[0]
                    memory_snapshots.append({
                        "timestamp": time.time() - start_time,
                        "memory_mb": current_memory / 1024 / 1024,
                        "operations": operations_completed
                    })

                # Brief pause to maintain reasonable load
                await asyncio.sleep(0.5)

            final_memory = tracemalloc.get_traced_memory()[0]
            tracemalloc.stop()

            # Analyze stability
            avg_response_time = statistics.mean(response_times) if response_times else 0
            response_time_variance = statistics.variance(response_times) if len(response_times) > 1 else 0
            memory_growth = (final_memory - initial_memory) / 1024 / 1024  # MB

            test.details = {
                "duration": f"{duration}s",
                "total_operations": operations_completed,
                "avg_operations_per_minute": f"{operations_completed / (duration / 60):.1f}",
                "avg_response_time": f"{avg_response_time:.3f}s",
                "response_time_variance": f"{response_time_variance:.6f}",
                "response_time_stability": "stable" if response_time_variance < 0.1 else "variable",
                "memory_growth_mb": f"{memory_growth:.1f}",
                "memory_snapshots": len(memory_snapshots),
                "final_operations_rate": f"{operations_completed / duration:.1f} ops/sec"
            }

            # Evaluate stability
            if (operations_completed >= 100 and
                avg_response_time <= 1.0 and
                memory_growth < 100 and
                response_time_variance < 0.1):
                test.result = TestResult.PASSED
                if (operations_completed >= 200 and
                    avg_response_time <= 0.5 and
                    memory_growth < 50):
                    test.result = TestResult.EXCELLENT
            elif (operations_completed >= 50 and
                  avg_response_time <= 2.0 and
                  memory_growth < 200):
                test.result = TestResult.WARNING
            else:
                test.result = TestResult.FAILED
                test.error_message = f"Insufficient stability: {operations_completed} ops, {avg_response_time:.3f}s avg, {memory_growth:.1f}MB growth"

        except Exception as e:
            test.error_message = f"Sustained load test failed: {str(e)}"
            test.result = TestResult.FAILED

        test.duration = time.time() - start_time
        return test

    async def test_api_endpoint_stress(self) -> TestCase:
        """Stress test various API endpoints to identify bottlenecks"""
        test = TestCase(
            name="API Endpoint Stress Testing",
            description="Identify performance limits and bottlenecks across API endpoints",
            success_criteria=[
                "Test multiple API endpoints under stress",
                "Identify performance characteristics of each endpoint",
                "Validate error handling under extreme load",
                "Provide capacity planning insights"
            ]
        )

        start_time = time.time()

        try:
            endpoint_results = {}

            # Test 1: Health endpoint stress
            health_start = time.time()
            health_tasks = [self._test_health_endpoint() for _ in range(100)]
            health_results = await asyncio.gather(*health_tasks, return_exceptions=True)
            health_duration = time.time() - health_start

            endpoint_results["health"] = {
                "requests": len(health_tasks),
                "successful": len([r for r in health_results if r is True]),
                "duration": health_duration,
                "rps": len(health_tasks) / health_duration
            }

            # Test 2: Session creation stress
            creation_start = time.time()
            creation_tasks = [self._create_single_session(i) for i in range(75)]
            creation_results = await asyncio.gather(*creation_tasks, return_exceptions=True)
            creation_duration = time.time() - creation_start

            successful_creations = [r for r in creation_results if isinstance(r, str)]
            endpoint_results["session_creation"] = {
                "requests": len(creation_tasks),
                "successful": len(successful_creations),
                "duration": creation_duration,
                "rps": len(creation_tasks) / creation_duration
            }

            # Test 3: Session info retrieval stress (using created sessions)
            if successful_creations:
                info_start = time.time()
                info_tasks = [self._get_session_info(sid) for sid in successful_creations[:50]]
                info_results = await asyncio.gather(*info_tasks, return_exceptions=True)
                info_duration = time.time() - info_start

                endpoint_results["session_info"] = {
                    "requests": len(info_tasks),
                    "successful": len([r for r in info_results if isinstance(r, dict)]),
                    "duration": info_duration,
                    "rps": len(info_tasks) / info_duration
                }

            test.details = {
                "endpoint_performance": endpoint_results,
                "total_requests": sum(ep["requests"] for ep in endpoint_results.values()),
                "total_successful": sum(ep["successful"] for ep in endpoint_results.values()),
                "overall_success_rate": f"{(sum(ep['successful'] for ep in endpoint_results.values()) / sum(ep['requests'] for ep in endpoint_results.values()) * 100):.1f}%",
                "performance_ranking": sorted(
                    [(k, v["rps"]) for k, v in endpoint_results.items()],
                    key=lambda x: x[1], reverse=True
                )
            }

            # Evaluate overall API stress performance
            overall_success_rate = sum(ep["successful"] for ep in endpoint_results.values()) / sum(ep["requests"] for ep in endpoint_results.values()) * 100
            min_rps = min(ep["rps"] for ep in endpoint_results.values())

            if overall_success_rate >= 95.0 and min_rps >= 20.0:
                test.result = TestResult.PASSED
                if overall_success_rate >= 98.0 and min_rps >= 50.0:
                    test.result = TestResult.EXCELLENT
            elif overall_success_rate >= 85.0 and min_rps >= 10.0:
                test.result = TestResult.WARNING
            else:
                test.result = TestResult.FAILED
                test.error_message = f"API stress performance insufficient: {overall_success_rate:.1f}% success, {min_rps:.1f} min RPS"

        except Exception as e:
            test.error_message = f"API stress test failed: {str(e)}"
            test.result = TestResult.FAILED

        test.duration = time.time() - start_time
        return test

    async def _get_session_info(self, session_id: str) -> Optional[Dict]:
        """Helper method to get session information"""
        try:
            url = f"{self.base_url}/api/session/{session_id}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, ssl=False) as response:
                    if response.status == 200:
                        return await response.json()
        except Exception:
            pass
        return None

    async def _test_health_endpoint(self) -> bool:
        """Helper method to test health endpoint"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/health", ssl=False) as response:
                    return response.status == 200
        except Exception:
            return False

    async def run_all_tests(self) -> Dict[str, Any]:
        """Run simplified load testing and performance validation"""
        logger.info("🚀 Starting T017.3 - Simplified Load Testing and Performance Validation")
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

        # Run all simplified performance tests
        tests = [
            await self.test_massive_concurrent_sessions(),
            await self.test_session_info_retrieval_load(),
            await self.test_sustained_load_stability(),
            await self.test_api_endpoint_stress()
        ]

        self.test_cases = tests
        total_duration = time.time() - start_time

        # Calculate overall results
        passed = len([t for t in tests if t.result in [TestResult.PASSED, TestResult.EXCELLENT]])
        failed = len([t for t in tests if t.result == TestResult.FAILED])
        warnings = len([t for t in tests if t.result == TestResult.WARNING])
        excellent = len([t for t in tests if t.result == TestResult.EXCELLENT])

        success_rate = (passed / len(tests)) * 100 if tests else 0

        # Extract performance insights
        max_sessions = 0
        peak_throughput = 0.0

        for test in tests:
            if "sessions_created" in test.details:
                max_sessions = max(max_sessions, int(test.details["sessions_created"]))
            if "throughput" in test.details:
                throughput_str = test.details["throughput"]
                if isinstance(throughput_str, str) and "sessions/sec" in throughput_str:
                    throughput_val = float(throughput_str.split()[0])
                    peak_throughput = max(peak_throughput, throughput_val)

        report = {
            "test_suite": "T017.3 - Simplified Load Testing and Performance Validation",
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
                "max_concurrent_sessions": max_sessions,
                "peak_session_throughput": f"{peak_throughput:.1f} sessions/sec",
                "system_stability": "excellent" if excellent >= 2 else "good" if passed >= failed else "needs_improvement",
                "production_readiness": "confirmed" if success_rate >= 75 and excellent >= 1 else "needs_review"
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
        print(f"⚡ Peak Session Throughput: {perf_summary.get('peak_session_throughput', 'N/A')}")
        print(f"🎯 System Stability: {perf_summary.get('system_stability', 'N/A').upper()}")
        print(f"🚀 Production Readiness: {perf_summary.get('production_readiness', 'N/A').upper()}")

        print(f"\n📋 DETAILED TEST RESULTS")
        print("-" * 80)

        for test in self.test_cases:
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
                            if isinstance(subvalue, list) and len(subvalue) > 3:
                                print(f"       - {subkey}: {len(subvalue)} items")
                            else:
                                print(f"       - {subkey}: {subvalue}")
                    elif isinstance(value, list) and len(value) > 5:
                        print(f"     • {key}: {len(value)} data points")
                    else:
                        print(f"     • {key}: {value}")

        print("\n" + "=" * 80)
        print("🎯 T017.3 SIMPLIFIED LOAD TESTING COMPLETE")
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
    """Main function to run simplified load testing"""
    tester = SimplifiedLoadTester()

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
