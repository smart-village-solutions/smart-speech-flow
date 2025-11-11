Smart Speech Flow: Lokales KI-Backend für Übersetzungen im Stadtteiltreff

Die meisten Anwendungen für Sprachverarbeitung und Übersetzung basieren auf Cloud-Diensten großer Anbieter wie Google oder DeepL. Mit Smart Speech Flow hat die Smart Village Solutions SVS GmbH im Auftrag der Stadt Kassel nun jedoch ein System entwickelt, das komplett lokal arbeitet. Ziel ist es, Sprachbarrieren im Stadtteiltreff zu überwinden – ohne dass Daten das lokale Netzwerk verlassen.

Lokale Verarbeitung statt Cloud

Das Projekt setzt auf eine Edge-KI-Architektur: Alle Komponenten laufen auf einem Server in einem deutschen Rechenzentrum, wodurch keine Audiodaten an externe Dienste übertragen werden. Neben Datenschutz und Souveränität verspricht das Setup auch geringere Latenzen. Nach Angaben der Entwickler wurde der funktionsfähige Prototyp innerhalb weniger Wochen umgesetzt.

Architektur in Microservices

Das Backend ist als Microservice-Architektur umgesetzt, bestehend aus sechs Modulen:

ASR (Speech-to-Text): Transkription gesprochener Sprache mit dem Open-Source-Modell Whisper von OpenAI.

Translation Service: Übersetzung mit M2M100 von Meta, optimiert für GPU-Beschleunigung.

LLM Translation Refinement (optional): Nachbearbeitung von Übersetzungen mit Ollama und GPT-OSS-20B für höhere Qualität – bewusst auf Kosten der Geschwindigkeit.

TTS (Text-to-Speech): Sprachsynthese mit Coqui-TTS; bei Bedarf übernimmt HuggingFace MMS-TTS als Fallback.

API-Gateway: Zentrale Steuerung der Verarbeitungskette (ASR → Translation → [Refinement] → TTS), WebSocket-Management für bidirektionale Echtzeit-Kommunikation und Session-Verwaltung.

Session Store (Redis): Persistente Ablage von Sessions, Nachrichten und Timeout-Metadaten mit Append-Only-File (AOF) für Datensicherheit.

Die Architektur soll eine einfache Erweiterbarkeit und Austauschbarkeit der Komponenten ermöglichen.

Hardwarebasis: Starke Leistung zu moderatem Preis

Zum Einsatz kommt ein Server mit Intel Core i5-13500 (13 Kerne, Hyper-Threading), 64 GB DDR4-RAM und einer Nvidia RTX 4000 SFF Ada GPU. Die Daten werden auf zwei 1,92-TB-NVMe-SSDs im Software-RAID 1 gespeichert. Die Anbindung erfolgt über einen garantierten 1-Gbit/s-Port mit unbegrenztem Traffic.

Nutzungsszenario

Die Anwendung ist als React-basierte Web-App konzipiert, optimiert für Tablet-Nutzung. Das System ermöglicht bidirektionale Echtzeit-Kommunikation zwischen zwei Parteien – typischerweise einem Mitarbeiter (Admin) und einem Besucher (Customer) im Stadtteiltreff:

Admin-Seite: Der Mitarbeiter erstellt eine Session und erhält einen QR-Code bzw. einen 8-stelligen PIN-Code.

Customer-Seite: Der Besucher scannt den QR-Code oder gibt den PIN ein und wählt seine Muttersprache.

Bidirektionale Übersetzung: Beide Parteien sprechen ihre Nachricht in das Mikrofon, die Nachricht wird automatisch transkribiert, übersetzt und als synthetisierte Audio-Ausgabe an das Gegenüber übermittelt – in Echtzeit über WebSocket-Verbindungen.

Optional: Übersetzungsveredelung durch LLM – wenn aktiviert, werden maschinelle Übersetzungen durch ein großes Sprachmodell (GPT-OSS-20B) nachbearbeitet, um natürlichere und kontextbewusstere Formulierungen zu erzielen. Dies erhöht die Qualität deutlich, verlängert aber die Antwortzeit um einige Sekunden.

Monitoring und Observability: Alle Pipeline-Schritte werden mit Prometheus gemessen und in Grafana visualisiert. Ein Loki-Stack sammelt strukturierte Logs für Debugging und Analyse.

Grenzen und Herausforderungen

Im Testbetrieb zeigten sich typische Einschränkungen aktueller Open-Source-Sprachmodelle:

Die Stimmenqualität ist in Sprachen wie Deutsch oder Englisch vergleichsweise hoch, in weniger verbreiteten Sprachen klingt sie dagegen teils unnatürlich.

Übersetzungen sind funktional, erreichen aber nicht das Niveau menschlicher Dolmetscher. Die optionale LLM-Veredelung verbessert die Qualität merklich, erhöht aber die Latenz: Während die Standard-Pipeline in 2-4 Sekunden arbeitet, benötigt die verfeinerte Variante 8-12 Sekunden je nach Textlänge.

Der Praxiseinsatz im Stadtteiltreff soll zeigen, wie robust das System bei Hintergrundgeräuschen und Dialekten arbeitet.

Qualität vs. Geschwindigkeit: Die Entwickler haben bewusst eine Wahlmöglichkeit eingebaut – schnelle Basisübersetzung für spontane Kommunikation oder verfeinerte Übersetzung für wichtige Gespräche, bei denen Nuancen zählen.

Perspektive: Edge-KI im Praxiseinsatz

Mit Smart Speech Flow demonstriert Kassel eine kostengünstige und datenschutzfreundliche Alternative zu Cloud-basierten Sprachdiensten. Das Projekt könnte als Blaupause für weitere lokale Anwendungen dienen, bei denen Datenschutz, schnelle Reaktionszeiten und offene Software eine Rolle spielen.

Besonders hervorzuheben ist die flexible Architektur: Durch das modulare Design können einzelne Komponenten ausgetauscht, erweitert oder deaktiviert werden – etwa die LLM-Veredelung, die nur bei Bedarf zugeschaltet wird. Die Echtzeit-Kommunikation über WebSockets ermöglicht natürliche Gespräche trotz Sprachbarriere, während das Monitoring-System (Prometheus, Grafana, Loki) kontinuierlich Qualität und Performance überwacht.

Der vollständige Quellcode ist unter MIT-Lizenz verfügbar und lädt zur Weiterentwicklung ein – sei es für andere Kommunale Einrichtungen, Bildungsträger oder soziale Projekte, die Sprachbarrieren überwinden wollen, ohne auf Cloud-Dienste angewiesen zu sein.
