from fastapi.responses import Response
from prometheus_client import generate_latest
from services.api_gateway.app import app, registry

@app.get("/metrics")
def metrics():
    return Response(generate_latest(registry), media_type="text/plain")
