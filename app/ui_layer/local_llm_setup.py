# -*- coding: utf-8 -*-
"""Local LLM setup utilities for Ollama."""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import socket
import subprocess
import urllib.error
import urllib.request
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)

OLLAMA_DEFAULT_URL = "http://localhost:11434"

SUGGESTED_MODELS = [
    # ── Llama ──────────────────────────────────────────────────────────────
    {
        "name": "llama3.2:1b",
        "label": "Llama 3.2 1B",
        "size": "~1 GB",
        "recommended": False,
    },
    {
        "name": "llama3.2:3b",
        "label": "Llama 3.2 3B",
        "size": "~2 GB",
        "recommended": True,
    },
    {
        "name": "llama3.1:8b",
        "label": "Llama 3.1 8B",
        "size": "~5 GB",
        "recommended": False,
    },
    # ── Phi ────────────────────────────────────────────────────────────────
    {
        "name": "phi4-mini",
        "label": "Phi-4 Mini",
        "size": "~2.5 GB",
        "recommended": False,
    },
    {"name": "phi4", "label": "Phi-4", "size": "~9 GB", "recommended": False},
    # ── Gemma ──────────────────────────────────────────────────────────────
    {"name": "gemma3:1b", "label": "Gemma 3 1B", "size": "~1 GB", "recommended": False},
    {"name": "gemma3:4b", "label": "Gemma 3 4B", "size": "~3 GB", "recommended": False},
    {
        "name": "gemma3:12b",
        "label": "Gemma 3 12B",
        "size": "~8 GB",
        "recommended": False,
    },
    {
        "name": "gemma3:27b",
        "label": "Gemma 3 27B",
        "size": "~17 GB",
        "recommended": False,
    },
    # ── Qwen ───────────────────────────────────────────────────────────────
    {
        "name": "qwen3:0.6b",
        "label": "Qwen 3 0.6B",
        "size": "~0.5 GB",
        "recommended": False,
    },
    {
        "name": "qwen3:1.7b",
        "label": "Qwen 3 1.7B",
        "size": "~1 GB",
        "recommended": False,
    },
    {"name": "qwen3:4b", "label": "Qwen 3 4B", "size": "~3 GB", "recommended": False},
    {"name": "qwen3:8b", "label": "Qwen 3 8B", "size": "~5 GB", "recommended": False},
    {"name": "qwen3:14b", "label": "Qwen 3 14B", "size": "~9 GB", "recommended": False},
    {
        "name": "qwen3:30b",
        "label": "Qwen 3 30B",
        "size": "~18 GB",
        "recommended": False,
    },
    {
        "name": "qwen3-coder:4b",
        "label": "Qwen 3 Coder 4B",
        "size": "~3 GB",
        "recommended": False,
    },
    {
        "name": "qwen3-coder:8b",
        "label": "Qwen 3 Coder 8B",
        "size": "~5 GB",
        "recommended": False,
    },
    # ── Mistral ────────────────────────────────────────────────────────────
    {
        "name": "mistral:7b",
        "label": "Mistral 7B",
        "size": "~4 GB",
        "recommended": False,
    },
    {
        "name": "mistral-nemo",
        "label": "Mistral Nemo 12B",
        "size": "~7 GB",
        "recommended": False,
    },
    # ── DeepSeek ───────────────────────────────────────────────────────────
    {
        "name": "deepseek-r1:1.5b",
        "label": "DeepSeek R1 1.5B",
        "size": "~1 GB",
        "recommended": False,
    },
    {
        "name": "deepseek-r1:7b",
        "label": "DeepSeek R1 7B",
        "size": "~4 GB",
        "recommended": False,
    },
    {
        "name": "deepseek-r1:8b",
        "label": "DeepSeek R1 8B",
        "size": "~5 GB",
        "recommended": False,
    },
    {
        "name": "deepseek-r1:14b",
        "label": "DeepSeek R1 14B",
        "size": "~9 GB",
        "recommended": False,
    },
    {
        "name": "deepseek-r1:32b",
        "label": "DeepSeek R1 32B",
        "size": "~20 GB",
        "recommended": False,
    },
    # ── Code models ────────────────────────────────────────────────────────
    {
        "name": "codellama:7b",
        "label": "Code Llama 7B",
        "size": "~4 GB",
        "recommended": False,
    },
    {
        "name": "codellama:13b",
        "label": "Code Llama 13B",
        "size": "~8 GB",
        "recommended": False,
    },
    {
        "name": "starcoder2:3b",
        "label": "StarCoder2 3B",
        "size": "~2 GB",
        "recommended": False,
    },
    {
        "name": "starcoder2:7b",
        "label": "StarCoder2 7B",
        "size": "~4 GB",
        "recommended": False,
    },
    # ── Multimodal ─────────────────────────────────────────────────────────
    {
        "name": "llava:7b",
        "label": "LLaVA 7B (vision)",
        "size": "~4 GB",
        "recommended": False,
    },
    {
        "name": "llava:13b",
        "label": "LLaVA 13B (vision)",
        "size": "~8 GB",
        "recommended": False,
    },
    # ── Other ──────────────────────────────────────────────────────────────
    {
        "name": "orca-mini:3b",
        "label": "Orca Mini 3B",
        "size": "~2 GB",
        "recommended": False,
    },
    {"name": "vicuna:7b", "label": "Vicuna 7B", "size": "~4 GB", "recommended": False},
    {
        "name": "openchat:7b",
        "label": "OpenChat 7B",
        "size": "~4 GB",
        "recommended": False,
    },
    {
        "name": "neural-chat:7b",
        "label": "Neural Chat 7B",
        "size": "~4 GB",
        "recommended": False,
    },
    {
        "name": "dolphin-phi:2.7b",
        "label": "Dolphin Phi 2.7B",
        "size": "~2 GB",
        "recommended": False,
    },
]


def check_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """Check if a TCP port is open."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def get_ollama_status() -> Dict[str, Any]:
    """Return Ollama installation and runtime status."""
    installed = False
    version = None

    try:
        result = subprocess.run(
            ["ollama", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            installed = True
            version = result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    running = check_port_open("localhost", 11434)

    return {
        "installed": installed,
        "running": running,
        "version": version,
        "default_url": OLLAMA_DEFAULT_URL,
    }


def test_ollama_connection_sync(url: str) -> Dict[str, Any]:
    """Test an HTTP connection to an Ollama instance (synchronous)."""
    try:
        tags_url = url.rstrip("/") + "/api/tags"
        with urllib.request.urlopen(tags_url, timeout=5) as resp:
            data = json.loads(resp.read())
        models = [m["name"] for m in data.get("models", [])]
        if models:
            msg = f"Connected! {len(models)} model(s) available."
        else:
            msg = "Connected! No models downloaded yet — run 'ollama pull llama3' to get one."
        return {"success": True, "models": models, "message": msg}
    except urllib.error.URLError as exc:
        return {"success": False, "error": f"Cannot connect: {exc.reason}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def install_ollama(progress_callback: Callable) -> Dict[str, Any]:
    """Install Ollama for the current platform, streaming progress via callback."""
    system = platform.system()

    try:
        if system == "Windows":
            # Try winget first
            await progress_callback("Checking for winget...")
            try:
                proc = await asyncio.create_subprocess_exec(
                    "winget",
                    "install",
                    "--id",
                    "Ollama.Ollama",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                    "--silent",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await progress_callback(
                    "Installing Ollama via winget (this may take a minute)..."
                )

                # Stream winget output line-by-line so the UI doesn't appear frozen.
                # winget writes useful lines like "Downloading …", "Verifying …",
                # "Starting package install…" which we surface directly.
                async def _stream_winget(stream: asyncio.StreamReader) -> None:
                    while True:
                        line = await stream.readline()
                        if not line:
                            break
                        text = line.decode("utf-8", errors="replace").strip()
                        # Skip blank lines and raw progress-bar characters
                        if text and not set(text).issubset(set("█▓░▒ \t\r")):
                            await progress_callback(text[:120])

                await asyncio.gather(
                    _stream_winget(proc.stdout),
                    _stream_winget(proc.stderr),
                )
                await proc.wait()

                # Verify actual install regardless of exit code — winget can return non-zero on success
                if get_ollama_status()["installed"]:
                    subprocess.run(
                        ["taskkill", "/F", "/IM", "ollama app.exe", "/T"],
                        capture_output=True,
                    )
                    await progress_callback("Ollama installed successfully!")
                    return {"success": True, "message": "Ollama installed via winget"}
                await progress_callback(
                    "winget install failed, switching to direct download..."
                )
            except FileNotFoundError:
                await progress_callback(
                    "winget not found — downloading installer directly..."
                )

            # Direct download fallback
            import os

            tmp = os.environ.get("TEMP", os.getcwd())
            installer_path = os.path.join(tmp, "OllamaSetup.exe")
            installer_url = "https://ollama.com/download/OllamaSetup.exe"

            await progress_callback("Downloading Ollama installer from ollama.com...")
            dl_proc = await asyncio.create_subprocess_exec(
                "powershell",
                "-Command",
                f"Invoke-WebRequest -Uri '{installer_url}' -OutFile '{installer_path}' -UseBasicParsing",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Stream PowerShell output so download progress is visible
            async def _stream_ps(stream: asyncio.StreamReader) -> None:
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").strip()
                    if text:
                        await progress_callback(text[:120])

            await asyncio.gather(
                _stream_ps(dl_proc.stdout),
                _stream_ps(dl_proc.stderr),
            )
            await dl_proc.wait()
            if dl_proc.returncode != 0:
                return {"success": False, "error": "Installer download failed"}

            await progress_callback("Running installer silently...")
            run_proc = await asyncio.create_subprocess_exec(
                installer_path,
                "/S",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await run_proc.communicate()
            if get_ollama_status()["installed"]:
                subprocess.run(
                    ["taskkill", "/F", "/IM", "ollama app.exe", "/T"],
                    capture_output=True,
                )
                await progress_callback("Ollama installed successfully!")
                return {"success": True, "message": "Ollama installed"}
            return {
                "success": False,
                "error": "Installer ran but Ollama was not detected",
            }

        elif system in ("Darwin", "Linux"):
            await progress_callback("Downloading Ollama install script...")
            proc = await asyncio.create_subprocess_exec(
                "sh",
                "-c",
                "curl -fsSL https://ollama.com/install.sh | sh",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            # Stream stdout lines as progress
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if text:
                    await progress_callback(text[:120])

            await proc.wait()
            if proc.returncode == 0:
                await progress_callback("Ollama installed successfully!")
                return {"success": True}
            else:
                return {
                    "success": False,
                    "error": "Install script exited with an error",
                }

        else:
            return {"success": False, "error": f"Unsupported platform: {system}"}

    except Exception as exc:
        logger.exception("Error installing Ollama")
        return {"success": False, "error": str(exc)}


async def start_ollama() -> Dict[str, Any]:
    """Start the Ollama server in the background and wait for it to become ready."""
    try:
        kwargs: Dict[str, Any] = {
            "stdout": asyncio.subprocess.DEVNULL,
            "stderr": asyncio.subprocess.DEVNULL,
        }
        if platform.system() == "Windows":
            kwargs["creationflags"] = 0x00000008  # DETACHED_PROCESS

        await asyncio.create_subprocess_exec("ollama", "serve", **kwargs)

        # Poll until ready (max 15 seconds)
        for _ in range(15):
            await asyncio.sleep(1)
            if check_port_open("localhost", 11434):
                return {"success": True, "message": "Ollama started successfully"}

        return {
            "success": False,
            "error": "Ollama started but not responding on port 11434",
        }

    except FileNotFoundError:
        return {
            "success": False,
            "error": "Ollama executable not found — is it installed?",
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def pull_ollama_model(
    model: str, progress_callback: Callable, base_url: str | None = None
) -> Dict[str, Any]:
    """Pull an Ollama model via REST API, streaming structured progress via callback.

    Uses a background thread so the asyncio event loop stays unblocked and no
    asyncio.timeout() issues occur (Python 3.11 + aiohttp compatibility).

    Each progress_callback call receives a dict with:
      message   – current status string
      total     – total bytes (0 if unknown)
      completed – bytes downloaded so far
      percent   – 0-100 integer
    """
    import queue
    import threading
    import urllib.request as _ureq

    ollama_url = (base_url or OLLAMA_DEFAULT_URL).rstrip("/")
    pull_url = ollama_url + "/api/pull"
    payload = json.dumps({"name": model, "stream": True}).encode()

    line_queue: "queue.Queue[str | Exception | None]" = queue.Queue()

    def _pull_thread() -> None:
        try:
            req = _ureq.Request(
                pull_url,
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with _ureq.urlopen(req) as resp:
                for raw in resp:
                    line_queue.put(raw.decode(errors="replace").strip())
            line_queue.put(None)  # sentinel — done
        except Exception as exc:
            line_queue.put(exc)

    thread = threading.Thread(target=_pull_thread, daemon=True)
    thread.start()

    try:
        while True:
            try:
                item = line_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)
                continue

            if item is None:
                break
            if isinstance(item, Exception):
                return {"success": False, "error": str(item)}

            line = str(item).strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            status = obj.get("status", "")
            total = obj.get("total", 0) or 0
            completed = obj.get("completed", 0) or 0
            percent = int(completed / total * 100) if total > 0 else 0
            await progress_callback(
                {
                    "message": status,
                    "total": total,
                    "completed": completed,
                    "percent": percent,
                }
            )
            if status == "success":
                break

        thread.join(timeout=5)
        return {"success": True, "model": model}

    except Exception as exc:
        logger.exception("Error pulling model %s", model)
        return {"success": False, "error": str(exc)}
