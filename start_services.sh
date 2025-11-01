echo "Beende ggf. laufende Services auf den Ports 8100-8103..."
for PORT in 8100 8101 8102 8103; do
	PID=$(lsof -ti tcp:$PORT)
	if [ -n "$PID" ]; then
		kill -9 $PID 2>/dev/null && echo "Prozess auf Port $PORT beendet (PID $PID)"
	fi
done
#!/bin/bash
# Startet alle Microservices für lokale Tests

export DOCKER_COMPOSE=0

set -e

# ASR
(cd services/asr && source .venv/bin/activate && pip install --break-system-packages -r requirements.txt && uvicorn app:app --host 0.0.0.0 --port 8101 &)

# Translation
(cd services/translation && source .venv/bin/activate && pip install --break-system-packages -r requirements.txt && uvicorn app:app --host 0.0.0.0 --port 8102 &)

# TTS
(cd services/tts && source .venv/bin/activate && pip install --break-system-packages -r requirements.txt && uvicorn app:app --host 0.0.0.0 --port 8103 &)

# API-Gateway
(cd services/api_gateway && source .venv/bin/activate && pip install --break-system-packages -r requirements.txt && PYTHONPATH=../.. uvicorn app:app --host 0.0.0.0 --port 8100 &)

# Hinweis
sleep 2
echo "Alle Services wurden gestartet. Du kannst jetzt die Tests ausführen."
echo "Beende alle Services mit: kill $(jobs -p)"
