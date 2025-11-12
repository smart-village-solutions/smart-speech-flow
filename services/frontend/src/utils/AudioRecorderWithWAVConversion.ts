/**
 * Audio Recording & WAV Conversion Utility
 *
 * This module provides browser-based audio recording with automatic conversion
 * to WAV format (16kHz, 16-bit, Mono PCM) for backend compatibility.
 *
 * @module AudioRecorderWithWAVConversion
 */

/**
 * Configuration options for the audio recorder
 */
export interface AudioRecorderConfig {
  /** Sample rate in Hz (default: 16000 for backend compatibility) */
  sampleRate?: number;

  /** Bit depth: 8 or 16 (default: 16) */
  bitDepth?: 8 | 16;

  /** Number of audio channels: 1 (mono) or 2 (stereo) (default: 1) */
  channels?: 1 | 2;

  /** Maximum recording duration in milliseconds (default: 20000 = 20 seconds) */
  maxDurationMs?: number;

  /** Callback when recording starts */
  onStart?: () => void;

  /** Callback when recording stops */
  onStop?: () => void;

  /** Callback when WAV blob is ready for upload */
  onDataAvailable?: (wavBlob: Blob) => void;

  /** Callback on any error (microphone access, conversion, etc.) */
  onError?: (error: Error) => void;
}

/**
 * Result of WAV format validation
 */
export interface WAVValidationResult {
  /** Whether the WAV file is valid */
  valid: boolean;

  /** Error message if validation failed */
  error?: string;

  /** Format details if validation succeeded */
  format?: {
    /** Audio format code (1 = PCM) */
    audioFormat: number;

    /** Number of channels */
    channels: number;

    /** Sample rate in Hz */
    sampleRate: number;

    /** Bit depth */
    bitDepth: number;

    /** Total file size in bytes */
    fileSize: number;
  };
}

/**
 * Audio Recording & WAV Conversion Utility Class
 *
 * Usage:
 * ```typescript
 * const recorder = new AudioRecorderWithWAVConversion({
 *   sampleRate: 16000,
 *   bitDepth: 16,
 *   channels: 1,
 *   maxDurationMs: 20000,
 *   onDataAvailable: async (wavBlob) => {
 *     // Upload to backend
 *     await uploadAudio(wavBlob);
 *   },
 *   onError: (error) => console.error('Recording error:', error)
 * });
 *
 * await recorder.startRecording();
 * // User speaks...
 * recorder.stopRecording(); // Or auto-stops after maxDurationMs
 * ```
 */
export class AudioRecorderWithWAVConversion {
  private options: Required<AudioRecorderConfig>;
  private mediaRecorder: MediaRecorder | null = null;
  private audioContext: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private recordedChunks: Blob[] = [];
  private isRecording = false;
  private autoStopTimeout: number | null = null;

  constructor(options: AudioRecorderConfig = {}) {
    this.options = {
      sampleRate: options.sampleRate ?? 16000,
      bitDepth: options.bitDepth ?? 16,
      channels: options.channels ?? 1,
      maxDurationMs: options.maxDurationMs ?? 20000,
      onStart: options.onStart ?? (() => {}),
      onStop: options.onStop ?? (() => {}),
      onDataAvailable: options.onDataAvailable ?? (() => {}),
      onError: options.onError ?? (() => {}),
    };
  }

  /**
   * Start audio recording
   * Requests microphone permission and begins recording
   */
  async startRecording(): Promise<void> {
    try {
      // Request microphone access
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: this.options.sampleRate,
          channelCount: this.options.channels,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      // Create AudioContext for WAV conversion
      const AudioContextConstructor = window.AudioContext || (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      this.audioContext = new (AudioContextConstructor!)({
        sampleRate: this.options.sampleRate,
      });

      // Try different MIME types in order of preference
      const mimeTypes = [
        'audio/webm;codecs=opus',
        'audio/webm',
        'audio/mp4',
        'audio/wav',
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
        audioBitsPerSecond: 128000,
      });

      this.recordedChunks = [];

      // Event handlers
      this.mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          this.recordedChunks.push(event.data);
        }
      };

      this.mediaRecorder.onstop = async () => {
        await this.processRecording();
        this.cleanup();
      };

      this.mediaRecorder.onerror = (event: Event) => {
        console.error('MediaRecorder error:', event);
        this.options.onError(new Error('MediaRecorder-Fehler'));
        this.cleanup();
      };

      // Start recording
      this.mediaRecorder.start(1000); // Collect data every 1 second
      this.isRecording = true;

      // Auto-stop after max duration
      this.autoStopTimeout = window.setTimeout(() => {
        if (this.isRecording) {
          this.stopRecording();
        }
      }, this.options.maxDurationMs);

      this.options.onStart();
      console.log('✅ Recording started with:', selectedMimeType);
    } catch (error) {
      console.error('❌ Failed to start recording:', error);
      this.options.onError(error as Error);
      this.cleanup();
    }
  }

  /**
   * Stop audio recording
   * Triggers WAV conversion and cleanup
   */
  stopRecording(): void {
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
      this.isRecording = false;

      if (this.autoStopTimeout) {
        clearTimeout(this.autoStopTimeout);
        this.autoStopTimeout = null;
      }
    }
  }

  /**
   * Process recorded audio: combine chunks, convert to WAV, validate
   */
  private async processRecording(): Promise<void> {
    try {
      // Combine recorded chunks
      const audioBlob = new Blob(this.recordedChunks, { type: 'audio/wav' });

      // Convert to WAV format
      const wavBlob = await this.convertToWAV(audioBlob);

      // Validate WAV format
      const validationResult = await this.validateWAVFormat(wavBlob);

      if (validationResult.valid) {
        console.log('✅ WAV conversion successful:', validationResult);
        this.options.onDataAvailable(wavBlob);
      } else {
        console.error('❌ WAV validation failed:', validationResult.error);
        this.options.onError(
          new Error(`WAV-Validierung fehlgeschlagen: ${validationResult.error}`)
        );
      }
    } catch (error) {
      console.error('❌ Error processing audio:', error);
      this.options.onError(error as Error);
    }
  }

  /**
   * Convert browser audio format to WAV
   */
  private async convertToWAV(audioBlob: Blob): Promise<Blob> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();

      reader.onload = async () => {
        try {
          if (!this.audioContext) {
            throw new Error('AudioContext not initialized');
          }

          // Decode audio data
          const arrayBuffer = reader.result as ArrayBuffer;
          const audioBuffer = await this.audioContext.decodeAudioData(arrayBuffer);

          // Normalize audio properties
          const { sampleRate, channels } = this.options;
          const normalizedBuffer = this.normalizeAudioBuffer(audioBuffer, sampleRate, channels);

          // Create WAV header and combine with audio data
          const wavArrayBuffer = this.encodeWAV(normalizedBuffer, sampleRate);
          const wavBlob = new Blob([wavArrayBuffer], { type: 'audio/wav' });

          resolve(wavBlob);
        } catch (error) {
          console.error('Error decoding audio:', error);
          reject(error);
        }
      };

      reader.onerror = () => reject(new Error('FileReader error'));
      reader.readAsArrayBuffer(audioBlob);
    });
  }

  /**
   * Normalize audio buffer: resample and convert to mono if needed
   */
  private normalizeAudioBuffer(
    audioBuffer: AudioBuffer,
    targetSampleRate: number,
    targetChannels: number
  ): Float32Array {
    const { sampleRate, numberOfChannels } = audioBuffer;

    // If already correct specs, use directly
    if (sampleRate === targetSampleRate && numberOfChannels === targetChannels) {
      return audioBuffer.getChannelData(0);
    }

    // Resample if needed
    const length = Math.floor(audioBuffer.length * (targetSampleRate / sampleRate));
    const result = new Float32Array(length);
    const channelData = audioBuffer.getChannelData(0);

    // Simple linear resampling
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

    return result;
  }

  /**
   * Encode audio data as WAV format with proper headers
   */
  private encodeWAV(audioData: Float32Array, sampleRate: number): ArrayBuffer {
    const { bitDepth, channels } = this.options;
    const bytesPerSample = bitDepth / 8;
    const blockAlign = channels * bytesPerSample;
    const byteRate = sampleRate * blockAlign;
    const dataSize = audioData.length * bytesPerSample;
    const fileSize = 36 + dataSize;

    // Create buffer for WAV file
    const buffer = new ArrayBuffer(44 + dataSize);
    const view = new DataView(buffer);

    // RIFF chunk descriptor
    this.writeString(view, 0, 'RIFF');
    view.setUint32(4, fileSize, true);
    this.writeString(view, 8, 'WAVE');

    // fmt sub-chunk
    this.writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true); // Subchunk1Size (16 for PCM)
    view.setUint16(20, 1, true); // AudioFormat (1 = PCM)
    view.setUint16(22, channels, true); // NumChannels
    view.setUint32(24, sampleRate, true); // SampleRate
    view.setUint32(28, byteRate, true); // ByteRate
    view.setUint16(32, blockAlign, true); // BlockAlign
    view.setUint16(34, bitDepth, true); // BitsPerSample

    // data sub-chunk
    this.writeString(view, 36, 'data');
    view.setUint32(40, dataSize, true);

    // Write audio data (Float32 → Int16 conversion)
    let offset = 44;
    for (let i = 0; i < audioData.length; i++) {
      // Normalize and clip
      let sample = Math.max(-1, Math.min(1, audioData[i]));
      // Convert to 16-bit integer
      sample = sample * 0x7fff;
      view.setInt16(offset, sample, true);
      offset += 2;
    }

    return buffer;
  }

  /**
   * Write string to DataView at specified offset
   */
  private writeString(view: DataView, offset: number, string: string): void {
    for (let i = 0; i < string.length; i++) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  }

  /**
   * Validate WAV format structure
   */
  private async validateWAVFormat(wavBlob: Blob): Promise<WAVValidationResult> {
    return new Promise((resolve) => {
      const reader = new FileReader();

      reader.onload = () => {
        const arrayBuffer = reader.result as ArrayBuffer;
        const dataView = new DataView(arrayBuffer);

        try {
          // Check RIFF header
          const riff = String.fromCharCode(
            ...new Uint8Array(arrayBuffer, 0, 4)
          );
          if (riff !== 'RIFF') {
            resolve({ valid: false, error: 'Kein RIFF-Header gefunden' });
            return;
          }

          // Check WAVE format
          const wave = String.fromCharCode(
            ...new Uint8Array(arrayBuffer, 8, 4)
          );
          if (wave !== 'WAVE') {
            resolve({ valid: false, error: 'Kein WAVE-Format gefunden' });
            return;
          }

          // Check fmt chunk
          const fmt = String.fromCharCode(
            ...new Uint8Array(arrayBuffer, 12, 4)
          );
          if (fmt !== 'fmt ') {
            resolve({ valid: false, error: 'Kein fmt-chunk gefunden' });
            return;
          }

          // Read audio properties
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
              fileSize: arrayBuffer.byteLength,
            },
          });
        } catch (error) {
          resolve({
            valid: false,
            error: (error as Error).message,
          });
        }
      };

      reader.onerror = () =>
        resolve({ valid: false, error: 'FileReader-Fehler' });
      reader.readAsArrayBuffer(wavBlob);
    });
  }

  /**
   * Clean up resources
   */
  private cleanup(): void {
    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop());
      this.stream = null;
    }

    if (this.audioContext && this.audioContext.state !== 'closed') {
      this.audioContext.close();
      this.audioContext = null;
    }

    if (this.autoStopTimeout) {
      clearTimeout(this.autoStopTimeout);
      this.autoStopTimeout = null;
    }

    this.mediaRecorder = null;
    this.recordedChunks = [];
    this.isRecording = false;
  }

  /**
   * Get current recording state
   */
  getIsRecording(): boolean {
    return this.isRecording;
  }
}
