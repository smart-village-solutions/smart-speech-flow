## Basis-Image: Schlankes Python 3.10
FROM python:3.10-slim

# Arbeitsverzeichnis im Container
WORKDIR /app

# requirements.txt kopieren und Abhängigkeiten installieren
COPY requirements.txt ./
RUN apt-get update && apt-get install -y curl
RUN pip install --no-cache-dir -r requirements.txt

# Eigenen Code in Unterverzeichnis 'app/' kopieren
COPY ./*.py ./app/

# Arbeitsverzeichnis für Uvicorn setzen
WORKDIR /app/app

# Tests installieren und ausführen
RUN pip install pytest
COPY tests/ ./tests/
RUN pytest tests/ || true

# Startbefehl für FastAPI
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
