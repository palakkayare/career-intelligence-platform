#!/bin/sh
# Container startup: wait for Postgres, apply migrations, collect static.
#
# Migrations run here rather than in a separate deploy step because this
# project is deployed as a single compose stack. On a multi-replica setup this
# would move to a one-shot job, so that ten containers do not race each other.
set -e

echo "Waiting for Postgres..."
until python -c "
import os, sys, psycopg2
from urllib.parse import urlparse
url = urlparse(os.environ['DATABASE_URL'])
try:
    psycopg2.connect(
        dbname=url.path[1:], user=url.username, password=url.password,
        host=url.hostname, port=url.port or 5432,
    ).close()
except Exception:
    sys.exit(1)
" 2>/dev/null; do
    sleep 1
done
echo "Postgres is up."

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "Applying migrations..."
    python manage.py migrate --noinput
fi

if [ "${COLLECT_STATIC:-true}" = "true" ]; then
    echo "Collecting static files..."
    python manage.py collectstatic --noinput --clear
fi

exec "$@"
