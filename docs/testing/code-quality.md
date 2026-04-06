# Code Quality Standards

Dieses Dokument beschreibt die Code-Qualitätsstandards für das Smart Speech Flow Backend Projekt.

## 🎯 Übersicht

Das Projekt verwendet automatisierte Tools zur Sicherstellung von Code-Qualität, Sicherheit und Konsistenz. Alle Änderungen müssen die definierten Quality Gates erfüllen.

## 🛠 Tools und Standards

### 1. Code-Formatierung

#### Black (Code Formatter)
- **Zweck**: Konsistente Python-Code-Formatierung
- **Konfiguration**: 100 Zeichen Zeilenlaenge
- **Ausführung**: `black services/`
- **Pre-commit**: Automatisch bei jedem Commit

#### isort (Import Sorting)
- **Zweck**: Konsistente Import-Sortierung
- **Profil**: Black-kompatibel
- **Ausführung**: `isort services/`
- **Gruppierung**: STDLIB → THIRDPARTY → FIRSTPARTY → LOCAL

### 2. Statische Code-Analyse

#### flake8 (Linting)
- **Zweck**: Code-Stil und potenzielle Fehler erkennen
- **Konfiguration**: `setup.cfg`
- **Max. Zeilenlaenge**: 100 Zeichen
- **Ausführung**: `flake8 services/`
- **Ignorierte Regeln**: E203, W503, E501 (Black-Kompatibilität)

#### Erweiterte Linting-Regeln:
- `flake8-bugbear`: Erweiterte Bug-Erkennung
- `flake8-docstrings`: Docstring-Validierung
- `pep8-naming`: Naming-Konventionen

### 3. Sicherheitsanalyse

#### Bandit (Security Linter)
- **Zweck**: Sicherheitslücken im Code erkennen
- **Ausführung**: `bandit -r services/`
- **Schwellenwerte**:
  - High/Critical: Blockierend
  - Medium: Geprüft, aber nicht blockierend
  - Low: Informativ

#### pip-audit (Dependency Scanner)
- **Zweck**: Bekannte Sicherheitslücken in Dependencies
- **Ausführung**: `pip-audit`
- **Verhalten**: Der Report wird in CI erzeugt; Blocking-Regeln koennen schrittweise verschaerft werden

### 4. Zentralisierte Qualitaetsanalyse

#### SonarCloud
- **Zweck**: Zentrale Analyse fuer Maintainability, Code Smells, Duplication und Quality Gates
- **Ausfuehrung**: In GitHub Actions ueber die Code-Quality-Pipeline
- **Scope**: Aktive Backend- und relevante Frontend-Quellpfade, keine Archive oder Laufzeitdaten
- **Qualitaetsgate**: Wird in CI ausgewertet, sobald die SonarCloud-Repository-Konfiguration vorhanden ist

### 5. Type-Checking (Graduell)

#### MyPy (Type Checker)
- **Zweck**: Statische Typenprüfung
- **Status**: Nicht-blockierend während Einführungsphase
- **Ziel**: >80% Type-Coverage für kritische Module
- **Ausführung**: `mypy services/api_gateway/`

## 📋 Quality Gates

### Mandatory (Blockierend)
1. **Code-Formatierung**: Muss Black-Standards erfüllen
2. **Import-Sortierung**: Muss isort-Standards erfüllen
3. **Linting**: Keine kritischen flake8-Fehler
4. **Sicherheit**: Keine High/Critical Bandit-Issues
5. **Sonar Quality Gate**: Muss im konfigurierten CI-Setup erfolgreich sein

### Advisory (Nicht-blockierend)
1. **Type-Coverage**: Graduelle Verbesserung angestrebt
2. **Medium Security Issues**: Sollten behoben werden
3. **Code-Komplexität**: Funktionen unter Komplexität 15

## 🚀 Workflow Integration

### Pre-commit Hooks
```bash
# Installation
pre-commit install

# Manuelle Ausführung
pre-commit run --all-files
```

### Lokale Quality-Checks
```bash
# Vollständiger Check
./scripts/quality-check.sh

# Einzelne Tools
black services/               # Auto-fix Formatierung
isort services/               # Auto-fix Imports
flake8 services/              # Linting-Report
bandit -r services/           # Security-Analyse
pip-audit                     # Dependency-Check
```

### CI/CD Pipeline
- **Trigger**: Push/PR auf main/develop
- **Jobs**: Code-Quality, Security, Type-Checking, Dependencies, SonarCloud
- **Reports**: Artifacts für alle Tool-Outputs
- **Quality Gate**: SonarCloud liefert zentrales Qualitaetsfeedback fuer PRs und Branches

### SonarCloud-Konfiguration

Fuer die GitHub-Integration werden folgende Repository-Einstellungen benoetigt:

- Secret: `SONAR_TOKEN`
- optional Repository Variable: `SONAR_ORGANIZATION`
- optional Repository Variable: `SONAR_PROJECT_KEY`

Falls die Variablen nicht gesetzt werden, verwendet der Workflow standardmaessig:

- Sonar-Organisation = GitHub Repository Owner
- Sonar Project Key = `<repository_owner>_<repository_name>`

Die Scanner-Konfiguration liegt in `sonar-project.properties`.

## 📊 Metriken und Monitoring

### Tracked Metrics
- **Linting-Fehler**: Anzahl flake8-Violations
- **Security-Issues**: Bandit-Findings nach Severity
- **Type-Coverage**: Prozent typisierter Code-Abschnitte
- **Dependency-Vulnerabilities**: Bekannte CVEs

### Quality Trends
- **Ziel**: Kontinuierliche Verbesserung
- **Review**: Monatliche Quality-Reports
- **Threshold-Anpassung**: Bei Bedarf nach Team-Review

## 🔧 Entwickler-Guidelines

### Neuer Code
1. Verwende Type-Annotations für neue Funktionen
2. Füge Docstrings für öffentliche APIs hinzu
3. Teste lokal mit `./scripts/quality-check.sh`
4. Committe nur bei erfolgreichen Quality-Checks

### Legacy Code
1. Verbessere schrittweise bei Änderungen
2. Fokus auf kritische/oft geänderte Bereiche
3. Type-Annotations bei Refactoring hinzufügen
4. Security-Issues haben höchste Priorität

### Code Reviews
1. Quality-Check-Status prüfen
2. Type-Coverage bei neuen Features bewerten
3. Security-Implications berücksichtigen
4. Performance-Impact bei großen Änderungen

## 📁 Konfigurationsdateien

```
├── .pre-commit-config.yaml    # Pre-commit Hook-Konfiguration
├── pyproject.toml              # Tool-Konfigurationen (Black, isort, mypy)
├── setup.cfg                   # flake8-Konfiguration
├── requirements-dev.txt        # Entwicklungs-Dependencies
├── sonar-project.properties    # SonarCloud-Analysekonfiguration
└── .github/workflows/
    └── code-quality.yml        # CI/CD Quality Pipeline
```

## 🆘 Troubleshooting

### Häufige Probleme

#### "Black would reformat" Error
```bash
# Auto-fix:
black services/
```

#### "Import order incorrect" Error
```bash
# Auto-fix:
isort services/
```

#### Flake8 "line too long" trotz Black
- Prüfe auf sehr lange Strings/Comments
- Nutze parentheses für Multi-line expressions
- Verwende Black's string-splitting Features

#### Pre-commit Hook Failures
```bash
# Hooks updaten:
pre-commit autoupdate

# Cache leeren:
pre-commit clean

# Neu installieren:
pre-commit install --overwrite
```

#### MyPy "Module not found" Errors
```bash
# Type-Stubs installieren:
pip install types-requests types-redis

# Oder ignore für Third-party:
# type: ignore
```

## 📈 Kontinuierliche Verbesserung

### Monatliche Reviews
- Quality-Metriken analysieren
- Tool-Konfiguration anpassen
- Neue Best-Practices einführen
- Team-Feedback einarbeiten

### Tool-Updates
- Dependency-Updates monatlich
- Breaking Changes in Team abstimmen
- Backward-Compatibility sicherstellen

### Performance
- Quality-Check-Laufzeiten optimieren
- Parallel-Execution wo möglich
- Tool-Caching nutzen
