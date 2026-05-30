
# Getting started

This page walks you through installing and running **CraftBot** locally.

---

## Prerequisites

- Python 3.9+
- `git` and `pip`
- An API key for your chosen LLM provider (OpenAI or Gemini)

---

## Run locally

### 1) Clone the repository

```bash
git clone https://github.com/zfoong/CraftBot.git
cd CraftBot
````

### 2) Install dependencies

```bash
python install.py
```

### 3) Set your API key

Pick one provider:

```bash
export OPENAI_API_KEY="<YOUR_KEY_HERE>"
```

or:

```bash
export GOOGLE_API_KEY="<YOUR_KEY_HERE>"
```

### 4) Start the agent (CLI)

```bash
python -m app.main
```

Once it launches, you can:

* chat with the agent,
* ask it to perform tasks,
* run `/help` inside the interface to see available commands.

---

## Notes

* If you run into setup problems, double-check:

  * dependencies are installed (`python install.py`),
  * your API key is set,
  * you’re launching with `python -m app.main`.

