---
name: cli-anything
description: "Automatically handles image editing, document conversion, audio/video editing, 3D rendering, diagrams, AI image generation, and more — using GIMP, LibreOffice, Blender, Audacity, Inkscape, Krita, Kdenlive, Shotcut, OBS, Draw.io, Mermaid, Ollama, Stable Diffusion, ComfyUI, JupyterLab, FreeCAD, QGIS, Grafana, Gitea, GitLab, NextCloud, Jenkins, AdGuard Home, Zoom, Mubu. User does NOT need to mention CLI-Anything — agent auto-selects the right app for the task. Auto-installs if not present."
action-sets: ["shell", "file_operations"]
---

# CLI-Anything Skill

**Core rule: Do everything yourself. Never give the user a command to run. Never explain steps. Just execute the task and report the result.**

**Activation rule: The user does NOT need to say "CLI-Anything". If their task matches a supported app below, use it automatically — no prompting needed.**

---

## Task Routing — Auto-select the right app (check this before every task)

| If the user asks about... | Use this app | Command prefix |
|---|---|---|
| Resize / crop / filter / edit an image | **GIMP** | `cli-anything-gimp` |
| Convert image format (JPG→PNG, PNG→WEBP, etc.) | **GIMP** | `cli-anything-gimp` |
| SVG, vector graphics, logos | **Inkscape** | `cli-anything-inkscape` |
| Digital painting, .kra files | **Krita** | `cli-anything-krita` |
| Convert DOCX / XLSX / PPTX → PDF | **LibreOffice** | `cli-anything-libreoffice` |
| Writer / Calc / Impress / spreadsheet macros | **LibreOffice** | `cli-anything-libreoffice` |
| Trim / convert / export audio (MP3, WAV, FLAC) | **Audacity** | `cli-anything-audacity` |
| Render / edit video | **Kdenlive** or **Shotcut** | `cli-anything-kdenlive` |
| Record screen or live stream | **OBS Studio** | `cli-anything-obs` |
| 3D modeling / rendering / .blend files | **Blender** | `cli-anything-blender` |
| Create or export diagrams (.drawio) | **Draw.io** | `cli-anything-draw-io` |
| Render Mermaid diagram code | **Mermaid** | `cli-anything-mermaid` |
| Generate image from text prompt (AI) | **Stable Diffusion** or **ComfyUI** | `cli-anything-stable-diffusion` |
| Run a local LLM | **Ollama** | `cli-anything-ollama` |
| AI content generation | **AnyGen** | `cli-anything-anygen` |
| AI research / summarize PDF | **NotebookLM** | `cli-anything-notebooklm` |
| Execute a Jupyter notebook | **JupyterLab** | `cli-anything-jupyterlab` |
| CAD / 3D design, .fcstd files | **FreeCAD** | `cli-anything-freecad` |
| GIS / maps, .qgz files | **QGIS** | `cli-anything-qgis` |
| Monitoring dashboards | **Grafana** | `cli-anything-grafana` |
| Git hosting, create repos | **Gitea** or **GitLab** | `cli-anything-gitea` |
| CI/CD pipelines | **Jenkins** | `cli-anything-jenkins` |
| Cloud file sync | **NextCloud** | `cli-anything-nextcloud` |
| Network-wide ad blocking | **AdGuard Home** | `cli-anything-adguard-home` |
| Video conferencing | **Zoom** | `cli-anything-zoom` |
| Knowledge outlines | **Mubu** | `cli-anything-mubu` |

---

## Smart Fallback — When CLI-Anything fails

CLI-Anything is the first choice, but if it fails the agent must still complete the task:

1. **Try CLI-Anything first** — always attempt the harness (`cli-anything-<app>`)
2. **If harness fails after 1 retry** — fall back to Python (PIL, python-docx, pydub, moviepy, etc.) and complete the task anyway
3. **Always tell the user** what was actually used and suggest installing the app for better results

Example:
> "Done — resized using Python PIL as a fallback (GIMP harness failed). Install GIMP for higher quality results next time."

Never leave the user with no result. Always complete the task one way or another.

---

## FORBIDDEN — Never Do These (causes bugs on all platforms)

These patterns are strictly banned. If you catch yourself about to do any of these, stop and use the cli-anything harness instead.

| ❌ FORBIDDEN | ✅ CORRECT |
|---|---|
| `soffice.exe --headless --convert-to pdf ...` | `cli-anything-libreoffice convert doc.docx output.pdf` |
| `cd "C:\Program Files\LibreOffice\program" && soffice.exe ...` | `cli-anything-libreoffice convert doc.docx output.pdf` |
| `gimp --batch-interpreter=script-fu-use-v2 ...` | `cli-anything-gimp image resize input.jpg output.jpg 1920 1080` |
| `blender --background scene.blend --render-output ...` | `cli-anything-blender render scene.blend --output frames/ --format PNG` |
| `inkscape --export-type=png logo.svg` | `cli-anything-inkscape export logo.svg logo.png --dpi 300` |
| Chaining with `&&`: `cmd1 && cmd2` | Two separate `run_shell` calls |
| Any `.exe` extension in a command | No `.exe` — harness is cross-platform |
| Hardcoded paths like `C:\Program Files\...` | Use the harness — it finds the app automatically |

**Why these are banned:**
- `.exe` only exists on Windows — breaks on macOS and Linux
- `C:\Program Files\...` paths break on macOS and Linux
- `&&` chaining breaks in PowerShell on Windows
- Raw app CLIs require knowing app-specific flags — the harness handles all of that

---

## Help Response (no tools needed — just reply with text)

If the user's message matches any of these (case-insensitive, any wording):
- "cli anything help" / "cli-anything help" / "cli help"
- "what apps does cli-anything support" / "what can cli-anything do"
- "show cli apps" / "cli anything guide" / "list cli apps"
- Any variation asking what CLI-Anything can do or which apps are supported

**Do not run any tools. Reply directly with this message:**

---

**CLI-Anything — What I Can Do**

Just describe your task in plain English — you don't need to mention CLI-Anything. I'll pick the right app, install it if needed, and complete the task. Works on Windows, macOS, and Linux.

**Creative & Media**
| App | What I do | Example |
|---|---|---|
| GIMP _(image editing)_ | Resize, crop, filter, convert, export images | "Resize photo.jpg to 1920×1080" |
| Blender _(3D modeling & rendering)_ | Render scenes, export models, run scripts | "Render scene.blend to PNG frames" |
| Inkscape _(vector graphics)_ | Export SVG to PNG/PDF, convert vectors | "Export logo.svg as 300 DPI PNG" |
| Audacity _(audio production)_ | Trim, convert, export audio | "Trim first 30s from audio.mp3" |
| OBS Studio _(live streaming & recording)_ | Record screen, capture video, stream | "Record my screen for 60 seconds" |
| Kdenlive _(video editing)_ | Render video projects to MP4/MKV | "Render project.kdenlive to MP4" |
| Shotcut _(video editing)_ | Render video projects to MP4 | "Render project.mlt to MP4" |
| Krita _(digital painting)_ | Export paintings, batch convert .kra files | "Export painting.kra as PNG" |

**Office & Productivity**
| App | What I do | Example |
|---|---|---|
| LibreOffice _(Writer, Calc, Impress)_ | Convert DOCX/XLSX/PPTX to PDF, run macros | "Convert report.docx to PDF" |
| Mubu _(knowledge management & outlining)_ | Manage outlines and knowledge bases | "Open my outline in Mubu" |

**Communication**
| App | What I do | Example |
|---|---|---|
| Zoom _(video conferencing)_ | Start or join meetings | "Start a Zoom meeting" |

**Diagramming**
| App | What I do | Example |
|---|---|---|
| Draw.io _(diagrams)_ | Export diagrams to PNG/SVG/PDF | "Export diagram.drawio as PNG" |
| Mermaid Live Editor _(diagrams)_ | Render diagram code to image | "Render: graph TD; A-->B; B-->C" |

**AI & ML**
| App | What I do | Example |
|---|---|---|
| ComfyUI _(AI image generation)_ | Run AI image workflows | "Run workflow.json, save to output/" |
| AnyGen _(AI content generation)_ | Generate AI content | "Generate content using AnyGen" |
| NotebookLM _(AI research assistant)_ | Research, summarize documents | "Summarize this PDF in NotebookLM" |
| Ollama _(local LLM inference)_ | Run local AI models | "Run llama3: summarize this text" |
| Stable Diffusion WebUI | Generate images from text prompts | "Generate 'sunset over mountains'" |

**Network & Infrastructure**
| App | What I do | Example |
|---|---|---|
| AdGuard Home _(network-wide ad blocking)_ | Set up DNS-level ad blocking | "Set up AdGuard Home ad blocking" |
| JupyterLab | Execute notebooks, save output | "Run notebook.ipynb and save output" |
| Jenkins | Trigger CI/CD pipelines | "Trigger my build pipeline" |
| Gitea | Git hosting, create/manage repos | "Create private repo called myrepo" |
| NextCloud | Cloud file sync | "Sync my folder to NextCloud" |
| GitLab | Projects, CI/CD pipelines | "Create a new GitLab project" |
| Grafana | Export monitoring dashboards | "Export my dashboard as JSON" |
| FreeCAD | Export 3D models to STL/STEP | "Export model.fcstd as STL" |
| QGIS | Export maps to PNG/PDF | "Export map.qgz as PNG" |

**Tips:**
- Give me the full file path (e.g. `C:\Users\you\Desktop\photo.jpg` or `/home/user/photo.jpg`)
- If the app isn't installed, I install it automatically — no action needed from you
- If the app fails, I fall back to a Python alternative and tell you
- Works on Windows, macOS, and Linux

---

## Supported Apps Reference

Use this table to look up the correct names for every step.

| App | cli-hub name | Windows (winget) | macOS (brew cask) | Linux (apt) |
|---|---|---|---|---|
| GIMP | `gimp` | `GIMP.GIMP` | `gimp` | `gimp` |
| Blender | `blender` | `BlenderFoundation.Blender` | `blender` | `blender` |
| Inkscape | `inkscape` | `Inkscape.Inkscape` | `inkscape` | `inkscape` |
| Audacity | `audacity` | `Audacity.Audacity` | `audacity` | `audacity` |
| OBS Studio | `obs` | `OBSProject.OBSStudio` | `obs` | `obs-studio` |
| Kdenlive | `kdenlive` | `KDE.Kdenlive` | `kdenlive` | `kdenlive` |
| Shotcut | `shotcut` | `Meltytech.Shotcut` | `shotcut` | `shotcut` |
| Krita | `krita` | `KDE.Krita` | `krita` | `krita` |
| LibreOffice | `libreoffice` | `TheDocumentFoundation.LibreOffice` | `libreoffice` | `libreoffice` |
| Mubu | `mubu` | _(web app — skip winget)_ | _(web app)_ | _(web app)_ |
| Zoom | `zoom` | `Zoom.Zoom` | `zoom` | `zoom` |
| Draw.io | `draw-io` | `JGraph.Draw` | `drawio` | _(AppImage)_ |
| Mermaid | `mermaid` | `OpenJS.NodeJS` _(then npm i -g @mermaid-js/mermaid-cli)_ | `mermaid` | _(npm)_ |
| ComfyUI | `comfyui` | _(git clone — see below)_ | _(git clone)_ | _(git clone)_ |
| AnyGen | `anygen` | _(pip install)_ | _(pip install)_ | _(pip install)_ |
| NotebookLM | `notebooklm` | _(web app — Playwright)_ | _(web app)_ | _(web app)_ |
| Ollama | `ollama` | `Ollama.Ollama` | `ollama` | _(curl install)_ |
| AdGuard Home | `adguard-home` | `AdGuard.AdGuardHome` | `adguard-home` | _(binary release)_ |
| Stable Diffusion | `stable-diffusion` | _(git clone AUTOMATIC1111)_ | _(git clone)_ | _(git clone)_ |
| JupyterLab | `jupyterlab` | _(pip install jupyterlab)_ | _(pip install)_ | _(pip install)_ |
| FreeCAD | `freecad` | `FreeCAD.FreeCAD` | `freecad` | `freecad` |
| QGIS | `qgis` | `OSGeo.QGIS` | `qgis` | `qgis` |
| Grafana | `grafana` | `GrafanaLabs.Grafana` | `grafana` | `grafana` |
| Gitea | `gitea` | `Gitea.Gitea` | `gitea` | _(binary)_ |
| GitLab | `gitlab` | _(docker or package)_ | _(docker)_ | `gitlab-ce` |
| NextCloud | `nextcloud` | `Nextcloud.NextcloudDesktop` | `nextcloud` | _(snap/docker)_ |
| Jenkins | `jenkins` | `Jenkins.Jenkins` | `jenkins` | `jenkins` |

---

## Execution Flow (follow every time — use EXACT timeouts listed)

**CRITICAL: Always pass the timeout shown below to run_shell. Never use the default (30s). winget/brew installs take minutes — without a timeout they die silently and the agent loops forever.**

**CRITICAL: Never chain commands with `&&` or `;` in a single run_shell call. Use one separate run_shell call per command.**

### Step 1 — Detect OS
Run with `timeout: 10`:
```
python -c "import platform; print(platform.system())"
```
Result: `Windows`, `Darwin`, or `Linux`.

### Step 2 — Check if the app is installed
Run with `timeout: 10`:
```
gimp --version
```
(replace with the correct app: `blender --version`, `libreoffice --version`, etc.)

- Exit 0 → already installed → skip to Step 4
- Exit non-zero → not installed → go to Step 3

### Step 3 — Install the app (ONE attempt only — never retry install)

**Windows** — run with `timeout: 600`:
```
winget install --id <WingetID> --silent --accept-package-agreements --accept-source-agreements
```

**macOS** — run with `timeout: 600`:
```
brew install --cask <cask-name>
```

**Linux** — run with `timeout: 300`:
```
sudo apt-get install -y <package>
```

**Special cases:**
- ComfyUI / Stable Diffusion: `git clone` + `pip install -r requirements.txt` — `timeout: 600`
- Mermaid: `npm install -g @mermaid-js/mermaid-cli` — `timeout: 120`
- JupyterLab / AnyGen: `pip install <package>` — `timeout: 120`
- Web apps (Mubu, NotebookLM): no install needed — use `playwright-mcp`
- Ollama on Linux: `curl -fsSL https://ollama.com/install.sh | sh` — `timeout: 300`

After install, re-run Step 2 check once (`timeout: 10`). If still fails → tell the user, stop completely.

### Step 4 — Check if CLI harness is installed
Run with `timeout: 10`:
```
cli-anything-<appname> --version
```
- Found → skip to Step 6
- Not found → go to Step 5

### Step 5 — Install CLI harness (ONE attempt only)

**Always try CLI-Hub first** — run with `timeout: 120`:
```
pip install cli-anything-hub --quiet
```
Then run with `timeout: 120`:
```
cli-hub install <cli-hub-name>
```
(Two separate run_shell calls — do NOT chain with &&)

If CLI-Hub fails → generate a minimal harness with `write_file` (a Click CLI wrapping the app's real scripting API), then run with `timeout: 60`:
```
pip install -e cli_anything/<appname> --quiet
```

If harness install also fails → tell the user, stop completely.

### Step 6 — Execute the user's task using the CLI harness ONLY

**MANDATORY: Use ONLY `cli-anything-<app>` commands. Never call soffice, gimp, blender, or any app binary directly.**

Run with `timeout: 300` (or `timeout: 600` for renders/exports):

```
# Image editing — GIMP
cli-anything-gimp image resize input.jpg output.jpg 1920 1080
cli-anything-gimp filter blur input.jpg --radius 3 --output out.jpg
cli-anything-gimp export input.xcf output.png

# 3D / rendering — Blender
cli-anything-blender render scene.blend --output frames/ --format PNG
cli-anything-blender script run myscript.py scene.blend

# Vector — Inkscape
cli-anything-inkscape export logo.svg logo.png --dpi 300
cli-anything-inkscape convert input.svg output.pdf

# Painting — Krita
cli-anything-krita export painting.kra output.png

# Audio — Audacity
cli-anything-audacity trim audio.mp3 output.mp3 --start 0 --end 30
cli-anything-audacity export-mp3 project.aup3 output.mp3

# Video — Kdenlive / Shotcut
cli-anything-kdenlive render project.kdenlive output.mp4
cli-anything-shotcut render project.mlt output.mp4

# Office — LibreOffice (NEVER use soffice.exe directly)
cli-anything-libreoffice convert doc.docx output.pdf
cli-anything-libreoffice convert spreadsheet.xlsx output.pdf
cli-anything-libreoffice calc run macro.py spreadsheet.xlsx

# Diagrams
cli-anything-draw-io export diagram.drawio output.png
cli-anything-mermaid render diagram.mmd output.png

# AI / ML
cli-anything-comfyui run workflow.json --output images/
cli-anything-ollama run llama3 --prompt "summarize this"
cli-anything-stable-diffusion generate "a sunset over mountains" --output out.png

# Dev / Infra
cli-anything-jupyterlab execute notebook.ipynb --output result.ipynb
cli-anything-grafana export-dashboard my-dashboard dashboard.json
cli-anything-gitea create-repo myrepo --private

# GIS / Design
cli-anything-freecad export model.fcstd output.stl
cli-anything-qgis export map.qgz output.png
```

**Always run the task. Never print commands and ask the user to run them.**

If the task command fails → retry once with adjusted args. If it fails again → report the error and stop.

### Step 7 — Report result
One or two sentences only:
> "Done — rendered `output.mp4` from your Kdenlive project."
> "Converted `report.docx` to PDF at `report.pdf`."

---

## Hard Stop Rules (prevents infinite loops)

- **Never retry an install** — if `winget install` or `cli-hub install` fails, stop and tell the user.
- **Never loop on a timeout** — if a command times out once, it will time out again. Stop immediately.
- **Max 1 retry on the task command (Step 6) only** — not on installs.
- **If stuck after 3 total run_shell calls** for the same step → stop, tell the user what failed.
- **Never use `&&` or `;` to chain commands** — always use separate run_shell calls.
- **Never use `.exe` extensions** — use the cli-anything harness which is cross-platform.
- **Never hardcode app installation paths** — use the harness, it resolves the path automatically.