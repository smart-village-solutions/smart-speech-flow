FROM nvidia/cuda:13.2.0-cudnn-runtime-ubuntu22.04

# System- und Python-Abhängigkeiten installieren
RUN apt-get update && \
	apt-get install -y python3 python3-pip ffmpeg curl && \
	rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
COPY app.py ./
# COPY tests/ ./tests/

RUN pip install --no-cache-dir -r requirements.txt
# RUN pip install pytest
# RUN pytest tests/ || true
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
