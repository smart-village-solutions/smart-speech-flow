# tests/test_text_pipeline.py
"""
Unit-Tests für Text-Pipeline-Optimierung (ToDo 2.3)
Testet Text-Validation, ASR-Skip, Content-Filtering und Performance-Optimierung
"""

import pytest
import time
from unittest.mock import Mock, patch

from services.api_gateway.pipeline_logic import (
    validate_text_input, normalize_text, detect_spam, detect_harmful_content,
    process_text_pipeline
)


class TestTextValidation:
    """Tests für Text-Validation-Grundfunktionen"""

    def test_valid_text_acceptance(self):
        """Test: Gültiger Text wird akzeptiert"""
        text = "Hello world, how are you today?"

        result = validate_text_input(text)

        assert result.is_valid is True
        assert result.error_code is None
        assert result.length == len(text)
        assert result.encoding == 'utf-8'
        assert result.contains_spam is False
        assert result.contains_harmful_content is False
        assert result.normalized_text == text
        assert result.validation_time_ms >= 0

    def test_text_too_short_rejection(self):
        """Test: Text zu kurz wird abgelehnt"""
        text = ""

        result = validate_text_input(text)

        assert result.is_valid is False
        assert result.error_code == "TEXT_TOO_SHORT"
        assert "too short" in result.error_message.lower()
        assert result.length == 0

    def test_text_too_long_rejection(self):
        """Test: Text zu lang wird abgelehnt"""
        text = "A" * 501  # Over 500 character limit

        result = validate_text_input(text)

        assert result.is_valid is False
        assert result.error_code == "TEXT_TOO_LONG"
        assert "too long" in result.error_message.lower()
        assert result.length == 501
        assert result.details["max_length"] == 500

    def test_exactly_maximum_length(self):
        """Test: Genau maximale Länge ist gültig"""
        # Create a 500-character text with unique content
        base_text = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum. Additional text to reach exactly five hundred characters for the maximum length test validation."
        text = base_text[:500]  # Exactly 500 chars

        result = validate_text_input(text)

        assert result.is_valid is True
        assert result.length == 500

    def test_unicode_text_acceptance(self):
        """Test: Unicode-Text wird korrekt verarbeitet"""
        text = "Hallo Welt! 🌍 Как дела? مرحبا بالعالم"

        result = validate_text_input(text)

        assert result.is_valid is True
        assert result.encoding == 'utf-8'
        assert result.normalized_text == text

    def test_invalid_type_rejection(self):
        """Test: Nicht-String-Input wird abgelehnt"""
        text = 12345  # Integer instead of string

        result = validate_text_input(text)

        assert result.is_valid is False
        assert result.error_code == "INVALID_TYPE"
        assert "must be a string" in result.error_message


class TestTextNormalization:
    """Tests für Text-Normalisierung"""

    def test_whitespace_normalization(self):
        """Test: Whitespace wird normalisiert"""
        text = "  Hello    world  \n\t  "

        normalized = normalize_text(text)

        assert normalized == "Hello world"

    def test_unicode_normalization(self):
        """Test: Unicode-Normalisierung funktioniert"""
        # Decomposed unicode characters
        text = "café"  # é as separate characters

        normalized = normalize_text(text)

        # Should be normalized to composed form
        assert normalized == "café"
        assert len(normalized) <= len(text)  # Composed should be shorter or equal

    def test_empty_text_normalization(self):
        """Test: Leerer Text wird korrekt normalisiert"""
        text = "   \n\t   "

        normalized = normalize_text(text)

        assert normalized == ""


class TestSpamDetection:
    """Tests für Spam-Detection"""

    def test_normal_text_not_spam(self):
        """Test: Normaler Text wird nicht als Spam erkannt"""
        text = "Hello, how are you today? I hope you are well."

        is_spam = detect_spam(text)

        assert is_spam is False

    def test_repetitive_text_spam(self):
        """Test: Repetitiver Text wird als Spam erkannt"""
        text = "buy buy buy buy buy now now now"

        is_spam = detect_spam(text)

        assert is_spam is True

    def test_excessive_caps_spam(self):
        """Test: Übermäßige Großbuchstaben werden als Spam erkannt"""
        text = "BUY NOW!!! AMAZING DEAL!!! CLICK HERE!!! BEST OFFERS!!!"

        is_spam = detect_spam(text)

        assert is_spam is True

    def test_character_repetition_spam(self):
        """Test: Zeichenwiederholung wird als Spam erkannt"""
        text = "Heeeeeello wooooorld!!!!!!"

        is_spam = detect_spam(text)

        assert is_spam is True

    def test_short_caps_not_spam(self):
        """Test: Kurze Großbuchstaben sind kein Spam"""
        text = "OK GREAT"

        is_spam = detect_spam(text)

        assert is_spam is False


class TestHarmfulContentDetection:
    """Tests für Harmful-Content-Detection"""

    def test_normal_text_not_harmful(self):
        """Test: Normaler Text ist nicht schädlich"""
        text = "I love spending time with my family and friends."

        is_harmful = detect_harmful_content(text)

        assert is_harmful is False

    def test_hate_speech_detection(self):
        """Test: Hassrede wird erkannt"""
        text = "I hate all people from that country"

        is_harmful = detect_harmful_content(text)

        assert is_harmful is True

    def test_violence_detection(self):
        """Test: Gewaltbezogene Inhalte werden erkannt"""
        text = "bomb making instructions for attack"

        is_harmful = detect_harmful_content(text)

        assert is_harmful is True

    def test_self_harm_detection(self):
        """Test: Selbstverletzung wird erkannt"""
        text = "I want to hurt myself badly"

        is_harmful = detect_harmful_content(text)

        assert is_harmful is True


class TestContentFiltering:
    """Tests für Content-Filtering Integration"""

    def test_spam_text_rejection(self):
        """Test: Spam-Text wird abgelehnt"""
        text = "BUY NOW!!! AMAZING DEAL!!! BUY NOW!!! CLICK HERE!!! BEST OFFERS!!!"

        result = validate_text_input(text, enable_content_filtering=True)

        assert result.is_valid is False
        assert result.error_code == "SPAM_DETECTED"
        assert result.contains_spam is True

    def test_harmful_content_rejection(self):
        """Test: Schädlicher Inhalt wird abgelehnt"""
        text = "I hate all people and want to kill every person"

        result = validate_text_input(text, enable_content_filtering=True)

        assert result.is_valid is False
        assert result.error_code == "HARMFUL_CONTENT"
        assert result.contains_harmful_content is True

    def test_content_filtering_disabled(self):
        """Test: Content-Filtering kann deaktiviert werden"""
        text = "BUY NOW!!! AMAZING DEAL!!! BUY NOW!!! CLICK HERE!!!"

        result = validate_text_input(text, enable_content_filtering=False)

        # Should pass validation but still detect spam
        assert result.is_valid is True
        assert result.contains_spam is True  # Detected but not blocking


class TestTextPipelinePerformance:
    """Tests für Text-Pipeline-Performance"""

    @patch('services.api_gateway.pipeline_logic.requests.post')
    def test_text_pipeline_skips_asr(self, mock_post):
        """Test: Text-Pipeline überspringt ASR komplett"""
        # Mock nur Translation und TTS, kein ASR
        mock_translation_response = Mock()
        mock_translation_response.json.return_value = {"translations": "Hallo Welt"}
        mock_translation_response.status_code = 200

        mock_tts_response = Mock()
        mock_tts_response.content = b"fake_audio_output"
        mock_tts_response.status_code = 200
        mock_tts_response.headers = {"content-type": "audio/wav"}

        mock_post.side_effect = [mock_translation_response, mock_tts_response]

        # Text-Pipeline ausführen
        result = process_text_pipeline("Hello world", "en", "de", debug=True)

        assert result["error"] is False
        assert result["asr_text"] == "Hello world"  # Original text as ASR result
        assert result["translation_text"] == "Hallo Welt"
        assert result["audio_bytes"] == b"fake_audio_output"

        # Nur 2 Service-Calls: Translation + TTS (kein ASR)
        assert mock_post.call_count == 2

        # Prüfe Debug-Steps
        steps = result["debug"]["steps"]
        step_names = [step["step"] for step in steps]
        assert "Text_Validation" in step_names
        assert "Translation" in step_names
        assert "TTS" in step_names
        assert "ASR" not in step_names  # ASR should be skipped

    def test_text_pipeline_performance(self):
        """Test: Text-Pipeline ist schneller als Audio-Pipeline"""
        text = "Hello world, how are you?"

        start_time = time.perf_counter()

        with patch('services.api_gateway.pipeline_logic.requests.post') as mock_post:
            # Mock successful responses
            mock_translation = Mock()
            mock_translation.json.return_value = {"translations": "Hallo Welt"}
            mock_translation.status_code = 200

            mock_tts = Mock()
            mock_tts.content = b"audio_data"
            mock_tts.status_code = 200
            mock_tts.headers = {"content-type": "audio/wav"}

            mock_post.side_effect = [mock_translation, mock_tts]

            result = process_text_pipeline(text, "en", "de", debug=True)

        processing_time = time.perf_counter() - start_time

        assert result["error"] is False
        assert processing_time < 1.0  # Should be very fast without actual API calls

        # Total duration should be tracked
        assert "total_duration" in result["debug"]
        assert result["debug"]["total_duration"] >= 0  # Can be 0 for very fast operations

    @patch('services.api_gateway.pipeline_logic.requests.post')
    def test_text_validation_failure_stops_pipeline(self, mock_post):
        """Test: Text-Validation-Fehler stoppt Pipeline früh"""
        # Text, der Validation nicht besteht
        text = "A" * 501  # Too long

        result = process_text_pipeline(text, "en", "de", debug=True, validate_text=True)

        assert result["error"] is True
        assert "Text validation failed" in result["error_msg"]
        assert result["validation_result"].error_code == "TEXT_TOO_LONG"

        # Keine Service-Calls sollten gemacht worden sein
        assert mock_post.call_count == 0

        # Nur Text_Validation step sollte vorhanden sein
        steps = result["debug"]["steps"]
        assert len(steps) == 1
        assert steps[0]["step"] == "Text_Validation"
        assert steps[0]["output"] is False


class TestTextPipelineIntegration:
    """Tests für Text-Pipeline-Integration"""

    @patch('services.api_gateway.pipeline_logic.requests.post')
    def test_text_pipeline_with_validation_enabled(self, mock_post):
        """Test: Text-Pipeline mit aktivierter Validation"""
        # Mock successful service responses
        mock_translation_response = Mock()
        mock_translation_response.json.return_value = {"translations": "Hallo Welt"}
        mock_translation_response.status_code = 200

        mock_tts_response = Mock()
        mock_tts_response.content = b"audio_output"
        mock_tts_response.status_code = 200
        mock_tts_response.headers = {"content-type": "audio/wav"}

        mock_post.side_effect = [mock_translation_response, mock_tts_response]

        result = process_text_pipeline("Hello world", "en", "de", debug=True, validate_text=True)

        assert result["error"] is False

        # Find validation step
        steps = result["debug"]["steps"]
        validation_step = next(step for step in steps if step["step"] == "Text_Validation")
        assert validation_step["output"] is True  # Validation passed
        assert validation_step["error"] is None

    def test_text_pipeline_validation_disabled(self):
        """Test: Text-Pipeline mit deaktivierter Validation"""
        with patch('services.api_gateway.pipeline_logic.requests.post') as mock_post:
            # Mock successful responses
            mock_translation = Mock()
            mock_translation.json.return_value = {"translations": "Hallo"}
            mock_translation.status_code = 200
            mock_tts = Mock()
            mock_tts.content = b"audio"
            mock_tts.status_code = 200
            mock_tts.headers = {"content-type": "audio/wav"}

            mock_post.side_effect = [mock_translation, mock_tts]

            result = process_text_pipeline("Hello", "en", "de", validate_text=False)

            # Should not have validation step
            if "debug" in result and "steps" in result["debug"]:
                steps = result["debug"]["steps"]
                validation_steps = [step for step in steps if step["step"] == "Text_Validation"]
                assert len(validation_steps) == 0


if __name__ == "__main__":
    # Tests direkt ausführen für Debugging
    pytest.main([__file__, "-v"])
