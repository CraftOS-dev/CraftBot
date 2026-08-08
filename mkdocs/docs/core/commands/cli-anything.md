# CLI-anything

CLI-anything is a bundled [skill](../concepts/skills.md) that lets the agent drive real desktop applications (GIMP, Blender, LibreOffice, Audacity, and two dozen others) from the command line, on Windows, macOS, and Linux. You describe the task ("convert report.docx to PDF", "resize photo.jpg to 1920×1080"). The agent picks the right app, installs it if it's missing, runs it, and reports the result. You never name the app, and you never run a command yourself.

!!! note "Disabled by default"
    CLI-anything ships in the `disabled_skills` list of `app/config/skills_config.json`. Turn it on with `/skill enable cli-anything` or in **Settings → Skills**. Once enabled, it activates automatically whenever a task matches a supported app. Like any enabled skill, it also gets a `/cli-anything` slash command.

## What it can automate

Each app is driven through a cross-platform harness command, `cli-anything-<app>`, so the agent never touches platform-specific binaries or paths:

| Task | App | Harness |
|---|---|---|
| Resize / crop / filter / convert images | GIMP | `cli-anything-gimp` |
| SVG and vector graphics, logo export | Inkscape | `cli-anything-inkscape` |
| Digital painting, `.kra` export | Krita | `cli-anything-krita` |
| DOCX / XLSX / PPTX → PDF, office macros | LibreOffice | `cli-anything-libreoffice` |
| Trim / convert / export audio | Audacity | `cli-anything-audacity` |
| Render and edit video | Kdenlive, Shotcut | `cli-anything-kdenlive`, `cli-anything-shotcut` |
| Screen recording and streaming | OBS Studio | `cli-anything-obs` |
| 3D modeling and rendering, `.blend` files | Blender | `cli-anything-blender` |
| Diagrams (`.drawio`) | Draw.io | `cli-anything-draw-io` |
| Render Mermaid diagram code | Mermaid | `cli-anything-mermaid` |
| AI image generation | Stable Diffusion, ComfyUI | `cli-anything-stable-diffusion`, `cli-anything-comfyui` |
| Run a local LLM | Ollama | `cli-anything-ollama` |
| AI content generation | AnyGen | `cli-anything-anygen` |
| AI research / PDF summarization | NotebookLM | `cli-anything-notebooklm` |
| Execute Jupyter notebooks | JupyterLab | `cli-anything-jupyterlab` |
| CAD, `.fcstd` → STL/STEP | FreeCAD | `cli-anything-freecad` |
| GIS maps, `.qgz` export | QGIS | `cli-anything-qgis` |
| Monitoring dashboards | Grafana | `cli-anything-grafana` |
| Git hosting, repo creation | Gitea, GitLab | `cli-anything-gitea` |
| CI/CD pipelines | Jenkins | `cli-anything-jenkins` |
| Cloud file sync | NextCloud | `cli-anything-nextcloud` |
| Network-wide ad blocking | AdGuard Home | `cli-anything-adguard-home` |
| Video conferencing | Zoom | `cli-anything-zoom` |
| Knowledge outlines | Mubu | `cli-anything-mubu` |

Ask the agent "what can cli-anything do" and it replies with this catalogue directly, without running anything.

## How routing works

The skill's instructions (`skills/cli-anything/SKILL.md`) contain a routing table mapping task descriptions to apps. When the skill is enabled and your request matches ("convert this DOCX", "render this .blend file") the agent selects the app and follows a fixed execution flow:

1. **Detect the OS** (Windows / macOS / Linux).
2. **Check the app is installed** (`gimp --version` and equivalents).
3. **Install it if missing**, one attempt only, via the platform's package manager: `winget` on Windows, `brew` on macOS, `apt-get` on Linux. A few apps use their own path instead (ComfyUI and Stable Diffusion via `git clone`, Mermaid via npm, JupyterLab via pip, Ollama on Linux via its install script; web apps like Mubu and NotebookLM need no install and are driven through the browser-automation skill).
4. **Check the harness** (`cli-anything-<app> --version`); if missing, install `cli-anything-hub` via pip and pull the harness with `cli-hub install <app>`. If the hub fails, the agent generates a minimal harness itself.
5. **Run the task** using only harness commands, for example:

    ```
    cli-anything-gimp image resize input.jpg output.jpg 1920 1080
    cli-anything-libreoffice convert doc.docx output.pdf
    cli-anything-blender render scene.blend --output frames/ --format PNG
    ```

6. **Report** in a sentence or two: what was produced and where.

Every step runs as a shell action, so you can watch the whole flow (version checks, installs, the task command) in the [task panel](../interfaces/browser.md#tasks), and it all lands in [logs](../concepts/logs.md).

The skill hard-bans the failure modes of driving desktop apps directly: no `.exe` suffixes, no hardcoded `C:\Program Files\...` paths, no `&&` command chaining, no raw `soffice`/`gimp`/`blender` invocations. The harness resolves app locations and flags per platform, which is what makes the same task work on all three OSes.

## Python fallback

CLI-anything is the first choice, not the only one. If a harness command fails after one retry, the agent falls back to a pure-Python route (PIL for images, python-docx for documents, pydub for audio, moviepy for video), completes the task anyway, and tells you what it actually used (with a note that installing the app gives better results next time). Installs are never retried, timeouts are never looped on, and after repeated failures on one step the agent stops and reports rather than spinning.

## Requirements

- **Enable the skill** (see the note above). It does nothing while disabled.
- **Action sets:** the skill declares `shell` and `file_operations`. It works through ordinary shell actions, no extra plumbing.
- **A package manager** for auto-install: `winget` (Windows), Homebrew (macOS), or `apt` (Linux, where installs run under `sudo`). `pip` is needed for the harness hub.
- **Internet access** the first time any given app or harness is installed.
- **File paths:** give the agent full paths to input files (`C:\Users\you\Desktop\photo.jpg`, `/home/user/photo.jpg`) for the smoothest run.

!!! warning "It installs software"
    By design, this skill can install real applications on your machine (silently, with license agreements auto-accepted) and run them with your privileges. Each install is a visible shell action in the task panel, and installs are attempted at most once. If you don't want the agent installing anything, keep the skill disabled or preinstall the apps you care about.

## Related

- [Skills](../concepts/skills.md): how skills are enabled, discovered, and invoked
- [Built-in commands](builtin.md#skill): `/skill enable cli-anything` and friends
- [Actions and action sets](../concepts/actions-and-action-sets.md): the shell actions underneath
- [Living UI](../../living-ui/index.md): a different kind of "agent builds it for you"
