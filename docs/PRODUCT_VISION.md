# Product Vision

## Smart Speech Flow

Smart Speech Flow macht mehrsprachige, betreute Echtzeitkommunikation sofort moeglich.

Das Produkt ist nicht als isolierter Uebersetzer gedacht, sondern als offene Gespraechsinfrastruktur fuer Situationen, in denen Menschen ohne gemeinsame Sprache trotzdem schnell, respektvoll und verlaesslich miteinander kommunizieren muessen.

## Vision Statement

Smart Speech Flow ist die offene und souveraen betreibbare Betriebsplattform fuer kommunale Sprach-KI und mehrsprachige Echtzeitgespraeche.

SSF ermoeglicht sprachuebergreifende Kommunikation in unterschiedlichen Nutzungskontexten und Interaktionsformen.

SSF kann direkt als eigenstaendige Anwendung genutzt und zugleich als integrierbare Capability in andere Produkte, Portale und Fachverfahren eingebettet werden.

## Wofuer das Produkt steht

- Sprachbarrieren sollen kein Grund mehr sein, ein wichtiges Gespraech nicht fuehren zu koennen.
- Die Nutzung muss radikal einfach sein: starten, verbinden, sprechen oder schreiben.
- Das Produkt muss in realen Gespraechssituationen funktionieren, nicht nur in technischen Demos.
- Smart Speech Flow ist zugleich anwendungsnahes Produkt und wiederverwendbarer Plattformbaustein.

## Zielbild

Smart Speech Flow soll der Standardbaustein fuer kommunale Sprach-KI werden. Sprachuebergreifende Gespraeche sind der erste Anwendungsfall; die Plattform soll weitere sprachbasierte Verwaltungsservices sicher und standardisiert betreibbar machen.

Im Zielbild ermoeglicht SSF:

- direkte Gespraeche zwischen Mitarbeitenden und Nutzerinnen oder Nutzern mit unterschiedlichen Sprachen
- einen nachvollziehbaren Kommunikationsfluss ueber Text, Audio und Session-Kontext
- unterschiedliche Gespraechsmodi je nach Situation, Geraet und Nutzungskontext
- einen Betrieb auf eigener Infrastruktur oder in anderen kontrollierten Betriebsmodellen
- die Einbettung in bestehende digitale Angebote statt einer erzwungenen Parallelanwendung
- die sichere Verwaltung von Mandanten, Rollen, Ressourcen und Nutzungsdaten in einer Control Plane
- austauschbare ASR-, Uebersetzungs- und TTS-Komponenten statt einer Abhaengigkeit von einem einzelnen Modell

## Produktformen

### 1. Standalone

Organisationen nutzen Smart Speech Flow direkt als fertige Anwendung mit eigener Oberflaeche, Session-Logik und Echtzeitkommunikation.

### 2. Embedded

Andere Produkte, Portale und Fachverfahren nutzen Smart Speech Flow als integrierte Sprach- und Gespraechsfunktion ueber APIs, WebSockets und spaeter moegliche SDK- oder White-Label-Modelle.

## Produktprinzipien

- Kommunikation vor Assistenz
- Gespraechsfluss vor Einzelrequest
- unterschiedliche Interaktionsmuster dort, wo sie das Gespraech wirklich verbessern
- Echtzeit und Verstaendlichkeit vor technischer Perfektion
- Einfachheit vor Funktionsballast
- Vertrauen, Stabilitaet und Transparenz im operativen Einsatz
- Offene Architektur fuer Integration, Erweiterung und selbstbestimmten Betrieb
- Mandantentrennung, Datenschutz und kontrollierter Zugriff als Voraussetzung fuer Vertrauen
- messbare Qualitaet, Latenz und Ressourcenverbrauch als Grundlage fuer wirtschaftlichen Betrieb

## Open-Source-Verstaendnis

Smart Speech Flow ist Open Source. Der Quellcode ist offen, nachvollziehbar und selbst betreibbar.

Wertschoepfung entsteht nicht ueber proprietaere Lizenzierung, sondern ueber die Faehigkeit, das Produkt wirksam in Einsatz zu bringen und verlaesslich zu betreiben.

Dazu gehoeren insbesondere:

- Setup und Inbetriebnahme
- Hosting und Betrieb
- Support und SLA
- Integration in bestehende Systeme
- gemeinschaftliche Betreiber- und Plattformmodelle

## Plattformperspektive

Smart Speech Flow ist so gedacht, dass eine Organisation eine Instanz selbst nutzen und zugleich weiteren Partnern oder Organisationseinheiten zugaenglich machen kann.

Damit eignet sich SSF nicht nur fuer Einzelnutzung, sondern auch als gemeinsam betriebene Infrastruktur in Netzwerken, Verbuenden oder lokalen Oekosystemen.

Die Plattform unterscheidet dabei die technische Betreiberrolle von den Rollen eines Mandanten: Ein `system_admin` betreibt eine SSF-Installation, ein `tenant_admin` verwaltet den eigenen Mandanten, operative `admin`-Nutzer fuehren Sessions durch und `customer` nimmt an einer zugewiesenen Session teil. Details beschreiben das [Rollen- und Berechtigungsmodell](architecture/roles-and-permissions.md) und die [Customer Journey](architecture/customer-journey.md).

SVA Studio kann diese Control Plane als einheitliche Betreiber- und Mandanten-Admin-Oberfläche bereitstellen. Studio verantwortet dann Mandanten, administrative Identitäten, Rollen, Konfigurationen und Lebenszyklusworkflows; SSF verantwortet Sessions und die Sprach-KI-Runtime. Die Systeme kommunizieren über versionierte APIs und Ereignisse, nicht über eine gemeinsame Datenbank.

## Nordstern

Jedes wichtige Gespraech soll auch dann sofort fuehrbar sein, wenn die Beteiligten keine gemeinsame Sprache sprechen.
