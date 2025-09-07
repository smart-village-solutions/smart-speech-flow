FROM python:3.10-slim
WORKDIR /app
COPY app.py ./
COPY requirements.txt ./
COPY tests/ ./tests/
RUN apt-get update && apt-get install -y espeak-ng
RUN apt-get update && apt-get install -y curl
RUN pip install --no-cache-dir -r requirements.txt
RUN pytest tests/ || true
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
