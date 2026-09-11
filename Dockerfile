# Multi-stage: the build tools needed to compile psycopg2 and friends have no
# place in the image that ships, so dependencies are built here and only the
# finished virtualenv is copied across.
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements/ /tmp/requirements/
RUN pip install --upgrade pip && \
    pip install -r /tmp/requirements/production.txt

# The spaCy model is baked in rather than downloaded at boot: resume parsing
# would otherwise fail on a fresh container until someone remembered to fetch
# it, and a 12 MB layer is cheaper than that failure mode.
RUN python -m spacy download en_core_web_sm


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.production

# libpq5 is the runtime half of libpq-dev; curl is for the healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Running as root inside a container is a container escape away from running
# as root on the host.
RUN groupadd --system app && useradd --system --gid app --create-home app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app . .

RUN mkdir -p /app/staticfiles /app/media && chown -R app:app /app

USER app

COPY --chown=app:app docker/entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]

EXPOSE 8000

# No CMD: the entrypoint starts Gunicorn, the worker or beat depending on
# SERVICE_ROLE (default web). See docker/entrypoint.sh.

# Git commit of this image, passed in by CI. Sentry tags every error with it,
# so a bug can be traced to the deploy that introduced it. Kept last: a value
# that changes every commit would otherwise bust the layer cache above it.
ARG GIT_SHA=
ENV SENTRY_RELEASE=${GIT_SHA}
