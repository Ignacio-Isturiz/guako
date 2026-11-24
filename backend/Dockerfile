FROM python:3.12-slim

# No .pyc files, unbuffered logs (so `docker logs` shows output immediately)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ffmpeg converts the browser's webm/opus recordings to the WAV 16 kHz mono that Azure Speech
# (pronunciation assessment) accepts. No recommended packages, apt lists removed: keeps the layer small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Unprivileged user: a compromised process can't act as root inside the container
RUN groupadd --system app && useradd --system --gid app --no-create-home app

# Writable data (turn audio, TTS cache). /app belongs to root, so the app user needs its own
# directory; docker-compose mounts a volume here so the files survive container rebuilds.
RUN mkdir /data && chown app:app /data
ENV SESSIONS_AUDIO_DIR=/data/sessions \
    TTS_CACHE_DIR=/data/tts-cache

# Dependencies first: this layer is rebuilt only when requirements.txt changes
COPY requirements.txt .
RUN pip install -r requirements.txt

# Source code last: it changes often, so it must not invalidate the layer above
COPY --chown=app:app app ./app
COPY --chown=app:app alembic.ini ./alembic.ini
COPY --chown=app:app alembic ./alembic

USER app

EXPOSE 8000

# Apply pending migrations, then start the API
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
