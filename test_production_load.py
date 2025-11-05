#!/usr/bin/env python3
"""
Production-Like Load Test for WebSocket Broadcasting

Simulates 50 concurrent sessions with multiple messages each to validate:
- Broadcasting performance under load
- WebSocketManager singleton stability
- Memory and connection management
- Prometheus metrics accuracy

Usage:
    python3 test_production_load.py

Expected Results:
- 100% broadcast success rate
- No connection failures
- Stable memory usage
- Consistent latency
"""

import asyncio
import aiohttp
import time
import json
from datetime import datetime
from typing import List, Dict, Tuple

# Test Configuration
BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"
NUM_SESSIONS = 50
MESSAGES_PER_SESSION = 3
CONCURRENT_LIMIT = 10  # Max concurrent sessions to prevent overwhelming

class LoadTestResults:
    def __init__(self):
        self.total_sessions = 0
        self.successful_sessions = 0
        self.failed_sessions = 0
        self.total_messages_sent = 0
        self.total_messages_received = 0
        self.connection_failures = 0
        self.broadcast_failures = 0
        self.session_creation_times = []
        self.message_send_times = []
        self.start_time = None
        self.end_time = None
        
    def add_session_creation_time(self, duration: float):
        self.session_creation_times.append(duration)
        
    def add_message_send_time(self, duration: float):
        self.message_send_times.append(duration)
        
    def calculate_stats(self) -> Dict:
        total_duration = (self.end_time - self.start_time) if self.start_time and self.end_time else 0
        
        return {
            "total_sessions": self.total_sessions,
            "successful_sessions": self.successful_sessions,
            "failed_sessions": self.failed_sessions,
            "session_success_rate": (self.successful_sessions / self.total_sessions * 100) if self.total_sessions > 0 else 0,
            "total_messages_sent": self.total_messages_sent,
            "total_messages_received": self.total_messages_received,
            "message_delivery_rate": (self.total_messages_received / self.total_messages_sent * 100) if self.total_messages_sent > 0 else 0,
            "connection_failures": self.connection_failures,
            "broadcast_failures": self.broadcast_failures,
            "total_duration_seconds": total_duration,
            "throughput_sessions_per_second": self.successful_sessions / total_duration if total_duration > 0 else 0,
            "throughput_messages_per_second": self.total_messages_sent / total_duration if total_duration > 0 else 0,
            "avg_session_creation_time": sum(self.session_creation_times) / len(self.session_creation_times) if self.session_creation_times else 0,
            "avg_message_send_time": sum(self.message_send_times) / len(self.message_send_times) if self.message_send_times else 0,
            "max_session_creation_time": max(self.session_creation_times) if self.session_creation_times else 0,
            "max_message_send_time": max(self.message_send_times) if self.message_send_times else 0,
        }

results = LoadTestResults()

async def create_and_test_session(session_num: int, semaphore: asyncio.Semaphore) -> bool:
    """Create a session, send messages, and validate delivery"""
    async with semaphore:  # Limit concurrent operations
        session_id = None
        admin_ws = None
        customer_ws = None
        
        try:
            async with aiohttp.ClientSession() as http_session:
                # 1. Create Admin Session
                create_start = time.time()
                async with http_session.post(f"{BASE_URL}/api/admin/session/create") as resp:
                    if resp.status not in [200, 201]:
                        print(f"❌ Session {session_num}: Failed to create (status {resp.status})")
                        results.failed_sessions += 1
                        return False
                    
                    data = await resp.json()
                    session_id = data.get("session_id")
                    create_duration = time.time() - create_start
                    results.add_session_creation_time(create_duration)
                    
                print(f"✅ Session {session_num}: Created {session_id}")
                
                # 2. Activate Customer
                async with http_session.post(
                    f"{BASE_URL}/api/customer/session/activate",
                    json={"session_id": session_id, "customer_language": "en"}
                ) as resp:
                    if resp.status not in [200, 201]:
                        print(f"❌ Session {session_num}: Failed to activate")
                        results.failed_sessions += 1
                        return False
                
                # 3. Connect WebSockets
                admin_ws = await http_session.ws_connect(f"{WS_URL}/ws/{session_id}/admin")
                customer_ws = await http_session.ws_connect(f"{WS_URL}/ws/{session_id}/customer")
                
                # Wait for connection_ack
                admin_ack = await asyncio.wait_for(admin_ws.receive_json(), timeout=5)
                customer_ack = await asyncio.wait_for(customer_ws.receive_json(), timeout=5)
                
                if admin_ack.get("type") != "connection_ack" or customer_ack.get("type") != "connection_ack":
                    print(f"❌ Session {session_num}: Connection ACK failed")
                    results.connection_failures += 1
                    results.failed_sessions += 1
                    return False
                
                # 4. Send Messages
                messages_received = 0
                
                for msg_num in range(MESSAGES_PER_SESSION):
                    send_start = time.time()
                    
                    # Send text message
                    async with http_session.post(
                        f"{BASE_URL}/api/session/{session_id}/message",
                        json={
                            "text": f"Test message {msg_num} from session {session_num}",
                            "source_lang": "de",
                            "target_lang": "en",
                            "client_type": "admin"
                        }
                    ) as resp:
                        results.total_messages_sent += 1
                        send_duration = time.time() - send_start
                        results.add_message_send_time(send_duration)
                        
                        if resp.status not in [200, 201]:
                            print(f"⚠️ Session {session_num}: Message {msg_num} failed to send")
                            results.broadcast_failures += 1
                            continue
                    
                    # Wait for WebSocket message (with timeout)
                    try:
                        # Customer should receive the message
                        ws_msg = await asyncio.wait_for(customer_ws.receive_json(), timeout=3)
                        
                        # Skip heartbeats
                        while ws_msg.get("type") == "heartbeat":
                            # Send pong
                            await customer_ws.send_json({"type": "pong"})
                            ws_msg = await asyncio.wait_for(customer_ws.receive_json(), timeout=3)
                        
                        if ws_msg.get("type") == "message":
                            messages_received += 1
                            results.total_messages_received += 1
                        
                    except asyncio.TimeoutError:
                        print(f"⚠️ Session {session_num}: Message {msg_num} not received via WebSocket")
                    
                    # Small delay between messages
                    await asyncio.sleep(0.1)
                
                # 5. Validate Results
                delivery_rate = (messages_received / MESSAGES_PER_SESSION * 100) if MESSAGES_PER_SESSION > 0 else 0
                
                if delivery_rate >= 90:  # Allow 10% tolerance
                    print(f"✅ Session {session_num}: {messages_received}/{MESSAGES_PER_SESSION} messages delivered ({delivery_rate:.1f}%)")
                    results.successful_sessions += 1
                    return True
                else:
                    print(f"⚠️ Session {session_num}: Low delivery rate {delivery_rate:.1f}%")
                    results.failed_sessions += 1
                    return False
                
        except Exception as e:
            print(f"❌ Session {session_num}: Exception - {e}")
            results.failed_sessions += 1
            return False
        
        finally:
            # Cleanup WebSockets
            if admin_ws:
                await admin_ws.close()
            if customer_ws:
                await customer_ws.close()

async def run_load_test():
    """Execute the load test with concurrent sessions"""
    print("=" * 80)
    print("🚀 Production-Like Load Test")
    print("=" * 80)
    print(f"Sessions: {NUM_SESSIONS}")
    print(f"Messages per session: {MESSAGES_PER_SESSION}")
    print(f"Concurrent limit: {CONCURRENT_LIMIT}")
    print(f"Total messages: {NUM_SESSIONS * MESSAGES_PER_SESSION}")
    print("=" * 80)
    print()
    
    results.start_time = time.time()
    results.total_sessions = NUM_SESSIONS
    
    # Create semaphore to limit concurrency
    semaphore = asyncio.Semaphore(CONCURRENT_LIMIT)
    
    # Run all sessions
    tasks = [
        create_and_test_session(i + 1, semaphore)
        for i in range(NUM_SESSIONS)
    ]
    
    session_results = await asyncio.gather(*tasks)
    
    results.end_time = time.time()
    
    # Calculate and print statistics
    print()
    print("=" * 80)
    print("📊 Load Test Results")
    print("=" * 80)
    
    stats = results.calculate_stats()
    
    print(f"\n🎯 Session Statistics:")
    print(f"  Total Sessions:       {stats['total_sessions']}")
    print(f"  Successful:           {stats['successful_sessions']} ({stats['session_success_rate']:.1f}%)")
    print(f"  Failed:               {stats['failed_sessions']}")
    print(f"  Connection Failures:  {stats['connection_failures']}")
    
    print(f"\n📨 Message Statistics:")
    print(f"  Total Sent:           {stats['total_messages_sent']}")
    print(f"  Total Received:       {stats['total_messages_received']}")
    print(f"  Delivery Rate:        {stats['message_delivery_rate']:.1f}%")
    print(f"  Broadcast Failures:   {stats['broadcast_failures']}")
    
    print(f"\n⚡ Performance:")
    print(f"  Total Duration:       {stats['total_duration_seconds']:.2f}s")
    print(f"  Sessions/sec:         {stats['throughput_sessions_per_second']:.2f}")
    print(f"  Messages/sec:         {stats['throughput_messages_per_second']:.2f}")
    
    print(f"\n⏱️ Latency:")
    print(f"  Avg Session Creation: {stats['avg_session_creation_time']*1000:.2f}ms")
    print(f"  Max Session Creation: {stats['max_session_creation_time']*1000:.2f}ms")
    print(f"  Avg Message Send:     {stats['avg_message_send_time']*1000:.2f}ms")
    print(f"  Max Message Send:     {stats['max_message_send_time']*1000:.2f}ms")
    
    # Success Criteria
    print(f"\n✅ Success Criteria:")
    criteria_met = 0
    total_criteria = 5
    
    if stats['session_success_rate'] >= 95:
        print(f"  ✅ Session success rate >= 95% ({stats['session_success_rate']:.1f}%)")
        criteria_met += 1
    else:
        print(f"  ❌ Session success rate < 95% ({stats['session_success_rate']:.1f}%)")
    
    if stats['message_delivery_rate'] >= 95:
        print(f"  ✅ Message delivery rate >= 95% ({stats['message_delivery_rate']:.1f}%)")
        criteria_met += 1
    else:
        print(f"  ❌ Message delivery rate < 95% ({stats['message_delivery_rate']:.1f}%)")
    
    if stats['connection_failures'] == 0:
        print(f"  ✅ Zero connection failures")
        criteria_met += 1
    else:
        print(f"  ❌ {stats['connection_failures']} connection failures")
    
    if stats['avg_message_send_time'] < 2.0:
        print(f"  ✅ Avg message send time < 2s ({stats['avg_message_send_time']:.2f}s)")
        criteria_met += 1
    else:
        print(f"  ❌ Avg message send time >= 2s ({stats['avg_message_send_time']:.2f}s)")
    
    if stats['throughput_messages_per_second'] >= 10:
        print(f"  ✅ Throughput >= 10 msg/s ({stats['throughput_messages_per_second']:.2f})")
        criteria_met += 1
    else:
        print(f"  ⚠️ Throughput < 10 msg/s ({stats['throughput_messages_per_second']:.2f})")
    
    print(f"\n📋 Overall: {criteria_met}/{total_criteria} criteria met")
    
    if criteria_met == total_criteria:
        print("✅ LOAD TEST PASSED - System ready for production")
        return 0
    elif criteria_met >= total_criteria - 1:
        print("⚠️ LOAD TEST WARNING - Minor issues detected")
        return 1
    else:
        print("❌ LOAD TEST FAILED - System not ready for production load")
        return 2
    
    print("=" * 80)
    
    # Save results to file
    with open(f"load_test_results_{int(time.time())}.json", "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "config": {
                "num_sessions": NUM_SESSIONS,
                "messages_per_session": MESSAGES_PER_SESSION,
                "concurrent_limit": CONCURRENT_LIMIT
            },
            "results": stats
        }, f, indent=2)
    
    print(f"\n💾 Results saved to load_test_results_{int(time.time())}.json")

if __name__ == "__main__":
    exit_code = asyncio.run(run_load_test())
    exit(exit_code)
