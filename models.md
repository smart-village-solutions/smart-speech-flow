# Übersicht der genutzten KI-Modelle

## **1. Whisper** (ASR Service)
- **Beschreibung:** Ein neuronales Modell von OpenAI für die automatische Spracherkennung (ASR). Es ist für viele Sprachen verfügbar.
- **Lizenz:** MIT License
- **Link:** [https://github.com/openai/whisper](https://github.com/openai/whisper)
- **Verwendung im Code:**
  - **Datei:** `services/asr/app.py`
  - **Details:** Wird über `import whisper` eingebunden und mit `whisper.load_model("base", ...)` geladen. Die Transkription erfolgt über die Funktion `model.transcribe(...)`.


## **2. M2M100** (Translation Service)
- **Beschreibung:** Ein neuronales Übersetzungsmodell von Facebook, das Übersetzungen zwischen über 100 Sprachen ermöglicht. Es wird die größere Variante mit 1.2B genutzt.
- **Lizenz:** MIT License
- **Link:** [https://huggingface.co/facebook/m2m100_1.2B](https://huggingface.co/facebook/m2m100_1.2B)
- **Verwendung im Code:**
  - **Datei:** `services/translation/app.py`
  - **Details:** Es werden `M2M100ForConditionalGeneration` und `M2M100Tokenizer` aus der `transformers`-Bibliothek importiert. Das Modell wird über `M2M100ForConditionalGeneration.from_pretrained(MODEL_NAME, ...)` geladen.


## **3. Coqui-TTS** (TTS Service)
- **Beschreibung:** Ein Open-Source-Framework für Text-zu-Sprache (TTS) mit einer Vielzahl vortrainierter Modelle.
- **Lizenz:** Mozilla Public License 2.0
- **Link:** [https://github.com/coqui-ai/TTS](https://github.com/coqui-ai/TTS)
- **Verwendung im Code:**
  - **Datei:** `services/tts/app.py`
  - **Details:** Wird primär für die Sprachsynthese versucht zu laden und zu nutzen. Ein Fallback-Handling ist integriert.
- **Genutzte Modelle pro Sprache:**
  - **Deutsch:** [`tts_models/de/thorsten/vits`](https://github.com/coqui-ai/TTS/blob/main/tts_models/de/thorsten/vits)
  - **Englisch:** [`tts_models/en/ljspeech/vits`](https://github.com/coqui-ai/TTS/blob/main/tts_models/en/ljspeech/vits)
  - **Türkisch:** [`tts_models/tr/common-voice/glow-tts`](https://github.com/coqui-ai/TTS/blob/main/tts_models/tr/common-voice/glow-tts)
  - **Persisch:** `tts_models/fa/custom/glow-tts` (Custom, ggf. interner Link)
  - **Ukrainisch:** [`tts_models/uk/mai/vits`](https://github.com/coqui-ai/TTS/blob/main/tts_models/uk/mai/vits)

## **4. HuggingFace MMS-TTS** (TTS Service, Fallback)
- **Beschreibung:** Multilingual Massive Speech (MMS) TTS von Meta/HuggingFace, das Text-zu-Sprache für über 100 Sprachen bietet.
- **Lizenz:** Apache 2.0
- **Link:** [https://huggingface.co/facebook/mms-tts](https://huggingface.co/facebook/mms-tts)
- **Verwendung im Code:**
  - **Datei:** `services/tts/app.py`
  - **Details:** Dient als Fallback, falls Coqui-TTS fehlschlägt. Es wird die Modell-ID `facebook/mms-tts-{hf_code}` verwendet und der Ladevorgang wird geloggt.
- **Genutzte Modelle pro Sprache:**
  - Die Modellquelle ist für alle Sprachen identisch, die Modell-ID variiert je nach Sprachcode, z. B.:
    - **Arabisch:** [`facebook/mms-tts-ara`](https://huggingface.co/facebook/mms-tts-ara)
    - **Russisch:** [`facebook/mms-tts-rus`](https://huggingface.co/facebook/mms-tts-rus)
    - **Amharisch:** [`facebook/mms-tts-amh`](https://huggingface.co/facebook/mms-tts-amh)
