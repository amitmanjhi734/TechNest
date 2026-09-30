#!/usr/bin/env bash
set -o errexit

python manage.py migrate
python manage.py loaddata technest_data.json
python manage.py collectstatic --no-input