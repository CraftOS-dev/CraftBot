
# Getting started

This page walks you through installing and running **CraftBot** locally (Conda) or via Docker.

---

## Prerequisites

- Python 3.9+
- `git`, `conda`, and `pip`
- An API key for your chosen LLM provider (OpenAI or Gemini)

---

## Run locally (Conda)

### 1) Clone the repository

```bash
git clone https://github.com/zfoong/CraftBot.git
cd CraftBot
````

### 2) Create the Conda environment

```bash
conda env create -f environment.yml
```

### 3) Activate the environment

If you’re not sure what the environment is called, list them and activate the one created from `environment.yml`:

```bash
conda env list
conda activate <ENV_NAME>
```

### 4) Set your API key

Pick one provider:

```bash
export OPENAI_API_KEY="<YOUR_KEY_HERE>"
```

or:

```bash
export GOOGLE_API_KEY="<YOUR_KEY_HERE>"
```

### 5) Start the agent (CLI)

```bash
python -m app.main
```

Once it launches, you can:

* chat with the agent,
* ask it to perform tasks,
* run `/help` inside the interface to see available commands.

---

## Run with Docker

### 1) Build the image

From the repository root:

```bash
docker build -t craftbot .
```

### 2) Run the container

Run interactively:

```bash
docker run --rm -it craftbot
```

If you want to supply environment variables via a file (for example, based on `.env.example`):

```bash
cp .env.example .env
docker run --rm -it --env-file .env craftbot
```

### 3) Enable GUI / screen automation (optional)

GUI actions (mouse/keyboard events, screenshots) require an X11 server. Choose one approach:

**A) Use the host display (Linux + X11)**

```bash
docker run --rm -it \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $(pwd)/data:/app/app/data \
  craftbot
```

**B) Run headlessly with a virtual display (Xvfb)**

```bash
docker run --rm -it --env-file .env craftbot \
  bash -lc "Xvfb :99 -screen 0 1920x1080x24 & export DISPLAY=:99 && exec python -m app.main"
```

---

## Notes

* GUI mode is experimental, so expect issues if/when the agent decides to switch to GUI mode.
* If you run into setup problems, double-check:

  * your environment is activated,
  * your API key is set,
  * you’re launching with `python -m app.main`.

