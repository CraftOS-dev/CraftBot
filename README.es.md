
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
    <img src="https://img.shields.io/badge/Discord-Unirse%20a%20la%20comunidad-5865F2?logo=discord&logoColor=white" alt="Discord">
  </a>
<br/>
<br/>

[![SPONSORED BY E2B FOR STARTUPS](https://img.shields.io/badge/SPONSORED%20BY-E2B%20FOR%20STARTUPS-ff8800?style=for-the-badge)](https://e2b.dev/startups)

<a href="https://www.producthunt.com/products/craftbot?embed=true&amp;utm_source=badge-top-post-badge&amp;utm_medium=badge&amp;utm_campaign=badge-craftbot" target="_blank" rel="noopener noreferrer"><img alt="CraftBot - Self-hosted proactive AI assistant that lives locally | Product Hunt" width="250" height="54" src="https://api.producthunt.com/widgets/embed-image/v1/top-post-badge.svg?post_id=1110300&amp;theme=dark&amp;period=daily&amp;t=1776679679509"></a>
</div>

<p align="center">
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## 🚀 Descripción general
<h3 align="center">
CraftBot es tu Asistente de IA Personal que vive dentro de tu máquina y trabaja 24/7 para ti.
</h3>

Interpreta tareas de forma autónoma, planifica acciones y las ejecuta para alcanzar tus objetivos.
Aprende tus preferencias y metas, y te ayuda de manera proactiva a planificar e iniciar tareas para cumplir tus objetivos de vida.
Soporta MCP, Skills e integraciones con apps externas.

CraftBot espera tus órdenes. Configura tu propio CraftBot ahora.

<div align="center">
    <img src="assets/craftbot_overview.png" alt="CraftBot Overview" width="1280"/>
</div>

---

## ✨ Características

- **Bring Your Own Key (BYOK)** — Sistema flexible de proveedores de LLM con soporte para OpenAI, Google Gemini, Anthropic Claude, BytePlus y modelos locales de Ollama. Cambia entre proveedores fácilmente.
- **Sistema de Memoria** — Destila y consolida los eventos del día cada medianoche.
- **Agente Proactivo** — Aprende tus preferencias, hábitos y metas de vida. Luego planifica e inicia tareas (con tu aprobación, por supuesto) para ayudarte a mejorar en la vida.
- **Living UI** — Crea, importa o evoluciona aplicaciones personalizadas que viven dentro de CraftBot. El agente es consciente del estado de la UI y puede leer, escribir y actuar sobre sus datos directamente.
- **Integración con herramientas externas** — Conéctate a Google Workspace, Slack, Notion, Zoom, LinkedIn, Discord y Telegram (¡vendrán más!) con credenciales integradas y soporte OAuth.
- **MCP** — Integración con Model Context Protocol para ampliar las capacidades del agente con herramientas y servicios externos.
- **Skills** — Framework de skills extensible con skills integradas para planificación de tareas, investigación, revisión de código, operaciones de git y más.
- **Multiplataforma** — Soporte completo para Windows, macOS y Linux con variantes de código específicas por plataforma y contenedorización con Docker.

> [!IMPORTANT]
> **El modo GUI está obsoleto.** CraftBot ya no admite el modo GUI (automatización de escritorio). Usa en su lugar el modo Browser o CLI.

<div align="center">
    <img src="assets/craftbot_readme_features.png" alt="CraftBot Banner" width="1280"/>
	<img src="assets/craftbot_features_custom.png" alt="CraftBot Banner" width="1280"/>
</div>

---


## 🧰 Primeros pasos

### Requisitos previos
- Python **3.10+**
- `git` (necesario para clonar el repositorio)
- Una clave API del proveedor de LLM que elijas (OpenAI, Gemini o Anthropic)
- `Node.js` **18+** (opcional — solo necesario para la interfaz del navegador)
- `conda` (opcional — si no se encuentra, el instalador ofrece instalar Miniconda automáticamente)

### ¿Qué opción debo elegir?

> **¿No estás seguro? Usa la Opción 1.** Se encarga de todo por ti.

| | Opción 1 — Servicio | Opción 2 — Conda | Opción 3 — Manual |
|---|---|---|---|
| **Para quién** | La mayoría de usuarios, principiantes, pruebas | Usuarios de Conda que quieren entornos aislados | Usuarios avanzados, Python personalizado, control total |
| **¿Gestiona Python/entorno automáticamente?** | ✅ Automático | ✅ Automático | ❌ Lo gestionas tú |
| **¿Corre en segundo plano?** | ✅ Sí, como servicio | ❌ No | ❌ No |
| **Cómo empezar** | `python craftbot.py install` | `python install.py --conda` | `python install.py` |

---

### ⭐ Opción 1 — Instalación como servicio (Recomendada)

**Elige esta si:** quieres que CraftBot simplemente funcione — servicio en segundo plano, inicio automático al arrancar, acceso directo en el escritorio, sin pasos manuales.

`craftbot.py` se encarga de todo: entorno Python, dependencias, gestión de procesos en segundo plano y registro de inicio automático.

```bash
# 1. Clona el repositorio
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Instala, registra el inicio automático y lanza CraftBot
python craftbot.py install
```

Eso es todo. El terminal se cierra solo, CraftBot se ejecuta en segundo plano y el navegador se abre automáticamente. Se crea un **acceso directo en el escritorio** para que puedas abrir el navegador en cualquier momento.

**Gestión del servicio tras la instalación:**

```bash
python craftbot.py start      # Iniciar CraftBot en segundo plano
python craftbot.py stop       # Detener CraftBot
python craftbot.py restart    # Reiniciar CraftBot
python craftbot.py status     # Comprobar si está en ejecución y si el inicio automático está activado
python craftbot.py logs       # Ver el registro reciente
python craftbot.py uninstall  # Detener, quitar inicio automático y desinstalar paquetes
```

> [!TIP]
> Tras `install` o `start`, se crea automáticamente un **acceso directo de CraftBot en el escritorio**. Si cierras el navegador, haz doble clic en el acceso directo para reabrirlo.

---

### Opción 2 — Instalación con Conda

**Elige esta si:** ya usas conda y quieres CraftBot en un entorno conda aislado.

`install.py --conda` configura un entorno conda dedicado `craftbot`. Si no se encuentra Miniconda en tu sistema, se instalará automáticamente.

```bash
# 1. Clona el repositorio
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Instala en un entorno conda
python install.py --conda

# 3. Ejecuta CraftBot
conda run -n craftbot python run.py

# Si conda no está en PATH (solo Windows):
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

> [!NOTE]
> Cada vez que quieras ejecutar CraftBot, usa `conda run -n craftbot python run.py`. No hay servicio en segundo plano — lo inicias y detienes tú mismo.

---

### Opción 3 — Instalación manual (pip)

**Elige esta si:** quieres control total sobre tu entorno Python y prefieres gestionar CraftBot tú mismo, sin servicio automático ni proceso en segundo plano.

`install.py` (sin opciones) hace una instalación pip estándar en el entorno Python activo. Inicias y detienes CraftBot manualmente con `run.py`.

```bash
# 1. Clona el repositorio
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Instala las dependencias en tu entorno Python activo
python install.py

# 3. Ejecuta CraftBot
python run.py
```

La primera ejecución te guiará para configurar tus claves API y preferencias.

> [!NOTE]
> Si Node.js no está instalado, el instalador te ofrecerá instrucciones paso a paso. También puedes omitir completamente el modo navegador y usar el modo CLI — sin Node.js: `python run.py --cli`

### ¿Qué puedes hacer justo después?
- Hablar con el agente de forma natural
- Pedirle que realice tareas complejas de varios pasos
- Escribir `/help` para ver los comandos disponibles
- Conectarte a Google, Slack, Notion y más

### 🖥️ Modos de interfaz

<div align="center">
    <img src="assets/WCA_README_banner.png" alt="CraftOS Banner" width="1280"/>
</div>

CraftBot soporta varios modos de UI. Elige según tu preferencia:

| Modo | Comando | Requisitos | Recomendado para |
|------|---------|--------------|----------|
| **Browser** | `python run.py` | Node.js 18+ | Interfaz web moderna, la más sencilla de usar |
| **CLI** | `python run.py --cli` | Ninguno | Línea de comandos, ligero |

El **modo navegador** es el predeterminado y recomendado. Si no tienes Node.js, el instalador te ofrecerá instrucciones de instalación o puedes usar el **modo CLI** en su lugar.

---

## 🧬 Living UI

**Living UI es un sistema/app/panel que evoluciona con tus necesidades.**

¿Necesitas un tablero kanban con un copiloto de IA integrado? ¿Un CRM personalizado que se
ajuste exactamente a tu flujo de trabajo? ¿Un panel de empresa que CraftBot pueda leer y
manejar por ti? Pon uno en marcha como Living UI: se ejecuta junto a CraftBot y crece a
medida que cambian tus necesidades.

<div align="center">
    <img src="assets/living-ui-example.png" alt="Living UI example" width="1280"/>
</div>

### Tres formas de crear una Living UI

1. **Construir desde cero.** Describe lo que quieres en lenguaje natural. CraftBot
   monta el modelo de datos, la API del backend y la interfaz React, e itera contigo
   a través de un proceso de diseño estructurado.

<div align="center">
    <img src="assets/living-ui-custom-build.png" alt="Building a Living UI from scratch" width="448"/>
</div>

2. **Instalar desde el marketplace.** Explora Living UIs creadas por la comunidad en [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace).

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Living UI marketplace" width="448"/>
</div>

3. **Importar un proyecto existente.** Apunta CraftBot a un código fuente o repositorio
   de GitHub de Go, Node.js, Python, Rust o estático. Detecta el runtime, configura los
   chequeos de salud y lo envuelve como una Living UI.

<div align="center">
    <img src="assets/living-ui-import.png" alt="Importing an existing project as a Living UI" width="448"/>
</div>

### Sigue evolucionando con CraftBot dentro del bucle

Una Living UI nunca está "terminada". Pide al agente que añada funciones, rediseñe
una vista o la conecte con nuevos datos a medida que crecen tus necesidades.

CraftBot está integrado en cada Living UI y es **consciente de su estado**:
puede leer el DOM actual y los valores de los formularios, consultar los datos
de la app mediante la API REST, y disparar acciones en tu nombre.

---

## 🧩 Visión general de la arquitectura

| Componente | Descripción |
|-----------|-------------|
| **Agent Base** | Capa de orquestación central que gestiona el ciclo de vida de las tareas, coordina los componentes y maneja el bucle agente principal. |
| **LLM Interface** | Interfaz unificada que soporta múltiples proveedores LLM (OpenAI, Gemini, Anthropic, BytePlus, Ollama). |
| **Context Engine** | Genera prompts optimizados con soporte de KV-cache. |
| **Action Manager** | Recupera y ejecuta acciones desde la biblioteca. Las acciones personalizadas son fáciles de extender. |
| **Action Router** | Selecciona inteligentemente la acción que mejor se ajusta a los requisitos de la tarea y resuelve los parámetros de entrada mediante el LLM cuando es necesario. |
| **Event Stream** | Sistema de publicación de eventos en tiempo real para seguimiento del progreso de tareas, actualizaciones de UI y monitoreo de ejecución. |
| **Memory Manager** | Memoria semántica basada en RAG con ChromaDB. Gestiona fragmentación de memoria, embeddings, recuperación y actualizaciones incrementales. |
| **State Manager** | Gestión global del estado para rastrear el contexto de ejecución del agente, el historial de conversación y la configuración en tiempo de ejecución. |
| **Task Manager** | Administra definiciones de tareas, habilita modos de tareas simples y complejas, crea todos y hace seguimiento a flujos de trabajo multietapa. |
| **Skill Manager** | Carga e inyecta skills intercambiables en el contexto del agente. |
| **MCP Adapter** | Integración con Model Context Protocol que convierte herramientas MCP en acciones nativas. |

---

## 🔜 Hoja de ruta

- [X] **Módulo de memoria** — Listo.
- [ ] **Integración con herramientas externas** — ¡Seguimos añadiendo más!
- [X] **Capa MCP** — Listo.
- [X] **Capa de Skills** — Listo.
- [ ] **Comportamiento proactivo** — En curso

---

## 📋 Referencia de comandos

### install.py

| Flag | Descripción |
|------|-------------|
| `--conda` | Usa entorno conda (opcional) |

### run.py

| Flag | Descripción |
|------|-------------|
| (ninguno) | Ejecutar en modo **Browser** (recomendado, requiere Node.js) |
| `--cli` | Ejecutar en modo **CLI** (ligero) |

### craftbot.py

| Comando | Descripción |
|---------|-------------|
| `install` | Instala dependencias, registra el autoarranque e inicia CraftBot |
| `start` | Inicia CraftBot en segundo plano |
| `stop` | Detiene CraftBot |
| `restart` | Detener y luego iniciar |
| `status` | Muestra el estado de ejecución y del autoarranque |
| `logs [-n N]` | Muestra las últimas N líneas de log (por defecto: 50) |
| `uninstall` | Elimina el registro de autoarranque |

**Ejemplos de instalación:**
```bash
# Instalación simple con pip (sin conda)
python install.py

# Con entorno conda (recomendado para usuarios de conda)
python install.py --conda
```

**Ejecución de CraftBot:**

```powershell
# Modo navegador (por defecto, requiere Node.js)
python run.py

# Modo CLI (ligero)
python run.py --cli

# Con entorno conda
conda run -n craftbot python run.py

# O usando la ruta completa si conda no está en PATH
&"$env:USERPROFILE\miniconda3\Scripts\conda.exe" run -n craftbot python run.py
```

**Linux/macOS (Bash):**
```bash
# Modo navegador (por defecto, requiere Node.js)
python run.py

# Modo CLI (ligero)
python run.py --cli

# Con entorno conda
conda run -n craftbot python run.py
```

### 🔧 Servicio en segundo plano (recomendado)

Ejecuta CraftBot como un servicio en segundo plano para que siga funcionando incluso después de cerrar la terminal. Se crea automáticamente un acceso directo en el escritorio para reabrir el navegador cuando quieras.

```bash
# Instala dependencias, registra autoarranque al iniciar sesión e inicia CraftBot
python craftbot.py install
```

Eso es todo. La terminal se cierra sola, CraftBot se ejecuta en segundo plano y el navegador se abre automáticamente.

```bash
# Otros comandos del servicio:
python craftbot.py start    # Inicia CraftBot en segundo plano
python craftbot.py status   # Comprueba si está en ejecución
python craftbot.py stop     # Detiene CraftBot
python craftbot.py restart  # Reinicia CraftBot
python craftbot.py logs     # Ver el log reciente
```

| Comando | Descripción |
|---------|-------------|
| `python craftbot.py install` | Instala dependencias, registra autoarranque al iniciar sesión, inicia CraftBot, abre el navegador y cierra la terminal automáticamente |
| `python craftbot.py start` | Inicia CraftBot en segundo plano — se reinicia automáticamente si ya está en ejecución (la terminal se cierra sola) |
| `python craftbot.py stop` | Detiene CraftBot |
| `python craftbot.py restart` | Detiene e inicia CraftBot |
| `python craftbot.py status` | Comprueba si CraftBot está en ejecución y si el autoarranque está habilitado |
| `python craftbot.py logs` | Muestra la salida reciente del log (`-n 100` para más líneas) |
| `python craftbot.py uninstall` | Detiene CraftBot, elimina el registro de autoarranque, desinstala paquetes pip y purga la caché de pip |

> [!TIP]
> Tras `craftbot.py start` o `craftbot.py install`, se crea automáticamente un **acceso directo de CraftBot en el escritorio**. Si cierras el navegador por error, haz doble clic en el acceso directo para reabrirlo.

> [!NOTE]
> **Instalación:** El instalador ahora ofrece orientación clara si faltan dependencias. Si no se encuentra Node.js, se te pedirá instalarlo o podrás cambiar al modo CLI. La instalación detecta automáticamente la disponibilidad de GPU y recurre al modo solo CPU si es necesario.

> [!TIP]
> **Configuración inicial:** CraftBot te guiará por una secuencia de onboarding para configurar claves API, el nombre del agente, MCPs y Skills.

> [!NOTE]
> **Playwright Chromium:** Opcional para la integración con WhatsApp Web. Si falla la instalación, el agente seguirá funcionando para otras tareas. Puedes instalarlo manualmente más tarde con: `playwright install chromium`

---

## 🔧 Solución de problemas y preguntas frecuentes

### Falta Node.js (para el modo navegador)
Si ves **"npm not found in PATH"** al ejecutar `python run.py`:
1. Descárgalo desde [nodejs.org](https://nodejs.org/) (elige la versión LTS)
2. Instálalo y reinicia tu terminal
3. Ejecuta `python run.py` de nuevo

**Alternativa:** Usa el modo CLI (no necesita Node.js):
```bash
python run.py --cli
```

### La instalación falla por dependencias
Ahora el instalador ofrece mensajes de error detallados con soluciones. Si la instalación falla:
- **Revisa la versión de Python:** asegúrate de tener Python 3.10+ (`python --version`)
- **Revisa tu conexión a Internet:** las dependencias se descargan durante la instalación
- **Limpia la caché de pip:** ejecuta `pip install --upgrade pip` e inténtalo de nuevo

### Problemas de instalación de Playwright
La instalación de Playwright Chromium es opcional. Si falla:
- El agente **seguirá funcionando** para otras tareas
- Puedes omitirla o instalarla más tarde: `playwright install chromium`
- Solo es necesaria para la integración con WhatsApp Web

Para una solución de problemas más detallada, consulta [INSTALLATION_FIX.md](INSTALLATION_FIX.md).

---

## 🔌 Integración de servicios externos

El agente puede conectarse a varios servicios usando OAuth. Las builds de release incluyen credenciales integradas, pero también puedes usar las tuyas.

### Inicio rápido

Para builds de release con credenciales integradas:
```
/google login    # Conectar Google Workspace
/zoom login      # Conectar Zoom
/slack invite    # Conectar Slack
/notion invite   # Conectar Notion
/linkedin login  # Conectar LinkedIn
```

### Detalles de los servicios

| Servicio | Tipo de auth | Comando | ¿Requiere secreto? |
|---------|-----------|---------|------------------|
| Google | PKCE | `/google login` | No (PKCE) |
| Zoom | PKCE | `/zoom login` | No (PKCE) |
| Slack | OAuth 2.0 | `/slack invite` | Sí |
| Notion | OAuth 2.0 | `/notion invite` | Sí |
| LinkedIn | OAuth 2.0 | `/linkedin login` | Sí |

### Uso de tus propias credenciales

Si prefieres usar tus propias credenciales OAuth, añádelas a tu archivo `.env`:

#### Google (PKCE — solo se necesita el Client ID)
```bash
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
```
1. Ve a [Google Cloud Console](https://console.cloud.google.com/)
2. Habilita las APIs de Gmail, Calendar, Drive y People
3. Crea credenciales OAuth de tipo **Desktop app**
4. Copia el Client ID (el secreto no es necesario con PKCE)

#### Zoom (PKCE — solo se necesita el Client ID)
```bash
ZOOM_CLIENT_ID=your-zoom-client-id
```
1. Ve a [Zoom Marketplace](https://marketplace.zoom.us/)
2. Crea una app OAuth
3. Copia el Client ID

#### Slack (requiere ambos)
```bash
SLACK_SHARED_CLIENT_ID=your-slack-client-id
SLACK_SHARED_CLIENT_SECRET=your-slack-client-secret
```
1. Ve a [Slack API](https://api.slack.com/apps)
2. Crea una nueva app
3. Añade los scopes OAuth: `chat:write`, `channels:read`, `users:read`, etc.
4. Copia el Client ID y el Client Secret

#### Notion (requiere ambos)
```bash
NOTION_SHARED_CLIENT_ID=your-notion-client-id
NOTION_SHARED_CLIENT_SECRET=your-notion-client-secret
```
1. Ve a [Notion Developers](https://developers.notion.com/)
2. Crea una nueva integración (Public integration)
3. Copia el OAuth Client ID y el Secret

#### LinkedIn (requiere ambos)
```bash
LINKEDIN_CLIENT_ID=your-linkedin-client-id
LINKEDIN_CLIENT_SECRET=your-linkedin-client-secret
```
1. Ve a [LinkedIn Developers](https://developer.linkedin.com/)
2. Crea una app
3. Añade los scopes OAuth 2.0
4. Copia el Client ID y el Client Secret

---
## 🐳 Ejecutar con contenedor

La raíz del repositorio incluye una configuración Docker con Python 3.10, paquetes clave del sistema (incluido Tesseract para OCR) y todas las dependencias de Python definidas en `environment.yml`/`requirements.txt`, de modo que el agente pueda ejecutarse de forma consistente en entornos aislados.

A continuación las instrucciones para ejecutar nuestro agente con contenedor.

### Construir la imagen

Desde la raíz del repositorio:

```bash
docker build -t craftbot .
```

### Ejecutar el contenedor

La imagen está configurada para lanzar el agente con `python -m app.main` por defecto. Para ejecutarlo de forma interactiva:

```bash
docker run --rm -it craftbot
```

Si necesitas suministrar variables de entorno, pasa un archivo env (por ejemplo, basado en `.env.example`):

```bash
docker run --rm -it --env-file .env craftbot
```

Monta cualquier directorio que deba persistir fuera del contenedor (como carpetas de datos o caché) usando `-v`, y ajusta los puertos u otras opciones según lo necesite tu despliegue. La imagen trae dependencias del sistema para OCR (`tesseract`) y clientes HTTP comunes, de modo que el agente pueda trabajar con archivos y APIs de red dentro del contenedor.

Por defecto, la imagen usa Python 3.10 y empaqueta las dependencias de Python de `environment.yml`/`requirements.txt`, así que `python -m app.main` funciona de entrada.

---

## 🤝 Cómo contribuir

¡Las PRs son bienvenidas! Consulta [CONTRIBUTING.md](CONTRIBUTING.md) para el flujo de trabajo (fork → rama desde `dev` → PR). Todas las pull requests pasan automáticamente por CI de lint + smoke-test. Si tienes preguntas o quieres una conversación más rápida, únete a nuestro [Discord](https://discord.gg/ZN9YHc37HG) o escríbenos a thamyikfoong(at)craftos.net.

## 🧾 Licencia

Este proyecto está licenciado bajo la [Licencia MIT](LICENSE). Eres libre de usar, alojar y monetizar este proyecto (debes dar crédito a este proyecto en caso de distribución y monetización).

---

## ⭐ Agradecimientos

Desarrollado y mantenido por [CraftOS](https://craftos.net/) y los contribuyentes [@zfoong](https://github.com/zfoong) y [@ahmad-ajmal](https://github.com/ahmad-ajmal).
Si **CraftBot** te resulta útil, ¡pon una ⭐ al repositorio y compártelo con otras personas!

---

## Star History

<a href="https://www.star-history.com/?repos=CraftOS-dev%2FCraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
