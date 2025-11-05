from fastapi.responses import Response
from prometheus_client import generate_latest

def metrics():
    """Kombinierte Prometheus-Metriken für Gateway und WebSocket-Monitoring"""
    try:
        # Importiere zur Laufzeit um zirkuläre Imports zu vermeiden
        from services.api_gateway.app import app
        registry = app.state.prometheus_registry

        # Hole alle Metriken aus der Haupt-Registry
        main_metrics = generate_latest(registry)

        # Versuche WebSocket-Metriken hinzuzufügen wenn sie in separater Registry sind
        try:
            from services.api_gateway.websocket_monitor import get_websocket_monitor
            monitor = get_websocket_monitor()

            # Wenn WebSocket-Monitor separate Registry hat, füge sie hinzu
            if (hasattr(monitor, '_registry') and
                monitor._registry is not None and
                monitor._registry != registry):

                ws_metrics = generate_latest(monitor._registry)
                # Kombiniere beide Metriken-Ausgaben
                combined = main_metrics.decode('utf-8').rstrip() + '\n' + ws_metrics.decode('utf-8')
                return Response(combined, media_type="text/plain")
        except Exception:
            pass  # Fallback zu nur Gateway-Metriken

        return Response(main_metrics, media_type="text/plain")

    except Exception:
        # Absoluter Fallback
        return Response("# Fehler beim Generieren der Metriken\n", media_type="text/plain")