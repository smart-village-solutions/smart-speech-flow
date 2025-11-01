from fastapi.responses import Response
from services.api_gateway.app import app, generate_latest

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain")
