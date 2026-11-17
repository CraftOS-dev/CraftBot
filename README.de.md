<div align="center">
    <img src="assets/README_cover.png" alt="CraftBot" width="1280"/>
</div>

Die meisten Agent-Frameworks hören bei Chat und Tool-Aufrufen auf. CraftBot geht weiter: Er baut, entwickelt und betreibt seine eigenen SaaS-Tools und nutzt diese Tool-Schicht dann, um mit dir zu kommunizieren und Aufgaben für dich zu automatisieren.

Darüber hinaus bringt CraftBot alle Kernfunktionen eines universellen Agent-Frameworks mit. Er erledigt Aufgaben wie ein:e Mitarbeitende:r aus der Ferne, merkt sich deine Vorlieben und Ziele und unterstützt dich proaktiv dabei, das zu planen und umzusetzen, was dir wichtig ist.

<p align="center">
  <img src="https://img.shields.io/badge/OS-Windows-blue?logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/OS-macOS-lightgrey?logo=apple&logoColor=white" alt="macOS">
  <img src="https://img.shields.io/badge/OS-Linux-yellow?logo=linux&logoColor=black" alt="Linux">


  <a href="https://github.com/CraftOS-dev/CraftBot">
    <img src="https://img.shields.io/github/stars/CraftOS-dev/CraftBot?style=social" alt="GitHub Repo stars">
  </a>

  <img src="https://img.shields.io/github/license/CraftOS-dev/CraftBot" alt="License">

  <a href="https://discord.gg/ZN9YHc37HG">
    <img src="https://img.shields.io/badge/Discord-Join%20the%20community-5865F2?logo=discord&logoColor=white" alt="Discord">
  </a>

  <a href="https://deepwiki.com/CraftOS-dev/CraftBot">
    <img src="https://deepwiki.com/badge.svg" alt="Ask DeepWiki">
  </a>
</p>

<div align="center">
	
[![SPONSORED BY E2B FOR STARTUPS](https://img.shields.io/badge/SPONSORED%20BY-E2B%20FOR%20STARTUPS-ff8800?style=for-the-badge)](https://e2b.dev/startups)
</div>

<p align="center">
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.es.md">Español</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a>
</p>

## ✨ Wichtigste Funktionen

Über die Fähigkeit hinaus, eigene SaaS-Tools zu erstellen und zu betreiben, bringt CraftBot alle Kernfunktionen eines Agent-Frameworks mit. So kann er als universeller KI-Agent an deiner Seite über deine Aufgaben, Tools, dein Gedächtnis und deine täglichen Workflows hinweg arbeiten.

- **Agent-Profile** Mehr als 40 Agent-Profile (CEO-Agent, Finance-Agent, Marketing-Lead-Agent, DevOps-Engineer, Video-Producer-Agent oder 37 weitere) stehen bereit, um für dich zu arbeiten. Finde die gewünschten Rollen in den **[CraftBot Agent Bundles](https://github.com/CraftOS-dev/craftbot-agent-bundles)** und importiere sie mit einem Klick.
- **Playbook-Katalog** Du weißt nicht, wie du mit einem KI-Agenten automatisieren sollst? CraftBot bringt 120 sofort einsatzbereite Playbooks mit (in 19 Kategorien). Öffne den Playbook-Picker in der oberen Leiste, wähle ein Playbook aus, und es beginnt, die Aufgabe für dich auszuführen.
- **Agent App.** Baue, importiere oder entwickle eigene Apps, die innerhalb von CraftBot leben. Der Agent kennt den Zustand der UI jederzeit und kann ihre Daten direkt lesen, schreiben und damit arbeiten.
- **Multitasking und Session-Routing.** Tippst du noch von Hand `/new`? CraftBot weiß selbst, wann eine neue Session sinnvoll ist und wann eine bestehende Aufgabe wieder aufgenommen werden sollte, so bleiben Gespräch und Kontext einheitlich.
- **Self-hosted und BYOK.** Flexibles LLM-Provider-System mit Unterstützung für OpenAI, Google Gemini, Anthropic Claude, OpenRouter und mehr. Oder hoste mit Ollama dein eigenes Modell, ganz ohne Token-Verbrauch.
- **Memory-System.** Ein zweites Gehirn, aufgebaut aus deinen Interaktionen mit CraftBot. Hybrider Ansatz: RAG + Wissensgraph + Agent-Dateisystem. Um Mitternacht „träumt" CraftBot und konsolidiert die Ereignisse des Tages.
- **Proaktiver Agent.** Er lernt deine Vorlieben, Gewohnheiten und Lebensziele kennen, plant darauf basierend und stößt Aufgaben an (natürlich nur mit deiner Freigabe), um dich in deinem Leben weiterzubringen.
- **Integration externer Tools.** Verbinde deine Apps wie Google Workspace, Slack, Notion, Zoom, LinkedIn, Discord, Telegram und mehr (weitere folgen!) mit OAuth-Unterstützung oder deinem eigenen Schlüssel. Du kannst mit jeder Integration mehrere Konten verbinden.
- **Skills und MCP.** Über 150 MCPs und 170 Skills sofort einsatzbereit. Neue Skills und MCPs lassen sich schnell installieren, und aus abgeschlossenen Aufgaben kannst du mit einem Klick neue Skills erstellen oder verbessern.
- **Browser-Oberfläche und CLI.** Nutze CraftBot so, wie es zu dir passt: über eine einfache Browser-UI für die tägliche Arbeit oder per CLI für Skripte und Headless-Umgebungen.

---


## 🧰 Erste Schritte

**Voraussetzungen**

- Windows 10 oder 11 (x64), macOS 12 oder neuer (Apple Silicon oder Intel) oder Linux (x86_64 oder ARM64)
- Mindestens 5 GB freier Speicherplatz
- Ein API-Schlüssel eines LLM-Anbieters wie OpenAI, Anthropic, Google Gemini oder OpenRouter, oder ein lokales Modell über Ollama
- Nur für die Installation aus dem Quellcode: Python 3.8 oder neuer. Node.js wird nicht benötigt.

### Option 1: Installer (empfohlen, ohne Python oder Git)

Lade die passende Datei für dein System vom [neuesten Release](https://github.com/CraftOS-dev/CraftBot/releases/latest) herunter:

| System | Datei |
|---|---|
| Windows (x64) | `CraftBotInstaller-windows.exe` |
| macOS (Apple Silicon und Intel) | `CraftBotInstaller-macos.zip` |
| Linux (x86_64) | `CraftBotInstaller-linux-x86_64` |
| Linux (ARM64) | `CraftBotInstaller-linux-aarch64` |

Öffne die Datei und klicke auf **Install CraftBot**. Der Installer lädt alles herunter, was CraftBot braucht, startet CraftBot und öffnet es im Browser.

Die Installer sind noch nicht codesigniert, daher ist beim ersten Start ein zusätzlicher Schritt nötig:

- **Windows:** Wenn SmartScreen „Der Computer wurde durch Windows geschützt“ anzeigt, klicke auf **Weitere Informationen** (More info) und dann auf **Trotzdem ausführen** (Run anyway).
- **macOS:** Entpacke die Datei und öffne `CraftBotInstaller.app`. Ab macOS 15 wird der erste Start blockiert: Öffne **Systemeinstellungen > Datenschutz & Sicherheit**, klicke neben dem Hinweis zu CraftBotInstaller auf **Dennoch öffnen** (Open Anyway) und bestätige. Unter macOS 12 bis 14 klickst du stattdessen mit der rechten Maustaste auf die App und wählst **Öffnen** (Open).
- **Linux:** Mache die Datei ausführbar und starte sie in einer Desktop-Sitzung (auf einem Server ohne Desktop nutzt du die Installation aus dem Quellcode):
  ```bash
  chmod +x CraftBotInstaller-linux-x86_64
  ./CraftBotInstaller-linux-x86_64
  ```

### Option 2: Installation aus dem Quellcode

Jedes Python ab Version 3.8, das bereits auf deinem Rechner ist, reicht aus. CraftBot lädt ein eigenes, privates Python 3.10 und Node.js 24 herunter und verändert das auf deinem System installierte Python oder Node.js nicht.

```bash
git clone --depth 1 https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot
```

Führe dann den Installationsbefehl für dein System aus:

```bash
# Windows
python craftbot.py install        # oder: py craftbot.py install

# macOS und Linux
python3 craftbot.py install
```

- **Kein Git?** Klicke auf der [Repository-Seite](https://github.com/CraftOS-dev/CraftBot) auf **Code > Download ZIP**, entpacke die Datei, öffne ein Terminal im entpackten Ordner und führe denselben Befehl aus.
- **Kein Python oder älter als 3.8?** Nutze den Installer (Option 1).

Die erste Installation lädt etwa 1 GB herunter und dauert bei einer üblichen Verbindung einige Minuten. Danach läuft CraftBot im Hintergrund, öffnet http://localhost:7925 im Browser und legt eine Desktop-Verknüpfung an. Ist Port 7925 oder 7926 bereits belegt, wählt CraftBot die nächsten freien Ports und gibt die Adresse aus, die du öffnen musst.

Beim ersten Start fragt das Onboarding im Browser nach deinem LLM-API-Schlüssel. CraftBot speichert ihn in `app/config/settings.json` (änderbar später unter Einstellungen) und liest keine API-Schlüssel aus einer `.env`-Datei.

### CraftBot verwalten

Verwende denselben Befehl `python` oder `python3` wie bei der Installation:

```bash
python craftbot.py start      # CraftBot im Hintergrund starten
python craftbot.py stop       # CraftBot stoppen
python craftbot.py restart    # CraftBot neu starten
python craftbot.py status     # Prüfen, ob CraftBot läuft und ob Autostart aktiv ist
python craftbot.py logs       # Die letzten 50 Logzeilen anzeigen (mehr mit logs -n 200)
python craftbot.py uninstall  # Stoppen, Autostart entfernen und Pakete deinstallieren
python run.py --cli           # Im Terminal statt im Browser ausführen
```

Mit dem Installer erledigst du dasselbe im Installer-Fenster (**Start**, **Stop**, **Repair**, **Uninstall**).

> [!TIP]
> Nach `install` oder `start` wird automatisch eine **CraftBot-Desktop-Verknüpfung** erstellt. Wenn du den Browser geschlossen hast, öffnest du ihn per Doppelklick auf die Verknüpfung erneut.

---

## 🌱 Agent App

**Agent App ist ein System/App/Dashboard, das mit deinen Anforderungen wächst.**

<div align="center">
    <img src="assets/agent_app_banner.gif" alt="CraftBot Banner" width="1280"/>
</div>

- Brauchst du ein Kanban-Board mit eingebautem KI-Copiloten? 
- Ein maßgeschneidertes CRM, das exakt deinem Workflow folgt? 
- Ein Unternehmens-Dashboard, das CraftBot lesen und für dich bedienen kann? 

Bring es als Agent App an den Start: Es läuft neben CraftBot und wächst mit deinen Anforderungen.

### Drei Wege, eine Agent App zu erstellen

1. **Von Grund auf bauen.** Beschreibe in natürlicher Sprache, was du brauchst. CraftBot
   erstellt das Gerüst für Datenmodell, Backend-API und React-UI und iteriert mit dir
   über einen strukturierten Designprozess.

<div align="center">
    <img src="assets/agent-app-custom-build.png" alt="Building a Agent App from scratch" width="448"/>
</div>

2. **Aus dem Marketplace installieren.** Stöbere in von der Community gebauten Agent Apps auf [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace).

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Agent App marketplace" width="448"/>
</div>

3. **Ein bestehendes Projekt importieren.** Verweise CraftBot auf ein Projekt in Go, Node.js, Python,
   Rust oder auf statischen Quellcode bzw. ein GitHub-Repo. Er erkennt die Runtime, konfiguriert die Health Checks und verpackt das Ganze als Agent App.

<div align="center">
    <img src="assets/agent-app-import.png" alt="Importing an existing project as a Agent App" width="448"/>
</div>

### Entwickelt sich weiter, mit CraftBot mittendrin

Eine Agent App ist nie „fertig". Bitte den Agent, Funktionen zu ergänzen,
eine Ansicht neu zu gestalten oder sie an neue Daten anzubinden, wenn sich deine Anforderungen ändern.

CraftBot ist in jede Agent App eingebettet und **kennt deren Zustand**:
Er kann das aktuelle DOM und Formularwerte lesen, App-Daten über die REST-API
abfragen und in deinem Namen Aktionen auslösen.

### Hält SaaS-Tools offen und lebendig

Baue, passe an und entwickle deine eigene Agent App weiter und reduziere deine Abhängigkeit von Abo-Tools, die nie wirklich für dich gemacht waren.

---
 
# Drei Agent Apps, die du in 5 Minuten ausprobieren kannst
 
- **📋 Kanban-Board:** Alle Aufgaben, Follow-ups und CTAs an einem Ort. CraftBot kann es bedienen und die PM-Arbeit für dich übernehmen.
- **📊 Habit Tracker:** Baue deine Gewohnheiten auf und verfolge sie. Ein Aktivitätskalender im GitHub-Stil hilft dir, deine Gewohnheiten wie ein:e Entwickler:in zu pflegen.
- **🐦 Luolinglo:** Kein Duolingo, aber damit kannst du neue Sprachen lernen, Karteikarten erstellen und mit CraftBot üben.

**[Stöbere im Agent-App-Marketplace und trage etwas bei →](https://craftos.net/marketplace)**

---

## 🔧 Fehlerbehebung & häufige Probleme

**Beginne mit dem Log.** `python craftbot.py logs` zeigt die letzten 50 Zeilen (mehr mit `logs -n 200`). Schlägt `install` oder `start` fehl, gibt der Befehl das Ende des Logs aus und beendet sich mit einem Fehler. `python craftbot.py doctor` prüft jeden Installationsschritt, ohne etwas zu verändern. Im Installer klickst du auf **Open log**.

**Die Installation erneut auszuführen ist sicher.** `python craftbot.py install` überspringt bereits erfolgreiche Schritte und wiederholt nur den Rest. Im Installer klickst du auf **Repair**.

### Port 7925 oder 7926 ist belegt

CraftBot weicht auf die nächsten freien Ports aus und gibt die Adresse aus, die du öffnen musst. So legst du die Ports selbst fest:

```bash
python craftbot.py start --frontend-port 8925 --backend-port 8926
```

### Proxy oder Firmennetzwerk

Alle Downloads (Python, pip, npm, Node.js) verwenden die üblichen Proxy-Variablen. Setze sie vor der Installation im selben Terminal:

```bash
# macOS und Linux
export HTTPS_PROXY=http://proxy.example.com:8080
export HTTP_PROXY=http://proxy.example.com:8080
export NO_PROXY=localhost,127.0.0.1
python3 craftbot.py install
```

```powershell
# Windows PowerShell
$env:HTTPS_PROXY = "http://proxy.example.com:8080"
$env:HTTP_PROXY = "http://proxy.example.com:8080"
$env:NO_PROXY = "localhost,127.0.0.1"
python craftbot.py install
```

Netzwerke, die TLS-Verkehr prüfen, brauchen keinen zusätzlichen Schritt: CraftBot vertraut den Zertifikaten im Zertifikatsspeicher deines Betriebssystems.

### Langsame oder blockierte Downloads (zum Beispiel in Festlandchina)

Leite die Downloads vor der Installation auf Mirrors um:

| Variable | Wofür | Beispiel |
|---|---|---|
| `PIP_INDEX_URL` | Python-Pakete | `https://pypi.tuna.tsinghua.edu.cn/simple` |
| `npm_config_registry` | npm-Pakete | `https://registry.npmmirror.com` |
| `HF_ENDPOINT` | Embedding-Modell | `https://hf-mirror.com` |
| `CRAFTBOT_MIRRORS` | Downloads von Python, Node.js, PocketBase und Embedding-Modell | siehe unten |

`CRAFTBOT_MIRRORS` ist eine durch Semikolons getrennte Liste von URL-Umschreibungen im Format `prefix=replacement` (Präfix=Ersatz):

```bash
export CRAFTBOT_MIRRORS="https://github.com/=https://<your-github-proxy>/https://github.com/;https://nodejs.org/dist/=https://npmmirror.com/mirrors/node/"
```

Python-Pakete und das Embedding-Modell für den Speicher werden weiterhin gegen fest hinterlegte SHA-256-Prüfsummen geprüft, ein Mirror kann sie also nicht verändern. Die Python- und Node.js-Laufzeiten sind nicht fest hinterlegt, verwende dafür nur einen Mirror, dem du vertraust. In Windows PowerShell setzt du Variablen mit `$env:NAME = "value"` statt `export`.

### Server ohne Desktop

Installiere CraftBot auf dem Server aus dem Quellcode, ohne einen Browser zu öffnen:

```bash
python3 craftbot.py install --no-open-browser
```

CraftBot lauscht auf `localhost` und nimmt nur Browserverbindungen an, die an `localhost` gerichtet sind. Um CraftBot von deinem eigenen Rechner aus zu nutzen, öffne einen SSH-Tunnel, der beide Ports mit denselben Nummern weiterleitet, und öffne dann http://localhost:7925 auf deinem Rechner:

```bash
ssh -L 7925:localhost:7925 -L 7926:localhost:7926 user@server
```

`CRAFTBOT_BIND_HOST` lässt CraftBot auf einer anderen Netzwerkschnittstelle lauschen (das Docker-Image verwendet `0.0.0.0`). Für den Fernzugriff bleibt der SSH-Tunnel der vorgesehene Weg.

### Linux: CraftBot startet nach einem Neustart nicht

Der Autostart ist ein systemd-Benutzerdienst und braucht daher eine systemd-Benutzersitzung. Damit CraftBot beim Booten ohne Anmeldung startet und nach dem Abmelden weiterläuft, aktiviere einmalig Lingering:

```bash
loginctl enable-linger $USER
```

Ohne systemd (zum Beispiel unter WSL ohne aktiviertes systemd) startest du CraftBot nach jedem Booten mit `python3 craftbot.py start`.

### macOS: Der Installer wird blockiert

Der Installer ist noch nicht codesigniert. Ab macOS 15 versuchst du einmal, ihn zu öffnen, öffnest dann **Systemeinstellungen > Datenschutz & Sicherheit** und klickst auf **Dennoch öffnen** (Open Anyway). Unter macOS 12 bis 14 klickst du mit der rechten Maustaste auf die App und wählst **Öffnen** (Open).

### Windows: SmartScreen blockiert den Installer

Klicke auf **Weitere Informationen** (More info) und dann auf **Trotzdem ausführen** (Run anyway). Die Warnung erscheint, weil der Installer noch nicht codesigniert ist.

### Windows: `python` öffnet den Microsoft Store

Python ist nicht installiert. Nutze den Installer oder installiere Python von [python.org](https://www.python.org/downloads/) und führe `py craftbot.py install` aus.

### CraftBot-Daten an einem anderen Ort speichern

Setze vor der Installation `CRAFTBOT_HOME` auf einen Ordner, damit alle CraftBot-Daten und heruntergeladenen Laufzeitumgebungen dort liegen, zum Beispiel auf einem größeren Laufwerk. Der Autostart übernimmt diese Einstellung.

### Browser-Funktionen (Playwright)

Der Mini Browser und die Browser-Automatisierung verwenden Playwrights Chromium. Schlägt dieser Download fehl, funktioniert der Rest von CraftBot trotzdem. Führe später `python craftbot.py install` erneut aus, um es nochmals zu versuchen.

---

## 🐳 Mit Container ausführen

Das Docker-Image führt CraftBot im Browser-Modus aus, mit allem vorinstalliert: Python 3.10 mit den festgelegten Abhängigkeiten, Node.js 24, die Browser-Oberfläche, PocketBase und Playwrights Chromium.

Im Stammverzeichnis des Repositorys:

```bash
docker compose up -d
```

Der erste Build dauert einige Minuten. Öffne danach http://localhost:7925 und gib im Onboarding deinen LLM-API-Schlüssel ein.

Einstellungen und API-Schlüssel, Agent-Dateien, Gedächtnis und Logs liegen im Volume `craftbot-data` und bleiben bei Neustarts und neuen Image-Builds erhalten.

```bash
docker compose logs -f craftbot              # Log fortlaufend anzeigen
docker compose ps                            # Status inklusive Health-Check
docker compose down                          # Stoppen (das Daten-Volume bleibt erhalten)
git pull && docker compose up -d --build     # Auf die neueste Version aktualisieren
```

- Die Ports werden nur auf `127.0.0.1` veröffentlicht, weil die CraftBot-Oberfläche keine eigene Anmeldung hat. Belasse es auf einem entfernten Server dabei und verbinde dich über den SSH-Tunnel, der unter Fehlerbehebung beschrieben ist. Behalte die Host-Ports 7925 und 7926 bei: CraftBot nimmt auf diesen Ports nur Browserverbindungen an, die an `localhost` gerichtet sind.
- Proxy- und Mirror-Einstellungen (`HTTPS_PROXY`, `PIP_INDEX_URL`, `HF_ENDPOINT`, `CRAFTBOT_MIRRORS` und die übrigen in `.env.example`) werden an den Container übergeben, wenn sie in deiner Shell oder in einer `.env`-Datei neben `docker-compose.yml` gesetzt sind.
- Agent Apps laufen im Container auf den Ports 3100 bis 3199 und lassen sich noch nicht im Browser des Hosts öffnen. Für Agent Apps nutzt du den Installer oder die Installation aus dem Quellcode.
- Ohne Compose:
  ```bash
  docker build -t craftbot .
  docker run -d --name craftbot -p 127.0.0.1:7925:7925 -p 127.0.0.1:7926:7926 --shm-size 1g -v craftbot-data:/data craftbot
  ```

---

## 🤝 Wie du beitragen kannst

PRs sind willkommen! Den Ablauf (Fork → Branch von `dev` → PR) findest du in [CONTRIBUTING.md](CONTRIBUTING.md). Alle Pull Requests durchlaufen automatisch eine Lint- und Smoke-Test-CI. 

> [!IMPORTANT]
> **CraftBot** wird aktiv entwickelt, mit Verbesserungen Woche für Woche. Für Fragen oder einen schnelleren Austausch komm zu uns auf [Discord](https://discord.gg/ZN9YHc37HG) oder schreib eine Mail an thamyikfoong(at)craftos.net.

---

## 🧾 Lizenz

Dieses Projekt steht unter der [MIT-Lizenz](LICENSE). Du darfst es frei nutzen, hosten und monetarisieren (bei Weiterverbreitung und Monetarisierung musst du dieses Projekt nennen).

---

## ⭐ Danksagung

Entwickelt und gepflegt von [CraftOS](https://craftos.net/) und Mitwirkenden.  
Wenn dir **CraftBot** weiterhilft, gib dem Repository bitte einen ⭐ und teile es mit anderen!

---

## Star-Verlauf

<a href="https://star-history.dera.page/#CraftOS-dev/CraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
