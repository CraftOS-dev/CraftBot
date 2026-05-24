<div align="center">
    <a href="https://www.youtube.com/watch?v=8GpdW-gJrDA&autoplay=1" target="_blank">
        <img src="https://img.youtube.com/vi/8GpdW-gJrDA/maxresdefault.jpg" alt="CraftBot Demo Video" width="1280"/>
    </a>
</div>

<div align="center">
    <img src="assets/craftbot_logo_text_small.png" alt="CraftBot" width="400"/>
</div>

La mayoría de los agentes se quedan en el chat y las llamadas a herramientas. CraftBot va más allá: construye, hace evolucionar y opera sus propias herramientas SaaS, y luego usa esa capa de herramientas para comunicarse contigo y automatizar tu trabajo.

Además de eso, CraftBot incluye todas las capacidades de un agente de propósito general. Ejecuta tareas como lo haría un empleado remoto, recuerda tus preferencias y objetivos, y te ayuda de forma proactiva a planificar y actuar sobre lo que más te importa.

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
</p>

<div align="center">
	
[![SPONSORED BY E2B FOR STARTUPS](https://img.shields.io/badge/SPONSORED%20BY-E2B%20FOR%20STARTUPS-ff8800?style=for-the-badge)](https://e2b.dev/startups)
</div>

<p align="center" style="display: inline-block">
<a href="https://www.producthunt.com/products/craftbot?embed=true&amp;utm_source=badge-top-post-badge&amp;utm_medium=badge&amp;utm_campaign=badge-craftbot" target="_blank" rel="noopener noreferrer" style="display: inline-block">
	<img alt="CraftBot - Self-hosted proactive AI assistant that lives locally | Product Hunt" width="250" height="54" src="https://api.producthunt.com/widgets/embed-image/v1/top-post-badge.svg?post_id=1110300&amp;theme=dark&amp;period=daily&amp;t=1776679679509">
</a>
<a href="https://theresanaiforthat.com/ai/craftbot/?ref=featured&v=10277523" target="_blank" rel="nofollow"><img width="265" src="https://media.theresanaiforthat.com/featured-on-taaft.png?width=600"></a>
</p>

<p align="center">
  <a href="README.md">English</a> | <a href="README.ja.md">日本語</a> | <a href="README.cn.md">简体中文</a> | <a href="README.zh-TW.md">繁體中文</a> | <a href="README.ko.md">한국어</a> | <a href="README.pt-BR.md">Português</a> | <a href="README.fr.md">Français</a> | <a href="README.de.md">Deutsch</a>
</p>

## ✨ Características destacadas

Más allá de ser un agente de IA capaz de crear y operar sus propias herramientas SaaS, CraftBot incluye todas las capacidades básicas de un agente, lo que le permite funcionar como un agente de propósito general que te acompaña en tus tareas, herramientas, memoria y flujos de trabajo diarios.

- **Living UI.** Crea, importa o haz evolucionar aplicaciones personalizadas que viven dentro de CraftBot. El agente conoce en todo momento el estado de la UI y puede leer, escribir y actuar directamente sobre sus datos.
- **Multitarea y enrutamiento de sesiones.** ¿Sigues escribiendo `/new` a mano? CraftBot decide cuándo iniciar una nueva sesión y cuándo retomar una tarea existente, manteniendo unificados la conversación y el contexto.
- **Autohospedado y BYOK.** Sistema flexible de proveedores LLM compatible con OpenAI, Google Gemini, Anthropic Claude, OpenRouter y más. O aloja tu propio modelo sin gastar tokens usando Ollama.
- **Sistema de memoria.** Base de conocimiento local construida a partir de tu interacción con CraftBot mediante RAG + sistema de archivos del agente + destilación. CraftBot "sueña" a medianoche y consolida los eventos del día.
- **Agente proactivo.** Aprende tus preferencias, hábitos y objetivos de vida. Luego planifica e inicia tareas (con tu aprobación, por supuesto) para ayudarte a mejorar.
- **Integración con herramientas externas.** Conecta con Google Workspace, Slack, Notion, Zoom, LinkedIn, Discord y Telegram (¡y vienen más!), con credenciales embebidas y soporte para OAuth.
- **Skills y MCP.** Más de 150 MCP y 170 Skills listos para usar. Instalación rápida de nuevas Skills y MCPs. Crea o mejora Skills a partir de tareas completadas con un solo clic.
- **Multiplataforma.** Compatibilidad completa con Windows, macOS y Linux, con variantes de código específicas por plataforma y contenedorización Docker.
- **Interfaz de navegador y soporte de CLI.** Usa CraftBot como mejor te encaje: con una UI de navegador sencilla para el día a día, o desde la CLI para scripting y entornos headless.

---

## 🧰 Primeros pasos

Requisitos: Python 3.10+ · Node.js 18+ para el modo navegador

```bash
# 1. Clona el repositorio
git clone https://github.com/CraftOS-dev/CraftBot.git
cd CraftBot

# 2. Instala, registra el autoinicio y lanza CraftBot
python craftbot.py install
```

Eso es todo. La terminal se cierra sola, CraftBot queda corriendo en segundo plano y el navegador se abre automáticamente. Además se crea un **acceso directo en el escritorio** para que puedas reabrir el navegador cuando quieras.

**Gestión del servicio tras la instalación:**

```bash
python craftbot.py start      # Inicia CraftBot en segundo plano
python craftbot.py stop       # Detiene CraftBot
python craftbot.py restart    # Reinicia CraftBot
python craftbot.py status     # Comprueba si está corriendo y si el autoinicio está activo
python craftbot.py logs       # Muestra la salida reciente de logs
python craftbot.py uninstall  # Detiene, quita el autoinicio y desinstala los paquetes
```

> [!TIP]
> Tras `install` o `start` se crea automáticamente un **acceso directo de CraftBot en el escritorio**. Si cierras el navegador, basta con hacer doble clic en él para volver a abrirlo.

---

## 🌱 Living UI

**Living UI es un sistema/app/dashboard que evoluciona con tus necesidades.**

- ¿Necesitas un tablero kanban con un copiloto de IA incorporado?
- ¿Un CRM a medida que encaje exactamente con tu flujo de trabajo?
- ¿Un dashboard corporativo que CraftBot pueda leer y operar por ti?

Móntalo como una Living UI que corre junto a CraftBot y crece según tus necesidades cambian.

<div align="center">
    <img src="assets/living-ui-example.png" alt="Living UI example" width="1280"/>
</div>

### Tres formas de crear una Living UI

1. **Construir desde cero.** Describe en lenguaje natural lo que quieres. CraftBot
   genera el modelo de datos, la API de backend y la UI en React, y luego itera
   contigo a través de un proceso de diseño estructurado.

<div align="center">
    <img src="assets/living-ui-custom-build.png" alt="Building a Living UI from scratch" width="448"/>
</div>

2. **Instalar desde el marketplace.** Explora las Living UIs creadas por la comunidad en [living-ui-marketplace](https://github.com/CraftOS-dev/living-ui-marketplace).

<div align="center">
    <img src="assets/living-ui-marketplace.png" alt="Living UI marketplace" width="448"/>
</div>

3. **Importar un proyecto existente.** Indícale a CraftBot un proyecto en Go, Node.js, Python,
   Rust, o código estático o un repositorio de GitHub. Detecta el runtime, configura los health checks y lo envuelve como una Living UI.

<div align="center">
    <img src="assets/living-ui-import.png" alt="Importing an existing project as a Living UI" width="448"/>
</div>

### Sigue evolucionando con CraftBot dentro del bucle

Una Living UI nunca está "terminada". Pídele al agente que añada funciones, rediseñe
una vista o la conecte con nuevos datos según tus necesidades cambien.

CraftBot está embebido en cada Living UI y es **consciente de su estado**:
puede leer el DOM y los valores de los formularios, consultar los datos de la app a través de la
API REST y disparar acciones en tu nombre.

### Mantén las herramientas SaaS abiertas y vivas

Construye, personaliza y haz evolucionar tu propia Living UI, y depende menos de herramientas por suscripción que nunca se diseñaron para encajar perfectamente con tus necesidades.

Estamos buscando activamente desarrolladores que muestren sus Living UIs y las exporten al **[marketplace de Living UI](https://craftos.net/marketplace)**. ¡Los PRs son bienvenidos!

---
 
# Tres Living UIs que puedes probar en 5 minutos
 
- **📋 Tablero Kanban** — Cada tarea, seguimiento y CTA en un solo lugar. CraftBot puede manejarlo para hacer el trabajo de PM por ti.
- **📊 Habit Tracker** — Desarrolla y mantén tus hábitos. Un calendario de actividad al estilo GitHub para seguir tus hábitos como un desarrollador.
- **🐦 Luolinglo** — No es Duolingo, pero puedes aprender nuevos idiomas, crear flashcards y practicar con CraftBot.

**[Explora y contribuye al marketplace de Living UI →](https://craftos.net/marketplace)**

---
 
# CraftBot frente a las alternativas
 
|                                  | v0 / Lovable / Bolt | OpenClaw | Claude Code | **CraftBot**                            |
| -------------------------------- | ------------------- | -------------------- | -------------------- | --------------------------------------- |
| **Construye apps personalizadas**           | ✅ De un tirón         | 🚫                   | ✅ (manual)          | ✅ Conversacional                       |
| **El agente opera la app**       | 🚫                  | ⚠️ Llamando a herramientas      | 🚫                   | ✅ Embebido en cada Living UI         |
| **Memoria persistente del agente**      | 🚫                  | ✅            | ✅                   | ✅ RAG + sistema de archivos del agente + destilación        |
| **Autohospedable**     | ⚠️ Parcial         | ✅                   | 🚫 SaaS              | ✅ MIT, en tu propia máquina                    |
| **Independiente del modelo**     | ✅         | ✅                   | ⚠️ Parcial              | ✅ Principales proveedores + OpenRouter                    |
 
---

## 🔧 Solución de problemas y dudas comunes

### Falta Node.js (para el modo navegador)
Si al ejecutar `python run.py` ves **"npm not found in PATH"**:
1. Descarga la versión LTS desde [nodejs.org](https://nodejs.org/)
2. Instálala y reinicia la terminal
3. Vuelve a ejecutar `python run.py`

**Alternativa:** Usa el modo TUI, que no requiere Node.js:
```bash
python run.py --tui
```

### La instalación falla por dependencias
El instalador ahora muestra mensajes de error detallados con posibles soluciones. Si falla:
- **Comprueba la versión de Python:** asegúrate de tener Python 3.10+ (`python --version`)
- **Comprueba la conexión a internet:** las dependencias se descargan durante la instalación
- **Limpia la caché de pip:** ejecuta `pip install --upgrade pip` y vuelve a intentarlo

### Problemas al instalar Playwright
La instalación de Chromium de Playwright es opcional. Si falla:
- El agente **seguirá funcionando** para el resto de tareas
- Puedes saltártelo e instalarlo más tarde con `playwright install chromium`
- Solo es necesario para la integración con WhatsApp Web

Para una solución de problemas más detallada, consulta [INSTALLATION_FIX.md](INSTALLATION_FIX.md).

---
## 🐳 Ejecutar con un contenedor

La raíz del repositorio incluye una configuración Docker con Python 3.10, los paquetes de sistema clave (incluido Tesseract para OCR) y todas las dependencias de Python definidas en `environment.yml`/`requirements.txt`, de modo que el agente puede ejecutarse de forma consistente en entornos aislados.

A continuación tienes las instrucciones para correr nuestro agente con un contenedor.

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

Si necesitas pasar variables de entorno, usa un archivo env (por ejemplo, basado en `.env.example`):

```bash
docker run --rm -it --env-file .env craftbot
```

Monta con `-v` los directorios que deban persistir fuera del contenedor (por ejemplo carpetas de datos o caché) y ajusta puertos u otros parámetros según tu despliegue. La imagen trae dependencias del sistema para OCR (`tesseract`) y clientes HTTP habituales, de modo que el agente pueda trabajar con archivos y APIs de red dentro del contenedor.

Por defecto, la imagen usa Python 3.10 y empaqueta las dependencias de Python de `environment.yml`/`requirements.txt`, así que `python -m app.main` funciona sin más.

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
Si **CraftBot** te resulta útil, dale una ⭐ al repositorio y compártelo.

---

## Historial de stars

<a href="https://www.star-history.com/?repos=CraftOS-dev%2FCraftBot&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=CraftOS-dev/CraftBot&type=date&legend=top-left" />
 </picture>
</a>
