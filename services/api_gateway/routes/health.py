import requests
from fastapi import APIRouter
from requests import RequestException

from services.api_gateway.app import SERVICE_URLS

router = APIRouter()


@router.get("/health")
def health():
    status = {}
    for name, url in SERVICE_URLS.items():
        try:
            r = requests.get(url, timeout=2)
            status[name] = "ok" if r.status_code == 200 else f"Fehler ({r.status_code})"
        except RequestException:
            # The exception text names internal hosts and ports; this route is public.
            status[name] = "nicht erreichbar"
    return {"services": status}
