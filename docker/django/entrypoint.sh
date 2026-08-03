#!/bin/sh

set -e

echo "Applying migrations..."
python /app/order_service/manage.py migrate --noinput

echo "Collecting static files..."
python /app/order_service/manage.py collectstatic --noinput

echo "Starting Gunicorn..."
exec gunicorn \
    --chdir /app/order_service \
    order_service.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 120