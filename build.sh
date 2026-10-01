#!/usr/bin/env bash
set -o errexit

echo "=== Starting TechNest build ==="

python manage.py migrate

python manage.py loaddata technest_data.json

echo "=== Checking media files ==="
ls -lah media/
ls -lah media/products/

echo "=== Verifying fixture-referenced media files ==="
python - <<'PY2'
import json
from pathlib import Path

fixture = Path("technest_data.json")
media_root = Path("media")
data = json.loads(fixture.read_text(encoding="utf-8"))
refs = []

def walk(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "image" and isinstance(item, str) and item.startswith("products/"):
                refs.append(item)
            walk(item)
    elif isinstance(value, list):
        for item in value:
            walk(item)

walk(data)
missing = [ref for ref in sorted(set(refs)) if not (media_root / ref).is_file()]
if missing:
    print("ERROR: Missing fixture-referenced media files:")
    for ref in missing:
        print(f"  - {ref}")
    raise SystemExit(1)

print(f"OK: {len(set(refs))} fixture-referenced media files are present.")
PY2

echo "=== Checking Samsung image ==="
ls -lah "media/products/samsung-galaxy-s25-navy.webp"

echo "=== Collecting static files ==="
python manage.py collectstatic --no-input

echo "=== TechNest build completed ==="