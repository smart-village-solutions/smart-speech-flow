FROM nvidia/cuda:13.0.0-cudnn-runtime-ubuntu22.04

# System- und Python-Abhängigkeiten installieren
RUN apt-get update && \
	apt-get install -y python3 python3-pip espeak-ng curl && \
	rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app.py ./
COPY requirements.txt ./
# COPY tests/ ./tests/
RUN pip3 install --upgrade pip && \
	pip3 install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu121 && \
	pip3 install --no-cache-dir -r requirements.txt
# RUN pytest tests/ || true
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
