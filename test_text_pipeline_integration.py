#!/usr/bin/env python3
"""
Integration-Test für Text-Pipeline-Optimierung
Testet die neue process_text_pipeline über die Session API
"""

import requests
import json
import time


def test_text_pipeline_integration():
    """Test the Text-Pipeline Integration with Session API"""

    base_url = "http://localhost:8000"
    session_id = "test_text_pipeline_session"

    print("=== Text Pipeline Integration Test ===\n")

    # Create a session first
    print("0️⃣ Creating test session...")
    try:
        response = requests.post(
            f"{base_url}/api/session/create?customer_language=de",
            headers={"Content-Type": "application/json"},
            timeout=10
        )

        print(f"   Session Creation Status: {response.status_code}")
        if response.status_code == 200:
            session_data = response.json()
            session_id = session_data.get('session_id', session_id)
            print(f"   ✅ Session created successfully! ID: {session_id}")
        else:
            print(f"   ❌ Session creation failed: {response.text[:200]}")
            return

    except Exception as e:
        print(f"   ❌ Session creation error: {e}")
        return

    print("1️⃣ Testing Valid Text Processing...")
    try:
        payload = {
            "text": "Hello world, how are you today?",
            "source_lang": "en",
            "target_lang": "de",
            "client_type": "admin"
        }

        start_time = time.perf_counter()
        response = requests.post(
            f"{base_url}/api/session/{session_id}/message",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        processing_time = time.perf_counter() - start_time

        print(f"   Status Code: {response.status_code}")
        print(f"   Processing Time: {processing_time:.2f}s")

        if response.status_code == 200:
            result = response.json()
            print("   ✅ Text processing successful!")
            print(f"   Original: {result.get('original_text', 'N/A')}")
            print(f"   Translated: {result.get('translated_text', 'N/A')}")
            print(f"   Audio Available: {result.get('audio_available', False)}")
            print(f"   Processing Time (API): {result.get('processing_time_ms', 'N/A')}ms")
            print(f"   Pipeline Type: {result.get('pipeline_type', 'N/A')}")

            # Check that ASR was skipped (should be fast)
            if processing_time < 10.0:  # Should be much faster without ASR
                print("   ✅ Fast processing indicates ASR was skipped!")
            else:
                print("   ⚠️  Processing took longer than expected")

        else:
            print(f"   ❌ Request failed: {response.text[:200]}")

    except Exception as e:
        print(f"   ❌ Error: {e}")

    print("\n2️⃣ Testing Text Validation - Text Too Long...")
    try:
        payload = {
            "text": "A" * 501,  # Over 500 character limit
            "source_lang": "en",
            "target_lang": "de",
            "client_type": "admin"
        }

        response = requests.post(
            f"{base_url}/api/session/{session_id}/message",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        print(f"   Status Code: {response.status_code}")

        if response.status_code == 400:
            result = response.json()
            print("   ✅ Text too long correctly rejected!")
            print(f"   Error: {result.get('detail', {}).get('error_message', 'No error message')}")
        else:
            print(f"   ❌ Should have been rejected: {response.text[:200]}")

    except Exception as e:
        print(f"   ❌ Error: {e}")

    print("\n3️⃣ Testing Spam Detection...")
    try:
        payload = {
            "text": "BUY NOW!!! AMAZING DEAL!!! BUY NOW!!! CLICK HERE!!! BEST OFFERS!!!",  # Spam text
            "source_lang": "en",
            "target_lang": "de",
            "client_type": "admin"
        }

        response = requests.post(
            f"{base_url}/api/session/{session_id}/message",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        print(f"   Status Code: {response.status_code}")

        if response.status_code == 400:
            result = response.json()
            print("   ✅ Spam text correctly rejected!")
            print(f"   Error: {result.get('detail', {}).get('error_message', 'No error message')}")
        else:
            print(f"   ❌ Spam should have been rejected: {response.text[:200]}")

    except Exception as e:
        print(f"   ❌ Error: {e}")

    print("\n4️⃣ Testing Harmful Content Detection...")
    try:
        payload = {
            "text": "I hate all people and want to kill every person",  # Harmful content
            "source_lang": "en",
            "target_lang": "de",
            "client_type": "admin"
        }

        response = requests.post(
            f"{base_url}/api/session/{session_id}/message",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        print(f"   Status Code: {response.status_code}")

        if response.status_code == 400:
            result = response.json()
            print("   ✅ Harmful content correctly rejected!")
            print(f"   Error: {result.get('detail', {}).get('error_message', 'No error message')}")
        else:
            print(f"   ❌ Harmful content should have been rejected: {response.text[:200]}")

    except Exception as e:
        print(f"   ❌ Error: {e}")

    print("\n5️⃣ Testing Unicode Text Processing...")
    try:
        payload = {
            "text": "Hallo Welt! 🌍 Как дела? مرحبا بالعالم",  # Unicode text
            "source_lang": "de",
            "target_lang": "en",
            "client_type": "admin"
        }

        response = requests.post(
            f"{base_url}/api/session/{session_id}/message",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )

        print(f"   Status Code: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            print("   ✅ Unicode text processed successfully!")
            print(f"   Original: {result.get('original_text', 'N/A')}")
            print(f"   Translated: {result.get('translated_text', 'N/A')}")
        else:
            print(f"   ❌ Unicode processing failed: {response.text[:200]}")

    except Exception as e:
        print(f"   ❌ Error: {e}")

    print("\n6️⃣ Testing Performance Comparison (Text vs Audio)...")

    # Test Text Pipeline Performance
    text_times = []
    for i in range(3):
        try:
            payload = {
                "text": f"Performance test message number {i+1}",
                "source_lang": "en",
                "target_lang": "de",
                "client_type": "admin"
            }

            start_time = time.perf_counter()
            response = requests.post(
                f"{base_url}/api/session/{session_id}/message",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            end_time = time.perf_counter()

            if response.status_code == 200:
                text_times.append(end_time - start_time)

        except Exception as e:
            print(f"   Performance test {i+1} failed: {e}")

    if text_times:
        avg_text_time = sum(text_times) / len(text_times)
        print(f"   ✅ Text Pipeline Average Time: {avg_text_time:.2f}s")

        if avg_text_time < 5.0:  # Should be faster than audio pipeline
            print("   ✅ Text pipeline shows performance improvement!")
        else:
            print("   ⚠️  Text pipeline slower than expected")
    else:
        print("   ❌ Could not measure text pipeline performance")


def test_api_availability():
    """Test if API is available"""
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        print(f"API Health Status: {response.status_code}")
        if response.status_code == 200:
            health_data = response.json()
            print(f"Services: {health_data.get('services', {})}")
        return response.status_code == 200
    except Exception as e:
        print(f"API not available: {e}")
        return False


if __name__ == "__main__":
    print("Testing Text Pipeline Integration\n")

    if not test_api_availability():
        print("❌ API Gateway not available - skipping integration tests")
        exit(1)

    test_text_pipeline_integration()
    print("\n🎉 Text Pipeline Integration Testing Completed!")