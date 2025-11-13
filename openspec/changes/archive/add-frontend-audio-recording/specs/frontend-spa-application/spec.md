# Spec Delta: Frontend SPA Application - Audio Recording

This file contains requirement deltas for the `frontend-spa-application` capability related to audio recording functionality.

## ADDED Requirements

### Requirement: Audio Recording with WAV Conversion
The system SHALL provide a browser-based audio recording utility that captures microphone input and converts it to WAV format compatible with the backend ASR service.

#### Scenario: Successful audio recording and conversion
- **GIVEN** user grants microphone permissions
- **AND** user is in an active session
- **WHEN** user clicks the recording button
- **THEN** the system SHALL start recording audio using MediaRecorder API
- **AND** the system SHALL display a pulsing microphone icon
- **AND** the system SHALL show recording duration in real-time
- **AND** the system SHALL automatically stop after 20 seconds maximum

#### Scenario: WAV format conversion after recording
- **GIVEN** user has completed an audio recording
- **WHEN** the recording stops
- **THEN** the system SHALL decode the browser-native audio format (WebM/Opus, OGG/Opus, or MP4/AAC)
- **AND** the system SHALL resample to 16kHz sample rate
- **AND** the system SHALL convert to mono channel
- **AND** the system SHALL encode as 16-bit PCM WAV format
- **AND** the system SHALL validate the generated WAV file structure (RIFF/WAVE headers)
- **AND** the system SHALL provide the WAV blob for upload

#### Scenario: Cross-browser audio format support
- **GIVEN** user opens the application in any supported browser
- **WHEN** the system initializes audio recording
- **THEN** the system SHALL detect supported MediaRecorder MIME types
- **AND** the system SHALL try formats in order: audio/webm;codecs=opus, audio/webm, audio/mp4, audio/wav
- **AND** the system SHALL use the first supported format
- **AND** the system SHALL fail gracefully with error message if no format is supported

#### Scenario: Microphone permission denied
- **GIVEN** user has not granted microphone permissions
- **WHEN** user attempts to start recording
- **THEN** the system SHALL request microphone access via navigator.mediaDevices.getUserMedia
- **AND** IF permission is denied
- **THEN** the system SHALL display error message "Mikrofon-Zugriff verweigert. Bitte Berechtigungen prüfen."
- **AND** the system SHALL remain in idle state
- **AND** the system SHALL allow retry

#### Scenario: Audio conversion failure handling
- **GIVEN** user has completed a recording
- **WHEN** WAV conversion fails due to decode error or unsupported format
- **THEN** the system SHALL display error message with conversion failure reason
- **AND** the system SHALL reset recording state to idle
- **AND** the system SHALL clean up audio resources (AudioContext, MediaStream)
- **AND** the system SHALL allow user to retry recording

### Requirement: Audio Message Upload via FormData
The system SHALL upload recorded audio messages to the backend using multipart/form-data format with all required parameters.

#### Scenario: Successful audio message upload
- **GIVEN** user has recorded and converted audio to WAV format
- **AND** user is in an active session with valid session ID
- **WHEN** the system initiates upload
- **THEN** the system SHALL create a FormData object
- **AND** the system SHALL append the WAV blob with filename 'recording.wav'
- **AND** the system SHALL append source_lang parameter based on client type
- **AND** the system SHALL append target_lang parameter based on client type
- **AND** the system SHALL append client_type parameter ('admin' or 'customer')
- **AND** the system SHALL send POST request to /api/session/{sessionId}/message
- **AND** the system SHALL handle response with message_id and pipeline_metadata

#### Scenario: Upload progress indication
- **GIVEN** audio upload is in progress
- **WHEN** the system is sending the audio file
- **THEN** the system SHALL display "Wird verarbeitet..." message
- **AND** the system SHALL show loading spinner
- **AND** the system SHALL disable input controls during upload
- **AND** the system SHALL remain responsive for other UI interactions

#### Scenario: Upload error handling
- **GIVEN** audio upload is initiated
- **WHEN** upload fails due to network error, timeout, or backend error
- **THEN** the system SHALL display user-friendly error message extracted from API response
- **AND** the system SHALL log technical error details to console
- **AND** the system SHALL reset recording state to idle
- **AND** the system SHALL allow user to retry recording

#### Scenario: Optimistic UI update during upload
- **GIVEN** user completes audio recording
- **WHEN** upload starts
- **THEN** the system SHALL immediately add message to UI with 'sending' status
- **AND** the system SHALL assign temporary message ID
- **AND** WHEN backend response is received
- **THEN** the system SHALL map temporary ID to actual message_id
- **AND** the system SHALL update message status to 'sent'
- **AND** WHEN WebSocket broadcast arrives
- **THEN** the system SHALL merge WebSocket message with existing message using ID mapping

### Requirement: Audio Resource Management
The system SHALL properly manage and clean up audio-related resources to prevent memory leaks and ensure stable operation.

#### Scenario: Resource cleanup on component unmount
- **GIVEN** user navigates away from chat interface
- **OR** user closes the browser tab
- **WHEN** MessageInput component unmounts
- **THEN** the system SHALL stop any active recording
- **AND** the system SHALL close AudioContext if open
- **AND** the system SHALL stop all MediaStream tracks
- **AND** the system SHALL clear all audio chunk references
- **AND** the system SHALL clear recording interval timer

#### Scenario: Resource cleanup after successful upload
- **GIVEN** audio has been successfully converted and uploaded
- **WHEN** upload completes
- **THEN** the system SHALL close the AudioContext used for conversion
- **AND** the system SHALL stop all MediaStream tracks from recording
- **AND** the system SHALL clear audio chunks array
- **AND** the system SHALL allow garbage collection of Blob references

#### Scenario: Resource cleanup after error
- **GIVEN** audio recording or conversion fails
- **WHEN** error is handled
- **THEN** the system SHALL perform full cleanup of audio resources
- **AND** the system SHALL ensure no AudioContext remains open
- **AND** the system SHALL ensure no MediaStream tracks are active
- **AND** the system SHALL reset all recording-related state

## MODIFIED Requirements

### Requirement: Message Input Component
The system SHALL provide a message input interface that allows users to send both text and audio messages with mode toggle and appropriate visual feedback.

**NOTE:** This is an extension of the existing requirement to include fully functional audio recording.

#### Scenario: Audio mode activation (UPDATED)
- **GIVEN** user is in text input mode
- **WHEN** user clicks the "🎤 Audio" toggle button
- **THEN** the system SHALL switch to audio input mode
- **AND** the system SHALL hide text input field
- **AND** the system SHALL display audio recording button
- **AND** the system SHALL disable mode toggle during active recording

#### Scenario: Text mode deactivation during recording (UPDATED)
- **GIVEN** user is currently recording audio
- **WHEN** user attempts to switch to text mode
- **THEN** the system SHALL keep mode toggle button disabled
- **AND** the system SHALL prevent mode change
- **AND** the system SHALL only allow mode change after recording is stopped or completed

#### Scenario: Send audio message integration (NEW)
- **GIVEN** user has recorded audio
- **AND** WAV conversion is complete
- **WHEN** the system uploads audio message
- **THEN** the system SHALL use the same optimistic UI pattern as text messages
- **AND** the system SHALL register temporary-to-real message ID mapping
- **AND** the system SHALL update message status based on API response
- **AND** the system SHALL merge with WebSocket broadcast when received
- **AND** the system SHALL display error if upload fails

### Requirement: Error Display and User Feedback
The system SHALL provide clear, actionable error messages for all audio-related failures with appropriate visual styling.

**NOTE:** Extended to include audio-specific error scenarios.

#### Scenario: Audio recording error display (NEW)
- **GIVEN** an error occurs during audio recording, conversion, or upload
- **WHEN** the error is detected
- **THEN** the system SHALL display error in red-bordered alert box
- **AND** the system SHALL show user-friendly error message (German)
- **AND** the system SHALL include actionable guidance if applicable
- **AND** the system SHALL auto-dismiss after user interaction or 10 seconds
- **AND** the system SHALL log technical details to browser console

#### Scenario: Permission error guidance (NEW)
- **GIVEN** microphone permission is denied
- **WHEN** error is displayed to user
- **THEN** the system SHALL show message "Mikrofon-Zugriff verweigert. Bitte Berechtigungen prüfen."
- **AND** the system SHALL include guidance to check browser settings
- **AND** the system SHALL provide retry button

## RENAMED Requirements

None.

## REMOVED Requirements

None.

---

**Implementation Notes:**

1. **TypeScript Utility Module**: Create `src/utils/AudioRecorderWithWAVConversion.ts` as standalone, reusable module
2. **No Additional Dependencies**: Use only browser-native APIs (Web Audio API, MediaRecorder, FileReader)
3. **Cross-Browser Testing**: Validate on Chrome, Firefox, Safari, Edge
4. **Performance Target**: WAV conversion should complete in < 500ms for 10 seconds of audio
5. **Memory Safety**: Ensure all AudioContext, MediaStream, and Blob references are properly cleaned up
