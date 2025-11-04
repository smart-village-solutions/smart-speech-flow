import logging

from fastapi import File, Form, UploadFile
from fastapi.responses import HTMLResponse

from services.api_gateway.app import app
from services.api_gateway.pipeline_logic import process_wav

logger = logging.getLogger("api_gateway")


@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    source_lang: str = Form(...),
    target_lang: str = Form(...),
):
    from base64 import b64encode

    requests_total = app.requests_total if hasattr(app, "requests_total") else None
    if requests_total:
        requests_total.inc()
    logger.info(
        "Upload form received: source_lang=%s, target_lang=%s", source_lang, target_lang
    )
    if not source_lang or not target_lang:
        return HTMLResponse(
            content="<html><body><h2>Fehler</h2><p>Sprachparameter fehlen! Bitte Ausgangs- und Zielsprache wählen.</p></body></html>",
            status_code=400,
        )
    file_bytes = await file.read()
    result = process_wav(file_bytes, source_lang, target_lang)
    if result["error"]:
        logger.info(
            "Upload pipeline error: error=%s, originalText=%s, translatedText=%s",
            result["error_msg"],
            result.get("asr_text"),
            result.get("translation_text"),
        )
        return HTMLResponse(
            content="""
            <html>
            <head><title>Fehler bei der Verarbeitung</title></head>
            <body>
                <h2>Fehler</h2>
                <p>{result['error_msg']}</p>
                <p>Transkription: {result['asr_text']}</p>
                <p>Übersetzung: {result['translation_text']}</p>
            </body>
            </html>
        """
        )
    audio_b64 = b64encode(result["audio_bytes"]).decode()
    logger.info(
        "Upload pipeline success: source_lang=%s, target_lang=%s, originalText=%s, translatedText=%s, audioBytes=%s",
        source_lang,
        target_lang,
        result["asr_text"],
        result["translation_text"],
        len(result["audio_bytes"]) if result["audio_bytes"] else 0,
    )
    return HTMLResponse(
        content=f"""
        <html>
        <head><title>Ergebnis Download</title></head>
        <body>
            <h2>Ergebnis</h2>
            <p>Transkription: {result['asr_text']}</p>
            <p>Übersetzung: {result['translation_text']}</p>
            <p>Ausgangssprache: {source_lang}</p>
            <p>Zielsprache: {target_lang}</p>
            <a href='data:audio/wav;base64,{audio_b64}' download='output.wav'>WAV herunterladen</a>
            <audio controls src='data:audio/wav;base64,{audio_b64}'></audio>
        </body>
        </html>
    """
    )
