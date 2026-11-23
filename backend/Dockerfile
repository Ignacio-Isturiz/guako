FROM python:3.12-slim

# No .pyc files, unbuffered logs (so `docker logs` shows output immediately)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Unprivileged user: a compromised process can't act as root inside the container
RUN groupadd --system app && useradd --system --gid app --no-create-home app

# Dependencies first: this layer is rebuilt only when requirements.txt changes
COPY requirements.txt .
RUN pip install -r requirements.txt

# Source code last: it changes often, so it must not invalidate the layer above
COPY --chown=app:app app ./app

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
