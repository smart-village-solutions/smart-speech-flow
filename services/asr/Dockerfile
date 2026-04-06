FROM nvidia/cuda:13.0.0-cudnn-runtime-ubuntu22.04

# System- und Python-Abhängigkeiten installieren
RUN apt-get update && \
	apt-get install -y --no-install-recommends curl ffmpeg python3 python3-pip && \
	rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
COPY app.py ./
# COPY tests/ ./tests/
RUN pip3 install --upgrade pip && \
	pip3 install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu121 && \
	pip3 install --no-cache-dir -r requirements.txt && \
	useradd --system --create-home --uid 10001 appuser && \
	chown -R appuser:appuser /app
# RUN pip install pytest
# RUN pytest tests/ || true
USER appuser
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
