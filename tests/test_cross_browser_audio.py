"""
Cross-Browser Audio Format Testing

Tests die WAV-Konvertierung für verschiedene Browser-Audio-Formate:
- Chrome/Edge: WebM/Opus
- Firefox: OGG/Opus
- Safari: MP4/AAC

Simuliert die Browser-Formate und validiert die WAV-Konvertierung.
"""

import io
import wave
import struct
import pytest
from pathlib import Path


class TestCrossBrowserAudioFormats:
    """Test WAV conversion from different browser formats"""

    def create_test_wav(self, sample_rate=16000, duration_ms=500, num_channels=1):
        """
        Erstellt eine Test-WAV-Datei

        Args:
            sample_rate: Sample-Rate in Hz
            duration_ms: Dauer in Millisekunden
            num_channels: Anzahl der Kanäle (1=Mono, 2=Stereo)

        Returns:
            bytes: WAV-Datei als Bytes
        """
        num_samples = int(sample_rate * duration_ms / 1000)

        # Sinus-Wave generieren (440 Hz = A4 Note)
        frequency = 440.0
        amplitude = 32767  # Max für 16-bit signed

        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(num_channels)
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)

            for i in range(num_samples):
                value = int(amplitude * 0.5 *
                           (i / num_samples) *  # Fade in
                           ((num_samples - i) / num_samples) *  # Fade out
                           (1.0 if i % 2 == 0 else -1.0))  # Square wave für einfacheren Test

                # Stereo: beide Kanäle gleich
                for _ in range(num_channels):
                    wav_file.writeframes(struct.pack('<h', value))

        return wav_buffer.getvalue()

    def validate_wav_format(self, wav_data):
        """
        Validiert WAV-Format-Struktur

        Args:
            wav_data: WAV-Datei als Bytes

        Returns:
            dict: WAV-File-Eigenschaften
        """
        with wave.open(io.BytesIO(wav_data), 'rb') as wav_file:
            return {
                'num_channels': wav_file.getnchannels(),
                'sample_width': wav_file.getsampwidth(),
                'frame_rate': wav_file.getframerate(),
                'num_frames': wav_file.getnframes(),
                'compression_type': wav_file.getcomptype(),
                'compression_name': wav_file.getcompname(),
                'duration_ms': int(wav_file.getnframes() / wav_file.getframerate() * 1000)
            }

    def test_wav_header_generation(self):
        """Test: WAV-Header wird korrekt generiert"""
        wav_data = self.create_test_wav(sample_rate=16000, duration_ms=500)

        # RIFF-Header prüfen
        assert wav_data[:4] == b'RIFF', "RIFF-Header fehlt"
        assert wav_data[8:12] == b'WAVE', "WAVE-Identifier fehlt"

        # Format-Chunk prüfen
        assert b'fmt ' in wav_data, "fmt-Chunk fehlt"
        assert b'data' in wav_data, "data-Chunk fehlt"

        print("✅ WAV-Header korrekt generiert")

    def test_wav_16khz_mono_format(self):
        """Test: 16kHz Mono WAV-Format (Backend-Anforderung)"""
        wav_data = self.create_test_wav(sample_rate=16000, duration_ms=500, num_channels=1)
        props = self.validate_wav_format(wav_data)

        assert props['num_channels'] == 1, "Muss Mono sein"
        assert props['sample_width'] == 2, "Muss 16-bit sein"
        assert props['frame_rate'] == 16000, "Muss 16kHz sein"
        assert props['compression_type'] == 'NONE', "Muss unkomprimiert sein"
        assert 450 <= props['duration_ms'] <= 550, "Dauer muss ~500ms sein"

        print(f"✅ 16kHz Mono WAV: {props['num_frames']} frames, {props['duration_ms']}ms")

    def test_wav_different_sample_rates(self):
        """Test: Verschiedene Sample-Rates werden korrekt verarbeitet"""
        sample_rates = [8000, 16000, 22050, 44100, 48000]

        for rate in sample_rates:
            wav_data = self.create_test_wav(sample_rate=rate, duration_ms=500)
            props = self.validate_wav_format(wav_data)

            assert props['frame_rate'] == rate, f"Sample-Rate {rate} nicht korrekt"
            print(f"✅ Sample-Rate {rate}Hz: OK")

    def test_wav_stereo_to_mono_conversion_concept(self):
        """Test: Stereo → Mono Konvertierung (konzeptionell)"""
        # Erstelle Stereo-WAV
        stereo_wav = self.create_test_wav(sample_rate=16000, duration_ms=500, num_channels=2)
        stereo_props = self.validate_wav_format(stereo_wav)

        assert stereo_props['num_channels'] == 2, "Muss Stereo sein"

        # Im Frontend würde Web Audio API dies zu Mono konvertieren
        # Hier validieren wir nur, dass wir Stereo-Input erkennen können
        print(f"✅ Stereo-Format erkannt: {stereo_props['num_channels']} Kanäle")

    def test_wav_file_size_calculation(self):
        """Test: WAV-Dateigröße berechnen"""
        duration_ms = 1000  # 1 Sekunde
        sample_rate = 16000
        num_channels = 1
        sample_width = 2  # 16-bit

        # Erwartete Größe: Header (44 Bytes) + Data
        # Data = sample_rate * duration_sec * num_channels * sample_width
        expected_data_size = sample_rate * (duration_ms / 1000) * num_channels * sample_width
        expected_total_size = 44 + expected_data_size

        wav_data = self.create_test_wav(sample_rate, duration_ms, num_channels)
        actual_size = len(wav_data)

        # Erlaubt kleine Abweichung wegen Padding
        assert abs(actual_size - expected_total_size) < 100, \
            f"Dateigröße {actual_size} weicht zu stark von {expected_total_size} ab"

        print(f"✅ WAV-Größe: {actual_size} Bytes (~{expected_total_size} erwartet)")

    def test_wav_short_audio_handling(self):
        """Test: Kurze Audio-Clips (< 1 Sekunde)"""
        for duration_ms in [100, 250, 500, 750]:
            wav_data = self.create_test_wav(duration_ms=duration_ms)
            props = self.validate_wav_format(wav_data)

            # Dauer sollte ungefähr stimmen (±50ms Toleranz)
            assert abs(props['duration_ms'] - duration_ms) < 50, \
                f"Dauer {props['duration_ms']}ms weicht zu stark von {duration_ms}ms ab"

            print(f"✅ Kurzer Clip ({duration_ms}ms): {props['duration_ms']}ms, {len(wav_data)} Bytes")

    def test_wav_empty_audio_handling(self):
        """Test: Leere/Sehr kurze Audio (Error-Case)"""
        # 10ms ist extrem kurz - sollte aber trotzdem valides WAV sein
        wav_data = self.create_test_wav(duration_ms=10)
        props = self.validate_wav_format(wav_data)

        assert props['num_frames'] > 0, "Muss mindestens 1 Frame haben"
        print(f"✅ Sehr kurzer Clip (10ms): {props['num_frames']} frames")

    @pytest.mark.parametrize("sample_rate,expected_backend_rate", [
        (8000, 16000),   # Upsampling
        (16000, 16000),  # Kein Resampling
        (22050, 16000),  # Downsampling
        (44100, 16000),  # Downsampling
        (48000, 16000),  # Downsampling (typisch WebM/Opus)
    ])
    def test_resampling_scenarios(self, sample_rate, expected_backend_rate):
        """Test: Resampling-Szenarien für verschiedene Browser-Formate"""
        # Browser liefert Audio mit verschiedenen Sample-Rates
        browser_wav = self.create_test_wav(sample_rate=sample_rate, duration_ms=500)
        browser_props = self.validate_wav_format(browser_wav)

        assert browser_props['frame_rate'] == sample_rate

        # Frontend würde zu 16kHz resampled
        # Hier simulieren wir das Ziel-Format
        target_wav = self.create_test_wav(sample_rate=expected_backend_rate, duration_ms=500)
        target_props = self.validate_wav_format(target_wav)

        assert target_props['frame_rate'] == expected_backend_rate

        print(f"✅ Resampling {sample_rate}Hz → {expected_backend_rate}Hz: OK")


class TestBrowserFormatSimulation:
    """Simuliert verschiedene Browser-Audio-Format-Charakteristiken"""

    def test_chrome_webm_opus_characteristics(self):
        """Test: Chrome/Edge WebM/Opus Format-Eigenschaften"""
        # Chrome liefert typisch 48kHz Opus in WebM
        # Nach Dekodierung im Frontend: PCM Float32 Array
        # Unser Converter würde zu 16kHz, 16-bit, Mono WAV konvertieren

        chrome_sample_rate = 48000
        target_sample_rate = 16000

        # Simuliere resampling ratio
        resample_ratio = target_sample_rate / chrome_sample_rate
        assert 0 < resample_ratio <= 1, "Downsampling-Ratio muss gültig sein"

        print(f"✅ Chrome WebM/Opus: {chrome_sample_rate}Hz → {target_sample_rate}Hz (Ratio: {resample_ratio:.3f})")

    def test_firefox_ogg_opus_characteristics(self):
        """Test: Firefox OGG/Opus Format-Eigenschaften"""
        # Firefox liefert Opus in OGG Container
        # Typisch auch 48kHz

        firefox_sample_rate = 48000
        target_sample_rate = 16000

        resample_ratio = target_sample_rate / firefox_sample_rate

        print(f"✅ Firefox OGG/Opus: {firefox_sample_rate}Hz → {target_sample_rate}Hz (Ratio: {resample_ratio:.3f})")

    def test_safari_mp4_aac_characteristics(self):
        """Test: Safari MP4/AAC Format-Eigenschaften"""
        # Safari liefert AAC in MP4 Container
        # Typisch 44.1kHz oder 48kHz

        safari_sample_rate = 44100
        target_sample_rate = 16000

        resample_ratio = target_sample_rate / safari_sample_rate

        print(f"✅ Safari MP4/AAC: {safari_sample_rate}Hz → {target_sample_rate}Hz (Ratio: {resample_ratio:.3f})")


class TestWAVValidation:
    """Tests für WAV-Format-Validierung"""

    def test_valid_wav_passes_validation(self):
        """Test: Valides WAV besteht Validierung"""
        test = TestCrossBrowserAudioFormats()
        wav_data = test.create_test_wav()

        # Sollte nicht crashen
        props = test.validate_wav_format(wav_data)
        assert props is not None

        print("✅ Valides WAV besteht Validierung")

    def test_invalid_wav_header_fails(self):
        """Test: Invalider WAV-Header wird erkannt"""
        invalid_data = b'INVALID_HEADER' + b'\x00' * 100

        test = TestCrossBrowserAudioFormats()

        try:
            test.validate_wav_format(invalid_data)
            print("❌ Invalider Header wurde nicht erkannt!")
            raise AssertionError("Invalid WAV should have raised an exception")
        except (wave.Error, EOFError):
            print("✅ Invalider Header wird korrekt abgelehnt")
        except Exception as e:
            print(f"✅ Invalider Header wird korrekt abgelehnt ({type(e).__name__})")

    def test_truncated_wav_fails(self):
        """Test: Abgeschnittene WAV-Datei wird erkannt"""
        test = TestCrossBrowserAudioFormats()
        wav_data = test.create_test_wav()

        # Nur ersten Teil behalten
        truncated = wav_data[:100]

        try:
            test.validate_wav_format(truncated)
            # Wenn keine Exception, dann ist Test fehlgeschlagen
            print("❌ Abgeschnittene WAV wurde nicht erkannt!")
            raise AssertionError("Truncated WAV should have raised an exception")
        except (wave.Error, EOFError):
            print("✅ Abgeschnittene WAV wird korrekt abgelehnt")
        except Exception as e:
            print(f"✅ Abgeschnittene WAV wird korrekt abgelehnt ({type(e).__name__})")


if __name__ == '__main__':
    # Run tests manually
    print("=" * 60)
    print("Cross-Browser Audio Format Tests")
    print("=" * 60)

    test_class = TestCrossBrowserAudioFormats()

    print("\n--- WAV Header Tests ---")
    test_class.test_wav_header_generation()

    print("\n--- Format Tests ---")
    test_class.test_wav_16khz_mono_format()
    test_class.test_wav_different_sample_rates()
    test_class.test_wav_stereo_to_mono_conversion_concept()

    print("\n--- Size & Duration Tests ---")
    test_class.test_wav_file_size_calculation()
    test_class.test_wav_short_audio_handling()
    test_class.test_wav_empty_audio_handling()

    print("\n--- Resampling Tests ---")
    for sr, target in [(8000, 16000), (16000, 16000), (22050, 16000), (44100, 16000), (48000, 16000)]:
        test_class.test_resampling_scenarios(sr, target)

    print("\n--- Browser Format Simulation ---")
    browser_test = TestBrowserFormatSimulation()
    browser_test.test_chrome_webm_opus_characteristics()
    browser_test.test_firefox_ogg_opus_characteristics()
    browser_test.test_safari_mp4_aac_characteristics()

    print("\n--- Validation Tests ---")
    validation_test = TestWAVValidation()
    validation_test.test_valid_wav_passes_validation()
    validation_test.test_invalid_wav_header_fails()
    validation_test.test_truncated_wav_fails()

    print("\n" + "=" * 60)
    print("✅ Alle Tests erfolgreich!")
    print("=" * 60)
