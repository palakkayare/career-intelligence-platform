#!/bin/sh
# Container startup. One image runs all three services; SERVICE_ROLE picks
# which one this container is:
#
#   web     wait for Postgres, migrate, collect static, start Gunicorn
#   worker  wait for Postgres, start the Celery worker
#   beat    start Celery beat (exactly one, ever)
#
# The role is an environment variable rather than a start command because
# hosting platforms disagree on whether a start command replaces the image's
# ENTRYPOINT or only its CMD. With an env var, every platform runs this file.
#
# An explicit command (docker compose run web python manage.py shell) skips
# all of this and runs as given.
set -e

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

ROLE="${SERVICE_ROLE:-web}"

wait_for_db() {
    limit="${DB_WAIT_SECONDS:-60}"
    started=$(date +%s)
    echo "Waiting for Postgres..."
    # libpq reads the whole URL, so sslmode and channel_binding from a
    # managed provider's connection string are honoured.
    until error=$(python -c "
import os, psycopg2
psycopg2.connect(os.environ['DATABASE_URL'], connect_timeout=5).close()
" 2>&1); do
        if [ $(( $(date +%s) - started )) -ge "$limit" ]; then
            # Waiting silently forever is how a typo in DATABASE_URL turns
            # into a deploy that hangs with nothing in the logs.
            echo "Postgres still unreachable after ${limit}s. Last error:" >&2
            echo "$error" | tail -n 3 >&2
            exit 1
        fi
        sleep 2
    done
    echo "Postgres is up."
}

case "$ROLE" in
    web)
        wait_for_db
        # Only the web role migrates. Worker and beat starting alongside it
        # would otherwise race it for the same migration.
        if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
            echo "Applying migrations..."
            python manage.py migrate --noinput
        fi
        if [ "${COLLECT_STATIC:-true}" = "true" ]; then
            echo "Collecting static files..."
            python manage.py collectstatic --noinput --clear -v 0
        fi
        # PORT is set by the platform; 8000 is the local default.
        # --max-requests recycles a worker now and then, which caps slow
        # memory growth from spaCy and PDF parsing.
        exec gunicorn config.wsgi:application \
            --bind "0.0.0.0:${PORT:-8000}" \
            --workers "${WEB_CONCURRENCY:-2}" \
            --threads "${GUNICORN_THREADS:-2}" \
            --timeout "${GUNICORN_TIMEOUT:-60}" \
            --max-requests 1000 \
            --max-requests-jitter 100 \
            --access-logfile - \
            --error-logfile -
        ;;
    worker)
        wait_for_db
        exec celery -A config worker \
            --loglevel=info \
            --concurrency "${CELERY_CONCURRENCY:-2}"
        ;;
    beat)
        # The schedule file lives in /tmp: it is disposable state, and a
        # copy baked into the image from the repo is stale from day one.
        exec celery -A config beat \
            --loglevel=info \
            --schedule /tmp/celerybeat-schedule
        ;;
    *)
        echo "Unknown SERVICE_ROLE '$ROLE'. Use web, worker or beat." >&2
        exit 1
        ;;
esac
