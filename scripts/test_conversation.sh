#!/bin/bash
"""
Einfacher End-to-End Test Runner
===============================

Führt den Python-basierten End-to-End Test aus und zeigt die wichtigsten
Ergebnisse in einer übersichtlichen Form.
"""

set -e  # Exit bei Fehlern

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_TEST="$SCRIPT_DIR/test_end_to_end_conversation.py"

echo "🎯 Smart Speech Flow - End-to-End Test"
echo "======================================"

# Prüfe Python-Abhängigkeiten
echo "🔍 Prüfe Abhängigkeiten..."
python3 -c "import websockets, aiohttp, requests" 2>/dev/null || {
    echo "❌ Fehlende Python-Abhängigkeiten"
    echo "Installiere mit:"
    echo "  pip install websockets aiohttp requests"
    exit 1
}

# Prüfe ob Docker-Services laufen
echo "🐳 Prüfe Docker-Services..."
if ! docker compose ps | grep -q "Up"; then
    echo "⚠️  Nicht alle Services laufen"
    echo "Starte Services..."
    docker compose up -d
    echo "⏳ Warte 10 Sekunden bis Services bereit sind..."
    sleep 10
fi

# API-Gateway Bereitschaft prüfen
echo "🔍 Prüfe API-Gateway..."
for i in {1..30}; do
    if curl -s http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ API-Gateway bereit"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "❌ API-Gateway nicht erreichbar nach 30 Versuchen"
        echo "Logs anzeigen:"
        echo "  docker logs ssf-backend-api_gateway-1"
        exit 1
    fi
    echo "⏳ Warte auf API-Gateway... ($i/30)"
    sleep 1
done

# Führe End-to-End Test aus
echo ""
echo "🚀 Starte End-to-End Test..."
echo "=============================="

# Python-Test ausführen und Exit-Code erfassen
if python3 "$PYTHON_TEST"; then
    echo ""
    echo "🎉 Test erfolgreich abgeschlossen!"
    echo ""
    echo "📋 Was wurde getestet:"
    echo "  ✅ Session-Erstellung (Admin)"
    echo "  ✅ Session-Aktivierung (Client, Englisch)"
    echo "  ✅ WebSocket-Verbindungen (bidirektional)"
    echo "  ✅ Audio-Upload und -Verarbeitung"
    echo "  ✅ ASR (Deutsch ↔ Englisch)"
    echo "  ✅ Übersetzung (M2M100)"
    echo "  ✅ TTS (Deutsch ↔ Englisch)"
    echo "  ✅ WebSocket-Benachrichtigungen"
    echo "  ✅ Session-Cleanup"
    echo ""
    echo "🔍 Weitere Informationen:"
    echo "  • Detaillierte Logs im Terminal ausgabe oben"
    echo "  • JSON-Ergebnisse in test_results_*.json"
    echo "  • WebSocket-Metriken: curl http://localhost:8000/metrics | grep websocket"

    exit 0
else
    echo ""
    echo "❌ Test fehlgeschlagen!"
    echo ""
    echo "🔍 Debugging-Schritte:"
    echo "  1. Services-Status prüfen: docker compose ps"
    echo "  2. API-Gateway Logs: docker logs ssf-backend-api_gateway-1"
    echo "  3. Microservice Logs:"
    echo "     • ASR: docker logs ssf-backend-asr-1"
    echo "     • Translation: docker logs ssf-backend-translation-1"
    echo "     • TTS: docker logs ssf-backend-tts-1"
    echo "  4. Metriken prüfen: curl http://localhost:8000/metrics"
    echo "  5. Manuelle API-Tests: curl http://localhost:8000/api/admin/session/create"

    exit 1
fi
