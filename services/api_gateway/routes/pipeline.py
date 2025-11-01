from fastapi import UploadFile, File, Form, Request, Response
from services.api_gateway.app import app
import base64
import requests
import logging
import time, psutil

from services.api_gateway.app import ASR_URL, TRANSLATION_URL, TTS_URL
from services.api_gateway.pipeline_logic import process_wav

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

# The process_wav function is now imported from pipeline_logic.py
# This old implementation has been replaced by the new one with audio validation

@app.post("/pipeline")
async def pipeline(
    request: Request,
    file: UploadFile = File(...),
    source_lang: str = Form(...),
    target_lang: str = Form(...),
    debug: str = Form(None)
):
    requests_total = app.requests_total if hasattr(app, 'requests_total') else None
    if requests_total:
        requests_total.inc()
    debug_query = request.query_params.get("debug", None)
    debug_active = (str(debug).lower() == "true") or (str(debug_query).lower() == "true")
    file_bytes = await file.read()
    result = process_wav(file_bytes, source_lang, target_lang, debug=debug_active, validate_audio=True)
    def get_origin(request: Request):
        o = request.headers.get("origin", "")
        allowed = [
            "https://parse-sticky-41228602.figma.site",
            "https://1cedb955-758f-44f9-850c-84a0259d095c-figmaiframepreview.figma.site",
            "https://translate.smart-village.solutions"
        ]
        return o if o in allowed else allowed[0]
    def pipeline_response(request, content, status_code=200):
        origin = get_origin(request)
        return Response(
            content=content,
            media_type="application/json",
            status_code=status_code,
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, Accept",
                "Access-Control-Allow-Credentials": "true"
            }
        )
    import logging
    logger = logging.getLogger("api_gateway")
    async def inner(request: Request):
        import json
        if result["error"]:
            logger.info(f"Frontend-Response: Fehler: {result['error_msg']}")
            response_obj = {
                "success": False,
                "error": result["error_msg"],
                "debug": result.get("debug", {})
            }
            return pipeline_response(request, json.dumps(response_obj), status_code=400)
        audio_b64 = base64.b64encode(result["audio_bytes"]).decode() if result["audio_bytes"] else None
        logger.info(f"Frontend-Response: success, originalText={result['asr_text']}, translatedText={result['translation_text']}, audioBytes={len(result['audio_bytes']) if result['audio_bytes'] else 0}")
        response_obj = {
            "success": True,
            "originalText": result["asr_text"],
            "translatedText": result["translation_text"],
            "audioBase64": audio_b64,
            "debug": result.get("debug", {})
        }
        return pipeline_response(request, json.dumps(response_obj))
    return await inner(request)
