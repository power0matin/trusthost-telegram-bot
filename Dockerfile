FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Unprivileged runtime user
RUN useradd --create-home --uid 10001 bot

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN mkdir -p /app/data && chown -R bot:bot /app
USER bot

# No secrets are baked into the image: everything comes from environment variables at runtime.
# Migrations run first, then the bot (long polling – no inbound ports needed).
CMD ["sh", "-c", "alembic upgrade head && exec python -m app.main"]
