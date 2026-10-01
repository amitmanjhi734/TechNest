#!/usr/bin/env bash
set -o errexit

echo "=== Starting TechNest build ==="

python manage.py migrate

python manage.py loaddata technest_data.json

echo "=== Checking media files ==="
ls -lah media/
ls -lah media/products/

echo "=== Checking Samsung image ==="
ls -lah "media/products/samsung-galaxy-s25-navy.webp"

echo "=== Collecting static files ==="
python manage.py collectstatic --no-input

echo "=== TechNest build completed ==="