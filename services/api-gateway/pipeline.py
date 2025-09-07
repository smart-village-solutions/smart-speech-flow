# Pipeline-Logik für die WAV-Verarbeitung
import requests
import logging

ASR_URL = "http://asr:8000/transcribe"
TRANSLATION_URL = "http://translation:8000/translate"
TTS_URL = "http://tts:8000/synthesize"

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

def process_wav(file_bytes, source_lang, target_lang):
    logging.info(f"Starte Pipeline: source_lang={source_lang}, target_lang={target_lang}")
    logging.info(f"ASR-Request: lang={source_lang}")
    asr_resp = requests.post(ASR_URL, files={"file": ("input.wav", file_bytes, "audio/wav")}, data={"lang": source_lang})
    logging.info(f"ASR-Response: {asr_resp.status_code}, text={asr_resp.json().get('text', '')}")
    asr_text = asr_resp.json().get("text", "")
    logging.info(f"Translation-Request: source_lang={source_lang}, target_lang={target_lang}, text={asr_text}")
    translation_payload = {
        "text": asr_text,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "model": "m2m100_1.2B"
    }
    translation_resp = requests.post(TRANSLATION_URL, json=translation_payload)
    logging.info(f"Translation-Response: {translation_resp.status_code}, translations={translation_resp.json().get('translations', '')}")
    if translation_resp.status_code != 200:
        try:
            error_json = translation_resp.json()
            error_msg = error_json.get("detail") or str(error_json)
        except Exception:
            error_msg = translation_resp.text
        logging.error(f"Translation-Fehler: {error_msg}")
        return {
            "error": True,
            "error_msg": f"Translation-Fehler: {error_msg}",
            "asr_text": asr_text,
            "translation_text": None,
            "audio_bytes": None
        }
    translation_text = translation_resp.json().get("translations", "")
    logging.info(f"TTS-Request: lang={target_lang}, text={translation_text}")
    tts_resp = requests.post(TTS_URL, json={"text": translation_text, "lang": target_lang})
    logging.info(f"TTS-Response: {tts_resp.status_code}, content-type={tts_resp.headers.get('content-type','')}")
    if tts_resp.status_code != 200 or tts_resp.headers.get("content-type","") != "audio/wav":
        try:
            error_json = tts_resp.json()
            error_msg = error_json.get("error") or str(error_json)
        except Exception:
            error_msg = tts_resp.text
        logging.error(f"TTS-Fehler: {error_msg}")
        return {
            "error": True,
            "error_msg": f"TTS-Fehler: {error_msg}",
            "asr_text": asr_text,
            "translation_text": translation_text,
            "audio_bytes": None
        }
    audio_bytes = tts_resp.content
    logging.info(f"Pipeline erfolgreich: ASR={asr_text}, Translation={translation_text}, Audio-Bytes={len(audio_bytes)}")
    return {
        "error": False,
        "asr_text": asr_text,
        "translation_text": translation_text,
        "audio_bytes": audio_bytes
    }
