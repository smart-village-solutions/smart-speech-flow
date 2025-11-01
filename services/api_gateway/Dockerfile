## Basis-Image: Schlankes Python 3.10
FROM python:3.10-slim

# Arbeitsverzeichnis im Container
WORKDIR /app

# requirements.txt kopieren und Abhängigkeiten installieren
COPY services/api_gateway/requirements.txt ./
RUN apt-get update && apt-get install -y curl
RUN pip install --no-cache-dir -r requirements.txt

# Gesamten Code (inkl. services/) nach /app kopieren
COPY ../../ /app
# Kopiere den examples-Ordner explizit nach /app/examples
COPY ../../examples /app/examples

# Arbeitsverzeichnis für Uvicorn setzen
WORKDIR /app

# PYTHONPATH setzen, damit absolute Imports funktionieren
ENV PYTHONPATH=/app

# Startbefehl für FastAPI
CMD ["uvicorn", "services.api_gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
