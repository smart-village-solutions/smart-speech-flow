# Übersicht der genutzten KI-Modelle

## **1. Whisper** (ASR Service)
- **Beschreibung:** Ein neuronales Modell von OpenAI für die automatische Spracherkennung (ASR). Es ist für viele Sprachen verfügbar.
- **Lizenz:** MIT License
- **Link:** [https://github.com/openai/whisper](https://github.com/openai/whisper)
- **Verwendung im Code:**
  - **Datei:** `services/asr/app.py`
  - **Details:** Wird über `import whisper` mit `whisper.load_model("large-v3-turbo", ...)` geladen. Die Transkription verwendet `model.transcribe(...)`.


## **2. M2M100** (Translation Service)
- **Beschreibung:** Ein neuronales Übersetzungsmodell von Facebook, das Übersetzungen zwischen über 100 Sprachen ermöglicht. Es wird die größere Variante mit 1.2B genutzt.
- **Lizenz:** MIT License
- **Link:** [https://huggingface.co/facebook/m2m100_1.2B](https://huggingface.co/facebook/m2m100_1.2B)
- **Verwendung im Code:**
  - **Datei:** `services/translation/app.py`
  - **Details:** Es werden `M2M100ForConditionalGeneration` und `M2M100Tokenizer` aus der `transformers`-Bibliothek importiert. Das Modell wird über `M2M100ForConditionalGeneration.from_pretrained(MODEL_NAME, ...)` geladen.


## **3. Piper** (TTS Service)
- **Description:** VITS voices exported to ONNX, with espeak-ng as the phonemizer. Runs on the GPU through `onnxruntime-gpu` (CUDA execution provider).
- **Licence:** `piper-tts` is GPL-3.0-or-later; each voice carries its own licence (below).
- **Link:** [https://github.com/OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl), voices from [`rhasspy/piper-voices`](https://huggingface.co/rhasspy/piper-voices)
- **Used in:** `services/tts/piper_engine.py`; the voice per language and its pinned files are in `services/tts/voices.py`. The files are baked into the image at build time.
- **Voices:**
  - **German:** `de_DE-thorsten-high` (CC0)
  - **English:** `en_US-ljspeech-high` (public domain)
  - **Turkish:** `tr_TR-dfki-medium` (CC BY-NC-SA 4.0)
  - **Russian:** `ru_RU-denis-medium` (CC0)
  - **Ukrainian:** `uk_UA-tetiana-high` (Apache 2.0)
  - **Arabic:** `ar_JO-kareem-medium` (licence not stated upstream)
  - **Persian:** `fa_IR-gyro-medium` (licence not stated upstream)
  - **Kurdish (Kurmanji):** `ku_TR-berfin_renas-medium` (CC BY-NC 4.0)

## **4. Meta MMS-TTS** (TTS Service)
- **Description:** Massively Multilingual Speech TTS from Meta, used for the two languages Piper has no voice for.
- **Licence:** CC-BY-NC 4.0
- **Link:** [https://huggingface.co/facebook/mms-tts](https://huggingface.co/facebook/mms-tts)
- **Used in:** `services/tts/mms_engine.py`, loaded as `VitsModel` on the GPU.
- **Voices:**
  - **Amharic:** [`facebook/mms-tts-amh`](https://huggingface.co/facebook/mms-tts-amh)
  - **Tigrinya:** [`facebook/mms-tts-tir`](https://huggingface.co/facebook/mms-tts-tir)

MMS was trained on text without digits, so `services/tts/speech_text.py` spells
numbers out for these two languages before synthesis.
