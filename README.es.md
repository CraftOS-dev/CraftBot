<div align="center">
    <img src="assets/README_cover.png" alt="CraftBot" width="1280"/>
</div>

La mayoría de los agentes se quedan en el chat y las llamadas a herramientas. CraftBot va más allá. Construye, hace evolucionar y opera sus propias herramientas SaaS, y luego usa esa capa de herramientas para comunicarse contigo y automatizar tu trabajo.

Además de eso, CraftBot incluye todas las capacidades básicas de un agente de propósito general. Ejecuta tareas como lo haría un empleado remoto, recuerda tus preferencias y objetivos, y te ayuda de forma proactiva a planificar y actuar sobre lo que más te importa.

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
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## ✨ Características destacadas

Más allá de ser un agente de IA capaz de crear y operar sus propias herramientas SaaS, CraftBot incluye todas las capacidades básicas de un agente, lo que le permite funcionar como un agente de propósito general que te acompaña en tus tareas, herramientas, memoria y flujos de trabajo diarios.

- **Perfiles de agente** Más de 40 perfiles de agente (agente CEO, agente de finanzas, agente líder de marketing, ingeniero DevOps, agente productor de vídeo y 37 más) listos para trabajar para ti. Encuentra los roles que deseas en **[CraftBot Agent Bundles](https://github.com/CraftOS-dev/craftbot-agent-bundles)** e impórtalos con un solo clic.
- **Catálogo de playbooks** ¿No sabes cómo automatizar con un agente IA? CraftBot incluye 120 playbooks listos para usar (en 19 categorías). Abre el selector de playbooks desde la barra superior, elige uno y empezará a ejecutar la tarea por ti.
- **Agent App.** Crea, importa o haz evolucionar aplicaciones personalizadas que viven dentro de CraftBot. El agente conoce en todo momento el estado de la UI y puede leer, escribir y actuar directamente sobre sus datos.
- **Multitarea y enrutamiento de sesiones.** ¿Sigues escribiendo `/new` a mano? CraftBot decide cuándo iniciar una nueva sesión y cuándo retomar una tarea existente, manteniendo unificados la conversación y el contexto.
- **Autohospedado y BYOK.** Sistema flexible de proveedores LLM compatible con OpenAI, Google Gemini, Anthropic Claude, OpenRouter y más. O aloja tu propio modelo sin gastar tokens usando Ollama.
- **Sistema de memoria.** Un segundo cerebro construido a partir de tus interacciones con CraftBot. Enfoque híbrido: RAG + grafo de conocimiento + sistema de archivos del agente. CraftBot "sueña" a medianoche y consolida los eventos del día.
- **Agente proactivo.** Aprende tus preferencias, hábitos y objetivos de vida. Luego planifica e inicia tareas (con tu aprobación, por supuesto) para ayudarte a mejorar.
- **Integración con herramientas externas.** Conecta tus aplicaciones como Google Workspace, Slack, Notion, Zoom, LinkedIn, Discord, Telegram y más (¡y vienen más!), con soporte para OAuth o usando tu propia clave. Puedes conectar varias cuentas a cada integración.
- **Skills y MCP.** Más de 150 MCP y 170 Skills listos para usar. Instalación rápida de nuevas Skills y MCPs. Crea o mejora Skills a partir de tareas completadas con un solo clic.
- **Navegador o terminal.** Usa CraftBot como mejor te encaje: con una UI de navegador sencilla para el día a día, o con la edición completa para terminal (`python run.py --tui`), con los mismos chats, ajustes y Agent Apps.

---


## 🧰 Primeros pasos

**Requisitos**

- Windows 10 u 11 (x64), macOS 12 o posterior (Apple Silicon o Intel), o Linux (x86_64 o ARM64)
- Al menos 5 GB de espacio libre en disco
- Una clave de API de un proveedor de LLM como OpenAI, Anthropic, Google Gemini u OpenRouter, o un modelo local servido con Ollama
- Solo para la instalación desde el código fuente: Python 3.8 o posterior. No hace falta Node.js.

### Opción 1: Instalador (recomendado, sin Python ni Git)

Descarga el archivo para tu sistema desde la [última versión publicada](https://github.com/CraftOS-dev/CraftBot/releases/latest):

| Sistema | Archivo |
|---|---|
| Windows (x64) | `CraftBotInstaller-windows.exe` |
| macOS (Apple Silicon e Intel) | `CraftBotInstaller-macos.zip` |
| Linux (x86_64) | `CraftBotInstaller-linux-x86_64` |
| Linux (ARM64) | `CraftBotInstaller-linux-aarch64` |

Ábrelo y haz clic en **Install CraftBot**. El instalador descarga todo lo que CraftBot necesita, lo inicia y lo abre en tu navegador.

Los instaladores todavía no tienen firma de código, así que el primer inicio necesita un paso adicional:

- **Windows:** si SmartScreen muestra "Windows protegió su PC", haz clic en **Más información** (More info) y luego en **Ejecutar de todas formas** (Run anyway).
- **macOS:** descomprime el archivo y abre `CraftBotInstaller.app`. En macOS 15 o posterior el primer intento se bloquea: abre **Ajustes del Sistema > Privacidad y seguridad**, haz clic en **Abrir igualmente** (Open Anyway) junto al mensaje sobre CraftBotInstaller y confirma. En macOS 12 a 14, haz clic derecho en la app y elige **Abrir** (Open).
- **Linux:** haz el archivo ejecutable y ejecútalo desde una sesión de escritorio (en un servidor sin escritorio, usa la instalación desde el código fuente):
  ```bash
  chmod +x CraftBotInstaller-linux-x86_64
  ./CraftBotInstaller-linux-x86_64
  ```

### Opción 2: Instalar desde el código fuente

Sirve cualquier Python 3.8 o posterior que ya tengas en tu equipo. CraftBot descarga su propio Python 3.10 y Node.js 24 privados y nunca modifica el Python ni el Node.js instalados en tu sistema.

```bash
git clone --depth 1 https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot
```

Después ejecuta el comando de instalación para tu sistema:

```bash
# Windows
python craftbot.py install        # o bien: py craftbot.py install

# macOS y Linux
python3 craftbot.py install
```

- **¿No tienes Git?** En la [página del repositorio](https://github.com/CraftOS-dev/CraftBot), haz clic en **Code > Download ZIP**, descomprímelo, abre una terminal en la carpeta descomprimida y ejecuta el mismo comando.
- **¿No tienes Python o es anterior a 3.8?** Usa el instalador (opción 1).

La primera instalación descarga alrededor de 1 GB y tarda unos minutos con una conexión normal. Al terminar, CraftBot queda en segundo plano, abre http://localhost:7925 en tu navegador y crea un acceso directo en el escritorio. Si el puerto 7925 o 7926 ya está en uso, CraftBot elige los siguientes puertos libres y muestra la dirección que debes abrir.

En el primer inicio, el onboarding del navegador te pide tu clave de API del LLM. CraftBot la guarda en `app/config/settings.json` (puedes cambiarla después en Ajustes) y no lee claves de API desde un archivo `.env`.

### Gestionar CraftBot

Usa el mismo comando `python` o `python3` que en la instalación:

```bash
python craftbot.py start      # Inicia CraftBot en segundo plano
python craftbot.py stop       # Detiene CraftBot
python craftbot.py restart    # Reinicia CraftBot
python craftbot.py status     # Comprueba si está en marcha y si el autoinicio está activo
python craftbot.py logs       # Muestra las últimas 50 líneas del log (más con logs -n 200)
python craftbot.py uninstall  # Detiene, quita el autoinicio y desinstala los paquetes
python run.py --tui           # Ejecuta en la terminal en lugar del navegador
```

Si usas el instalador, puedes hacer lo mismo desde su ventana (**Start**, **Stop**, **Repair**, **Uninstall**).

> [!TIP]
> Tras `install` o `start` se crea automáticamente un **acceso directo de CraftBot en el escritorio**. Si cierras el navegador, haz doble clic en él para volver a abrirlo.

---

## 🌱 Agent App

**Agent App es un sistema/app/dashboard que evoluciona con tus necesidades.**

<div align="center">
    <img src="assets/agent_app_banner.gif" alt="CraftBot Banner" width="1280"/>
</div>

- ¿Necesitas un tablero kanban con un copiloto de IA incorporado?
- ¿Un CRM a medida que encaje exactamente con tu flujo de trabajo?
- ¿Un dashboard corporativo que CraftBot pueda leer y operar por ti?

Ponlo en marcha como una Agent App que se ejecuta junto a CraftBot y crece a medida que cambian tus necesidades.

### Tres formas de crear una Agent App

1. **Construir desde cero.** Describe en lenguaje natural lo que quieres. CraftBot
   genera el modelo de datos, la API de backend y la UI en React, y luego itera
   contigo a través de un proceso de diseño estructurado.

<div align="center">
    <img src="assets/agent-app-custom-build.png" alt="Building a Agent App from scratch" width="448"/>
</div>

2. **Instalar desde el marketplace.** Explora las Agent Apps creadas por la comunidad en [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace).

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Agent App marketplace" width="448"/>
</div>

3. **Importar un proyecto existente.** Indícale a CraftBot un proyecto en Go, Node.js, Python,
   Rust, o código estático o un repositorio de GitHub. Detecta el runtime, configura los health checks y lo envuelve como una Agent App.

<div align="center">
    <img src="assets/agent-app-import.png" alt="Importing an existing project as a Agent App" width="448"/>
</div>

### Sigue evolucionando con CraftBot dentro del bucle

Una Agent App nunca está "terminada". Pídele al agente que añada funciones, rediseñe
una vista o la conecte con nuevos datos según tus necesidades cambien.

CraftBot está embebido en cada Agent App y es **consciente de su estado**:
puede leer el DOM y los valores de los formularios, consultar los datos de la app a través de la
API REST y disparar acciones en tu nombre.

### Mantén las herramientas SaaS abiertas y vivas

Construye, personaliza y haz evolucionar tu propia Agent App, y depende menos de herramientas por suscripción que nunca se diseñaron para encajar perfectamente con tus necesidades.

---
 
# Tres Agent Apps que puedes probar en 5 minutos
 
- **📋 Tablero Kanban**: Cada tarea, seguimiento y CTA en un solo lugar. CraftBot puede manejarlo para hacer el trabajo de PM por ti.
- **📊 Habit Tracker**: Desarrolla y mantén tus hábitos. Un calendario de actividad al estilo GitHub para seguir tus hábitos como un desarrollador.
- **🐦 Luolinglo**: No es Duolingo, pero puedes aprender nuevos idiomas, crear flashcards y practicar con CraftBot.

**[Explora y contribuye al marketplace de Agent App →](https://craftos.net/marketplace)**

---

## 🔧 Solución de problemas y preguntas frecuentes

**Empieza por el log.** `python craftbot.py logs` muestra las últimas 50 líneas (más con `logs -n 200`). Si `install` o `start` fallan, muestran el final del log y terminan con un error. `python craftbot.py doctor` revisa cada paso de la instalación sin cambiar nada. En el instalador, haz clic en **Open log**.

**Volver a ejecutar la instalación es seguro.** `python craftbot.py install` omite los pasos que ya se completaron y reintenta el resto. En el instalador, haz clic en **Repair**.

### Los puertos 7925 o 7926 ya están en uso

CraftBot pasa a los siguientes puertos libres y muestra la dirección que debes abrir. Para elegir los puertos tú mismo:

```bash
python craftbot.py start --frontend-port 8925 --backend-port 8926
```

### Proxy o red corporativa

Todas las descargas (Python, pip, npm, Node.js) usan las variables de proxy estándar. Defínelas en la misma terminal antes de instalar:

```bash
# macOS y Linux
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

Las redes que inspeccionan el tráfico TLS no requieren ningún paso adicional: CraftBot confía en los certificados del almacén de certificados de tu sistema operativo.

### Descargas lentas o bloqueadas (por ejemplo, en China continental)

Antes de instalar, dirige las descargas a mirrors:

| Variable | Uso | Ejemplo |
|---|---|---|
| `PIP_INDEX_URL` | Paquetes de Python | `https://pypi.tuna.tsinghua.edu.cn/simple` |
| `npm_config_registry` | Paquetes de npm | `https://registry.npmmirror.com` |
| `HF_ENDPOINT` | Modelo de embeddings | `https://hf-mirror.com` |
| `CRAFTBOT_MIRRORS` | Descargas de Python, Node.js, PocketBase y el modelo de embeddings | ver abajo |

`CRAFTBOT_MIRRORS` es una lista, separada por punto y coma, de reescrituras de URL con el formato `prefix=replacement` (prefijo=sustitución):

```bash
export CRAFTBOT_MIRRORS="https://github.com/=https://<your-github-proxy>/https://github.com/;https://nodejs.org/dist/=https://npmmirror.com/mirrors/node/"
```

Los paquetes de Python, los runtimes de Python y Node.js y el modelo de embeddings de la memoria se verifican con checksums SHA-256 fijados, así que un mirror no puede cambiarlos. En Windows PowerShell, define las variables con `$env:NAME = "value"` en lugar de `export`.

### Servidor sin escritorio

Instala desde el código fuente en el servidor sin abrir un navegador:

```bash
python3 craftbot.py install --no-open-browser
```

CraftBot escucha en `localhost` y solo acepta conexiones del navegador dirigidas a `localhost`. Para usarlo desde tu propio equipo, abre un túnel SSH que reenvíe ambos puertos con los mismos números y luego abre http://localhost:7925 en tu equipo:

```bash
ssh -L 7925:localhost:7925 -L 7926:localhost:7926 user@server
```

`CRAFTBOT_BIND_HOST` hace que CraftBot escuche en otra interfaz de red (la imagen de Docker usa `0.0.0.0`). Para el acceso remoto, el túnel SSH sigue siendo la vía recomendada.

### Linux: CraftBot no arranca después de reiniciar

El autoinicio es un servicio de usuario de systemd, por lo que necesita una sesión de usuario de systemd. Para que CraftBot arranque al encender el equipo sin iniciar sesión, y siga funcionando después de cerrarla, activa lingering una vez:

```bash
loginctl enable-linger $USER
```

Sin systemd (por ejemplo, en WSL con systemd desactivado), ejecuta `python3 craftbot.py start` después de cada arranque.

### macOS: el instalador está bloqueado

El instalador todavía no tiene firma de código. En macOS 15 o posterior, intenta abrirlo una vez, luego abre **Ajustes del Sistema > Privacidad y seguridad** y haz clic en **Abrir igualmente** (Open Anyway). En macOS 12 a 14, haz clic derecho en la app y elige **Abrir** (Open).

### Windows: SmartScreen bloquea el instalador

Haz clic en **Más información** (More info) y luego en **Ejecutar de todas formas** (Run anyway). El aviso aparece porque el instalador todavía no tiene firma de código.

### Windows: `python` abre Microsoft Store

Python no está instalado. Usa el instalador, o instala Python desde [python.org](https://www.python.org/downloads/) y ejecuta `py craftbot.py install`.

### Guardar los datos de CraftBot en otro lugar

Antes de instalar, define `CRAFTBOT_HOME` con una carpeta para guardar allí todos los datos de CraftBot y los runtimes descargados, por ejemplo en un disco más grande. El autoinicio conserva este ajuste.

### Funciones de navegador (Playwright)

El Mini Browser y la automatización del navegador usan el Chromium de Playwright. Si su descarga falla, el resto de CraftBot sigue funcionando. Vuelve a ejecutar `python craftbot.py install` más tarde para reintentarlo.

---

## 🐳 Ejecutar con un contenedor

La imagen de Docker ejecuta CraftBot en modo navegador con todo preinstalado: Python 3.10 con sus dependencias fijadas, Node.js 24, la interfaz del navegador, PocketBase y el Chromium de Playwright.

Desde la raíz del repositorio:

```bash
docker compose up -d
```

La primera compilación tarda varios minutos. Después abre http://localhost:7925 e introduce tu clave de API del LLM en el onboarding.

Los ajustes y claves de API, los archivos del agente, la memoria y los logs se guardan en el volumen `craftbot-data`, así que se conservan entre reinicios y nuevas compilaciones de la imagen.

```bash
docker compose logs -f craftbot              # Sigue el log
docker compose ps                            # Estado, incluido el health check
docker compose down                          # Detiene (el volumen de datos se conserva)
git pull && docker compose up -d --build     # Actualiza a la última versión
```

- Los puertos solo se publican en `127.0.0.1`, porque la interfaz de CraftBot no tiene inicio de sesión propio. En un servidor remoto, mantenlo así y conéctate mediante el túnel SSH descrito en Solución de problemas. Mantén los puertos del host en 7925 y 7926: CraftBot solo acepta conexiones del navegador dirigidas a `localhost` en esos puertos.
- Los ajustes de proxy y mirrors (`HTTPS_PROXY`, `PIP_INDEX_URL`, `HF_ENDPOINT`, `CRAFTBOT_MIRRORS` y los demás de `.env.example`) se pasan al contenedor cuando están definidos en tu shell o en un archivo `.env` junto a `docker-compose.yml`.
- Las Agent Apps se ejecutan en los puertos 3100 a 3199 dentro del contenedor y todavía no se pueden abrir desde el navegador del host. Para trabajar con Agent Apps, usa el instalador o la instalación desde el código fuente.
- Sin Compose:
  ```bash
  docker build -t craftbot .
  docker run -d --name craftbot -p 127.0.0.1:7925:7925 -p 127.0.0.1:7926:7926 --shm-size 1g -v craftbot-data:/data craftbot
  ```

---

## 🤝 Cómo contribuir

¡Los PRs son bienvenidos! Consulta el flujo (fork → rama desde `dev` → PR) en [CONTRIBUTING.md](CONTRIBUTING.md). Todos los pull requests pasan automáticamente por CI de lint + smoke test.

> [!IMPORTANT]
> **CraftBot** se encuentra en desarrollo activo, con mejoras semanales. Si tienes dudas o quieres una conversación más rápida, únete a [Discord](https://discord.gg/ZN9YHc37HG) o escribe a thamyikfoong(at)craftos.net.

---

## 🧾 Licencia

Este proyecto está bajo la [Licencia MIT](LICENSE). Puedes usarlo, hospedarlo y monetizarlo libremente (en caso de distribución o monetización, debes dar crédito a este proyecto).

---

## ⭐ Agradecimientos

Desarrollado y mantenido por [CraftOS](https://craftos.net/) y sus colaboradores.  
Si **CraftBot** te resulta útil, ¡dale una ⭐ al repositorio y compártelo con otros!

---

## Historial de stars

<a href="https://star-history.dera.page/#CraftOS-dev/CraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://star-history.dera.page/svg?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
