# syntax=docker/dockerfile:1
#
# CraftBot in browser mode.
#
#   docker compose up -d        then open http://localhost:7925
#
# Everything the app needs is installed at build time: Python 3.10 with the
# locked dependency set, Node.js 24, the compiled browser UI, the npm trees,
# PocketBase, Playwright's Chromium and the memory embedding model. A first
# start on a new named volume downloads nothing.
#
# All state lives in /data (a volume): settings and API keys, agent files,
# memory, logs and the user's home directory. The code in /app is replaceable.

# Keep NODE_VERSION on Node 24 or newer (MIN_NODE_MAJOR in app/node_runtime.py).
ARG PYTHON_VERSION=3.10
ARG NODE_VERSION=24.19.0

# ---------------------------------------------------------------------------
# Browser UI: compiled once and served as static files at runtime.
# The output is plain HTML/JS, so this stage runs on the build host's own
# architecture even when the image targets another one.
# ---------------------------------------------------------------------------
FROM --platform=$BUILDPLATFORM node:${NODE_VERSION}-bookworm-slim AS frontend
ARG npm_config_registry
WORKDIR /src/app/ui_layer/browser/frontend
COPY app/ui_layer/browser/frontend/package.json app/ui_layer/browser/frontend/package-lock.json ./
RUN npm install --no-audit --no-fund
COPY app/ui_layer/components/Mascot /src/app/ui_layer/components/Mascot
COPY app/ui_layer/browser/frontend ./
# The default backend port, used when the serving process does not inject
# the live one into index.html (src/utils/connection.ts).
RUN VITE_BACKEND_PORT=7926 npx vite build

# ---------------------------------------------------------------------------
# npm tree for the WhatsApp bridge. The Agent App CLI and its production
# dependencies are bundled under app/vendor/agent-app and unpacked by CraftBot
# into its runtime state directory.
# ---------------------------------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS node-runtime
FROM node-runtime AS node-deps
ARG npm_config_registry
WORKDIR /src/craftos_integrations/providers/whatsapp_web
COPY craftos_integrations/providers/whatsapp_web/package.json craftos_integrations/providers/whatsapp_web/package-lock.json ./
RUN npm install --no-audit --no-fund
# Collect the WhatsApp bridge's node_modules tree, ready to lay over /app.
WORKDIR /src
RUN mkdir /out && find . -name node_modules -prune -exec cp -a --parents {} /out/ \;

# ---------------------------------------------------------------------------
# Runtime image.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm

# CRAFTBOT_HOME        all CraftBot state goes to the /data volume.
# CRAFTBOT_BIND_HOST   listen on every interface inside the container;
#                      docker-compose.yml publishes the ports on the host's
#                      loopback only.
# CRAFTBOT_PYTHON/NODE pin the image's Python 3.10 (in a virtualenv the
#                      runtime user owns, so the agent can still pip install
#                      an action's missing package) and Node, so CraftBot
#                      never downloads private copies.
# PLAYWRIGHT_BROWSERS_PATH, AGENT_APP_PB_CACHE
#                      Chromium and PocketBase, baked in at build time below.
# HOME                 caches and per-user files land in the volume and
#                      survive image rebuilds.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/venv/bin:$PATH \
    CRAFTBOT_HOME=/data \
    CRAFTBOT_BIND_HOST=0.0.0.0 \
    CRAFTBOT_PYTHON=/opt/venv/bin/python \
    CRAFTBOT_NODE=/usr/local/bin/node \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    AGENT_APP_PB_CACHE=/opt/craftbot/pocketbase \
    HOME=/data/home

# System packages: tini (PID 1, forwards signals), git and curl (the agent's
# shell work and Agent App imports), tesseract (OCR), libgomp1 and libglib
# (native wheels). The X11/GUI packages are gone with GUI mode (V1.2.2).
#
# The Docker CLI and a bind mount of /var/run/docker.sock used to be here.
# Nothing in the codebase calls Docker, and the socket is the host's control
# plane: mounting it into a container that runs model-chosen commands hands
# that container root on the host. If a future feature needs Docker, give it
# a scoped proxy rather than the raw socket.
#
# Not version-pinned: the Debian release is fixed by the base image, and a
# pin breaks the build as soon as the archive publishes a security update.
ARG DEBIAN_FRONTEND=noninteractive
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        fonts-dejavu-core \
        git \
        libglib2.0-0 \
        libgomp1 \
        tesseract-ocr \
        tini \
    && rm -rf /var/lib/apt/lists/*

# Node.js 24 and its npm, from the official image of the pinned version.
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && node --version && npm --version

# Unprivileged runtime user. The agent executes commands the model chooses,
# so a bad command or an escape should not land as root. The UID is fixed so
# a host directory used instead of the named volume can be chowned to match:
#   sudo chown -R 10001:10001 /path/to/craftbot-data
# /data is created here with this owner: a named volume is seeded from it on
# first use.
RUN groupadd --gid 10001 craftbot \
    && useradd --uid 10001 --gid 10001 --home-dir /data/home --no-create-home \
        --shell /usr/sbin/nologin craftbot \
    && mkdir -p /app /data/home /opt/venv /opt/craftbot/pocketbase \
    && chown craftbot:craftbot /app /data /data/home /opt/venv /opt/craftbot/pocketbase

# Python dependencies from the committed lock for this architecture: the same
# hash-pinned closure every other install path uses (app/provision/deps.py).
# pip itself is pinned first, because the pip version decides how a lock is
# read (requirements/pip-bootstrap.txt).
USER 10001:10001
ARG PIP_INDEX_URL
COPY --chown=10001:10001 requirements/ /tmp/requirements/
RUN set -eu; \
    case "$(uname -m)" in \
        x86_64) plat=linux_x86_64 ;; \
        aarch64|arm64) plat=linux_aarch64 ;; \
        *) echo "CraftBot has no dependency lock for $(uname -m)." >&2; exit 1 ;; \
    esac; \
    /usr/local/bin/python3 -m venv /opt/venv; \
    py="$(python -c 'import sys; print("py%d%d" % sys.version_info[:2])')"; \
    lock="/tmp/requirements/lock-${plat}-${py}.txt"; \
    if [ ! -f "$lock" ]; then \
        echo "Missing requirements/lock-${plat}-${py}.txt. Generate it with scripts/generate_lock.py." >&2; \
        exit 1; \
    fi; \
    python -m pip install --no-cache-dir --require-hashes --no-deps -r /tmp/requirements/pip-bootstrap.txt; \
    python -m pip install --no-cache-dir --require-hashes --no-deps -r "$lock"; \
    rm -rf /tmp/requirements

# Chromium for the Mini Browser and browser automation, with the system
# libraries it needs (that part requires root, so it cannot happen at runtime).
USER 0:0
RUN HOME=/root python -m playwright install --with-deps chromium \
    && chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH" \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=node-deps --chown=craftbot:craftbot /out/ /app/
COPY --chown=craftbot:craftbot . /app/
COPY --from=frontend --chown=craftbot:craftbot /src/app/ui_layer/browser/frontend/dist /app/app/ui_layer/browser/frontend/dist

USER 10001:10001

# Mark /app as a managed install (code here, state in CRAFTBOT_HOME), so the
# prebuilt UI is served as-is rather than rebuilt (app/paths.py, run.py).
# Then run the real install pipeline once. Everything above already satisfies
# most of it; what is left is fetched into the image: PocketBase (into
# AGENT_APP_PB_CACHE) and the memory embedding model (into /data/runtime,
# which seeds a new named volume). A failure fails the build, not the first
# start. The image id lets the entrypoint skip this check on later starts.
RUN python -c "from app.paths import mark_managed_install; mark_managed_install('/app')" \
    && printf '{\n    "use_conda": false,\n    "gui_mode_enabled": false\n}\n' > /app/config.json \
    && mkdir -p /tmp/craftbot-build-home \
    && HOME=/tmp/craftbot-build-home python install.py --no-launch < /dev/null \
    && rm -rf /tmp/craftbot-build-home \
    && cat /proc/sys/kernel/random/uuid > /app/.craftbot-image-id \
    && cp /app/.craftbot-image-id /data/.craftbot-image-id

EXPOSE 7925 7926
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.build_opener(u.ProxyHandler({})).open('http://localhost:7925', timeout=8)"]

ENTRYPOINT ["tini", "-g", "--", "python", "/app/docker/entrypoint.py"]
CMD []
