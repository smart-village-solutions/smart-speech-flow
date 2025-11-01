from fastapi.responses import JSONResponse, HTMLResponse
from services.api_gateway.app import app, SERVICE_URLS
from services.api_gateway.utils.health_utils import get_health_status_html
import requests


@app.get("/health")
def health():
    status = {}
    for name, url in SERVICE_URLS.items():
        try:
            r = requests.get(url, timeout=2)
            status[name] = "ok" if r.status_code == 200 else f"Fehler ({r.status_code})"
        except Exception as e:
            status[name] = f"nicht erreichbar: {e}"
    return {"services": status}
