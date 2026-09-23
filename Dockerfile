FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_TIMEOUT=600 \
    PIP_PROGRESS_BAR=off

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
        tesseract-ocr \
        libtesseract-dev \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        scrot \
        xvfb \
        xauth \
        libxi6 \
        libxtst6 \
        x11-apps \
        fonts-dejavu \
        curl \
    && rm -rf /var/lib/apt/lists/*

# The Docker CLI used to be installed here, paired with a bind mount of
# /var/run/docker.sock in docker-compose.yml. Nothing in the codebase ever
# called it: a repo-wide search for `docker exec`, `docker run`, `docker.sock`,
# `DOCKER_HOST` and the docker SDK finds no usage. The socket is the host's
# control plane, so mounting it into a container that executes model-chosen
# shell commands hands that container root on the host. Both are removed; if a
# future feature needs to drive Docker, give it a scoped proxy rather than the
# raw socket.

WORKDIR /app

COPY requirements.txt ./requirements.txt

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --timeout 600 -r requirements.txt

COPY . .

# Run as an unprivileged user. The agent executes commands the model chooses,
# so a container escape or a bad command should not land as root. The UID is
# fixed (not auto-assigned) so a host bind mount can be chowned to match:
#   sudo chown -R 10001:10001 ./workspace
# The directories the compose file bind-mounts are pre-created here so they
# exist with the right owner when no host directory is supplied.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin craftbot \
    && mkdir -p /app/workspace /app/logs \
    && chown -R craftbot:craftbot /app

USER craftbot

CMD ["python", "-m", "app.main"]
