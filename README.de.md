
<div align="center">
    <img src="assets/craftbot_readme_banner.png" alt="CraftBot Banner" width="1280"/>
</div>
<br>

<div align="center">
  <img src="https://img.shields.io/badge/OS-Windows-blue?logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/OS-macOS-lightgrey?logo=apple&logoColor=white" alt="macOS">
  <img src="https://img.shields.io/badge/OS-Linux-yellow?logo=linux&logoColor=black" alt="Linux">

  <a href="https://github.com/CraftOS-dev/CraftBot">
    <img src="https://img.shields.io/github/stars/CraftOS-dev/CraftBot?style=social" alt="GitHub Repo stars">
  </a>

  <img src="https://img.shields.io/github/license/CraftOS-dev/CraftBot" alt="License">

  <a href="https://discord.gg/ZN9YHc37HG">
    <img src="https://img.shields.io/badge/Discord-Der%20Community%20beitreten-5865F2?logo=discord&logoColor=white" alt="Discord">
  </a>
<br/>
<br/>

[![SPONSORED BY E2B FOR STARTUPS](https://img.shields.io/badge/SPONSORED%20BY-E2B%20FOR%20STARTUPS-ff8800?style=for-the-badge)](https://e2b.dev/startups)

<a href="https://www.producthunt.com/products/craftbot?embed=true&amp;utm_source=badge-top-post-badge&amp;utm_medium=badge&amp;utm_campaign=badge-craftbot" target="_blank" rel="noopener noreferrer"><img alt="CraftBot - Self-hosted proactive AI assistant that lives locally | Product Hunt" width="250" height="54" src="https://api.producthunt.com/widgets/embed-image/v1/top-post-badge.svg?post_id=1110300&amp;theme=dark&amp;period=daily&amp;t=1776679679509"></a>
</div>

<p align="center">
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a>
</p>

## 🚀 Überblick
<h3 align="center">
CraftBot ist dein persönlicher KI-Assistent, der auf deinem Rechner lebt und rund um die Uhr für dich arbeitet.
</h3>

Er interpretiert Aufgaben autonom, plant Aktionen und führt sie aus, um deine Ziele zu erreichen.
Er lernt deine Vorlieben und Ziele kennen und hilft dir proaktiv dabei, Aufgaben zu planen und anzustoßen, damit du deine Lebensziele erreichst.
MCPs, Skills und Integrationen mit externen Apps werden unterstützt.

CraftBot wartet auf deine Befehle. Richte jetzt deinen eigenen CraftBot ein.

<div align="center">
    <img src="assets/craftbot_overview.png" alt="CraftBot Overview" width="1280"/>
</div>

---

## ✨ Funktionen

- **Bring Your Own Key (BYOK)** — Flexibles LLM-Provider-System mit Unterstützung für OpenAI, Google Gemini, Anthropic Claude, BytePlus und lokale Ollama-Modelle. Wechsle Anbieter mühelos.
- **Speichersystem** — Destilliert und konsolidiert um Mitternacht die Ereignisse des Tages.
- **Proaktiver Agent** — Lernt deine Vorlieben, Gewohnheiten und Lebensziele kennen. Anschließend plant er und startet (selbstverständlich nach Freigabe) Aufgaben, die dir beim Fortschritt helfen.
- **Living UI** — Baue, importiere oder entwickle eigene Apps weiter, die in CraftBot leben. Der Agent behält den UI-Zustand stets im Blick und kann deren Daten direkt lesen, schreiben und verarbeiten.
- **Externe Tool-Integration** — Verbinde dich mit Google Workspace, Slack, Notion, Zoom, LinkedIn, Discord und Telegram (weitere folgen!) mit eingebetteten Zugangsdaten und OAuth-Unterstützung.
- **MCP** — Integration des Model Context Protocol, um die Fähigkeiten des Agents um externe Tools und Dienste zu erweitern.
- **Skills** — Erweiterbares Skill-Framework mit eingebauten Skills für Aufgabenplanung, Recherche, Code-Reviews, Git-Operationen und mehr.
- **Plattformübergreifend** — Vollständige Unterstützung für Windows, macOS und Linux mit plattformspezifischen Code-Varianten und Docker-Containerisierung.

> [!IMPORTANT]
> **Der GUI-Modus ist veraltet.** CraftBot unterstützt den GUI-Modus (Desktop-Automatisierung) nicht mehr. Bitte verwende stattdessen den Browser- oder CLI-Modus.

<div align="center">
    <img src="assets/craftbot_readme_features.png" alt="CraftBot Banner" width="1280"/>
	<img src="assets/craftbot_features_custom.png" alt="CraftBot Banner" width="1280"/>
</div>

---


## 🧰 Erste Schritte

### Voraussetzungen
- Python **3.10+**
- `git` (erforderlich zum Klonen des Repositorys)
- Ein API-Schlüssel für den gewählten LLM-Anbieter (OpenAI, Gemini oder Anthropic)
- `Node.js` **18+** (optional – nur für die Browser-Oberfläche erforderlich)
- `conda` (optional – wenn nicht vorhanden, bietet das Installationsprogramm an, Miniconda automatisch zu installieren)

### Welches Setup soll ich verwenden?

> **Nicht sicher? Nimm Option 1.** Sie erledigt alles für dich.

| | Option 1 — Service | Option 2 — Conda | Option 3 — Manuell |
|---|---|---|---|
| **Für wen** | Die meisten Nutzer, Einsteiger, Tests | Conda-Nutzer, die isolierte Umgebungen wollen | Fortgeschrittene Nutzer, benutzerdefiniertes Python, volle Kontrolle |
| **Python/Umgebung automatisch verwalten?** | ✅ Automatisch | ✅ Automatisch | ❌ Du verwaltest es |
| **Läuft im Hintergrund?** | ✅ Ja, als Dienst | ❌ Nein | ❌ Nein |
| **Wie starten** | `python craftbot.py install` | `python install.py --conda` | `python install.py` |

---

### ⭐ Option 1 — Service-Installation (Empfohlen)

**Wähle dies, wenn:** du möchtest, dass CraftBot einfach funktioniert — Hintergrunddienst, automatischer Start beim Login, Desktop-Verknüpfung, keine manuellen Schritte.

`craftbot.py` übernimmt alles: Python-Umgebung, Abhängigkeiten, Hintergrundprozess-Verwaltung und Autostart-Registrierung.

```bash
# 1. Repository klonen
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Installieren, Autostart registrieren und CraftBot starten
python craftbot.py install
```

Das war's. Das Terminal schließt sich von selbst, CraftBot läuft im Hintergrund und der Browser öffnet sich automatisch. Eine **Desktop-Verknüpfung** wird erstellt, damit du den Browser jederzeit wieder öffnen kannst.

**Dienstverwaltung nach der Installation:**

```bash
python craftbot.py start      # CraftBot im Hintergrund starten
python craftbot.py stop       # CraftBot stoppen
python craftbot.py restart    # CraftBot neu starten
python craftbot.py status     # Prüfen ob er läuft und ob Autostart aktiviert ist
python craftbot.py logs       # Aktuelle Logs ansehen
python craftbot.py uninstall  # Stoppen, Autostart entfernen, Pakete deinstallieren
```

> [!TIP]
> Nach `install` oder `start` wird automatisch eine **CraftBot-Desktop-Verknüpfung** erstellt. Hast du den Browser versehentlich geschlossen, doppelklicke die Verknüpfung, um ihn wieder zu öffnen.

---

### Option 2 — Conda-Installation

**Wähle dies, wenn:** du bereits conda verwendest und CraftBot in einer isolierten conda-Umgebung betreiben möchtest.

`install.py --conda` richtet eine dedizierte `craftbot`-conda-Umgebung ein. Falls Miniconda auf deinem System nicht gefunden wird, wird es automatisch installiert.

```bash
# 1. Repository klonen
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. In einer conda-Umgebung installieren
python install.py --conda

# 3. CraftBot ausführen
conda run -n craftbot python run.py

# Falls conda nicht im PATH ist (nur Windows):
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

> [!NOTE]
> Jedes Mal wenn du CraftBot starten möchtest, verwende `conda run -n craftbot python run.py`. Es gibt keinen Hintergrunddienst — du startest und stoppst ihn selbst.

---

### Option 3 — Manuelle Installation (pip)

**Wähle dies, wenn:** du volle Kontrolle über deine Python-Umgebung möchtest und CraftBot lieber selbst verwaltest, ohne automatischen Dienst oder Hintergrundprozess.

`install.py` (ohne Optionen) führt eine Standard-pip-Installation in der aktuell aktiven Python-Umgebung durch. Du startest und stoppst CraftBot manuell mit `run.py`.

```bash
# 1. Repository klonen
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Abhängigkeiten in der aktiven Python-Umgebung installieren
python install.py

# 3. CraftBot starten
python run.py
```

Beim ersten Start wirst du durch die Einrichtung deiner API-Schlüssel und Einstellungen geführt.

> [!NOTE]
> Wenn Node.js nicht installiert ist, führt dich das Installationsprogramm Schritt für Schritt durch die Installation. Du kannst den Browser-Modus auch vollständig überspringen und den CLI-Modus verwenden — kein Node.js nötig: `python run.py --cli`

### Was kannst du direkt danach tun?
- Natürlich mit dem Agent sprechen
- Ihn komplexe, mehrstufige Aufgaben ausführen lassen
- `/help` eingeben, um verfügbare Befehle zu sehen
- Dich mit Google, Slack, Notion und mehr verbinden

### 🖥️ Schnittstellenmodi

<div align="center">
    <img src="assets/WCA_README_banner.png" alt="CraftOS Banner" width="1280"/>
</div>

CraftBot unterstützt mehrere UI-Modi. Wähle nach deinen Vorlieben:

| Modus | Befehl | Voraussetzungen | Empfohlen für |
|------|---------|--------------|----------|
| **Browser** | `python run.py` | Node.js 18+ | Moderne Web-Oberfläche, am einfachsten |
| **CLI** | `python run.py --cli` | Keine | Kommandozeile, leichtgewichtig |

Der **Browser-Modus** ist Standard und wird empfohlen. Ohne Node.js gibt dir das Installationsprogramm eine Anleitung – alternativ kannst du den **CLI-Modus** nutzen.

---

## 🧬 Living UI

**Living UI ist ein System/App/Dashboard, das mit deinen Anforderungen wächst.**

Brauchst du ein Kanban-Board mit eingebautem KI-Copiloten? Ein individuelles CRM,
das exakt zu deinem Workflow passt? Ein Unternehmens-Dashboard, das CraftBot
lesen und für dich steuern kann? Bring es als Living UI an den Start — es läuft
neben CraftBot und wächst mit deinen Anforderungen.

<div align="center">
    <img src="assets/living-ui-example.png" alt="Living UI example" width="1280"/>
</div>

### Drei Wege, eine Living UI zu erstellen

1. **Von Grund auf bauen.** Beschreibe in natürlicher Sprache, was du möchtest.
   CraftBot legt Datenmodell, Backend-API und React-UI an und iteriert mit dir
   in einem strukturierten Designprozess.

<div align="center">
    <img src="assets/living-ui-custom-build.png" alt="Building a Living UI from scratch" width="448"/>
</div>

2. **Aus dem Marketplace installieren.** Stöbere durch Community-erstellte Living UIs auf [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace).

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Living UI marketplace" width="448"/>
</div>

3. **Bestehendes Projekt importieren.** Verweise CraftBot auf Quellcode oder ein
   GitHub-Repository in Go, Node.js, Python, Rust oder statischem Web. Die Runtime
   wird erkannt, Health-Checks werden eingerichtet, und das Projekt wird als
   Living UI eingebunden.

<div align="center">
    <img src="assets/living-ui-import.png" alt="Importing an existing project as a Living UI" width="448"/>
</div>

### Entwickelt sich weiter — mit CraftBot im Loop

Eine Living UI ist nie „fertig". Bitte den Agent, Funktionen hinzuzufügen, eine
Ansicht neu zu gestalten oder sie an neue Daten anzubinden, sobald deine
Anforderungen wachsen.

CraftBot ist in jeder Living UI eingebettet und **kennt deren Zustand**:
Er kann das aktuelle DOM und Formularwerte lesen, App-Daten über die
REST-API abfragen und in deinem Namen Aktionen auslösen.

---

## 🧩 Architekturüberblick

| Komponente | Beschreibung |
|-----------|-------------|
| **Agent Base** | Zentrale Orchestrierungsschicht, die den Task-Lifecycle verwaltet, zwischen Komponenten koordiniert und die Haupt-Agenten-Schleife steuert. |
| **LLM Interface** | Einheitliche Schnittstelle mit Unterstützung mehrerer LLM-Anbieter (OpenAI, Gemini, Anthropic, BytePlus, Ollama). |
| **Context Engine** | Erzeugt optimierte Prompts mit KV-Cache-Unterstützung. |
| **Action Manager** | Ruft Aktionen aus der Bibliothek ab und führt sie aus. Eigene Aktionen lassen sich leicht erweitern. |
| **Action Router** | Wählt intelligent die am besten passende Aktion auf Basis der Task-Anforderungen und löst Eingabeparameter bei Bedarf über das LLM auf. |
| **Event Stream** | Echtzeit-Event-Publishing-System für Fortschrittsverfolgung, UI-Updates und Ausführungs-Monitoring. |
| **Memory Manager** | RAG-basiertes semantisches Gedächtnis mit ChromaDB. Übernimmt Memory-Chunking, Embedding, Retrieval und inkrementelle Updates. |
| **State Manager** | Globales State-Management zur Verfolgung von Ausführungskontext, Gesprächshistorie und Laufzeitkonfiguration. |
| **Task Manager** | Verwaltet Task-Definitionen, ermöglicht einfache und komplexe Task-Modi, erstellt To-dos und verfolgt mehrstufige Workflows. |
| **Skill Manager** | Lädt einsteckbare Skills und injiziert sie in den Agent-Kontext. |
| **MCP Adapter** | Model Context Protocol Integration, die MCP-Tools in native Aktionen umwandelt. |

---

## 🔜 Roadmap

- [X] **Memory-Modul** — Fertig.
- [ ] **Externe Tool-Integration** — Wir fügen noch weitere hinzu!
- [X] **MCP-Schicht** — Fertig.
- [X] **Skill-Schicht** — Fertig.
- [ ] **Proaktives Verhalten** — In Arbeit

---

## 📋 Befehlsreferenz

### install.py

| Flag | Beschreibung |
|------|-------------|
| `--conda` | conda-Umgebung nutzen (optional) |

### run.py

| Flag | Beschreibung |
|------|-------------|
| (keines) | Im **Browser**-Modus ausführen (empfohlen, Node.js erforderlich) |
| `--cli` | Im **CLI**-Modus ausführen (leichtgewichtig) |

### craftbot.py

| Befehl | Beschreibung |
|---------|-------------|
| `install` | Abhängigkeiten installieren, Autostart registrieren und CraftBot starten |
| `start` | CraftBot im Hintergrund starten |
| `stop` | CraftBot stoppen |
| `restart` | Stoppen und neu starten |
| `status` | Laufstatus und Autostart-Status anzeigen |
| `logs [-n N]` | Die letzten N Log-Zeilen anzeigen (Standard: 50) |
| `uninstall` | Autostart-Registrierung entfernen |

**Installationsbeispiele:**
```bash
# Einfache pip-Installation (ohne conda)
python install.py

# Mit conda-Umgebung (empfohlen für conda-Nutzer)
python install.py --conda
```

**CraftBot ausführen:**

```powershell
# Browser-Modus (Standard, Node.js erforderlich)
python run.py

# CLI-Modus (leichtgewichtig)
python run.py --cli

# Mit conda-Umgebung
conda run -n craftbot python run.py

# Oder mit vollständigem Pfad, falls conda nicht im PATH ist
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

**Linux/macOS (Bash):**
```bash
# Browser-Modus (Standard, Node.js erforderlich)
python run.py

# CLI-Modus (leichtgewichtig)
python run.py --cli

# Mit conda-Umgebung
conda run -n craftbot python run.py
```

### 🔧 Hintergrunddienst (empfohlen)

Betreibe CraftBot als Hintergrunddienst, sodass er auch nach dem Schließen des Terminals weiterläuft. Eine Desktop-Verknüpfung wird automatisch erstellt, damit du den Browser jederzeit wieder öffnen kannst.

```bash
# Abhängigkeiten installieren, Autostart bei Anmeldung registrieren und CraftBot starten
python craftbot.py install
```

Das war's. Das Terminal schließt sich von selbst, CraftBot läuft im Hintergrund und der Browser öffnet sich automatisch.

```bash
# Weitere Dienstbefehle:
python craftbot.py start    # CraftBot im Hintergrund starten
python craftbot.py status   # Prüfen, ob er läuft
python craftbot.py stop     # CraftBot stoppen
python craftbot.py restart  # CraftBot neu starten
python craftbot.py logs     # Aktuelle Log-Ausgabe ansehen
```

| Befehl | Beschreibung |
|---------|-------------|
| `python craftbot.py install` | Abhängigkeiten installieren, Autostart bei Anmeldung registrieren, CraftBot starten, Browser öffnen und Terminal automatisch schließen |
| `python craftbot.py start` | CraftBot im Hintergrund starten – startet automatisch neu, wenn er bereits läuft (Terminal schließt sich selbst) |
| `python craftbot.py stop` | CraftBot stoppen |
| `python craftbot.py restart` | CraftBot stoppen und starten |
| `python craftbot.py status` | Prüfen, ob CraftBot läuft und ob Autostart aktiviert ist |
| `python craftbot.py logs` | Aktuelle Log-Ausgabe anzeigen (`-n 100` für mehr Zeilen) |
| `python craftbot.py uninstall` | CraftBot stoppen, Autostart entfernen, pip-Pakete deinstallieren und pip-Cache leeren |

> [!TIP]
> Nach `craftbot.py start` oder `craftbot.py install` wird automatisch eine **CraftBot-Desktop-Verknüpfung** erstellt. Hast du den Browser versehentlich geschlossen, doppelklicke die Verknüpfung, um ihn wieder zu öffnen.

> [!NOTE]
> **Installation:** Das Installationsprogramm gibt nun klare Hinweise, falls Abhängigkeiten fehlen. Wird Node.js nicht gefunden, wirst du zur Installation aufgefordert oder kannst in den CLI-Modus wechseln. Die Installation erkennt die GPU-Verfügbarkeit automatisch und fällt bei Bedarf auf den CPU-Modus zurück.

> [!TIP]
> **Ersteinrichtung:** CraftBot führt dich durch einen Onboarding-Ablauf, um API-Schlüssel, den Agentennamen, MCPs und Skills zu konfigurieren.

> [!NOTE]
> **Playwright Chromium:** Optional für die WhatsApp-Web-Integration. Schlägt die Installation fehl, funktioniert der Agent weiterhin für andere Aufgaben. Manuell nachinstallieren mit: `playwright install chromium`

---

## 🔧 Fehlerbehebung und häufige Probleme

### Fehlendes Node.js (für den Browser-Modus)
Erscheint **"npm not found in PATH"** beim Ausführen von `python run.py`:
1. Von [nodejs.org](https://nodejs.org/) herunterladen (LTS-Version wählen)
2. Installieren und das Terminal neu starten
3. `python run.py` erneut ausführen

**Alternative:** CLI-Modus verwenden (kein Node.js nötig):
```bash
python run.py --cli
```

### Installation schlägt bei Abhängigkeiten fehl
Das Installationsprogramm liefert jetzt detaillierte Fehlermeldungen mit Lösungen. Wenn die Installation fehlschlägt:
- **Python-Version prüfen:** Stelle sicher, dass du Python 3.10+ hast (`python --version`)
- **Internet prüfen:** Abhängigkeiten werden während der Installation heruntergeladen
- **pip-Cache leeren:** `pip install --upgrade pip` ausführen und erneut versuchen

### Probleme bei der Playwright-Installation
Die Playwright-Chromium-Installation ist optional. Bei einem Fehlschlag:
- Der Agent **funktioniert weiterhin** für andere Aufgaben
- Du kannst ihn überspringen oder später installieren: `playwright install chromium`
- Nur für die WhatsApp-Web-Integration erforderlich

Ausführliche Hinweise zur Fehlerbehebung findest du in [INSTALLATION_FIX.md](INSTALLATION_FIX.md).

---

## 🔌 Externe Dienste integrieren

Der Agent kann sich über OAuth mit verschiedenen Diensten verbinden. Release-Builds enthalten eingebettete Zugangsdaten, du kannst aber auch deine eigenen verwenden.

### Schnellstart

Für Release-Builds mit eingebetteten Zugangsdaten:
```
/google login    # Google Workspace verbinden
/zoom login      # Zoom verbinden
/slack invite    # Slack verbinden
/notion invite   # Notion verbinden
/linkedin login  # LinkedIn verbinden
```

### Dienst-Details

| Dienst | Auth-Typ | Befehl | Secret nötig? |
|---------|-----------|---------|------------------|
| Google | PKCE | `/google login` | Nein (PKCE) |
| Zoom | PKCE | `/zoom login` | Nein (PKCE) |
| Slack | OAuth 2.0 | `/slack invite` | Ja |
| Notion | OAuth 2.0 | `/notion invite` | Ja |
| LinkedIn | OAuth 2.0 | `/linkedin login` | Ja |

### Eigene Zugangsdaten verwenden

Möchtest du deine eigenen OAuth-Zugangsdaten verwenden, trage sie in deine `.env`-Datei ein:

#### Google (PKCE – nur Client ID nötig)
```bash
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
```
1. Gehe zur [Google Cloud Console](https://console.cloud.google.com/)
2. Aktiviere die APIs für Gmail, Calendar, Drive und People
3. Erstelle OAuth-Zugangsdaten vom Typ **Desktop app**
4. Kopiere die Client ID (für PKCE ist kein Secret nötig)

#### Zoom (PKCE – nur Client ID nötig)
```bash
ZOOM_CLIENT_ID=your-zoom-client-id
```
1. Gehe zum [Zoom Marketplace](https://marketplace.zoom.us/)
2. Erstelle eine OAuth-App
3. Kopiere die Client ID

#### Slack (beides erforderlich)
```bash
SLACK_SHARED_CLIENT_ID=your-slack-client-id
SLACK_SHARED_CLIENT_SECRET=your-slack-client-secret
```
1. Gehe zur [Slack API](https://api.slack.com/apps)
2. Erstelle eine neue App
3. Füge OAuth-Scopes hinzu: `chat:write`, `channels:read`, `users:read` usw.
4. Kopiere Client ID und Client Secret

#### Notion (beides erforderlich)
```bash
NOTION_SHARED_CLIENT_ID=your-notion-client-id
NOTION_SHARED_CLIENT_SECRET=your-notion-client-secret
```
1. Gehe zu [Notion Developers](https://developers.notion.com/)
2. Erstelle eine neue Integration (Public integration)
3. Kopiere OAuth Client ID und Secret

#### LinkedIn (beides erforderlich)
```bash
LINKEDIN_CLIENT_ID=your-linkedin-client-id
LINKEDIN_CLIENT_SECRET=your-linkedin-client-secret
```
1. Gehe zu [LinkedIn Developers](https://developer.linkedin.com/)
2. Erstelle eine App
3. Füge OAuth-2.0-Scopes hinzu
4. Kopiere Client ID und Client Secret

---
## 🐳 Mit Container ausführen

Das Repository-Root enthält eine Docker-Konfiguration mit Python 3.10, wichtigen Systempaketen (inklusive Tesseract für OCR) und allen in `environment.yml`/`requirements.txt` definierten Python-Abhängigkeiten, damit der Agent konsistent in isolierten Umgebungen läuft.

Nachfolgend die Einrichtungsanleitung, um unseren Agent mit Container auszuführen.

### Image bauen

Im Repository-Root:

```bash
docker build -t craftbot .
```

### Container ausführen

Das Image ist so konfiguriert, dass der Agent standardmäßig mit `python -m app.main` gestartet wird. Für eine interaktive Ausführung:

```bash
docker run --rm -it craftbot
```

Wenn du Umgebungsvariablen bereitstellen musst, übergib eine env-Datei (z. B. basierend auf `.env.example`):

```bash
docker run --rm -it --env-file .env craftbot
```

Mounte alle Verzeichnisse, die außerhalb des Containers persistent sein sollen (etwa Daten- oder Cache-Ordner), mit `-v`, und passe Ports oder weitere Flags nach Bedarf an dein Deployment an. Das Image enthält Systemabhängigkeiten für OCR (`tesseract`) sowie gängige HTTP-Clients, damit der Agent im Container mit Dateien und Netzwerk-APIs arbeiten kann.

Standardmäßig nutzt das Image Python 3.10 und bündelt die Python-Abhängigkeiten aus `environment.yml`/`requirements.txt`, sodass `python -m app.main` sofort funktioniert.

---

## 🤝 Mitwirken

PRs sind willkommen! Siehe [CONTRIBUTING.md](CONTRIBUTING.md) für den Workflow (Fork → Branch von `dev` → PR). Alle Pull Requests durchlaufen automatisch Lint- und Smoke-Test-CI. Für Fragen oder schnelleren Austausch komm auf unseren [Discord](https://discord.gg/ZN9YHc37HG) oder schreib an thamyikfoong(at)craftos.net.

## 🧾 Lizenz

Dieses Projekt steht unter der [MIT-Lizenz](LICENSE). Du darfst das Projekt frei nutzen, hosten und monetarisieren (bei Weiterverbreitung und Monetarisierung muss dieses Projekt genannt werden).

---

## ⭐ Danksagung

Entwickelt und gepflegt von [CraftOS](https://craftos.net/) sowie den Contributors [@zfoong](https://github.com/zfoong) und [@ahmad-ajmal](https://github.com/ahmad-ajmal).
Wenn dir **CraftBot** nützlich ist, gib dem Repository bitte einen ⭐ und teile es mit anderen!

---

## Star History

<a href="https://www.star-history.com/?repos=CraftOS-dev%2FCraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
