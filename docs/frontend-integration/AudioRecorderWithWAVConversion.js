/**
 * Frontend Audio Recording & WAV Conversion Utility
 * Konvertiert MediaRecorder-Output zu WAV-Format für Backend-Kompatibilität
 */

class AudioRecorderWithWAVConversion {
  constructor(options = {}) {
    this.options = {
      sampleRate: 16000,        // Backend erwartet 16kHz
      bitDepth: 16,             // 16-bit für Backend
      channels: 1,              // Mono für Backend
      maxDurationMs: 20000,     // 20 Sekunden Frontend-Limit
      ...options
    };

    this.mediaRecorder = null;
    this.audioContext = null;
    this.stream = null;
    this.recordedChunks = [];
    this.isRecording = false;

    // Event handlers
    this.onStart = options.onStart || (() => {});
    this.onStop = options.onStop || (() => {});
    this.onDataAvailable = options.onDataAvailable || (() => {});
    this.onError = options.onError || (() => {});
  }

  async startRecording() {
    try {
      // 1. Mikrofonzugriff anfordern
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: this.options.sampleRate,
          channelCount: this.options.channels,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });

      // 2. AudioContext für WAV-Konvertierung vorbereiten
      this.audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: this.options.sampleRate
      });

      // 3. MediaRecorder mit optimalen Einstellungen
      const mimeTypes = [
        'audio/webm;codecs=opus',
        'audio/webm',
        'audio/mp4',
        'audio/wav'
      ];

      let selectedMimeType = '';
      for (const mimeType of mimeTypes) {
        if (MediaRecorder.isTypeSupported(mimeType)) {
          selectedMimeType = mimeType;
          break;
        }
      }

      if (!selectedMimeType) {
        throw new Error('Kein unterstütztes Audio-Format gefunden');
      }

      this.mediaRecorder = new MediaRecorder(this.stream, {
        mimeType: selectedMimeType,
        audioBitsPerSecond: 128000
      });

      this.recordedChunks = [];

      // Event-Handler
      this.mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          this.recordedChunks.push(event.data);
        }
      };

      this.mediaRecorder.onstop = async () => {
        await this.processRecording();
        this.cleanup();
      };

      this.mediaRecorder.onerror = (event) => {
        console.error('MediaRecorder-Fehler:', event.error);
        this.onError(event.error);
        this.cleanup();
      };

      // 4. Aufnahme starten
      this.mediaRecorder.start(1000); // Sammle Daten alle 1 Sekunde
      this.isRecording = true;

      // 5. Auto-Stop nach max. Dauer
      setTimeout(() => {
        if (this.isRecording) {
          this.stopRecording();
        }
      }, this.options.maxDurationMs);

      this.onStart();
      console.log('✅ Aufnahme gestartet mit:', selectedMimeType);

    } catch (error) {
      console.error('❌ Fehler beim Starten der Aufnahme:', error);
      this.onError(error);
      this.cleanup();
    }
  }

  stopRecording() {
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
      this.isRecording = false;
    }
  }

  async processRecording() {
    try {
      // 1. Aufgenommene Daten zu Blob kombinieren
      const audioBlob = new Blob(this.recordedChunks, { type: 'audio/wav' });

      // 2. Audio-Daten zu WAV konvertieren
      const wavBlob = await this.convertToWAV(audioBlob);

      // 3. Validierung der WAV-Datei
      const validationResult = await this.validateWAVFormat(wavBlob);

      if (validationResult.valid) {
        console.log('✅ WAV-Konvertierung erfolgreich:', validationResult);
        this.onDataAvailable(wavBlob);
      } else {
        console.error('❌ WAV-Validierung fehlgeschlagen:', validationResult.error);
        this.onError(new Error(`WAV-Validierung fehlgeschlagen: ${validationResult.error}`));
      }

    } catch (error) {
      console.error('❌ Fehler bei Audio-Verarbeitung:', error);
      this.onError(error);
    }
  }

  async convertToWAV(audioBlob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();

      reader.onload = async () => {
        try {
          // 1. Audio-Daten dekodieren
          const arrayBuffer = reader.result;
          const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer);

          // 2. Audio-Eigenschaften normalisieren
          const { sampleRate, channels } = this.options;
          const normalizedBuffer = this.normalizeAudioBuffer(audioBuffer, sampleRate, channels);

          // 3. WAV-Header erstellen und Audio-Daten kombinieren
          const wavArrayBuffer = this.encodeWAV(normalizedBuffer, sampleRate);
          const wavBlob = new Blob([wavArrayBuffer], { type: 'audio/wav' });

          resolve(wavBlob);

        } catch (error) {
          console.error('Fehler bei Audio-Dekodierung:', error);
          reject(error);
        }
      };

      reader.onerror = () => reject(new Error('FileReader-Fehler'));
      reader.readAsArrayBuffer(audioBlob);
    });
  }

  normalizeAudioBuffer(audioBuffer, targetSampleRate, targetChannels) {
    const { sampleRate, numberOfChannels } = audioBuffer;

    // Wenn bereits korrekte Specs, direkter Buffer-Zugriff
    if (sampleRate === targetSampleRate && numberOfChannels === targetChannels) {
      return audioBuffer.getChannelData(0);
    }

    // Resampling wenn nötig
    const length = Math.floor(audioBuffer.length * (targetSampleRate / sampleRate));
    const result = new Float32Array(length);

    const channelData = audioBuffer.getChannelData(0);

    // Einfaches Linear-Resampling
    for (let i = 0; i < length; i++) {
      const sourceIndex = i * (audioBuffer.length / length);
      const index = Math.floor(sourceIndex);
      const fraction = sourceIndex - index;

      if (index + 1 < audioBuffer.length) {
        result[i] = channelData[index] * (1 - fraction) + channelData[index + 1] * fraction;
      } else {
        result[i] = channelData[index];
      }
    }

    // Channel-Mixing bei Stereo -> Mono
    if (numberOfChannels > 1 && targetChannels === 1) {
      // Bereits oben behandelt mit getChannelData(0)
    }

    return result;
  }

  encodeWAV(audioData, sampleRate) {
    const { bitDepth, channels } = this.options;
    const bytesPerSample = bitDepth / 8;
    const blockAlign = channels * bytesPerSample;
    const byteRate = sampleRate * blockAlign;
    const dataSize = audioData.length * bytesPerSample;
    const fileSize = 36 + dataSize;

    // WAV-Header erstellen
    const buffer = new ArrayBuffer(44 + dataSize);
    const view = new DataView(buffer);

    // RIFF chunk descriptor
    this.writeString(view, 0, 'RIFF');
    view.setUint32(4, fileSize, true);
    this.writeString(view, 8, 'WAVE');

    // fmt sub-chunk
    this.writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true);           // Subchunk1Size (16 für PCM)
    view.setUint16(20, 1, true);            // AudioFormat (1 = PCM)
    view.setUint16(22, channels, true);     // NumChannels
    view.setUint32(24, sampleRate, true);   // SampleRate
    view.setUint32(28, byteRate, true);     // ByteRate
    view.setUint16(32, blockAlign, true);   // BlockAlign
    view.setUint16(34, bitDepth, true);     // BitsPerSample

    // data sub-chunk
    this.writeString(view, 36, 'data');
    view.setUint32(40, dataSize, true);

    // Audio-Daten schreiben (Float32 -> Int16 Konvertierung)
    let offset = 44;
    for (let i = 0; i < audioData.length; i++) {
      // Normalisierung und Clipping
      let sample = Math.max(-1, Math.min(1, audioData[i]));
      // Float zu 16-bit Integer
      sample = sample * 0x7FFF;
      view.setInt16(offset, sample, true);
      offset += 2;
    }

    return buffer;
  }

  writeString(view, offset, string) {
    for (let i = 0; i < string.length; i++) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  }

  async validateWAVFormat(wavBlob) {
    return new Promise((resolve) => {
      const reader = new FileReader();

      reader.onload = () => {
        const arrayBuffer = reader.result;
        const dataView = new DataView(arrayBuffer);

        try {
          // RIFF-Header prüfen
          const riff = String.fromCharCode(...new Uint8Array(arrayBuffer, 0, 4));
          if (riff !== 'RIFF') {
            resolve({ valid: false, error: 'Kein RIFF-Header gefunden' });
            return;
          }

          // WAVE-Format prüfen
          const wave = String.fromCharCode(...new Uint8Array(arrayBuffer, 8, 4));
          if (wave !== 'WAVE') {
            resolve({ valid: false, error: 'Kein WAVE-Format gefunden' });
            return;
          }

          // fmt chunk prüfen
          const fmt = String.fromCharCode(...new Uint8Array(arrayBuffer, 12, 4));
          if (fmt !== 'fmt ') {
            resolve({ valid: false, error: 'Kein fmt-chunk gefunden' });
            return;
          }

          // Audio-Eigenschaften lesen
          const audioFormat = dataView.getUint16(20, true);
          const channels = dataView.getUint16(22, true);
          const sampleRate = dataView.getUint32(24, true);
          const bitDepth = dataView.getUint16(34, true);

          resolve({
            valid: true,
            format: {
              audioFormat,
              channels,
              sampleRate,
              bitDepth,
              fileSize: arrayBuffer.byteLength
            }
          });

        } catch (error) {
          resolve({ valid: false, error: error.message });
        }
      };

      reader.onerror = () => resolve({ valid: false, error: 'FileReader-Fehler' });
      reader.readAsArrayBuffer(wavBlob);
    });
  }

  cleanup() {
    if (this.stream) {
      this.stream.getTracks().forEach(track => track.stop());
      this.stream = null;
    }

    if (this.audioContext && this.audioContext.state !== 'closed') {
      this.audioContext.close();
      this.audioContext = null;
    }

    this.mediaRecorder = null;
    this.recordedChunks = [];
    this.isRecording = false;
  }

  // Utility-Methoden für Frontend-Integration
  async uploadToAPI(wavBlob, sessionId, sourceLanguage, targetLanguage) {
    const formData = new FormData();
    formData.append('file', wavBlob, 'recording.wav');
    formData.append('source_lang', sourceLanguage);
    formData.append('target_lang', targetLanguage);
    formData.append('client_type', 'customer'); // oder 'admin'

    try {
      const response = await fetch(`/api/session/${sessionId}/message`, {
        method: 'POST',
        body: formData
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(`Upload fehlgeschlagen: ${errorData.error_message || response.statusText}`);
      }

      return await response.json();

    } catch (error) {
      console.error('❌ Audio-Upload-Fehler:', error);
      throw error;
    }
  }
}

// Verwendungsbeispiel:
/**
 * const recorder = new AudioRecorderWithWAVConversion({
 *   sampleRate: 16000,
 *   bitDepth: 16,
 *   channels: 1,
 *   maxDurationMs: 20000,
 *   onStart: () => console.log('Aufnahme gestartet'),
 *   onStop: () => console.log('Aufnahme gestoppt'),
 *   onDataAvailable: async (wavBlob) => {
 *     try {
 *       const result = await recorder.uploadToAPI(wavBlob, sessionId, 'de', 'en');
 *       console.log('Upload erfolgreich:', result);
 *     } catch (error) {
 *       console.error('Upload-Fehler:', error);
 *     }
 *   },
 *   onError: (error) => console.error('Aufnahme-Fehler:', error)
 * });
 *
 * // Aufnahme starten
 * await recorder.startRecording();
 *
 * // Manuell stoppen (oder automatisch nach 20s)
 * recorder.stopRecording();
 */

export default AudioRecorderWithWAVConversion;